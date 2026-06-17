# BWS Read-Guard v2 (PreToolUse) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A PreToolUse hook that content-peeks a file the agent is about to `Read` and denies the read (with a Keychain redirect) when the file contains a BWS token — so the token never enters the transcript.

**Architecture:** Repurpose the inert `security_scan.read_guard` package (built for the failed PostToolUse-redact model). Keep `token_shapes.BWS_TOKEN_RX`, `core.scan_for_bws`, and `audit.log_event`; delete the dead PostToolUse code; add a pure `core.peek_decision` and a PreToolUse `hook.py`. A thin bash shim wires it on the `Read` tool.

**Tech Stack:** Python 3.12+ (stdlib only — `os`, `json`, `sys`, `re`, `datetime`, `dataclasses`), pytest, bash shim, Claude Code PreToolUse hook contract.

## Global Constraints

- Python floor **>=3.12**; stdlib only — no new runtime deps.
- **Never write a literal BWS token** into any file (source/test/fixture/doc). Tests build shape-matching tokens at runtime by concatenation. The canonical shape regex is `0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}` in `security_scan.token_shapes`.
- **Fail-open everywhere:** deny ONLY on a confirmed content match; any uncertainty (missing/oversized/binary/unreadable/error/malformed envelope) → allow. A guard that errors must never block a legitimate read.
- v1: **Read tool only**, **BWS bare-token shape only**, **deny + redirect** action, no allowlist.
- Size cap: **262144 bytes** (256 KB) — above it, fail-open.
- Audit lines never contain a token value (only metadata).
- Tests run with `python -m pytest tests/test_read_guard.py -v`.
- The real Claude Code PreToolUse `Read` envelope is `{tool_name:"Read", tool_input:{file_path:...}, session_id:..., ...}` (confirmed empirically). PreToolUse `deny` is honored (confirmed by the write-guard and the v2 probe).

---

### Task 1: Remove the dead PostToolUse code

**Files:**
- Modify: `src/security_scan/read_guard/core.py`
- Delete: `src/security_scan/read_guard/hook.py`
- Modify: `tests/test_read_guard.py`
- (Unchanged, kept: `audit.py`, `token_shapes.py`, `read_guard/__init__.py`)

**Interfaces:**
- After this task, `core.py` exports only `scan_for_bws(output: str) -> list[str]` (plus its import of `BWS_TOKEN_RX`). `audit.py` and `token_shapes.py` are unchanged. `read_guard/hook.py` no longer exists.

- [ ] **Step 1: Delete the dead symbols from `core.py`**

Remove from `src/security_scan/read_guard/core.py` everything EXCEPT the module docstring, `from security_scan.token_shapes import BWS_TOKEN_RX`, and `scan_for_bws`. Specifically delete: `SENTINEL`, `redact`, `import re as _re`, `_SECRET_PATH_RX`, `is_secret_path`, `extract_path`, `from dataclasses import dataclass`, `SUPPRESS_MESSAGE`, `Decision`, `decide`. The file should end as:

```python
"""Pure read-guard logic: BWS token detection. No I/O, no side effects."""
from security_scan.token_shapes import BWS_TOKEN_RX


def scan_for_bws(output: str) -> list[str]:
    """Return all BWS-token substrings present in output (empty if none)."""
    return BWS_TOKEN_RX.findall(output)
```

- [ ] **Step 2: Delete the old PostToolUse hook**

Run: `git rm src/security_scan/read_guard/hook.py`

- [ ] **Step 3: Remove orphaned tests**

In `tests/test_read_guard.py`, delete every test function that references any deleted symbol (`redact`, `SENTINEL`, `is_secret_path`, `extract_path`, `decide`, `Decision`, `SUPPRESS_MESSAGE`, or the old `hook.run`/`hook.main`). KEEP: the `_synth_token` helper, the `token_shapes` tests, the `scan_for_bws` tests, the large-output performance test, and the transformed-token known-limit test (`scan_for_bws(t[::-1]) == []`). Remove the now-unused `from security_scan.read_guard import hook` import if present; keep `from security_scan.read_guard import core` and `from security_scan import token_shapes`. Remove any import left unused by the deletions.

