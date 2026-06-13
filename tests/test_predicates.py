from security_scan import predicates
from security_scan.findings import Severity


def _rule(check, severity=Severity.BLOCK, rid="bws.test"):
    return {"id": rid, "severity": severity, "check": check,
            "remediation": "fix it", "reason": "because"}


def test_forbidden_pattern_tracked_redacts_and_locates(git_repo):
    git_repo.write("a.sh", "TOK=0.45eb083f-4b05-4251-924d-b46700e5a643.SECRETPART:MOREMORE==\n")
    git_repo.commit()
    rule = _rule({"kind": "forbidden_pattern",
                  "pattern": r"0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}", "scope": "tracked"})
    findings = predicates.evaluate(rule, git_repo.path)
    assert len(findings) == 1
    f = findings[0]
    assert f.file == "a.sh" and f.line == 1
    assert "SECRETPART" not in f.evidence
    assert f.rule_id == "bws.test" and f.severity == Severity.BLOCK


def test_forbidden_pattern_history_scope(git_repo):
    git_repo.write("a.txt", "0.45eb083f-4b05-4251-924d-b46700e5a643.K:V==\n")
    git_repo.commit()
    git_repo.write("a.txt", "clean\n")
    git_repo.commit()
    rule = _rule({"kind": "forbidden_pattern",
                  "pattern": r"0\.[0-9a-f-]{36}\.", "scope": "history"})
    findings = predicates.evaluate(rule, git_repo.path)
    assert len(findings) == 1
    assert "history" in findings[0].evidence.lower()


def test_clean_repo_yields_nothing(git_repo):
    git_repo.write("a.py", "print('hi')\n")
    git_repo.commit()
    rule = _rule({"kind": "forbidden_pattern", "pattern": r"0\.[0-9a-f-]{36}\.", "scope": "tracked"})
    assert predicates.evaluate(rule, git_repo.path) == []


def test_gitignore_covers_flags_uncovered_secret_file(git_repo):
    git_repo.write(".gitignore", "*.key\n")          # covers *.key but NOT *.env
    git_repo.commit()
    rule = _rule({"kind": "gitignore_covers", "globs": ["*.env", "*.key"]})
    findings = predicates.evaluate(rule, git_repo.path)
    assert len(findings) == 1
    assert "*.env" in findings[0].evidence


def test_path_absent_flags_committed_dotenv(git_repo):
    git_repo.write(".env", "X=1\n")
    git_repo.commit()
    rule = _rule({"kind": "path_absent", "glob": ".env"})
    findings = predicates.evaluate(rule, git_repo.path)
    assert len(findings) == 1
    assert findings[0].file == ".env"


def test_required_pattern_passes_when_present(git_repo):
    git_repo.write("start.sh", "fetch_bws_secret 45eb083f\n")
    git_repo.commit()
    rule = _rule({"kind": "required_pattern", "pattern": "fetch_bws_secret",
                  "globs": ["*.sh"]}, severity=Severity.WARN)
    assert predicates.evaluate(rule, git_repo.path) == []
