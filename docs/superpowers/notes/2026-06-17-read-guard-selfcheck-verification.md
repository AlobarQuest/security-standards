# Read-guard self-check — live wiring verification (2026-06-17)

Both halves of the self-check are wired and verified against the live machine.

## SessionStart presence check
- `~/.claude/hooks/session-start.sh` runs `python -m security_scan.read_guard.selfcheck`
  (presence) after its existing bookkeeping. On failure it emits a SessionStart warning
  (`additionalContext`) and appends a value-free `guard-down` line to the audit log. Never blocks.
- **Verified:** guard healthy → silent, exit 0. Simulated broken guard (`chmod -x` the shim) →
  presence reports `FAIL - shim not executable`, the session-start warning fired
  ("read-guard is NOT wired/healthy …"), and a `guard-down` audit line was written. Restored `+x` → OK.
  (Note: running session-start.sh outside a GUI session exits 1 on the iCloud-docs path — pre-existing,
  unrelated to this block, which is inert when the guard is healthy.)

## Weekly canary (Check 12)
- Added to the infraops-managed weekly scanner source `~/Projects/infraops-mcp-server/scripts/security-scan.sh`
  (commit `infraops-mcp-server@a363b84`), deployed byte-identical to `~/.claude/bin/security-scan.sh`
  via `install-security-scan-launchd.sh` (which also reloads the `com.devon.security-scan` LaunchAgent).
- Runs `selfcheck --canary` (presence + an end-to-end canary through the real shim). A FAIL flows into
  the existing weekly email/Healthchecks alerting. Catches *functional* breakage the presence check
  can't (e.g. security-standards on a branch without the package → shim runs, import fails, fails open).
- **Verified:** the deployed scanner emits `PASS readguard.health — read-guard wired + canary ok`.
  The canary isolates its audit writes to a temp path — the real `high-power-actions.jsonl` stayed clean.

## Known follow-ups (flagged, not done here)
- The next 3am `security-drift` self-check will surface **one expected** `selfcheck.runner_integrity`
  URGENT ("scanner hash changed — verify intentional") because the deployed scanner hash changed; it
  then records the new hash. By design.
- The sibling weekly-scan tooling in infraops is still **untracked**: `skills-security-scan.sh`,
  `install-security-scan-launchd.sh`, `com.devon.security-scan.plist.template`. Pre-existing; bring
  under version control separately.
- The read-guard **wiring** (`session-start.sh` block, `bws-read-guard.sh` shim, the settings.json
  PreToolUse `Read` entry) is still machine-local and un-versioned — the self-check now *detects* its
  drift, but an installer to make the wiring *reproducible* is the remaining resilience step.
