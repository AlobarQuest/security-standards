#!/bin/bash
# Install (idempotent) the standalone weekly security-scan LaunchAgent on this Mac.
# Deploys the repo-managed detector + skills linter to ~/.claude/bin (the path the
# security-drift runtime, hooks, and global CLAUDE.md weekly-tool note all expect),
# renders the plist template, and loads the agent.
#
# Source of truth lives in THIS repo (scripts/security-scan.sh — tracked alongside the
# security-drift subsystem that consumes it — and scripts/skills-security-scan.sh); this
# script is how an edit gets deployed. The 3am security-drift self-check hashes the
# DEPLOYED ~/.claude/bin/security-scan.sh — so after editing the repo copy and re-running
# this installer, the next run surfaces ONE "scanner hash changed — verify intentional"
# URGENT, by design (then records the new hash). The same gate catches out-of-band edits.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.devon.security-scan.plist"
BIN_DIR="$HOME/.claude/bin"

mkdir -p "$BIN_DIR" "$HOME/.claude/audit" "$HOME/Library/LaunchAgents"

# Deploy the manifest-declared artifacts (detectors + hooks) from their home repo.
( cd "$REPO" && PYTHONPATH=src python3 -m security_scan.governance deploy )

sed -e "s#__HOME__#$HOME#g" \
  "$REPO/scripts/com.devon.security-scan.plist.template" > "$PLIST"

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Deployed scanners to $BIN_DIR and installed + loaded com.devon.security-scan (Mon 09:00)."
echo "Run once now:  launchctl start com.devon.security-scan   (or: bash $BIN_DIR/security-scan.sh)"
