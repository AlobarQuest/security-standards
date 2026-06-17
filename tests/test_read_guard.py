import re
import uuid
import pytest
from security_scan import token_shapes
from security_scan.read_guard import core


def _synth_token() -> str:
    """Build a shape-matching token at runtime — never a literal in source."""
    return "0." + str(uuid.uuid4()) + "." + ("A" * 30)


def test_bws_token_rx_matches_synthetic_token():
    assert token_shapes.BWS_TOKEN_RX.search(_synth_token()) is not None


def test_bws_token_rx_ignores_lookalikes():
    for s in ["0.1.2", str(uuid.uuid4()), "abc123def456", "0.short.x"]:
        assert token_shapes.BWS_TOKEN_RX.search(s) is None


def test_scan_finds_token_in_plain_text():
    t = _synth_token()
    out = f"some log line\nBWS_ACCESS_TOKEN={t}\nmore\n"
    assert core.scan_for_bws(out) == [t]


def test_scan_finds_multiple_tokens():
    a, b = _synth_token(), _synth_token()
    assert set(core.scan_for_bws(f"{a} and {b}")) == {a, b}


def test_scan_finds_token_in_decoded_output():
    # simulates `base64 -d` output: the decoded value is present in the string
    t = _synth_token()
    assert core.scan_for_bws(f"decoded: {t}") == [t]


def test_scan_returns_empty_for_clean_output():
    assert core.scan_for_bws("totally clean log output\nno secrets here\n") == []


def test_redact_replaces_token_preserves_surroundings():
    t = _synth_token()
    out = f"prefix [{t}] suffix"
    red = core.redact(out, [t])
    assert t not in red
    assert red == f"prefix [{core.SENTINEL}] suffix"


def test_redact_handles_multiple_and_special_chars():
    a, b = _synth_token(), _synth_token()
    out = f'line1 "{a}"\n\tline2 \\{b}\\ unicode-é'
    red = core.redact(out, [a, b])
    assert a not in red and b not in red
    assert "unicode-é" in red and "\t" in red and "\\" in red


def test_is_secret_path_true_for_known_secret_files():
    for p in [
        "/Users/devon/.config/infra-drift/env",
        "/home/x/.ssh/id_rsa",
        "/root/.aws/credentials",
        "/app/.env",
    ]:
        assert core.is_secret_path(p) is True


def test_is_secret_path_false_for_normal_files():
    for p in ["/Users/devon/Projects/foo/main.py", "/tmp/build.log", None]:
        assert core.is_secret_path(p) is False


def test_extract_path_from_read_and_bash():
    assert core.extract_path({"tool_name": "Read",
                              "tool_input": {"file_path": "/x/.env"}}) == "/x/.env"
    bash = core.extract_path({"tool_name": "Bash",
                              "tool_input": {"command": "cat ~/.config/foo/env"}})
    assert bash is not None and core.is_secret_path(bash) is True


def test_decide_passthrough_when_clean():
    d = core.decide({"tool_name": "Bash", "tool_input": {"command": "ls"},
                     "tool_output": "file1\nfile2\n"})
    assert d.action == "passthrough" and d.output is None


def test_decide_redacts_when_token_present():
    t = _synth_token()
    d = core.decide({"tool_name": "Read", "tool_input": {"file_path": "/x/.env"},
                     "tool_output": f"BWS_ACCESS_TOKEN={t}\n"})
    assert d.action == "redact" and t not in d.output and d.match_count == 1


def test_decide_suppresses_when_redaction_fails(monkeypatch):
    t = _synth_token()
    monkeypatch.setattr(core, "redact",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    d = core.decide({"tool_name": "Read", "tool_input": {"file_path": "/x/.env"},
                     "tool_output": f"{t}\n"})
    assert d.action == "suppress" and d.output == core.SUPPRESS_MESSAGE


def test_decide_missing_output_secret_path_suppresses():
    d = core.decide({"tool_name": "Read",
                     "tool_input": {"file_path": "/x/.config/foo/env"}})
    assert d.action == "suppress"


def test_decide_missing_output_normal_path_fail_open():
    d = core.decide({"tool_name": "Bash", "tool_input": {"command": "echo hi"}})
    assert d.action == "fail_open"
