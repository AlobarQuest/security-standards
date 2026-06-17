import json
import os
from security_scan.read_guard import selfcheck


def _settings(tmp_path, read_cmd):
    """Write a settings.json with a PreToolUse Read entry pointing at read_cmd (or omit if None)."""
    pre = [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "x"}]}]
    if read_cmd is not None:
        pre.append({"matcher": "Read", "hooks": [{"type": "command", "command": read_cmd}]})
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"PreToolUse": pre, "PostToolUse": []}}))
    return str(p)


def _shim(tmp_path, executable=True):
    s = tmp_path / "bws-read-guard.sh"
    s.write_text("#!/usr/bin/env bash\nexit 0\n")
    s.chmod(0o755 if executable else 0o644)
    return str(s)


def test_presence_ok_when_wired(tmp_path):
    shim = _shim(tmp_path)
    r = selfcheck.check_presence(_settings(tmp_path, shim), shim)
    assert r.ok is True


def test_presence_fails_no_read_entry(tmp_path):
    shim = _shim(tmp_path)
    r = selfcheck.check_presence(_settings(tmp_path, None), shim)
    assert r.ok is False and "Read" in r.detail


def test_presence_fails_read_entry_wrong_command(tmp_path):
    shim = _shim(tmp_path)
    r = selfcheck.check_presence(_settings(tmp_path, "/some/other/cmd"), shim)
    assert r.ok is False


def test_presence_fails_shim_missing(tmp_path):
    shim = str(tmp_path / "absent.sh")
    r = selfcheck.check_presence(_settings(tmp_path, shim), shim)
    assert r.ok is False and "missing" in r.detail


def test_presence_fails_shim_not_executable(tmp_path):
    shim = _shim(tmp_path, executable=False)
    r = selfcheck.check_presence(_settings(tmp_path, shim), shim)
    assert r.ok is False and "executable" in r.detail


def test_presence_fails_unparseable_settings(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("not json{")
    r = selfcheck.check_presence(str(p), _shim(tmp_path))
    assert r.ok is False
