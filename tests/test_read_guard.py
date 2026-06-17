import json
import os
import re
import time as _time
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


def test_hook_run_redacts_and_emits_contract(tmp_path):
    t = _synth_token()
    env = json.dumps({"session_id": "s1", "tool_name": "Read",
                      "tool_input": {"file_path": "/x/.env"},
                      "tool_output": f"BWS_ACCESS_TOKEN={t}\n"})
    from security_scan.read_guard import hook
    out = hook.run(env, now="2026-06-17T00:00:00Z")
    obj = json.loads(out)
    hso = obj["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse"
    assert t not in hso["updatedToolOutput"]
    assert "additionalContext" in hso


def test_hook_run_passthrough_emits_nothing():
    from security_scan.read_guard import hook
    env = json.dumps({"session_id": "s1", "tool_name": "Bash",
                      "tool_input": {"command": "ls"}, "tool_output": "clean\n"})
    assert hook.run(env, now="2026-06-17T00:00:00Z") == ""


def test_hook_run_passthrough_fidelity_special_chars():
    from security_scan.read_guard import hook
    nasty = 'quotes " backslash \\ newline \n tab \t unicode é \x00 end'
    env = json.dumps({"session_id": "s", "tool_name": "Bash",
                      "tool_input": {"command": "x"}, "tool_output": nasty})
    assert hook.run(env, now="2026-06-17T00:00:00Z") == ""  # no rewrite at all


def test_hook_run_malformed_input_fail_open():
    from security_scan.read_guard import hook
    assert hook.run("not json{", now="2026-06-17T00:00:00Z") == ""


def test_audit_log_written_on_redact_no_value(tmp_path, monkeypatch):
    log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("READ_GUARD_AUDIT_LOG", str(log))
    t = _synth_token()
    env = json.dumps({"session_id": "s1", "tool_name": "Read",
                      "tool_input": {"file_path": "/x/.env"},
                      "tool_output": f"{t}\n"})
    from security_scan.read_guard import hook
    hook.run(env, now="2026-06-17T00:00:00Z")
    line = log.read_text().strip()
    rec = json.loads(line)
    assert rec["tool"] == "read-guard" and rec["event"] == "redact"
    assert rec["match_count"] == 1 and t not in line


def test_scan_large_output_is_fast():
    big = ("x" * 1_000_000 + "\n") * 10  # ~10 MB, no token
    start = _time.perf_counter()
    assert core.scan_for_bws(big) == []
    assert _time.perf_counter() - start < 1.0  # well under any hook timeout


def test_known_limit_transformed_token_not_caught():
    # Token reversed before printing is intentionally NOT detected (documented).
    t = _synth_token()
    assert core.scan_for_bws(t[::-1]) == []


def test_known_limit_token_not_in_output_not_redacted():
    # Read-and-use-without-printing: nothing in the output, nothing to redact.
    d = core.decide({"tool_name": "Bash", "tool_input": {"command": "python use.py"},
                     "tool_output": "done\n"})
    assert d.action == "passthrough"
