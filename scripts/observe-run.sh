#!/usr/bin/env bash
# Source of truth: ~/Projects/security-standards/scripts/observe-run.sh (deployed → ~/.claude/bin/observe-run.sh)
# Edit here, not in place; then: cd ~/Projects/security-standards && make install
# Report a scheduled run's outcome to the orchestrator's observation spine (ADR-0021).
#
# Source this (don't execute it) and use three calls:
#
#     source "$(dirname "${BASH_SOURCE[0]}")/observe-run.sh"
#     observe_init "backup:vps-production" backup production
#     observe_fact databases_dumped 13
#     observe_report "$rc" "${#WARNINGS[@]}" restic     # from the EXIT trap
#
# ── The property that matters most ────────────────────────────────────────────
# Copied from infraops-mcp-server/scripts/drift-audit.sh: this is BEST-EFFORT and
# deliberately outside the caller's result code. The backup lane is never hostage to the
# orchestrator being reachable — a backup made conditional on the observability lane is
# strictly worse than an unobserved backup — but a failure is always logged, never silent.
# `observe_report` therefore returns 0 on every path, and the built payload is logged BEFORE
# it is posted, so a run that cannot reach the orchestrator still leaves the fact behind.
#
# ── Why the reference identifies the RUN and not the JOB ──────────────────────
# `record_observation` refuses a second observation at the same
# `(source_system, source_reference)` whose normalized facts differ — `observation_conflict`,
# with no supersession model and no delete route. `_fact_identity` covers status, severity,
# observed_at, summary and facts, so all five are part of what must not move.
#
# These jobs run every night and their facts differ every night. A reference naming the JOB
# would therefore conflict on the second night and wedge the producer permanently. So the
# reference is `recovery-floor:<subject>:<run start>`: a different night is a different
# reference and appends, while an unchanged re-post of the SAME run is byte-identical and
# replays on the idempotency key.
#
# That holds only while every field inside `_fact_identity` is a pure function of the run's
# captured results. `observed_at` is the run's OWN start time, never the post time — with a
# wall-clock post time an unchanged re-post would produce the same reference and a different
# fact hash, which is exactly the conflict branch. Do not add a fact that reads the clock, an
# environment variable, or a random id.
#
# Deliberately no fact digest in the reference (drift-audit.sh has one): that lane re-posts a
# stored report file, so its facts can legitimately be rebuilt. Here the facts are computed
# once, inside the run they describe, and are posted once at its exit.
#
# ── This file has a twin ──────────────────────────────────────────────────────
# `~/Projects/vps-backup/observe-run.sh` and
# `~/Projects/security-standards/scripts/observe-run.sh` are identical apart from the two
# `# Source of truth:` lines the governance verifier requires on a deployed artifact. Two
# copies rather than one shared deployment because the alternative couples the backup lane to
# another repo's install step; the drift this risks fails CLOSED and LOUD (a stale vocabulary
# is refused by the orchestrator and logged as a non-fatal WARN, and the run is unaffected).
# `diff` the two before editing either.
#
# ── Secrets ───────────────────────────────────────────────────────────────────
# The bearer is the `orchestrator-drift-reporter` credential — the OBSERVER role, whose entire
# write surface is POST /api/v1/observations and which 403s every other route. Fetched from BWS
# by stable UUID. `--color no` with FORCE_COLOR/CLICOLOR_FORCE unset: those variables make
# `bws secret get` wrap its JSON in ANSI codes even on a pipe, which breaks the parse.

OBSERVE_SOURCE_SYSTEM="recovery_floor"
OBSERVE_API_BASE="${OBSERVE_API_BASE:-https://sds.alobar.net}"
OBSERVE_CREDENTIAL_KEY_ID="${OBSERVE_CREDENTIAL_KEY_ID:-orchestrator-drift-reporter}"
BWS_OBSERVE_SECRET_ID="${BWS_OBSERVE_SECRET_ID:-8998c4ea-453c-4ae1-9b5c-b49500b8dacc}"
# Keychain account used only when the caller has no BWS token of its own. This is the broad
# machine account (one account behind both BWS_ACCESS_TOKEN_VPS_BACKUP and
# BWS_ACCESS_TOKEN_INFRA_DRIFT); the narrow `sds-operator` identity cannot read this secret.
# The vps-backup scripts source bws-token.sh first and already hold it.
OBSERVE_KEYCHAIN_ACCOUNT="${OBSERVE_KEYCHAIN_ACCOUNT:-BWS_ACCESS_TOKEN_VPS_BACKUP}"

