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
    cache = _cache(tmp_path, [{
        "id": "bws.no-token-in-tracked-files", "severity": "BLOCK",
        "check": {"kind": "forbidden_pattern",
                  "pattern": r"0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}", "scope": "tracked"},
        "remediation": "remove it", "reason": "leak"}])
    report, exit_code = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    assert exit_code == 1
    assert report["summary"]["by_severity"]["BLOCK"] == 1
    assert report["meta"]["rules_source"] == "cache"
    assert "SECRET" not in json.dumps(report)        # redacted end-to-end


def test_judgment_rule_emitted_as_placeholder(git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    git_repo.write("a.py", "ok\n"); git_repo.commit()
    cache = _cache(tmp_path, [{
        "id": "bws.least-privilege-scope", "severity": "INFO",
        "check": {"kind": "judgment"}, "remediation": "review scope", "reason": "least privilege"}])
    report, exit_code = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    assert exit_code == 0
    assert report["findings"][0]["kind"] == "judgment"


def test_manifest_rules(git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("INFRABRAIN_BASE_URL", raising=False)
    git_repo.write("start.sh", "bws secret get 45eb083f-4b05-4251-924d-b46700e5a643\n")
    git_repo.commit()
    cache = _cache(tmp_path, [
        {"id": "bws.secret-manifest-present", "severity": "WARN",
         "check": {"kind": "manifest_present"}, "remediation": "add manifest", "reason": "declare"},
        {"id": "bws.manifest-matches-usage", "severity": "WARN",
         "check": {"kind": "manifest_matches_usage"}, "remediation": "sync", "reason": "honest"}])
    report, _ = cli.scan(repo_path=git_repo.path, cache_path=cache, category="security")
    ids = {f["rule_id"] for f in report["findings"]}
    assert "bws.secret-manifest-present" in ids        # no manifest, but BWS used
    assert "bws.manifest-matches-usage" in ids          # undeclared uuid
