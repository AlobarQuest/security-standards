#!/bin/bash
# Install (idempotent) the standalone nightly factory-events LaunchAgent on this Mac.
# Deploys the repo-managed nightly script to ~/.claude/bin (the path the LaunchAgent
# plist expects), renders the plist template, and loads the agent.
#
# Source of truth lives in THIS repo (scripts/factory-events-nightly.sh — tracked
# alongside the factory_events package); this script is how an edit gets deployed.
# Runtime config (~/.factory/env, chmod 600) is provisioned separately — see Task 10.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.devon.factory-events.plist"
BIN_DIR="$HOME/.claude/bin"

mkdir -p "$BIN_DIR" "$HOME/.factory" "$HOME/Library/LaunchAgents"

cp "$REPO/scripts/factory-events-nightly.sh" "$BIN_DIR/factory-events-nightly.sh"
chmod 755 "$BIN_DIR/factory-events-nightly.sh"

sed -e "s#__HOME__#$HOME#g" \
  "$REPO/scripts/com.devon.factory-events.plist.template" > "$PLIST"

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Deployed nightly script to $BIN_DIR and installed + loaded com.devon.factory-events (03:30 daily)."
echo "Run once now:  launchctl start com.devon.factory-events   (or: bash $BIN_DIR/factory-events-nightly.sh)"