OBSERVE_SUBJECT=""
OBSERVE_TYPE=""
OBSERVE_ENVIRONMENT=""
OBSERVE_STARTED_AT=""
OBSERVE_FACTS_FILE=""

# Prefer the caller's own logger so the observation lands in the same log as everything else.
observe_log() {
    if declare -F log >/dev/null 2>&1; then log "$@"; else echo "[observe] $*"; fi
}

# observe_init <subject-reference> <observation-type> [environment]
observe_init() {
    OBSERVE_SUBJECT="$1"
    OBSERVE_TYPE="$2"
    OBSERVE_ENVIRONMENT="${3:-}"
    OBSERVE_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    OBSERVE_FACTS_FILE="$(mktemp -t observe-facts)" || OBSERVE_FACTS_FILE=""
    export OBSERVE_SOURCE_SYSTEM OBSERVE_API_BASE OBSERVE_CREDENTIAL_KEY_ID
    export OBSERVE_SUBJECT OBSERVE_TYPE OBSERVE_ENVIRONMENT OBSERVE_STARTED_AT OBSERVE_FACTS_FILE
}

# observe_fact <key> <value>. The value is used as JSON when it parses as JSON and as a string
# otherwise. Keys must avoid the ingest secret scanner's substrings (log, token, credential,
# secret, password, body, bearer, authorization, api_key, instruction) — it matches key NAMES,
# not just values, so `log_path` is refused however harmless it is.
observe_fact() {
    [ -n "$OBSERVE_FACTS_FILE" ] || return 0
    printf '%s\t%s\n' "$1" "$2" >> "$OBSERVE_FACTS_FILE" 2>/dev/null || true
}

