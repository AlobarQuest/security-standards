import json

from security_scan import cli


def _cache(tmp_path, rules):
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(rules))
    return p


def test_scan_reports_block_and_exit_nonzero(git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    git_repo.write("a.sh", "T=0.45eb083f-4b05-4251-924d-b46700e5a643.SECRET:MOREMORE==XXX\n")
    git_repo.commit()
    cache = _cache(
        tmp_path,
        [
            {
                "id": "bws.no-token-in-tracked-files",
                "severity": "BLOCK",
                "check": {
                    "kind": "forbidden_pattern",
                    "pattern": r"0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}",
                    "scope": "tracked",
                },
                "remediation": "remove it",
                "reason": "leak",
            }
        ],
    )
    report, exit_code = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    assert exit_code == 1
    assert report["summary"]["by_severity"]["BLOCK"] == 1
    assert report["meta"]["rules_source"] == "cache"
    assert "SECRET" not in json.dumps(report)  # redacted end-to-end


def test_judgment_rule_emitted_as_placeholder(git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    git_repo.write("a.py", "ok\n")
    git_repo.commit()
    cache = _cache(
        tmp_path,
        [
            {
                "id": "bws.least-privilege-scope",
                "severity": "INFO",
                "check": {"kind": "judgment"},
                "remediation": "review scope",
                "reason": "least privilege",
            }
        ],
    )
    report, exit_code = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    assert exit_code == 0
    assert report["findings"][0]["kind"] == "judgment"


def test_manifest_rules(git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    git_repo.write("start.sh", "bws secret get 45eb083f-4b05-4251-924d-b46700e5a643\n")
    git_repo.commit()
    cache = _cache(
        tmp_path,
        [
            {
                "id": "bws.secret-manifest-present",
                "severity": "WARN",
                "check": {"kind": "manifest_present"},
                "remediation": "add manifest",
                "reason": "declare",
            },
            {
                "id": "bws.manifest-matches-usage",
                "severity": "WARN",
                "check": {"kind": "manifest_matches_usage"},
                "remediation": "sync",
                "reason": "honest",
            },
        ],
    )
    report, _ = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    ids = {f["rule_id"] for f in report["findings"]}
    assert "bws.secret-manifest-present" in ids  # no manifest, but BWS used
    assert "bws.manifest-matches-usage" in ids  # undeclared uuid


def test_bundled_cache_has_v1_bws_rules():
    import json as _json

    from security_scan.cli import _DEFAULT_CACHE

    rules = _json.loads(_DEFAULT_CACHE.read_text())
    ids = {r["id"] for r in rules}
    assert {
        "bws.no-token-in-tracked-files",
        "bws.no-token-in-git-history",
        "bws.secret-files-gitignored",
        "bws.bootstrap-token-not-inline",
        "bws.reference-by-stable-uuid",
        "bws.secret-manifest-present",
        "bws.manifest-matches-usage",
        "bws.least-privilege-scope",
    } <= ids
    for r in rules:
        assert r["severity"] in ("BLOCK", "WARN", "INFO")
        assert "check" in r and "remediation" in r and "reason" in r


def test_allowlist_suppresses_block_and_restores_exit_zero(git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    git_repo.write("a.sh", "T=0.45eb083f-4b05-4251-924d-b46700e5a643.SECRET:MOREMORE==XXX\n")
    git_repo.commit()
    cache = _cache(
        tmp_path,
        [
            {
                "id": "bws.no-token-in-tracked-files",
                "severity": "BLOCK",
                "check": {
                    "kind": "forbidden_pattern",
                    "pattern": r"0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}",
                    "scope": "tracked",
                },
                "remediation": "remove it",
                "reason": "leak",
            }
        ],
    )
    report, code = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    assert code == 1
    ev = report["findings"][0]["evidence"]
    git_repo.write(
        ".security-scan-allow.toml",
        f'[[allow]]\nrule = "bws.no-token-in-tracked-files"\nfile = "a.sh"\nevidence = "{ev}"\n',
    )
    git_repo.commit()
    report2, code2 = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    assert code2 == 0
    assert report2["summary"]["by_severity"]["BLOCK"] == 0
    assert report2["meta"]["allowlisted"] == 1
    assert report2["allowlisted"][0]["rule_id"] == "bws.no-token-in-tracked-files"


def test_non_git_path_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    nongit = tmp_path / "plain"
    nongit.mkdir()
    cache = _cache(tmp_path, [])
    report, code = cli.scan(repo_path=nongit, cache_path=cache, category="security")
    assert code == 1
    assert report["findings"][0]["rule_id"] == "scan.not-a-git-repo"
    assert report["summary"]["by_severity"]["BLOCK"] == 1


def test_gitignore_rule_skipped_when_no_bws_usage(git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    git_repo.write("main.py", "print('hi')\n")  # no BWS usage anywhere
    git_repo.write(".gitignore", "*.log\n")  # does NOT cover *.env
    git_repo.commit()
    cache = _cache(
        tmp_path,
        [
            {
                "id": "bws.secret-files-gitignored",
                "severity": "BLOCK",
                "check": {"kind": "gitignore_covers", "globs": ["*.env"]},
                "remediation": "add to gitignore",
                "reason": "secret files must be ignored",
            }
        ],
    )
    report, code = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    assert code == 0
    assert report["findings"] == []


def test_gitignore_rule_fires_when_repo_uses_bws(git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    git_repo.write("start.sh", "bws secret get 45eb083f-4b05-4251-924d-b46700e5a643\n")
    git_repo.write(".gitignore", "*.log\n")  # does NOT cover *.env
    git_repo.commit()
    cache = _cache(
        tmp_path,
        [
            {
                "id": "bws.secret-files-gitignored",
                "severity": "BLOCK",
                "check": {"kind": "gitignore_covers", "globs": ["*.env"]},
                "remediation": "add to gitignore",
                "reason": "secret files must be ignored",
            }
        ],
    )
    report, code = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    assert code == 1
    assert any(f["rule_id"] == "bws.secret-files-gitignored" for f in report["findings"])
