#!/bin/bash
# factory-events nightly: adapt -> verify (incl. anchor) -> ship -> healthcheck ping.
# Source of truth: ~/Projects/security-standards/scripts/factory-events-nightly.sh (deployed → ~/.claude/bin/factory-events-nightly.sh)
# Edit here, not in place; then: cd ~/Projects/security-standards && make install
# Config: ~/.factory/env (chmod 600) — CM_BASE_URL, CM_M2M_TOKEN, FACTORY_DB_DSN,
# FACTORY_HC_PING_URL (optional; ping skipped when unset).
set -euo pipefail

REPO="$HOME/Projects/security-standards"
PY="$REPO/.venv-events/bin/python"
ENV_FILE="$HOME/.factory/env"
LOG_PREFIX="[factory-events]"
# launchd already captures stdout to ~/.factory/nightly.out, but that file is owned by the
# plist rather than by this script and is invisible beside the estate's other scheduled jobs.
# A run whose observation cannot be posted must still leave the fact somewhere durable and
# discoverable, so the job keeps its own log alongside vps-backup's.
LOG_FILE="${FACTORY_EVENTS_LOG:-$HOME/Library/Logs/factory-events.log}"

log() { echo "$LOG_PREFIX $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" | tee -a "$LOG_FILE"; }

# ── Best-effort run reporting to the orchestrator's observation spine (ADR-0021) ──────────────
# Deliberately outside this job's own result: the chain lane is never hostage to the
# orchestrator being reachable, but a failure to report is always logged, never silent. If the
# helper is not deployed the job says so and carries on, rather than dying on a `source`.
OBSERVE_HELPER="$(dirname "${BASH_SOURCE[0]}")/observe-run.sh"
if [ -r "$OBSERVE_HELPER" ]; then
    # shellcheck source=/dev/null
    source "$OBSERVE_HELPER"
else
    observe_init() { :; }; observe_fact() { :; }; observe_report() { :; }
    log "WARNING: $OBSERVE_HELPER missing — this run will not be observed (non-fatal)"
fi

STAGE="startup"
EVENTS_APPENDED=0
CHAIN_EVENTS=0
CHAIN_HEAD=""
ANCHOR_VERIFIED=false
SHIPPED=0
HEAD_SEQ=0
# Posted from the EXIT trap, because `fail` exits from the middle of the run: an end-of-script
# post would observe only the runs that succeeded, which is the shape this whole change exists
# to stop.
finish() {
    local rc=$?
    observe_fact events_appended "$EVENTS_APPENDED"
    observe_fact chain_events "$CHAIN_EVENTS"
    observe_fact chain_head "${CHAIN_HEAD:-null}"
    observe_fact anchor_verified "$ANCHOR_VERIFIED"
    observe_fact shipped "$SHIPPED"
    observe_fact head_seq "$HEAD_SEQ"
    observe_report "$rc" 0 "$STAGE"
}
observe_init "chain:factory-events" chain_integrity operator-machine
trap finish EXIT

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

# Each stage's own output is the only source of the facts below: nothing here decides a status
# the tools did not report.
STAGE="adapt"
log "adapt"
if ADAPT_OUT=$("$PY" -m factory_events adapt --source all 2>&1); then
    log "$ADAPT_OUT"
    EVENTS_APPENDED=$(printf '%s\n' "$ADAPT_OUT" \
        | sed -n 's/.*: \([0-9][0-9]*\) events appended.*/\1/p' \
        | awk '{ total += $1 } END { print total + 0 }')
else
    log "$ADAPT_OUT"
    fail "adapt"
fi

STAGE="verify"
log "verify (chain + anchor)"
if VERIFY_OUT=$("$PY" -m factory_events verify --against-anchor 2>&1); then
    log "$VERIFY_OUT"
    CHAIN_EVENTS=$(printf '%s\n' "$VERIFY_OUT" \
        | sed -n 's/^chain ok: \([0-9][0-9]*\) events.*/\1/p')
    CHAIN_EVENTS="${CHAIN_EVENTS:-0}"
    CHAIN_HEAD=$(printf '%s\n' "$VERIFY_OUT" | sed -n 's/^chain ok:.*, head \(.*\)$/\1/p')
    # An absent anchor is not a verified anchor. `verify --against-anchor` prints `anchor ok:`
    # only when one exists AND is present in the chain, so keying on that line reports what was
    # actually proven rather than assuming the strong case.
    if printf '%s\n' "$VERIFY_OUT" | grep -q '^anchor ok:'; then ANCHOR_VERIFIED=true; fi
else
    log "$VERIFY_OUT"
    fail "verify"
fi

STAGE="ship"
log "ship"
SHIP_OUT=$("$PY" -m factory_events ship)         || fail "ship"
log "$SHIP_OUT"
SHIPPED=$(printf '%s\n' "$SHIP_OUT" | sed -n 's/^shipped=\([0-9][0-9]*\).*/\1/p')
SHIPPED="${SHIPPED:-0}"
HEAD_SEQ=$(printf '%s\n' "$SHIP_OUT" | sed -n 's/.*head_seq=\([0-9][0-9]*\).*/\1/p')
HEAD_SEQ="${HEAD_SEQ:-0}"
hc_ping "" "$SHIP_OUT"

STAGE="complete"
log "done"
