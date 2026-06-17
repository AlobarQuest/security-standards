# Design: BWS read-guard v2 — PreToolUse content-peek + deny (Read tool)

**Date:** 2026-06-17 · **Owner:** Devon · **Status:** implemented
**Supersedes:** `2026-06-17-bws-read-guard-design.md` (the PostToolUse-redact design — SHELVED:
PostToolUse hooks cannot modify/suppress tool output on this Claude Code; see project memory
`posttooluse-cannot-redact-output`).

## 1. Purpose & threat

Keep the agent from **accidentally** reading a BWS access token into its (persistent) transcript.
The primary prevention — no plaintext tokens on disk — is already done (the Keychain migration).
This is the backstop for residual/future secret files. Threat model is **accidental**, not a
determined adversary: even an imperfect, Read-tool-scoped guard is worth it because nothing is
trying to bypass it.

## 2. Why PreToolUse + deny (the pivot)

A PreToolUse hook fires **before** the tool runs, so the file's contents are **not yet in the
transcript**, and — crucially — the hook runs as the user and can **open the target file itself**.
So it can content-scan the real bytes and `permissionDecision:"deny"` the Read before it executes.
This uses only the **`deny`** capability (confirmed working — the write-guard denies writes), not
output-rewrite (which this Claude Code does not support). Proven viable by an in-session probe
(2026-06-17): a token-bearing file was denied with a redirect; a normal file passed through.

Tradeoff (accepted): clean for the **Read** tool; **Bash** is out of scope for v1 (its output isn't
knowable pre-run; command-text parsing is fragile/bypassable, and the accidental vector is
overwhelmingly the Read tool).

## 3. Settled decisions

- **Action:** `deny` + a Keychain/BWS redirect message. No allowlist escape in v1 (content-peek is
  content-accurate → near-zero false positives; add an escape later only if needed).
- **Detection:** content-peek only (scan the file bytes for the BWS token shape). **Fail-open**
  (allow) when the file is missing / unreadable / oversized / binary. No gitignore/mode/filename
  amplifiers in v1 (secret files are tiny and always scannable — amplifiers are deferred).
- **Tool scope:** `Read` only.
- **Secret shape:** BWS bare-token only — the canonical `security_scan.token_shapes.BWS_TOKEN_RX`
  (shape `0.<uuid>.<secret>`; kept identical to the bash write-guard), consistent with the rest of v1.
- **Size cap:** 256 KB — above it, fail-open (don't read huge files into the hook).

## 4. Architecture — repurpose the existing `security_scan.read_guard` package

The package currently holds the dead PostToolUse-redact implementation. Repurpose it cleanly:

- **Keep / reuse:**
  - `token_shapes.BWS_TOKEN_RX` — unchanged.
  - `core.scan_for_bws(text) -> list[str]` — the content detector, unchanged.
  - `audit.log_event(...)` — used to log denies (path only, never the value).
- **Delete (dead PostToolUse code — dead code in a security module is a liability):**
  `core.redact`, `core.SENTINEL`, `core.Decision`, `core.decide`, `core.is_secret_path`,
  `core.extract_path`, the old PostToolUse `hook.py`, and all tests covering them.
- **Add:**
  - `core.peek_decision(file_path: str | None, *, size_cap: int = 262144) -> PeekResult` — the pure
    decision: returns a small `PeekResult` (a NEW minimal type, not the deleted `Decision`)
    indicating `deny` (file readable, within cap, contains a token shape) or `allow` (missing /
    unreadable / oversized / binary / no match), plus the matched path. Holds no I/O contract.
  - `hook.py` — PreToolUse entry: read stdin envelope, pull `tool_input.file_path`, call
    `peek_decision`, and on `deny` emit
    `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":<redirect>}}`
    + `audit.log_event`; on `allow` exit 0 with no output. Fail-open (allow) on any exception or
    unparseable stdin.

File boundaries stay: pure logic in `core`, I/O + audit in `hook`/`audit`, shape in `token_shapes`.

## 5. Behavior (data flow)

PreToolUse on `Read` → parse envelope → `file_path = tool_input.file_path`:
1. No path / file missing / not a regular file → **allow** (exit 0).
2. `stat` size > 256 KB → **allow** (fail-open; oversized).
3. Read bytes; if undecodable/binary → **allow** (fail-open).
4. `scan_for_bws` on the content:
   - match → **deny** + redirect ("this file holds a BWS token; fetch it at runtime from the login
     Keychain (`security find-generic-password …`) or BWS by UUID — do not read the file") + audit
     a `deny` event (timestamp, tool, session_id, matched_path, match_count — no value).
   - no match → **allow**.
Any exception anywhere → **allow** + (best-effort) audit a `fail_open` event. A guard that errors
must never block a legitimate read.

## 6. Testing

- **Pure `core.peek_decision` unit tests:** token file → deny (with matched_path); clean file →
  allow; missing path → allow; oversized file → allow; binary/undecodable file → allow; `None`
  path → allow. Tokens built at runtime (no literals).
- **`hook` I/O tests:** deny → correct `permissionDecision:"deny"` JSON + redirect; allow → empty
  stdout / exit 0; malformed envelope → fail-open (empty, exit 0); audit line written on deny with
  no token value (via `READ_GUARD_AUDIT_LOG` override so the real log is never touched).
- **Live validation (in the plan, before wiring):** with the hook wired, `Read` a runtime-built
  token fixture → assert denied + no contents; `Read` a normal file → assert contents returned.
  (This is the gate the PostToolUse design lacked until the end; here it's confirmed up front and
  re-run after build.)
- **CI:** the existing `tests/test_read_guard.py` step runs the new suite.

## 7. Wiring & docs (explicit infra step, gated by live validation)

- Bash shim `~/.claude/hooks/bws-read-guard.sh` → `PYTHONPATH=…/src python3 -m
  security_scan.read_guard.hook`; settings.json **PreToolUse** `Read` entry.
- Flip README, this design's status, and the `security-defense-layers` memory from SHELVED → a
  working PreToolUse read-guard (Read-tool scope). Update the `posttooluse-cannot-redact-output`
  memory to point at the shipped PreToolUse guard.

## 8. Non-goals / known limits (deliberate, documented)

- **Bash** reads (and any non-Read tool) are not guarded in v1.
- A **determined** agent can still exfiltrate (transform-before-read, read-via-uncaught-tool); this
  guards **accidents**, layered on prevention-by-absence + audit + awareness.
- Oversized/binary secret files fail open (rare; secret files are tiny).
- Non-BWS secret types (PEM, AWS keys, …) are future scope.

## 9. Definition of done

- `read_guard` package repurposed: dead PostToolUse code removed; `peek_decision` + PreToolUse
  `hook.py` added; `scan_for_bws`/`token_shapes`/`audit` reused.
- All unit + hook tests green; CI runs them.
- Live validation passes (token file denied, normal file allowed) before wiring.
- Shim + settings wired; deny path verified end-to-end.
- README / design status / defense-layers memory updated to reflect the shipped guard.
