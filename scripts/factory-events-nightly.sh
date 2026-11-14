#!/bin/bash
# factory-events nightly, in one of two modes (src/factory_events/README.md, "Nightly"):
#   file mode (no ~/.factory/chain-db.env):  adapt -> verify (incl. anchor) -> ship -> ping.
#   database mode (that file present):       verify -> adapt -> verify --record-anchor -> ping.
# Source of truth: ~/Projects/security-standards/scripts/factory-events-nightly.sh (deployed → ~/.claude/bin/factory-events-nightly.sh)
# Edit here, not in place; then: cd ~/Projects/security-standards && make install
# Config: ~/.factory/env (chmod 600) — CM_BASE_URL, FACTORY_DB_DSN, FACTORY_HC_PING_URL
# (optional; ping skipped when unset). CM_M2M_TOKEN is fetched from BWS on every run, never kept
# in that file: the executor rotates it (orchestrator ADR-0055 amendment 9, "The change-manager
# adapter"), and a copy would keep the old value after the rotation retired it.
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
# ACTIVATION — a merged change is not live on this machine until the code is pulled. The estate's
# Dependabot cascade stops at the merge, which is complete for a repository whose landing redeploys
# a hosted application and incomplete for this one, whose code runs from a working copy here
# (ADR-0031). Best-effort by construction: the helper prints one `[activation]` line and returns 0
# whatever it finds, so this job is never gated on being able to update itself.
_SDS_ACTIVATE="$HOME/.claude/bin/activate-checkout.sh"
if [ -r "$_SDS_ACTIVATE" ]; then
    # shellcheck source=/dev/null
    . "$_SDS_ACTIVATE"
else
    activate_checkout() {
        echo "[activation] helper missing at $HOME/.claude/bin/activate-checkout.sh —" \
             "this run is not activated"
    }
fi
activate_checkout "$REPO"


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

# FETCHED AFTER `/start` AND FATAL WHEN EMPTY, both deliberately. The rotation executor counts this
# job as switched to a new change-manager bearer once its check shows a successful run that
# started after the keeper was written, so the fetch must fall inside the run Healthchecks times,
# and an empty value must reach `/fail` rather than a success. The broad account reads the
# keeper, as for every other reader of it; `--color no` because FORCE_COLOR wraps the JSON.
STAGE="credential"
CM_KEEPER_ID="${FACTORY_CM_SECRET_ID:-af0e4192-edc6-46ae-9e4f-b469011dbb8d}"
CM_IDENTITY="${BWS_ACCESS_TOKEN_BROAD:-$(/usr/bin/security find-generic-password \
    -s 'Claude' -a 'BWS_ACCESS_TOKEN_VPS_BACKUP' -w 2>/dev/null || true)}"
[ -n "$CM_IDENTITY" ] || fail "no BWS identity for the change-manager credential (Keychain Claude)"
BWS_BIN="$(command -v bws 2>/dev/null || true)"
if [ -z "$BWS_BIN" ] && [ -x /usr/local/bin/bws ]; then BWS_BIN="/usr/local/bin/bws"; fi
[ -n "$BWS_BIN" ] || fail "bws is neither on PATH nor at /usr/local/bin/bws"
CM_M2M_TOKEN="$(BWS_ACCESS_TOKEN="$CM_IDENTITY" env -u FORCE_COLOR -u CLICOLOR_FORCE \
    "$BWS_BIN" secret get "$CM_KEEPER_ID" --output json --color no 2>/dev/null \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["value"])' 2>/dev/null || true)"
unset CM_IDENTITY
[ -n "$CM_M2M_TOKEN" ] || fail "could not read the change-manager credential from BWS"
export CM_M2M_TOKEN

