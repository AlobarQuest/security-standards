# BWS Read-Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an agent-scoped Claude Code `PostToolUse` hook that redacts a live BWS access token out of tool output before it persists to the transcript.

**Architecture:** A pure-logic core (`security_scan.read_guard.core`) and a thin I/O entry (`security_scan.read_guard.hook`) live inside the version-controlled `security_scan` package; a tiny bash shim in `~/.claude/hooks/` wires it as a `PostToolUse` hook on `Read|Bash` via the repo's existing `PYTHONPATH=…/src python3 -m …` invocation. Detection is content-shape (the BWS bare-token regex) with a secret-file path amplifier; the fail-safe is Option 3 (redact when found, suppress only when a found token can't be safely redacted or an unscannable read targets a secret path, otherwise pass through / fail-open-with-audit).

**Tech Stack:** Python 3.12+ (stdlib only — `re`, `json`, `sys`, `os`, `time`, `dataclasses`), pytest, bash shim, Claude Code hooks JSON contract.

## Global Constraints

- Python floor: **>=3.12** (matches `pyproject.toml`). Stdlib only — no new runtime deps.
- **Never write a literal BWS token into any file** (source, test, fixture, or doc). Tests build shape-matching tokens at runtime by concatenation; no literal token ever appears in a tracked file (the write-guard + Stop scan-gate would block it). The canonical bare-token shape regex is `0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}`.
- v1 detects **only the BWS bare-token shape**. No other secret types.
- Agent-scoped only; never machine-wide. Redact-don't-deny.
- Passthrough (no token found) MUST emit no rewrite (exit 0, empty stdout) so the original output is byte-untouched by definition.
- Audit lines never contain a token value.
- Tests run with `python -m pytest tests/test_read_guard.py -v` (pytest config: `pythonpath=["src"]`, `testpaths=["tests"]`).

---

### Task 1: Canonical token-shape module

**Files:**
- Create: `src/security_scan/token_shapes.py`
- Create: `src/security_scan/read_guard/__init__.py` (empty package marker)
- Test: `tests/test_read_guard.py`
- Modify (comment only): `~/.claude/hooks/bws-write-guard.sh` — add a cross-reference comment by its `PATTERN=` line pointing at `security_scan.token_shapes.BWS_TOKEN_RX` as the canonical Python definition.

**Interfaces:**
- Produces: `security_scan.token_shapes.BWS_TOKEN_RX` — a compiled `re.Pattern` matching the BWS bare-token shape. `security_scan.token_shapes.BWS_TOKEN_REGEX` — the raw pattern string.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_read_guard.py
import re
import uuid
from security_scan import token_shapes


def _synth_token() -> str:
    """Build a shape-matching token at runtime — never a literal in source."""
    return "0." + str(uuid.uuid4()) + "." + ("A" * 30)


def test_bws_token_rx_matches_synthetic_token():
    assert token_shapes.BWS_TOKEN_RX.search(_synth_token()) is not None


def test_bws_token_rx_ignores_lookalikes():
    for s in ["0.1.2", str(uuid.uuid4()), "abc123def456", "0.short.x"]:
        assert token_shapes.BWS_TOKEN_RX.search(s) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'security_scan.token_shapes'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/security_scan/token_shapes.py
"""Canonical BWS secret-shape patterns — the single source of truth.

The bare-token shape mirrors the regex in ~/.claude/hooks/bws-write-guard.sh
(kept identical by hand; that hook is bash and cannot import this). Any change
here must be reflected there.
"""
import re

# BWS access token: "0." + 36-char uuid-ish + "." + base64-ish secret (>=20).
BWS_TOKEN_REGEX = r"0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}"
BWS_TOKEN_RX = re.compile(BWS_TOKEN_REGEX)
```

```python
# src/security_scan/read_guard/__init__.py
# (empty package marker)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Add the cross-reference comment to the bash write-guard**

In `~/.claude/hooks/bws-write-guard.sh`, immediately above the `PATTERN=` line, add:

```bash
# NOTE: the bare-token half of this PATTERN is mirrored in
# security_scan.token_shapes.BWS_TOKEN_RX (the canonical Python definition used
# by the read-guard). Keep the two identical.
```

- [ ] **Step 6: Commit**

```bash
git add src/security_scan/token_shapes.py src/security_scan/read_guard/__init__.py tests/test_read_guard.py
git commit -m "feat: canonical BWS token-shape module for read-guard"
```

---

