#!/bin/bash
###############################################################################
# skills-security-scan.sh — static lint of agent skills + hooks (READ-ONLY)
# Flags dangerous *runtime instructions* that code-review of the fork misses:
# skills that invoke vps_exec without an approval note, curl|sh, eval $VAR,
# piped credential reads, and hook scripts lacking error handling.
# Exit 0 = clean, 1 = issues.
###############################################################################
# Source of truth: ~/Projects/security-standards/scripts/skills-security-scan.sh (deployed → ~/.claude/bin/skills-security-scan.sh)
# Edit here, not in place; then: cd ~/Projects/security-standards && make install
set -uo pipefail
ISSUES=0
flag() { ISSUES=$((ISSUES+1)); echo "FLAG  $1"; }

SKILL_DIRS=( "$HOME/.claude/skills" "$HOME/Developer/devon-plugins/octo" "$HOME/.claude/plugins/cache" )
for d in "${SKILL_DIRS[@]}"; do
  [ -d "$d" ] || continue
  while IFS= read -r f; do
    grep -qiE 'vps_exec' "$f" 2>/dev/null && ! grep -qiE 'approv|confirm|dangerous|CRITICAL|human' "$f" 2>/dev/null \
      && flag "$f: references vps_exec without an approval/confirmation note"
    grep -qE '(curl|wget)[^|]*\|[[:space:]]*(sh|bash)' "$f" 2>/dev/null \
      && flag "$f: pipe-to-shell (curl|sh) pattern"
    grep -qE 'eval[[:space:]]+"?\$[A-Za-z_]' "$f" 2>/dev/null \
      && flag "$f: eval of a variable"
    grep -qE '(security find-generic-password|bws secret get).*\|' "$f" 2>/dev/null \
      && flag "$f: piped secret read (possible exfil)"
  done < <(find "$d" -name '*.md' -type f 2>/dev/null)
done

for h in "$HOME/.claude/hooks"/*.sh; do
  [ -f "$h" ] || continue
  grep -qE 'set -[a-z]*e' "$h" 2>/dev/null || flag "$h: hook lacks 'set -e'-style error handling"
done

if [ "$ISSUES" -gt 0 ]; then echo "=== $ISSUES issue(s) ==="; exit 1; fi
echo "=== skills/hooks scan clean ==="; exit 0
