from security_scan import allowlist
from security_scan.findings import Finding, Severity


def _f(rule: str = "bws.r", file: str | None = "a.py", evidence: str = "ev"):
    return Finding(
        rule_id=rule,
        severity=Severity.BLOCK,
        file=file,
        line=1,
        evidence=evidence,
        remediation="x",
        reason="y",
        kind="deterministic",
    )


def test_no_file_loads_empty(tmp_path):
    assert allowlist.load(tmp_path) == []


def test_entry_matches_on_rule_file_evidence(git_repo):
    git_repo.write(
        ".security-scan-allow.toml",
        '[[allow]]\nrule = "bws.r"\nfile = "a.py"\nevidence = "ev"\nreason = "ok"\n',
    )
    git_repo.commit()
    entries = allowlist.load(git_repo.path)
    assert allowlist.is_allowed(_f(), entries) is True


def test_entry_does_not_match_different_file(git_repo):
    git_repo.write(".security-scan-allow.toml", '[[allow]]\nrule = "bws.r"\nfile = "a.py"\n')
    git_repo.commit()
    assert allowlist.is_allowed(_f(file="other.py"), allowlist.load(git_repo.path)) is False


def test_entry_does_not_match_different_evidence(git_repo):
    git_repo.write(
        ".security-scan-allow.toml", '[[allow]]\nrule = "bws.r"\nfile = "a.py"\nevidence = "ev"\n'
    )
    git_repo.commit()
    assert allowlist.is_allowed(_f(evidence="DIFFERENT"), allowlist.load(git_repo.path)) is False


def test_rule_only_entry_matches_any_finding_of_that_rule(git_repo):
    git_repo.write(
        ".security-scan-allow.toml",
        '[[allow]]\nrule = "bws.history"\nreason = "history is repo-wide"\n',
    )
    git_repo.commit()
    f = _f(rule="bws.history", file=None, evidence="pattern present in git history")
    assert allowlist.is_allowed(f, allowlist.load(git_repo.path)) is True


def test_scan_from_subdirectory_loads_root_allowlist(git_repo):
    from security_scan import repo

    git_repo.write(
        ".security-scan-allow.toml",
        '[[allow]]\nrule = "bws.bootstrap-token-not-inline"\nreason = "fixture"\n',
    )
    subdir = git_repo.write("nested/.keep", "").parent
    git_repo.commit()

    entries = allowlist.load(repo.root(subdir))

    assert len(entries) == 1
    assert entries[0].rule == "bws.bootstrap-token-not-inline"
