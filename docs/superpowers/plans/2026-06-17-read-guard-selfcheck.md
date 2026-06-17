# Read-Guard Self-Check + Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect silent failure of the machine-local read-guard wiring (which fails open) via a versioned self-check: a config presence check + an end-to-end canary through the real shim.

**Architecture:** A new `security_scan.read_guard.selfcheck` module (repo, tested) with `Result`, `check_presence`, `check_canary`, and a CLI (exit 0 ok / 1 not-ok). Two un-versioned runners invoke it: `session-start.sh` (presence, warns+logs, never blocks) and `security-scan.sh` (`--canary`, weekly FAIL alert). The check logic is versioned so the un-versioned runners stay thin.

**Tech Stack:** Python 3.12+ (stdlib only — `json`, `os`, `subprocess`, `sys`, `tempfile`, `uuid`, `dataclasses`), pytest, bash runners.

## Global Constraints

- Python floor **>=3.12**; stdlib only — no new runtime deps.
- **Never write a literal BWS token** into any file. The canary builds a shape-matching token at runtime by concatenation (`"0." + uuid4 + "." + blob`).
- **Warn loudly, never block, always log.** A failed check produces a session warning + weekly FAIL + audit line — never blocks a session and never auto-edits settings (no auto-repair).
- Canary isolates its audit writes via `READ_GUARD_AUDIT_LOG` (temp path) and cleans up its temp files — no real-audit-log pollution.
- CLI exit codes: **0 = ok, 1 = not-ok**, for both presence and `--canary` modes; the CLI never raises.
- Default paths: settings `~/.claude/settings.json`, shim `~/.claude/hooks/bws-read-guard.sh` — both parameters so tests use temp fixtures.
- Tests in `tests/test_read_guard_selfcheck.py`, run in CI.

---

### Task 1: `Result` + `check_presence`

**Files:**
- Create: `src/security_scan/read_guard/selfcheck.py`
- Test: `tests/test_read_guard_selfcheck.py`

**Interfaces:**
- Produces: `selfcheck.Result` (dataclass `ok: bool`, `detail: str`); `selfcheck.check_presence(settings_path: str = <default>, shim_path: str = <default>) -> Result`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_read_guard_selfcheck.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_read_guard_selfcheck.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'security_scan.read_guard.selfcheck'`

- [ ] **Step 3: Implement**

```python
# src/security_scan/read_guard/selfcheck.py
"""Self-check for the PreToolUse read-guard wiring: detect silent failure.

The guard's wiring is machine-local config and fails open, so a broken or
missing guard removes protection with no signal. These checks make that loud.
"""
import json
import os
from dataclasses import dataclass

_DEFAULT_SETTINGS = os.path.expanduser("~/.claude/settings.json")
_DEFAULT_SHIM = os.path.expanduser("~/.claude/hooks/bws-read-guard.sh")


@dataclass
class Result:
    ok: bool
    detail: str


