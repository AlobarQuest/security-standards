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