### Task 2: Detection — `scan_for_bws`

**Files:**
- Create: `src/security_scan/read_guard/core.py`
- Test: `tests/test_read_guard.py`

**Interfaces:**
- Consumes: `security_scan.token_shapes.BWS_TOKEN_RX`
- Produces: `core.scan_for_bws(output: str) -> list[str]` — returns the list of matched token substrings (empty if none). Robust on arbitrary text including newlines/control chars.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_read_guard.py
from security_scan.read_guard import core


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'security_scan.read_guard.core'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/security_scan/read_guard/core.py
"""Pure read-guard logic: detection, redaction, path amplifier, decision.

No I/O, no side effects — unit-tested without Claude Code. The hook entry
(security_scan.read_guard.hook) wraps this with stdin/stdout + audit logging.
"""
from security_scan.token_shapes import BWS_TOKEN_RX


def scan_for_bws(output: str) -> list[str]:
    """Return all BWS-token substrings present in output (empty if none)."""
    return BWS_TOKEN_RX.findall(output)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/read_guard/core.py tests/test_read_guard.py
git commit -m "feat: read-guard token detection (scan_for_bws)"
```

---

### Task 3: Redaction — `redact` + sentinel

**Files:**
- Modify: `src/security_scan/read_guard/core.py`
- Test: `tests/test_read_guard.py`

**Interfaces:**
- Produces: `core.SENTINEL` (str) and `core.redact(output: str, matches: list[str]) -> str` — returns output with each matched token replaced by `SENTINEL`, all other characters preserved exactly.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_read_guard.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'SENTINEL'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/security_scan/read_guard/core.py
SENTINEL = "[REDACTED — BWS token withheld from transcript; fetch at runtime from Keychain/BWS, do not read the file]"


def redact(output: str, matches: list[str]) -> str:
    """Replace every matched token with SENTINEL; preserve everything else."""
    red = output
    for m in matches:
        red = red.replace(m, SENTINEL)
    return red
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/read_guard/core.py tests/test_read_guard.py
git commit -m "feat: read-guard redaction + sentinel"
```

---

### Task 4: Path amplifier — `is_secret_path` + envelope path extraction

**Files:**
- Modify: `src/security_scan/read_guard/core.py`
- Test: `tests/test_read_guard.py`

**Interfaces:**
- Produces: `core.is_secret_path(path: str | None) -> bool` — True for known secret-file paths. `core.extract_path(envelope: dict) -> str | None` — best-effort target path from a hook envelope's `tool_input` (Read uses `file_path`; Bash command is searched for a secret-path substring).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_read_guard.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: FAIL with `AttributeError: ... 'is_secret_path'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/security_scan/read_guard/core.py
import re as _re

# Known secret-file path shapes (v1 amplifier set — modest by design).
_SECRET_PATH_RX = _re.compile(
    r"(/\.config/[^/]+/env\b"      # ~/.config/<workload>/env
    r"|/\.ssh/id_[^/]*"            # ssh private keys
    r"|/\.aws/credentials\b"       # aws creds
    r"|/\.env\b"                   # dotenv files
    r"|/\.netrc\b)"
)


def is_secret_path(path) -> bool:
    if not path:
        return False
    return _SECRET_PATH_RX.search(path) is not None


def extract_path(envelope: dict):
    ti = envelope.get("tool_input") or {}
    if envelope.get("tool_name") == "Read":
        return ti.get("file_path")
    cmd = ti.get("command")
    if isinstance(cmd, str):
        m = _SECRET_PATH_RX.search(cmd)
        if m:
            return cmd[m.start():m.end()]
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/read_guard/core.py tests/test_read_guard.py
git commit -m "feat: read-guard path amplifier (is_secret_path/extract_path)"
```

---

### Task 5: Decision matrix — `decide` (Option 3)

**Files:**
- Modify: `src/security_scan/read_guard/core.py`
- Test: `tests/test_read_guard.py`

**Interfaces:**
- Produces: `core.Decision` dataclass with fields `action: str` (one of `"passthrough"`, `"redact"`, `"suppress"`, `"fail_open"`), `output: str | None` (the replacement text for redact/suppress, else None), `match_count: int`, `matched_path: str | None`.
- Produces: `core.decide(envelope: dict) -> Decision`.
- Produces: `core.SUPPRESS_MESSAGE` (str).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_read_guard.py
import pytest


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: FAIL with `AttributeError: ... 'Decision'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/security_scan/read_guard/core.py
from dataclasses import dataclass

