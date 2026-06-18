#!/bin/bash
# bws-scan-gate v1 — Stop hook.
# When a session finishes, run the security-standards scanner against the repo
# and block stopping if any BLOCK finding is present (committed/historical token,
# missing secret-file gitignore coverage, BWS manifest drift) so the session must
# remediate before it can end. Silent on clean repos and repos that use no BWS.
# Fail-open: any error here must let the session stop, never trap it.
set -u

INPUT=$(cat 2>/dev/null)
command -v jq >/dev/null 2>&1 || exit 0

# Avoid the Stop-hook loop: if we already blocked once this turn, let it stop.
ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)
[ "$ACTIVE" = "true" ] && exit 0

CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[ -n "$CWD" ] || CWD="$PWD"

SCANNER_SRC="$HOME/Projects/security-standards/src"
[ -d "$SCANNER_SRC" ] || exit 0   # scanner not present → nothing to enforce

# Only gate inside a real git work tree. The scanner deliberately fail-closes to
# BLOCK on non-git dirs (correct for an explicit audit, wrong for an always-on
# gate), so skip those here rather than trap every non-repo session.
git -C "$CWD" rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

REPORT=$(PYTHONPATH="$SCANNER_SRC" python3 -m security_scan.cli "$CWD" --category security 2>/dev/null)
CODE=$?
[ "$CODE" -eq 0 ] && exit 0   # clean, or scanner unavailable → don't trap the session

# Non-zero = at least one active BLOCK finding. Summarize (scanner already redacts).
SUMMARY=$(printf '%s' "$REPORT" | jq -r '
  [ .findings[] | select(.severity=="BLOCK")
    | "• \(.rule_id) — \(.file // "repo")\(if .line then ":\(.line)" else "" end): \(.remediation)" ]
  | join("\n")' 2>/dev/null)
[ -n "$SUMMARY" ] || exit 0   # couldn't parse → fail open, don't trap

jq -nc --arg r "SECURITY-STANDARDS gate: this repo has BLOCK-level findings that must be fixed before finishing. If a token is committed or present in git history, treat it as LEAKED and ROTATE it — deletion alone is not enough.

$SUMMARY

Re-run the scan: PYTHONPATH=\"$SCANNER_SRC\" python3 -m security_scan.cli . --category security" \
  '{decision:"block",reason:$r}'
exit 0