- [ ] **Step 4: Run the suite — confirm only the kept tests remain and pass**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: PASS, ~8 tests (token_shapes + scan_for_bws + perf + transformed-token), no errors/warnings, no references to deleted symbols.

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/read_guard/core.py src/security_scan/read_guard/hook.py tests/test_read_guard.py
git commit -m "refactor: remove dead PostToolUse read-guard code (infeasible mechanism)"
```

---

### Task 2: Add `core.peek_decision` + `PeekResult`

**Files:**
- Modify: `src/security_scan/read_guard/core.py`
- Test: `tests/test_read_guard.py`

**Interfaces:**
- Consumes: `core.scan_for_bws`.
- Produces: `core.PeekResult` (dataclass: `action: str` one of `"deny"`/`"allow"`, `matched_path: str | None = None`, `match_count: int = 0`) and `core.peek_decision(file_path: str | None, *, size_cap: int = 262144) -> PeekResult`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_read_guard.py
def test_peek_denies_file_with_token(tmp_path):
    t = _synth_token()
    f = tmp_path / "secret.env"
    f.write_text(f"config=hello\nBWS_ACCESS_TOKEN={t}\n")
    d = core.peek_decision(str(f))
    assert d.action == "deny" and d.matched_path == str(f) and d.match_count == 1


def test_peek_allows_clean_file(tmp_path):
    f = tmp_path / "clean.txt"
    f.write_text("nothing secret here\njust text\n")
    assert core.peek_decision(str(f)).action == "allow"


def test_peek_allows_missing_path_and_none():
    assert core.peek_decision(str("/no/such/file/xyz.env")).action == "allow"
    assert core.peek_decision(None).action == "allow"


def test_peek_allows_oversized_file(tmp_path):
    t = _synth_token()
    f = tmp_path / "big.env"
    f.write_text("x" * 1000 + f"\n{t}\n")
    assert core.peek_decision(str(f), size_cap=100).action == "allow"  # token present but over cap


def test_peek_allows_binary_file(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\x01\x02\xff\xfe" * 10)
    assert core.peek_decision(str(f)).action == "allow"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_read_guard.py -k peek -v`
Expected: FAIL with `AttributeError: ... 'peek_decision'`

- [ ] **Step 3: Implement**

```python
# add to src/security_scan/read_guard/core.py (with imports `import os` and
# `from dataclasses import dataclass` at the top, after the existing import)
import os
from dataclasses import dataclass


@dataclass
class PeekResult:
    action: str            # "deny" | "allow"
    matched_path: str | None = None
    match_count: int = 0


def peek_decision(file_path: str | None, *, size_cap: int = 262144) -> PeekResult:
    """Decide whether a Read of file_path should be denied (file contains a BWS
    token) or allowed. Fail-open: any uncertainty returns allow."""
    if not isinstance(file_path, str) or not file_path:
        return PeekResult("allow")
    try:
        if not os.path.isfile(file_path):
            return PeekResult("allow", file_path)
        if os.path.getsize(file_path) > size_cap:
            return PeekResult("allow", file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return PeekResult("allow", file_path)
    matches = scan_for_bws(content)
    if matches:
        return PeekResult("deny", file_path, len(matches))
    return PeekResult("allow", file_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: PASS (all kept tests + 5 new peek tests)

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/read_guard/core.py tests/test_read_guard.py
git commit -m "feat: read-guard peek_decision (content-peek, fail-open)"
```

---

### Task 3: Add the PreToolUse `hook.py`

**Files:**
- Create: `src/security_scan/read_guard/hook.py`
- Test: `tests/test_read_guard.py`

**Interfaces:**
- Consumes: `core.peek_decision`, `audit.log_event(now, session_id, tool_name, event, matched_path, match_count)`.
- Produces: `hook.run(stdin_text: str, *, now: str) -> str` (`""` == allow; on deny, the `permissionDecision:"deny"` JSON string) and `hook.main()`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_read_guard.py
import json


def test_hook_denies_read_of_token_file(tmp_path):
    from security_scan.read_guard import hook
    t = _synth_token()
    f = tmp_path / "secret.env"
    f.write_text(f"BWS_ACCESS_TOKEN={t}\n")
    env = json.dumps({"session_id": "s", "tool_name": "Read",
                      "tool_input": {"file_path": str(f)}})
    out = hook.run(env, now="2026-06-17T00:00:00Z")
    obj = json.loads(out)["hookSpecificOutput"]
    assert obj["hookEventName"] == "PreToolUse"
    assert obj["permissionDecision"] == "deny"
    assert "Keychain" in obj["permissionDecisionReason"]
    assert t not in out