SUPPRESS_MESSAGE = ("[OUTPUT WITHHELD by read-guard: a BWS token was present and "
                    "could not be safely redacted. Fetch the value at runtime from "
                    "Keychain/BWS; do not read the file.]")


@dataclass
class Decision:
    action: str            # passthrough | redact | suppress | fail_open
    output: str | None = None
    match_count: int = 0
    matched_path: str | None = None


def decide(envelope: dict) -> Decision:
    path = extract_path(envelope)
    output = envelope.get("tool_output")
    if not isinstance(output, str):                 # cannot read content
        if is_secret_path(path):
            return Decision("suppress", SUPPRESS_MESSAGE, 0, path)
        return Decision("fail_open", None, 0, path)
    try:
        matches = scan_for_bws(output)
    except Exception:                               # scan blew up
        if is_secret_path(path):
            return Decision("suppress", SUPPRESS_MESSAGE, 0, path)
        return Decision("fail_open", None, 0, path)
    if not matches:
        return Decision("passthrough", None, 0, path)
    try:
        return Decision("redact", redact(output, matches), len(matches), path)
    except Exception:
        return Decision("suppress", SUPPRESS_MESSAGE, 0, path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/read_guard/core.py tests/test_read_guard.py
git commit -m "feat: read-guard Option-3 decision matrix"
```

---

### Task 6: Hook entry — stdin/stdout contract + audit log

**Files:**
- Create: `src/security_scan/read_guard/hook.py`
- Create: `src/security_scan/read_guard/audit.py`
- Test: `tests/test_read_guard.py`

**Interfaces:**
- Consumes: `core.decide`, `core.Decision`.
- Produces: `audit.log_event(now, session_id, tool_name, event, matched_path, match_count) -> None` — appends one JSON line to the audit log path (overridable via `READ_GUARD_AUDIT_LOG` env for tests). `hook.run(stdin_text: str, *, now: str) -> str` — pure-ish: takes the raw stdin JSON, returns the stdout JSON string (empty string == passthrough/exit-0). `hook.main()` — reads `sys.stdin`, calls `run`, prints, exits 0.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_read_guard.py
import json
import os


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'security_scan.read_guard.hook'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/security_scan/read_guard/audit.py
import json
import os

_DEFAULT = os.path.expanduser("~/.claude/audit/high-power-actions.jsonl")


def log_path() -> str:
    return os.environ.get("READ_GUARD_AUDIT_LOG", _DEFAULT)


def log_event(now, session_id, tool_name, event, matched_path, match_count) -> None:
    rec = {"timestamp": now, "tool": "read-guard", "session_id": session_id or "",
           "event": event, "tool_name": tool_name or "", "matched_path": matched_path,
           "match_count": match_count}
    path = log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass  # never let audit failure break the tool result
```

```python
# src/security_scan/read_guard/hook.py
"""PostToolUse hook entry for the BWS read-guard. Thin I/O over core.decide."""
import json
import sys
from datetime import datetime, timezone

from security_scan.read_guard import audit, core

_CONTEXT = ("A BWS token was withheld from this output by the read-guard. Fetch it at "
            "runtime from the login Keychain (security find-generic-password ...) or BWS "
            "— do not read the file. See ~/.claude/CLAUDE.md 'Secure Way of Working'.")


def run(stdin_text: str, *, now: str) -> str:
    try:
        env = json.loads(stdin_text)
        if not isinstance(env, dict):
            raise ValueError("envelope not an object")
    except Exception:
        # Cannot even parse the envelope: fail open, log the gap, never block.
        audit.log_event(now, None, None, "fail_open_gap", None, 0)
        return ""

    d = core.decide(env)
    sid = env.get("session_id")
    tool = env.get("tool_name")

    if d.action == "passthrough":
        return ""
    if d.action == "fail_open":
        audit.log_event(now, sid, tool, "fail_open_gap", d.matched_path, 0)
        return ""

    # redact or suppress -> emit a rewrite + log it
    audit.log_event(now, sid, tool, d.action, d.matched_path, d.match_count)
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "updatedToolOutput": d.output,
        "additionalContext": _CONTEXT,
    }})


def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = run(sys.stdin.read(), now=now)
    if out:
        sys.stdout.write(out)
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/read_guard/hook.py src/security_scan/read_guard/audit.py tests/test_read_guard.py
git commit -m "feat: read-guard hook entry + audit logging"
```

---

### Task 7: Bash shim + settings wiring (live invocation test)

**Files:**
- Create: `~/.claude/hooks/bws-read-guard.sh`
- Modify: `~/.claude/settings.json` (PostToolUse array)

**Interfaces:**
- Consumes: `python3 -m security_scan.read_guard.hook` with `PYTHONPATH` pointing at the repo `src`.

- [ ] **Step 1: Create the shim**

```bash
# ~/.claude/hooks/bws-read-guard.sh
#!/usr/bin/env bash
# PostToolUse read-guard: redacts BWS tokens out of Read/Bash output before they
# persist to the transcript. Pure logic lives in the security_scan package.
exec /usr/bin/env PYTHONPATH="$HOME/Projects/security-standards/src" \
    python3 -m security_scan.read_guard.hook
```

Then: `chmod +x ~/.claude/hooks/bws-read-guard.sh`

- [ ] **Step 2: Verify the shim end-to-end with a synthetic envelope**

Run (constructs a token inline so no literal is stored):

```bash
T="0.$(uuidgen | tr 'A-F' 'a-f').$(printf 'A%.0s' {1..30})"
printf '{"session_id":"t","tool_name":"Read","tool_input":{"file_path":"/x/.env"},"tool_output":"tok=%s\\n"}' "$T" \
  | ~/.claude/hooks/bws-read-guard.sh
```

Expected: JSON on stdout containing `"hookEventName":"PostToolUse"` and `updatedToolOutput` with `[REDACTED` — and NOT containing the value of `$T`.

- [ ] **Step 3: Verify passthrough emits nothing**

Run:

```bash
printf '{"session_id":"t","tool_name":"Bash","tool_input":{"command":"ls"},"tool_output":"clean\\n"}' \
  | ~/.claude/hooks/bws-read-guard.sh; echo "[exit=$?]"
```

Expected: no stdout before `[exit=0]`.

- [ ] **Step 4: Wire into settings**

In `~/.claude/settings.json`, add this object to the existing `hooks.PostToolUse` array (alongside the `.*` high-power-audit-log entry):

```json
{
  "matcher": "Read|Bash",
  "hooks": [
    { "type": "command", "command": "/Users/devon/.claude/hooks/bws-read-guard.sh" }
  ]
}
```

- [ ] **Step 5: Validate JSON and confirm Claude Code reloads settings**

Run: `python3 -c "import json; json.load(open('$HOME/.claude/settings.json')); print('settings.json valid')"`
Expected: `settings.json valid`

(Settings reload on next prompt; no commit — these files are outside the repo.)

---

### Task 8: Live wiring + field-name validation (manual / layer 5)

**Files:**
- Create: `docs/superpowers/notes/2026-06-17-read-guard-live-verification.md` (record the result)

**Interfaces:** none (verifies the installed Claude Code honors `updatedToolOutput`).

- [ ] **Step 1: Create a runtime fixture (no literal token committed)**

```bash
mkdir -p /tmp/rg && T="0.$(uuidgen | tr 'A-F' 'a-f').$(printf 'A%.0s' {1..30})"
printf 'config\nBWS_ACCESS_TOKEN=%s\nend\n' "$T" > /tmp/rg/fixture.env
echo "$T" > /tmp/rg/expected-token.txt
```

- [ ] **Step 2: Drive a real read through Claude Code (headless)**

Run: `claude -p "Read the file /tmp/rg/fixture.env and show me its exact contents." --output-format text > /tmp/rg/session-out.txt 2>&1`

- [ ] **Step 3: Assert the token did not surface**

Run:

```bash
if grep -qFf /tmp/rg/expected-token.txt /tmp/rg/session-out.txt; then
  echo "FAIL: token leaked into model output"; else echo "PASS: token redacted"; fi
grep -c "REDACTED" /tmp/rg/session-out.txt
```

Expected: `PASS: token redacted` and a non-zero REDACTED count.

- [ ] **Step 4: Record result + field-name confirmation**

Write `docs/superpowers/notes/2026-06-17-read-guard-live-verification.md` stating: the installed Claude Code version (`claude --version`), that `updatedToolOutput`/`additionalContext` were honored (PASS), and any field-name discrepancy found. **If the field names differ from the plan**, fix `hook.py` to match the installed contract, re-run Task 6 tests, and re-run this task.

- [ ] **Step 5: Clean up + commit the note**

```bash
rm -rf /tmp/rg
git add docs/superpowers/notes/2026-06-17-read-guard-live-verification.md
git commit -m "docs: read-guard live wiring verification"
```

---

### Task 9: Performance budget test

**Files:**
- Test: `tests/test_read_guard.py`

**Interfaces:** none new.

- [ ] **Step 1: Write the test**

```python
# add to tests/test_read_guard.py
import time as _time


def test_scan_large_output_is_fast():
    big = ("x" * 1_000_000 + "\n") * 10  # ~10 MB, no token
    start = _time.perf_counter()
    assert core.scan_for_bws(big) == []
    assert _time.perf_counter() - start < 1.0  # well under any hook timeout
```

- [ ] **Step 2: Run + verify pass**

Run: `python -m pytest tests/test_read_guard.py::test_scan_large_output_is_fast -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_read_guard.py
git commit -m "test: read-guard performance budget on large output"
```

---

### Task 10: Adversarial / known-limits tests (documented boundaries)

**Files:**
- Test: `tests/test_read_guard.py`

**Interfaces:** none new.

- [ ] **Step 1: Write the tests (these codify §9 non-goals — they assert the LIMITATION)**

```python
# add to tests/test_read_guard.py
def test_known_limit_transformed_token_not_caught():
    # Token reversed before printing is intentionally NOT detected (documented).
    t = _synth_token()
    assert core.scan_for_bws(t[::-1]) == []


def test_known_limit_token_not_in_output_not_redacted():
    # Read-and-use-without-printing: nothing in the output, nothing to redact.
    d = core.decide({"tool_name": "Bash", "tool_input": {"command": "python use.py"},
                     "tool_output": "done\n"})
    assert d.action == "passthrough"
```

- [ ] **Step 2: Run + verify pass**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: PASS (full suite)

- [ ] **Step 3: Commit**

```bash
git add tests/test_read_guard.py
git commit -m "test: read-guard documented known-limit boundaries"
```

---

### Task 11: CI + packaging + docs

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/security-scan.yml`
- Modify: `README.md` (or the scripts/README documenting the defense layers)

**Interfaces:** none new.

- [ ] **Step 1: Declare the test dependency**

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = ["pytest>=7.0"]
```

- [ ] **Step 2: Add the read-guard test step to CI**

In `.github/workflows/security-scan.yml`, after the `pip install -e .` step, add:

```yaml
      - name: Install test deps
        run: pip install -e ".[dev]"
      - name: Read-guard tests
        run: python -m pytest tests/test_read_guard.py -v
```

- [ ] **Step 3: Run the full suite locally**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: PASS (all tests across tasks 1–10)

- [ ] **Step 4: Document the read side of PREVENT**

Add a short subsection to `README.md` describing the read-guard: agent-scoped PostToolUse hook, redacts BWS tokens out of `Read`/`Bash` output (content-shape + path amplifier, Option-3 fail-safe), canonical shape in `security_scan.token_shapes`, wired via `~/.claude/hooks/bws-read-guard.sh`. Cross-reference the design doc `docs/superpowers/specs/2026-06-17-bws-read-guard-design.md`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .github/workflows/security-scan.yml README.md
git commit -m "ci+docs: wire read-guard tests, declare pytest, document PREVENT read side"
```

- [ ] **Step 6: Update the defense-layers memory (agent action, not a repo file)**

Update `security-defense-layers.md` memory: layer 1 (PREVENT) now has both a write side (`bws-write-guard.sh`) and a read side (`bws-read-guard.sh` → `security_scan.read_guard`). Link `[[bws-write-guard-blocks-doc-pattern]]`.

---

## Notes for the implementer

- **The hook runs on every `Read` and `Bash` result**, adding ~Python-startup latency per call. Keep `core`/`hook` imports stdlib-only (no heavy deps) so startup stays fast. This is the reason the core is small and dependency-free.
- **Passthrough must stay zero-rewrite.** The single most important behavioral invariant: when no token is found, emit nothing. Never round-trip clean output through a rewrite — that is how fidelity bugs happen.
- **No literal tokens, ever.** Every test builds tokens by concatenation at runtime. If you ever see a literal `0.`-uuid-secret string about to land in a file, stop — the write-guard will (correctly) deny it.
- **Field-name risk is real.** Task 8 is the gate that proves the installed Claude Code honors `updatedToolOutput`/`additionalContext`. Do not skip it; if names differ, the fix is localized to `hook.py`.
```