# ── The switch: ~/.factory/chain-db.env (orchestrator FE-5 cut-over plan, "The switch") ──────
# Absent, this run is the file chain's, exactly as before. Present, it holds exactly three
# non-secret `KEY=value` lines, and this run appends to and verifies the database chain. The file
# is parsed, never sourced, so it can set nothing but these three values. Its staging copy,
# chain-db.env.pending, is read only by the orchestrator's session wrapper, never here.
CHAIN_DB_FILE="$HOME/.factory/chain-db.env"
CHAIN_MODE="file"
# ~/.factory/env was sourced under `set -a`: a name it set would stay exported after a new
# assignment. Unsetting this mode's names first keeps every one of them unexported.
unset CHAIN_DB_HOST CHAIN_DB_PORT CHAIN_DB_NAME NIGHTLY_IDENTITY CHAIN_PASSWORD
if [ -e "$CHAIN_DB_FILE" ] || [ -L "$CHAIN_DB_FILE" ]; then
    CHAIN_MODE="database"
fi

if [ "$CHAIN_MODE" = "database" ]; then
    STAGE="chain-settings"
    if [ -L "$CHAIN_DB_FILE" ] || [ ! -f "$CHAIN_DB_FILE" ]; then
        fail "$CHAIN_DB_FILE is not a regular file"
    fi
    CHAIN_DB_HOST=""
    CHAIN_DB_PORT=""
    CHAIN_DB_NAME=""
    LINE_NO=0
    # A line's value is never echoed: only its number and key, in case a secret was pasted in.
    while IFS= read -r LINE || [ -n "$LINE" ]; do
        LINE_NO=$((LINE_NO + 1))
        case "$LINE" in
            *=*) ;;
            *) fail "$CHAIN_DB_FILE line $LINE_NO is not KEY=value" ;;
        esac
        KEY="${LINE%%=*}"
        VALUE="${LINE#*=}"
        case "$KEY" in
            FACTORY_EVENTS_DB_HOST | FACTORY_EVENTS_DB_PORT | FACTORY_EVENTS_DB_NAME) ;;
            *) fail "$CHAIN_DB_FILE line $LINE_NO has an unknown key" ;;
        esac
        # No quoting and no spaces: a value is a host, a port or a database name, taken literally.
        case "$VALUE" in
            "" | *[!A-Za-z0-9._:-]*)
                fail "$CHAIN_DB_FILE line $LINE_NO: $KEY is empty or has a character outside [A-Za-z0-9._:-]" ;;
        esac
        case "$KEY" in
            FACTORY_EVENTS_DB_HOST) [ -z "$CHAIN_DB_HOST" ] && CHAIN_DB_HOST="$VALUE" && continue ;;
            FACTORY_EVENTS_DB_PORT) [ -z "$CHAIN_DB_PORT" ] && CHAIN_DB_PORT="$VALUE" && continue ;;
            FACTORY_EVENTS_DB_NAME) [ -z "$CHAIN_DB_NAME" ] && CHAIN_DB_NAME="$VALUE" && continue ;;
        esac
        fail "$CHAIN_DB_FILE sets $KEY twice"
    done < "$CHAIN_DB_FILE"
    [ -n "$CHAIN_DB_HOST" ] || fail "$CHAIN_DB_FILE has no FACTORY_EVENTS_DB_HOST"
    [ -n "$CHAIN_DB_PORT" ] || fail "$CHAIN_DB_FILE has no FACTORY_EVENTS_DB_PORT"
    [ -n "$CHAIN_DB_NAME" ] || fail "$CHAIN_DB_FILE has no FACTORY_EVENTS_DB_NAME"

    # The append password, fetched through this job's own account only: never through the
    # change-manager identity above. The token and the password are unexported shell variables;
    # each reaches only its one child, as an assignment prefix, never argv. The Keychain binary
    # is overridable only so the test harness can stub it; the default is the absolute path.
    STAGE="chain-credential"
    APPEND_SECRET_ID="2ce0dbc7-eeac-4bf0-8204-b50200c97516"  # factory-events-append-password
    SECURITY_BIN="${FACTORY_EVENTS_SECURITY_BIN:-/usr/bin/security}"
    NIGHTLY_IDENTITY="$("$SECURITY_BIN" find-generic-password \
        -s 'Claude' -a 'BWS_ACCESS_TOKEN_FACTORY_EVENTS_NIGHTLY' -w 2>/dev/null || true)"
    [ -n "$NIGHTLY_IDENTITY" ] \
        || fail "no BWS identity for the append password (Keychain Claude / BWS_ACCESS_TOKEN_FACTORY_EVENTS_NIGHTLY)"
    CHAIN_PASSWORD="$(BWS_ACCESS_TOKEN="$NIGHTLY_IDENTITY" env -u FORCE_COLOR -u CLICOLOR_FORCE \
        "$BWS_BIN" secret get "$APPEND_SECRET_ID" --output json --color no 2>/dev/null \
        | python3 -c 'import sys,json; print(json.load(sys.stdin)["value"])' 2>/dev/null || true)"
    unset NIGHTLY_IDENTITY
    [ -n "$CHAIN_PASSWORD" ] || fail "could not read the append password from BWS"
