#!/usr/bin/env bash
# SessionStart hook — keep `main` current before coding begins.
#
# security-standards is the source of truth for the deployed control-plane
# artifacts: the weekly scan runner (~/.claude/bin/security-scan.sh), the BWS
# enforcement hooks, and the read-guard — all installed by `make install`
# (security_scan.governance deploy) FROM THIS LOCAL CHECKOUT, not from CI. So a
# stale `main` means `make install` would deploy stale enforcement code and
# `make verify` would then disagree with governance-map.toml (see CLAUDE.md).
# This hook fast-forwards `main` to origin at session start *only when it's safe*
# — on `main`, clean tree, behind origin. Otherwise it just informs and does
# nothing. It NEVER blocks session start and NEVER switches branches or deletes
# anything.
#
# Output: a SessionStart JSON object whose additionalContext is injected into the
# agent's context, so the agent starts knowing the repo is current (or why it isn't).
set -u

emit() {  # emit <message>  — inject context, then exit cleanly
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$1"
  exit 0
}
silent() { printf '{"suppressOutput":true}\n'; exit 0; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd)" || silent
cd "$REPO" 2>/dev/null || silent
git rev-parse --git-dir >/dev/null 2>&1 || silent

# Fetch latest; if it fails (offline), don't nag and don't block.
git fetch --quiet origin 2>/dev/null || silent

behind="$(git rev-list --count main..origin/main 2>/dev/null || echo 0)"
[ "${behind:-0}" -gt 0 ] 2>/dev/null || silent   # main already current → stay quiet

branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || echo DETACHED)"
dirty=""; [ -n "$(git status --porcelain 2>/dev/null)" ] && dirty=" with uncommitted changes"

if [ "$branch" = "main" ] && [ -z "$dirty" ]; then
  if git merge --ff-only origin/main >/dev/null 2>&1; then
    emit "[session-sync] main was ${behind} commit(s) behind origin; fast-forwarded to $(git rev-parse --short HEAD). Repo is current — safe to start."
  fi
  emit "[session-sync] main is ${behind} behind origin but fast-forward failed (diverged?). Run 'git sync' or inspect before coding."
fi

emit "[session-sync] main is ${behind} commit(s) behind origin, but you are on '${branch}'${dirty}; not auto-syncing. Run 'git sync' when ready to update main."
