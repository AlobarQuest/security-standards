# Read-guard v2 — live wiring verification (2026-06-17)

PreToolUse content-peek + deny read-guard, wired and validated against `main`'s package.

## Setup
- Shim: `~/.claude/hooks/bws-read-guard.sh` → `PYTHONPATH=…/security-standards/src python3 -m security_scan.read_guard.hook`
- Wiring: `~/.claude/settings.json` PreToolUse matchers now `["Edit|Write|NotebookEdit", ".*", "Bash", "Read"]` (the `Read` entry is the read-guard).

## Live validation (via the real `Read` tool, hook active)
- **Read a token-bearing fixture** (`/tmp/rgv/secret.env`, synthetic `0.<uuid>.<secret>` built at runtime) → **DENIED**. The tool returned the deny reason ("This file contains a BWS token; the read was blocked … fetch from the Keychain …"); the file contents (and the token) never entered the transcript.
- **Read a normal file** (`/tmp/rgv/clean.txt`) → **ALLOWED**, contents returned unchanged.

## Field/mechanism confirmation
- The installed Claude Code honors a PreToolUse `permissionDecision:"deny"` (under `hookSpecificOutput`) for the `Read` tool — the read is blocked and the reason surfaces to the agent. (Contrast: PostToolUse output-rewrite is NOT supported — see the shelved v1 design.)
- The deny path logs a value-free `deny` event to the audit log (event/path/match_count only — never the token value).

## Result: PASS. Read-guard is live (Read-tool scope).
Cleanup: `/tmp/rgv` removed after validation.
