# Design: read-guard self-check + canary (resilience monitoring)

**Date:** 2026-06-17 · **Owner:** Devon · **Status:** approved design, pre-implementation
**Builds on:** the shipped PreToolUse read-guard (`2026-06-17-bws-read-guard-pretooluse-design.md`).

## 1. Purpose & threat

The read-guard's wiring lives in machine-local config (`~/.claude/hooks/bws-read-guard.sh`,
`~/.claude/settings.json`), **not** in a code repo, and the guard **fails open** by design. So a
broken or missing guard (repo moved, branch without the package, settings reset, python error)
silently removes protection with **no signal** — you believe you're protected when you aren't. For
a security control, silent failure is the dangerous mode. This feature **detects** that drift and
makes it loud, so the guard can't silently rot.

It does NOT change the guard's behavior; it monitors that the guard is present and functional.

## 2. Settled decisions

- **Check logic lives in the repo** (versioned, tested): `security_scan.read_guard.selfcheck`. The
  two runners that invoke it (`session-start.sh`, `security-scan.sh`) are un-versioned machine
  config; keeping the logic in the package is the resilience point.
- **Hybrid cadence:** a cheap **presence check at SessionStart** (every session) + a full
  **functional canary weekly** (the existing `security-scan.sh` LaunchAgent run).
- **Failure posture: warn loudly, never block, always log.** A degraded guard becomes a visible
  session warning + a weekly FAIL alert + an audit line — but never stops work and never auto-edits
  settings (no auto-repair; the operator re-runs the installer).

## 3. Architecture — `security_scan/read_guard/selfcheck.py`

A small dataclass and two pure-ish check functions plus a CLI. No changes to the guard itself.

- `Result` — dataclass `{ok: bool, detail: str}` (detail is a one-line human reason).
- `check_presence(settings_path=…, shim_path=…) -> Result` — config-level, NO subprocess:
  1. Parse `~/.claude/settings.json` (default; overridable for tests). Not-ok if unparseable.
  2. Confirm `hooks.PreToolUse` has an entry with `matcher == "Read"` whose `hooks[].command`
     equals the shim path. Not-ok (with a specific detail) if absent or pointing elsewhere.
  3. Confirm the shim file exists and is executable. Not-ok otherwise.
  Returns `ok=True` only if all hold.
- `check_canary(shim_path=…) -> Result` — functional, end-to-end through the REAL shim (so it
  validates the wiring, not just the package):
  1. Build a synthetic token at runtime (`"0." + uuid4 + "." + blob`); write it to a temp file.
  2. Pipe a `Read` envelope (`{"tool_name":"Read","tool_input":{"file_path":<temp>}}`) into the
     shim subprocess, with `READ_GUARD_AUDIT_LOG` pointed at a temp path (so the canary's deny does
     NOT pollute the real audit log).
  3. Parse the shim's stdout; ok iff `hookSpecificOutput.permissionDecision == "deny"`.
  4. Also pipe a clean temp file; ok iff the shim allows (empty output).
  5. Always clean up the temp files. Any exception → `ok=False` with the error in `detail`.
- CLI `python -m security_scan.read_guard.selfcheck` → runs `check_presence`; `--canary` → runs
  both presence and canary. Prints the detail; **exit 0 if ok, exit 1 if not** (so bash runners can
  branch on the exit code). Never raises out of the CLI.

Default `settings_path`/`shim_path` resolve to the real `~/.claude/...` locations; both are
parameters so tests point them at temp fixtures.

## 4. Wiring (the un-versioned runners invoke the versioned check) — infra step

- **SessionStart** — `~/.claude/hooks/session-start.sh` (already exists) calls the presence-check
  CLI. On exit≠0 it emits a prominent SessionStart warning into the session context (e.g.
  `⚠️ BWS read-guard is NOT wired/healthy: <detail>. You are unprotected against accidental token
  reads — re-run the read-guard installer.`) and appends a `guard-down` line to the audit log. On
  exit 0 it does nothing. Never blocks the session.
- **Weekly** — `~/.claude/bin/security-scan.sh` (the `com.devon.security-scan` LaunchAgent) runs the
  `--canary` CLI as a new check. Failure surfaces as a **FAIL finding** in the scan's existing
  output, feeding the current email/Healthchecks alerting. Non-blocking (the weekly scan is advisory).

Both runners are machine-local config (not in the repo); they are updated as the controller-direct
infra step, mirroring how the read-guard shim/settings were wired.

## 5. Audit & data-safety

- The `guard-down` audit line (SessionStart) and any canary log use the existing value-free format
  (event, detail/path, no secret value). Never logs a token.
- The canary builds tokens at runtime (no literal in any file) and isolates its audit writes to a
  temp path. No real-audit-log pollution.

## 6. Testing

- `check_presence`: ok when settings has the correct `Read`→shim entry and the shim is
  present+executable; not-ok for each failure (unparseable settings; no `Read` entry; `Read` entry
  pointing at a different command; shim missing; shim non-executable). Use temp settings.json
  fixtures + a temp shim file.
- `check_canary`: against a temp "shim" that behaves like the real one (a small script invoking the
  package, or the real shim with a temp PYTHONPATH) — ok when it denies a token file and allows a
  clean file; not-ok when the shim is missing / errors / fails to deny. Confirm `READ_GUARD_AUDIT_LOG`
  isolation (no real-log write) and temp cleanup. Tokens built at runtime.
- CLI exit codes: 0 on ok, 1 on not-ok, for both modes.
- CI runs these in `tests/` alongside the existing read-guard suite.

## 7. Non-goals / known limits (deliberate)

- **No auto-repair.** The check detects and warns; it never edits settings.json or re-installs.
- **Canary proves the shim emits `deny`, not that Claude Code honors it.** The "platform honors the
  deny" fact was validated once at wiring; the canary detects shim/package/wiring drift, which is
  the realistic failure. (Platform-behavior regression is out of scope.)
- **Does not monitor the write-guard or other hooks** — read-guard only (v1).
- **SessionStart presence check adds ~one Python startup per session** (negligible; accepted for
  every-session detection of the common failure).

## 8. Definition of done

- `security_scan.read_guard.selfcheck` with `Result`, `check_presence`, `check_canary`, and the CLI
  (exit 0/1) — in the repo, fully unit-tested, CI-run.
- `session-start.sh` runs the presence check and warns + logs on failure (never blocks).
- `security-scan.sh` runs the `--canary` check as a FAIL-on-failure step feeding existing alerts.
- Canary isolates audit writes and cleans up; no literal tokens anywhere.
- A live verification: simulate a broken guard (e.g. temporarily mis-point the shim) → confirm the
  SessionStart warning fires and the weekly canary reports FAIL; restore.
