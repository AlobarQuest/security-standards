import json
import os
import security_scan

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
    assert shim in r.detail


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


def test_presence_fails_non_dict_hooks(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": [1, 2, 3]}))  # hooks is a list, not a dict
    r = selfcheck.check_presence(str(p), _shim(tmp_path))
    assert r.ok is False  # must not raise


def test_presence_fails_pretooluse_not_list(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"PreToolUse": "oops"}}))
    r = selfcheck.check_presence(str(p), _shim(tmp_path))
    assert r.ok is False  # must not raise


def _src_dir():
    # the repo `src` dir, so a temp shim's subprocess can import security_scan
    return os.path.dirname(os.path.dirname(security_scan.__file__))


def _make_shim(tmp_path, body):
    s = tmp_path / "shim.sh"
    s.write_text(body)
    s.chmod(0o755)
    return str(s)


def test_canary_ok_with_working_shim(tmp_path):
    shim = _make_shim(tmp_path,
        f'#!/usr/bin/env bash\nexec /usr/bin/env PYTHONPATH="{_src_dir()}" '
        f'python3 -m security_scan.read_guard.hook\n')
    r = selfcheck.check_canary(shim)
    assert r.ok is True, r.detail


def test_canary_fails_when_shim_missing(tmp_path):
    r = selfcheck.check_canary(str(tmp_path / "nope.sh"))
    assert r.ok is False and "missing" in r.detail


def test_canary_fails_when_shim_never_denies(tmp_path):
    # a shim that always allows (consumes stdin, emits nothing) must fail the canary
    shim = _make_shim(tmp_path, "#!/usr/bin/env bash\ncat >/dev/null\nexit 0\n")
    r = selfcheck.check_canary(shim)
    assert r.ok is False


def test_canary_does_not_pollute_real_audit_log(tmp_path, monkeypatch):
    # point the REAL default at a path that must stay empty; canary must use its own temp override
    sentinel = tmp_path / "real-audit.jsonl"
    monkeypatch.setenv("READ_GUARD_AUDIT_LOG", str(sentinel))
    shim = _make_shim(tmp_path,
        f'#!/usr/bin/env bash\nexec /usr/bin/env PYTHONPATH="{_src_dir()}" '
        f'python3 -m security_scan.read_guard.hook\n')
    selfcheck.check_canary(shim)
    # the canary sets its OWN READ_GUARD_AUDIT_LOG for the subprocess, so the sentinel stays absent
    assert not sentinel.exists()
