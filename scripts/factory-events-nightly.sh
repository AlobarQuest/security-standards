#!/bin/bash
# factory-events nightly: adapt -> verify (incl. anchor) -> ship -> healthcheck ping.
# Source of truth: security-standards scripts/factory-events-nightly.sh (WS-1.1).
# Config: ~/.factory/env (chmod 600) — CM_BASE_URL, CM_M2M_TOKEN, FACTORY_DB_DSN,
# FACTORY_HC_PING_URL (optional; ping skipped when unset).
set -euo pipefail

REPO="$HOME/Projects/security-standards"
PY="$REPO/.venv-events/bin/python"
ENV_FILE="$HOME/.factory/env"
LOG_PREFIX="[factory-events]"

log() { echo "$LOG_PREFIX $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"; }

hc_ping() { # $1 = "" | "/start" | "/fail" ; $2 = optional body
    [ -n "${FACTORY_HC_PING_URL:-}" ] || return 0
    curl -fsS --max-time 10 --data-raw "${2:-}" "${FACTORY_HC_PING_URL}$1" >/dev/null 2>&1 \
        || log "WARNING: healthcheck ping '$1' failed (non-fatal)"
}

fail() {
    log "FAILED: $1"
    hc_ping "/fail" "$1"
    exit 1
}

[ -f "$ENV_FILE" ] || fail "missing $ENV_FILE"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
[ -x "$PY" ] || fail "missing venv: $PY (run: python3 -m venv .venv-events && pip install -e '.[events]')"

hc_ping "/start"
log "adapt"
"$PY" -m factory_events adapt --source all       || fail "adapt"
log "verify (chain + anchor)"
"$PY" -m factory_events verify --against-anchor  || fail "verify"
log "ship"
SHIP_OUT=$("$PY" -m factory_events ship)         || fail "ship"
log "$SHIP_OUT"
hc_ping "" "$SHIP_OUT"
log "done"