def test_hook_allows_clean_file(tmp_path):
    from security_scan.read_guard import hook
    f = tmp_path / "clean.txt"
    f.write_text("nothing here\n")
    env = json.dumps({"session_id": "s", "tool_name": "Read",
                      "tool_input": {"file_path": str(f)}})
    assert hook.run(env, now="2026-06-17T00:00:00Z") == ""


def test_hook_malformed_envelope_fail_open():
    from security_scan.read_guard import hook
    assert hook.run("not json{", now="2026-06-17T00:00:00Z") == ""


def test_hook_audit_written_on_deny_no_value(tmp_path, monkeypatch):
    from security_scan.read_guard import hook
    monkeypatch.setenv("READ_GUARD_AUDIT_LOG", str(tmp_path / "a.jsonl"))
    t = _synth_token()
    f = tmp_path / "secret.env"
    f.write_text(f"{t}\n")
    env = json.dumps({"session_id": "s", "tool_name": "Read",
                      "tool_input": {"file_path": str(f)}})
    hook.run(env, now="2026-06-17T00:00:00Z")
    line = (tmp_path / "a.jsonl").read_text().strip()
    rec = json.loads(line)
    assert rec["event"] == "deny" and rec["tool"] == "read-guard" and t not in line
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_read_guard.py -k hook -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'security_scan.read_guard.hook'`

- [ ] **Step 3: Implement**

```python
# src/security_scan/read_guard/hook.py
"""PreToolUse hook for the BWS read-guard. Denies a Read whose target file
contains a BWS token, before the read executes. Thin I/O over core.peek_decision."""
import json
import sys
from datetime import datetime, timezone

from security_scan.read_guard import audit, core

_REDIRECT = ("This file contains a BWS token; the read was blocked so the token does not "
             "enter the transcript. Fetch the value at runtime from the login Keychain "
             "(security find-generic-password ...) or BWS by UUID — do not read the file.")


def run(stdin_text: str, *, now: str) -> str:
    try:
        env = json.loads(stdin_text)
        if not isinstance(env, dict):
            raise ValueError("envelope not an object")
    except Exception:
        return ""  # fail-open: cannot parse -> allow
    tool = env.get("tool_name")
    sid = env.get("session_id")
    fp = (env.get("tool_input") or {}).get("file_path")
    try:
        d = core.peek_decision(fp)
    except Exception:
        audit.log_event(now, sid, tool, "fail_open", fp if isinstance(fp, str) else None, 0)
        return ""
    if d.action == "deny":
        audit.log_event(now, sid, tool, "deny", d.matched_path, d.match_count)
        return json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"{_REDIRECT} (file: {d.matched_path})",
        }})
    return ""  # allow


def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = run(sys.stdin.read(), now=now)
    if out:
        sys.stdout.write(out)
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_read_guard.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/security_scan/read_guard/hook.py tests/test_read_guard.py
git commit -m "feat: read-guard PreToolUse hook (deny Read of token-bearing files)"
```

---

### Task 4: Live validation + wiring (CONTROLLER-DIRECT infra step — not a subagent)

**Files:**
- Create: `~/.claude/hooks/bws-read-guard.sh`
- Modify: `~/.claude/settings.json` (PreToolUse `Read` entry)
- Create: `docs/superpowers/notes/2026-06-17-read-guard-v2-live-verification.md`

> **Note:** these touch live `~/.claude` config. The controller does this directly (not a subagent), in safety order: shim → verify against the package → wire → live-validate → record. The branch must be merged to `main` first so `…/src` on disk has the package.

- [ ] **Step 1: Create the shim**

```bash
# ~/.claude/hooks/bws-read-guard.sh
#!/usr/bin/env bash
# PreToolUse read-guard: denies a Read whose target file contains a BWS token,
# before the read executes. Pure logic lives in the security_scan package.
exec /usr/bin/env PYTHONPATH="$HOME/Projects/security-standards/src" \
    python3 -m security_scan.read_guard.hook
