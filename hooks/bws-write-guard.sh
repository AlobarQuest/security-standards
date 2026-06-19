#!/bin/bash
# bws-write-guard v1 — PreToolUse hook for Edit|Write|NotebookEdit.
# Hard-denies writing a live BWS machine-account token to disk, so the token
# never reaches the working tree regardless of what the session "knows".
# Pattern mirrors the security-standards scanner (rules_cache.json: the
# bws.no-token-in-tracked-files / bws.bootstrap-token-not-inline BLOCK rules).
# Fail-open on any parse error: a guard that crashes must not block legit writes.
#
# The bare-token regex below is mirrored in security_scan.token_shapes.BWS_TOKEN_RX
# (the canonical Python definition used by the read-guard). Keep the two identical.
# Source of truth: ~/Projects/security-standards/hooks/bws-write-guard.sh (deployed → ~/.claude/hooks/bws-write-guard.sh)
# Edit here, not in place; then: cd ~/Projects/security-standards && make install
set -u

INPUT=$(cat)
command -v jq >/dev/null 2>&1 || exit 0
[ -n "$INPUT" ] || exit 0

# Pull every field that can carry written content across Write / Edit / NotebookEdit
# (including a multi-edit `edits` array), and join them for a single scan.
CONTENT=$(printf '%s' "$INPUT" | jq -r '
  [ .tool_input.content,
    .tool_input.new_string,
    .tool_input.new_source,
    (.tool_input.edits // [] | .[]?.new_string)
  ] | map(select(. != null)) | join("\n")' 2>/dev/null)
[ -n "$CONTENT" ] || exit 0

FP=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // "the file"' 2>/dev/null)

# Two BWS token signatures:
#   bare token:    0.<uuid>.<secret>
#   inline assign: BWS_ACCESS_TOKEN = 0....   (optionally quoted)
PATTERN='0\.[0-9a-f-]{36}\.[A-Za-z0-9+/=:_-]{20,}|BWS_ACCESS_TOKEN[[:space:]]*[=:][[:space:]]*["'\'']?0\.'

if printf '%s' "$CONTENT" | grep -qE "$PATTERN"; then
  jq -nc --arg r "BWS-WRITE-GUARD: the content being written to $FP contains a live BWS machine-account token (0.<uuid>.<secret>). Tokens must never be written to a tracked file. Source it at runtime from a gitignored env file (BWS_ACCESS_TOKEN), reference secrets by UUID, and if this token was ever real, treat it as LEAKED and ROTATE it — do not just remove it. (security-standards v1)" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
fi
exit 0
