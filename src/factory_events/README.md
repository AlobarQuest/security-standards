# factory_events — common audit-event envelope (WS-1.1)

One envelope (`factory-event/v1`, JSON Schema in `schema/`) across all factory
systems; hash-chained append-only JSONL store at `~/.factory/events.jsonl`;
nightly Postgres projection. Spec:
`docs/superpowers/specs/2026-07-02-ws11-audit-event-envelope-design.md`.

## CLI

    PYTHONPATH=src .venv-events/bin/python -m factory_events <cmd>

- `emit --actor A --action x.y --result success|failure|unknown --ref NAME
  [--target T] [--correlation-id C] [--evidence-json '{...}']` — append one
  direct event. Runtimes/executors declare identity by emitting with their
  registered actor id (validated against `registry/`).
- `adapt --source high-power|change-manager|all [--reanchor]` — translate
  source logs (watermarked, idempotent; `--reanchor` accepts a rewritten
  high-power source file and re-ingests with event_id dedupe).
- `verify [--against-anchor]` — walk the hash chain + schema-validate every
  event; `--against-anchor` also requires the last anchored head (chain_heads
  in the projection) to still be present in the chain.
- `ship [--rebuild]` — upsert into the projection + anchor the current head.
  `--rebuild` truncates `factory_events` (never `chain_heads`) and replays.

## Integration tests

The default repository gate excludes projection-store integration tests so
`make check` remains warning-clean and skip-clean without requiring a live DSN.
Run the explicit integration gate only against a disposable PostgreSQL database:

    FACTORY_TEST_DSN=postgresql://... make check-integration

## Actor identity — the agent registry (WS-1.2)

Actors are validated against the agent-identity registry at `registry/`
(`PYTHONPATH=src python3 -m agent_registry list|authority <id>`), which
supersedes the provisional vocabulary this section used to hold. Direct emits
with an unregistered actor are rejected; adapters fall back to
`claude-code-unattributed` / legacy mappings and always preserve the raw source
actor verbatim in `evidence[0].record`. See `registry/README.md` for the
authority model (ability / policy / task-authority / approval).

## Runtime config — `~/.factory/env` (chmod 600, never tracked)

    CM_BASE_URL=https://change-mgr.alobar.net
    CM_M2M_TOKEN=<from BWS — see .bws-secrets.toml>
    FACTORY_DB_DSN=postgresql://factory_events:<from BWS>@127.0.0.1:5545/factory_events
    FACTORY_HC_PING_URL=<healthchecks.io ping url>  # optional

## Recovery

`~/.factory/` is in the nightly mini-host backup (dir tree; env EXCLUDED by policy —
BWS is the secrets source of record). To recover: restore the tree from restic,
re-materialize `~/.factory/env` from BWS per the config section (chmod 600), run
`verify --tolerate-torn-tail` on the restored store (a mid-write copy may have one
truncated final line — valid up to the last complete event).

A torn final line must then be **removed** before the store accepts new work —
`ship --rebuild`, `adapt`, and `emit` all use strict parsing and fail on a torn
store. Repair it: keep only the first N complete lines (drop the trailing
partial one), then re-run plain `verify` (no flag) — it must pass before
resuming with `ship --rebuild`.

## Nightly

`com.devon.factory-events` (launchd, 03:30) → `scripts/factory-events-nightly.sh`:
adapt all → verify --against-anchor → ship → healthcheck ping with the head hash.