fi

# Runs `python -m factory_events "$@"`. In database mode the password and the three settings are
# an assignment prefix on this one command line, so only this child receives them.
run_factory_events() {
    if [ "$CHAIN_MODE" = "database" ]; then
        FACTORY_EVENTS_APPEND_PASSWORD="$CHAIN_PASSWORD" \
            FACTORY_EVENTS_DB_HOST="$CHAIN_DB_HOST" \
            FACTORY_EVENTS_DB_PORT="$CHAIN_DB_PORT" \
            FACTORY_EVENTS_DB_NAME="$CHAIN_DB_NAME" \
            "$PY" -m factory_events "$@"
    else
        "$PY" -m factory_events "$@"
    fi
}

# Each stage's own output is the only source of the facts below: nothing here decides a status
# the tools did not report.

# Database mode verifies before it appends (ADR-0059 amendment 7: verify, then resume the
# writers). `--against-anchor` checks the anchor when chain-anchor.json exists and is a plain
# database verify when it doesn't (cli.py `_verify_database`, `chain.read_anchor`).
if [ "$CHAIN_MODE" = "database" ]; then
    STAGE="verify-before-adapt"
    log "verify (database chain + anchor, before adapt)"
    if PRE_VERIFY_OUT=$(run_factory_events verify --against-anchor 2>&1); then
        log "$PRE_VERIFY_OUT"
    else
        log "$PRE_VERIFY_OUT"
        fail "verify before adapt"
    fi
fi

STAGE="adapt"
log "adapt"
if ADAPT_OUT=$(run_factory_events adapt --source all 2>&1); then
    log "$ADAPT_OUT"
    EVENTS_APPENDED=$(printf '%s\n' "$ADAPT_OUT" \
        | sed -n 's/.*: \([0-9][0-9]*\) events appended.*/\1/p' \
        | awk '{ total += $1 } END { print total + 0 }')
else
    log "$ADAPT_OUT"
    fail "adapt"
fi

STAGE="verify"
# Database mode anchors the verified head; file mode's anchor is the projection's, set by ship.
if [ "$CHAIN_MODE" = "database" ]; then VERIFY_FLAG="--record-anchor"; else VERIFY_FLAG="--against-anchor"; fi
log "verify (chain + anchor)"
if VERIFY_OUT=$(run_factory_events verify "$VERIFY_FLAG" 2>&1); then
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

if [ "$CHAIN_MODE" = "database" ]; then
    unset CHAIN_PASSWORD
    # `ship` projects the file chain and refuses in database mode (cli.py `_cmd_ship`), so the
    # run ends here, with `shipped` 0 in its observation.
    hc_ping "" "$VERIFY_OUT"
    STAGE="complete"
    log "done (database chain; ship skipped)"
    exit 0
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