# observe_report <exit-code> <warning-count> [stage]
# Status comes from what the job already computed and nothing else: a non-zero exit is `failed`,
# warnings without a failure are `degraded`, and a clean run is `passed`. No finer state is
# invented, because no caller computes one.
observe_report() {
    local rc="${1:-0}" warnings="${2:-0}" stage="${3:-complete}" status severity token
    if [ -z "$OBSERVE_SUBJECT" ]; then
        observe_log "WARNING: observation skipped — observe_init was never called"
        return 0
    fi
    # One report per run. A second call would post the same reference with the accumulated facts
    # already consumed, i.e. DIFFERENT facts under an identical run identity — the conflict this
    # file exists to avoid, manufactured by the reporter itself.
    if [ -n "${OBSERVE_REPORTED:-}" ]; then
        observe_log "WARNING: observation already reported for this run — ignoring second report"
        return 0
    fi
    OBSERVE_REPORTED=1
    if [ "$rc" -ne 0 ]; then status="failed"; severity="critical"
    elif [ "$warnings" -gt 0 ]; then status="degraded"; severity="warning"
    else status="passed"; severity="info"
    fi
    token="$(observe_bearer)"

    (
        set +e
        OBSERVE_RC="$rc" OBSERVE_WARNINGS="$warnings" OBSERVE_STAGE="$stage" \
        OBSERVE_STATUS="$status" OBSERVE_SEVERITY="$severity" OBSERVE_TOKEN="$token" \
        python3 - <<'OBSERVE_PY' 2>&1
import json, os, sys, urllib.error, urllib.request

def emit(line):
    sys.stdout.write(line + "\n")

def value(raw):
    """JSON when it parses as JSON, a bounded string otherwise."""
    try:
        return json.loads(raw)
    except Exception:
        return raw[:512]

try:
    facts = {"stage": os.environ["OBSERVE_STAGE"],
             "exit_code": int(os.environ["OBSERVE_RC"]),
             "warnings": int(os.environ["OBSERVE_WARNINGS"])}
    path = os.environ.get("OBSERVE_FACTS_FILE", "")
    if path and os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            key, _, raw = line.rstrip("\n").partition("\t")
            if key:
                facts[key[:64]] = value(raw)

    started = os.environ["OBSERVE_STARTED_AT"]
    subject = os.environ["OBSERVE_SUBJECT"]
    reference = f"recovery-floor:{subject}:{started}"
    status = os.environ["OBSERVE_STATUS"]
    environment = os.environ.get("OBSERVE_ENVIRONMENT") or None
    command = {
        "idempotency_key": reference,
        "expected_version": 0,
        "source_system": os.environ["OBSERVE_SOURCE_SYSTEM"],
        "source_reference": reference,
        "source_url": None,
        "trust_classification": "monitor",
        "subject_type": "external_run",
        "subject_reference": subject,
        "environment": environment,
        "observation_type": os.environ["OBSERVE_TYPE"],
        "status": status,
        "severity": os.environ["OBSERVE_SEVERITY"],
        "observed_at": started,
        "summary": f"{subject} — {status} ({facts['stage']}, {facts['warnings']} warning(s))"[:512],
        "facts": facts,
        "payload_digest": None,
    }
except Exception as error:                                    # never raise into the caller
    emit(f"WARNING: could not build the observation: {error!r}")
    raise SystemExit(0)

# Logged BEFORE the post, so a run that cannot reach the orchestrator still leaves the fact
# behind. This IS the record when the spine is unreachable.
emit("observation payload: " + json.dumps(command, sort_keys=True))

token = os.environ.get("OBSERVE_TOKEN", "")
if not token:
    emit("WARNING: observation not posted — no orchestrator bearer available (non-fatal)")
    raise SystemExit(0)

request = urllib.request.Request(
    os.environ["OBSERVE_API_BASE"].rstrip("/") + "/api/v1/observations",
    data=json.dumps(command).encode("utf-8"),
    headers={"Authorization": f"Bearer {token}",
             "X-Credential-Key-Id": os.environ["OBSERVE_CREDENTIAL_KEY_ID"],
             "Content-Type": "application/json",
             "User-Agent": "recovery-floor-observer/1"},
    method="POST")
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        emit(f"observation recorded: id={json.load(response).get('id')} ({reference})")
except urllib.error.HTTPError as error:
    emit(f"WARNING: observation POST -> {error.code}: {error.read().decode('utf-8', 'replace')[:200]} (non-fatal)")
except Exception as error:
    emit(f"WARNING: observation POST failed: {error!r} (non-fatal)")
OBSERVE_PY
    ) 2>&1 | while IFS= read -r line; do observe_log "$line"; done

    [ -n "$OBSERVE_FACTS_FILE" ] && rm -f "$OBSERVE_FACTS_FILE"
    return 0
}

# Empty string when unavailable — the poster then logs a WARN and posts nothing.
observe_bearer() {
    if [ -n "${OBSERVE_BEARER:-}" ]; then printf '%s' "$OBSERVE_BEARER"; return 0; fi
    local bws_token="${BWS_ACCESS_TOKEN:-}"
    if [ -z "$bws_token" ]; then
        bws_token="$(/usr/bin/security find-generic-password \
            -s 'Claude' -a "$OBSERVE_KEYCHAIN_ACCOUNT" -w 2>/dev/null || true)"
    fi
    [ -n "$bws_token" ] || return 0
    command -v bws >/dev/null 2>&1 || return 0
    BWS_ACCESS_TOKEN="$bws_token" env -u FORCE_COLOR -u CLICOLOR_FORCE \
        bws secret get "$BWS_OBSERVE_SECRET_ID" --output json --color no 2>/dev/null \
        | python3 -c 'import sys,json; print(json.load(sys.stdin)["value"])' 2>/dev/null || true
}