```
Then: `chmod +x ~/.claude/hooks/bws-read-guard.sh`

- [ ] **Step 2: Verify the shim against the package (no token printed)**

```bash
mkdir -p /tmp/rgv && T="0.$(uuidgen | tr 'A-F' 'a-f').$(printf 'A%.0s' {1..30})"
printf 'BWS_ACCESS_TOKEN=%s\n' "$T" > /tmp/rgv/secret.env
printf 'clean file\n' > /tmp/rgv/clean.txt
printf '{"tool_name":"Read","tool_input":{"file_path":"/tmp/rgv/secret.env"}}' | ~/.claude/hooks/bws-read-guard.sh | python3 -c "import sys,json;print('secret ->',json.load(sys.stdin)['hookSpecificOutput']['permissionDecision'])"
printf '{"tool_name":"Read","tool_input":{"file_path":"/tmp/rgv/clean.txt"}}' | ~/.claude/hooks/bws-read-guard.sh; echo "[clean -> exit $? empty=allow]"
```
Expected: `secret -> deny`; clean → empty output, exit 0.

- [ ] **Step 3: Wire into settings.json**

Add to the existing `hooks.PreToolUse` array:
```json
{
  "matcher": "Read",
  "hooks": [
    { "type": "command", "command": "/Users/devon/.claude/hooks/bws-read-guard.sh" }
  ]
}
```
Then validate: `python3 -c "import json; json.load(open('$HOME/.claude/settings.json')); print('valid')"`

- [ ] **Step 4: Live validation (the gate)**

With the hook wired, use the Read TOOL on `/tmp/rgv/secret.env` → expect a deny error with the Keychain redirect and NO file contents. Use the Read TOOL on `/tmp/rgv/clean.txt` → expect contents returned. Record both outcomes.

- [ ] **Step 5: Record + clean up**

Write `docs/superpowers/notes/2026-06-17-read-guard-v2-live-verification.md` (Claude Code version, the two outcomes = PASS). Remove the temp dir: `rm -f /tmp/rgv/secret.env /tmp/rgv/clean.txt && rmdir /tmp/rgv`. Commit the note:
```bash
git add docs/superpowers/notes/2026-06-17-read-guard-v2-live-verification.md
git commit -m "docs: read-guard v2 live wiring verification"
```

---

### Task 5: Docs + CI (flip SHELVED → shipped)

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/security-scan.yml` (confirm the read-guard test step still runs)
- Modify: `docs/superpowers/specs/2026-06-17-bws-read-guard-pretooluse-design.md` (status → implemented)

- [ ] **Step 1: Update the README read-guard section**

Replace the `## Read-guard (SHELVED …)` section with a section describing the shipped guard: a **PreToolUse** hook on the `Read` tool that content-peeks the target file and denies the read (Keychain redirect) when it contains a BWS token (shape `0.<uuid>.<secret>`, from `security_scan.token_shapes`); fail-open on any uncertainty; Read-tool scope (Bash out of scope v1); wired via `~/.claude/hooks/bws-read-guard.sh`. Cross-reference `docs/superpowers/specs/2026-06-17-bws-read-guard-pretooluse-design.md`. No literal token in the README (placeholder shape only).

- [ ] **Step 2: Confirm CI runs the suite**

Verify `.github/workflows/security-scan.yml` still has the `python -m pytest tests/test_read_guard.py -v` step (added previously). If present, no change. Run locally: `python -m pytest tests/test_read_guard.py -v` → all pass.

- [ ] **Step 3: Flip the design-doc status**

In `docs/superpowers/specs/2026-06-17-bws-read-guard-pretooluse-design.md`, change `**Status:** approved design, pre-implementation` to `**Status:** implemented`.

- [ ] **Step 4: Commit**

```bash
git add README.md .github/workflows/security-scan.yml docs/superpowers/specs/2026-06-17-bws-read-guard-pretooluse-design.md
git commit -m "docs+ci: ship PreToolUse read-guard (README, design status)"
```

- [ ] **Step 5: Update memory (controller action, not a repo file)**

Update the `security-defense-layers` memory: PREVENT read side is now a SHIPPED PreToolUse content-peek+deny guard (Read tool), not shelved. Update `posttooluse-cannot-redact-output` to note the shipped PreToolUse alternative.

---

## Notes for the implementer

- **Fail-open is the whole safety model.** Re-read it: deny ONLY on a confirmed content match; every error/edge → allow. Never let the guard block a legitimate read.
- **No literal tokens, ever.** Tests build tokens by concatenation (`_synth_token`); fixtures in Task 4 are built in bash with `uuidgen`. A literal token would trip the write-guard + scan-gate.
- **The deny field is `permissionDecision` under `hookSpecificOutput`** — same contract the write-guard uses. Confirmed honored for the Read tool by the v2 probe.
- **Tasks 1–3 and 5 are repo work (subagents). Task 4 is controller-direct** (live `~/.claude` config + the Read-tool validation), done after the branch merges to `main`.
