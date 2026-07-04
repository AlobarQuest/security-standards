from security_scan.findings import Finding, Severity, redact


def test_redact_masks_secret_tail_but_keeps_short_prefix():
    secret = "0.45eb083f-4b05-4251-924d-b46700e5a643.SECRETKEYPART:MOREMORE=="
    out = redact(secret)
    assert "SECRETKEYPART" not in out
    assert out.startswith("0.45eb08")
    assert "len" in out


def test_redact_fully_masks_short_values():
    assert redact("abcd") == "***"


def test_finding_to_dict_roundtrips():
    f = Finding(
        rule_id="r",
        severity=Severity.BLOCK,
        file="a.py",
        line=3,
        evidence="0.45eb08…",
        remediation="fix",
        reason="why",
        kind="deterministic",
    )
    d = f.to_dict()
    assert d["severity"] == "BLOCK"
    assert d["file"] == "a.py" and d["line"] == 3