def check_presence(settings_path: str = _DEFAULT_SETTINGS,
                   shim_path: str = _DEFAULT_SHIM) -> Result:
    """Config-level: is the read-guard wired into settings.json and the shim present+executable?"""
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, ValueError) as e:
        return Result(False, f"cannot read settings.json: {e}")
    pre = (settings.get("hooks") or {}).get("PreToolUse") or []
    entry = next((h for h in pre if isinstance(h, dict) and h.get("matcher") == "Read"), None)
    if entry is None:
        return Result(False, "no PreToolUse 'Read' hook entry in settings.json")
    cmds = [hk.get("command") for hk in (entry.get("hooks") or []) if isinstance(hk, dict)]
    if shim_path not in cmds:
        return Result(False, f"PreToolUse 'Read' entry does not point at {shim_path}")
    if not os.path.isfile(shim_path):
        return Result(False, f"shim missing: {shim_path}")
    if not os.access(shim_path, os.X_OK):
        return Result(False, f"shim not executable: {shim_path}")
    return Result(True, "read-guard wired (Read -> shim, executable)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_read_guard_selfcheck.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/read_guard/selfcheck.py tests/test_read_guard_selfcheck.py
git commit -m "feat: read-guard selfcheck presence check"
```

---

### Task 2: `check_canary`

**Files:**
- Modify: `src/security_scan/read_guard/selfcheck.py`
- Test: `tests/test_read_guard_selfcheck.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (independent of `check_presence`).
- Produces: `selfcheck.check_canary(shim_path: str = <default>) -> Result`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_read_guard_selfcheck.py
import security_scan


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_read_guard_selfcheck.py -k canary -v`
Expected: FAIL with `AttributeError: ... 'check_canary'`

- [ ] **Step 3: Implement**

```python
# add to src/security_scan/read_guard/selfcheck.py
# (add these imports at the top with the others: subprocess, tempfile, uuid)
import subprocess
import tempfile
import uuid


def _envelope(file_path: str) -> str:
    return json.dumps({"tool_name": "Read", "tool_input": {"file_path": file_path}})


def check_canary(shim_path: str = _DEFAULT_SHIM) -> Result:
    """Functional, end-to-end through the real shim: a token file must be denied,
    a clean file allowed. Builds a synthetic token at runtime; isolates audit writes
    to a temp path; cleans up. Any failure/exception -> not-ok."""
    if not os.path.isfile(shim_path):
        return Result(False, f"shim missing: {shim_path}")
    tmpdir = tempfile.mkdtemp(prefix="rg-canary-")
    secret = os.path.join(tmpdir, "secret.env")
    clean = os.path.join(tmpdir, "clean.txt")
    try:
        token = "0." + str(uuid.uuid4()) + "." + ("A" * 30)  # runtime-built; never a literal
        with open(secret, "w") as f:
            f.write(f"BWS_ACCESS_TOKEN={token}\n")
        with open(clean, "w") as f:
            f.write("nothing here\n")
        env = {**os.environ, "READ_GUARD_AUDIT_LOG": os.path.join(tmpdir, "audit.jsonl")}
        deny = subprocess.run([shim_path], input=_envelope(secret), capture_output=True,
                              text=True, env=env, timeout=10)
        try:
            decision = json.loads(deny.stdout)["hookSpecificOutput"]["permissionDecision"]
        except Exception:
            return Result(False, f"shim emitted no deny decision for a token file (stdout={deny.stdout[:200]!r})")
        if decision != "deny":
            return Result(False, f"shim returned '{decision}', expected 'deny' for a token file")
        allow = subprocess.run([shim_path], input=_envelope(clean), capture_output=True,
                               text=True, env=env, timeout=10)
        if allow.stdout.strip():
            return Result(False, f"shim did not allow a clean file (stdout={allow.stdout[:200]!r})")
        return Result(True, "canary ok (token file denied, clean file allowed)")
    except Exception as e:
        return Result(False, f"canary error: {e}")
    finally:
        for n in ("secret.env", "clean.txt", "audit.jsonl"):
            try:
                os.remove(os.path.join(tmpdir, n))
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_read_guard_selfcheck.py -v`
Expected: PASS (10 tests). (The working-shim canary tests spawn `python3 -m security_scan.read_guard.hook`; they need the repo importable, which `_src_dir()` provides.)

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/read_guard/selfcheck.py tests/test_read_guard_selfcheck.py
git commit -m "feat: read-guard selfcheck end-to-end canary"
```

---

### Task 3: CLI (`main`, exit codes)

**Files:**
- Modify: `src/security_scan/read_guard/selfcheck.py`
- Test: `tests/test_read_guard_selfcheck.py`

**Interfaces:**
- Consumes: `check_presence`, `check_canary`.
- Produces: `selfcheck.main(argv: list[str] | None = None) -> int` (0 ok / 1 not-ok); `python -m security_scan.read_guard.selfcheck` runs it.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_read_guard_selfcheck.py
def test_main_presence_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(selfcheck, "check_presence", lambda *a, **k: selfcheck.Result(True, "ok"))
    assert selfcheck.main([]) == 0
    monkeypatch.setattr(selfcheck, "check_presence", lambda *a, **k: selfcheck.Result(False, "nope"))
    assert selfcheck.main([]) == 1


def test_main_canary_exit_codes(monkeypatch):
    monkeypatch.setattr(selfcheck, "check_presence", lambda *a, **k: selfcheck.Result(True, "ok"))
    monkeypatch.setattr(selfcheck, "check_canary", lambda *a, **k: selfcheck.Result(True, "ok"))
    assert selfcheck.main(["--canary"]) == 0
    monkeypatch.setattr(selfcheck, "check_canary", lambda *a, **k: selfcheck.Result(False, "broken"))
    assert selfcheck.main(["--canary"]) == 1  # canary fail -> overall fail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_read_guard_selfcheck.py -k main -v`
Expected: FAIL with `AttributeError: ... 'main'`

- [ ] **Step 3: Implement**

```python
# add to src/security_scan/read_guard/selfcheck.py (add `import sys` at top)
import sys


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--canary" in argv:
        r1 = check_presence()
        r2 = check_canary()
        print(f"presence: {'OK' if r1.ok else 'FAIL'} - {r1.detail}")
        print(f"canary:   {'OK' if r2.ok else 'FAIL'} - {r2.detail}")
        return 0 if (r1.ok and r2.ok) else 1
    r = check_presence()
    print(f"presence: {'OK' if r.ok else 'FAIL'} - {r.detail}")
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_read_guard_selfcheck.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Smoke-test the CLI against the live machine (informational)**

Run: `PYTHONPATH="$HOME/Projects/security-standards/src" python3 -m security_scan.read_guard.selfcheck; echo "exit=$?"`
Expected: `presence: OK - read-guard wired ...` and `exit=0` (the guard is currently wired). If it prints FAIL, that itself is a useful signal — note it.

- [ ] **Step 6: Commit**

```bash
git add src/security_scan/read_guard/selfcheck.py tests/test_read_guard_selfcheck.py
git commit -m "feat: read-guard selfcheck CLI (exit 0 ok / 1 not-ok)"
```

---

### Task 4: CI — run the selfcheck tests

**Files:**
- Modify: `.github/workflows/security-scan.yml`

**Interfaces:** none new.

- [ ] **Step 1: Add the new test file to the read-guard test step**

In `.github/workflows/security-scan.yml`, change the existing read-guard pytest step command from
`python -m pytest tests/test_read_guard.py -v`
to
`python -m pytest tests/test_read_guard.py tests/test_read_guard_selfcheck.py -v`
(leave the step name and everything else unchanged).

- [ ] **Step 2: Run both files locally to confirm**

Run: `python -m pytest tests/test_read_guard.py tests/test_read_guard_selfcheck.py -v`
Expected: PASS (20 read-guard + 12 selfcheck = 32).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/security-scan.yml
git commit -m "ci: run read-guard selfcheck tests"
```

---

### Task 5: Wire the runners + live verification (CONTROLLER-DIRECT infra step — not a subagent)

**Files:**
- Modify: `~/.claude/hooks/session-start.sh`
- Modify: `~/.claude/bin/security-scan.sh`
- Create: `docs/superpowers/notes/2026-06-17-read-guard-selfcheck-verification.md`

> **Note:** these touch live, un-versioned `~/.claude` config. The controller does this directly, after the branch merges to `main` (so `…/src` has the selfcheck module). Read each runner first and integrate following its existing structure.

- [ ] **Step 1: Wire SessionStart presence check**

Read `~/.claude/hooks/session-start.sh`. Add (following its style) a presence check that warns but never blocks:
```bash
# read-guard presence self-check (warn, never block)
RG_OUT="$(PYTHONPATH="$HOME/Projects/security-standards/src" python3 -m security_scan.read_guard.selfcheck 2>/dev/null)"
if [ $? -ne 0 ]; then
  TS="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  printf '{"timestamp":"%s","tool":"read-guard","event":"guard-down","detail":%s}\n' \
    "$TS" "$(printf '%s' "$RG_OUT" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read().strip()))')" \
    >> "$HOME/.claude/audit/high-power-actions.jsonl"
  # surface a SessionStart warning to the agent (use the hook's existing context-injection mechanism)
  echo "⚠️ BWS read-guard is NOT wired/healthy: ${RG_OUT}. You are unprotected against accidental token reads — re-run the read-guard installer." >&2
fi
```
Match the hook's actual output contract for injecting context (if it emits JSON `hookSpecificOutput.additionalContext`, use that instead of stderr). Confirm `session-start.sh` still exits 0 in all paths.

- [ ] **Step 2: Verify SessionStart wiring doesn't break the hook**

Run: `bash -n ~/.claude/hooks/session-start.sh && echo OK`
Then run it once with the guard healthy (should be silent / no warning):
`bash ~/.claude/hooks/session-start.sh </dev/null; echo "exit=$?"` → expect exit 0, no guard-down warning.

- [ ] **Step 3: Wire the weekly canary into security-scan.sh**

Read `~/.claude/bin/security-scan.sh`. Add a check (following its existing numbered-check style) that runs the canary and emits a FAIL finding on non-zero:
```bash
# read-guard canary (functional end-to-end)
RG_CANARY="$(PYTHONPATH="$HOME/Projects/security-standards/src" python3 -m security_scan.read_guard.selfcheck --canary 2>&1)"
if [ $? -ne 0 ]; then
  # emit a FAIL finding in this script's existing finding format, e.g.:
  echo "FAIL secret.read_guard_canary  read-guard canary failed: ${RG_CANARY}"
fi
```
Use the script's ACTUAL finding-emission format (match the existing `FAIL <rule> <message>` lines so it flows into the email/Healthchecks digest). Non-blocking.

- [ ] **Step 4: Live verification — simulate a broken guard**

1. Healthy baseline: `PYTHONPATH="$HOME/Projects/security-standards/src" python3 -m security_scan.read_guard.selfcheck --canary; echo "exit=$?"` → expect both OK, exit 0.
2. Break it temporarily: `chmod -x ~/.claude/hooks/bws-read-guard.sh` → re-run presence: expect FAIL "not executable", exit 1. Restore: `chmod +x ~/.claude/hooks/bws-read-guard.sh` → OK again.
3. Confirm the SessionStart path warns when broken (repeat the chmod -x, run `bash ~/.claude/hooks/session-start.sh </dev/null`, expect the guard-down warning + an audit `guard-down` line; restore +x).

- [ ] **Step 5: Record + commit the note**

Write `docs/superpowers/notes/2026-06-17-read-guard-selfcheck-verification.md` (healthy baseline OK; broken-guard FAIL detected by both presence and canary; warning fired; restored). Commit:
```bash
git add docs/superpowers/notes/2026-06-17-read-guard-selfcheck-verification.md
git commit -m "docs: read-guard selfcheck live verification"
```

---

## Notes for the implementer

- **No literal tokens, ever.** The canary builds tokens at runtime (`"0." + uuid4 + "." + blob`).
- **The canary must isolate its audit writes** (`READ_GUARD_AUDIT_LOG` to a temp path) and clean up — never write the real `~/.claude/audit/...` log. A test asserts this.
- **Tasks 1–4 are repo work (subagents). Task 5 is controller-direct** (live `~/.claude` runners + the simulate-broken-guard verification), done after merge.
- **Match the real runners' formats** in Task 5: read `session-start.sh` and `security-scan.sh` first and integrate following their existing context-injection / finding-emission conventions, rather than assuming the snippets above are verbatim-correct for those scripts.
