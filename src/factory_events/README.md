# factory_events — common audit-event envelope (WS-1.1)

One envelope (`factory-event/v1`, JSON Schema in `schema/`) across all factory
systems; hash-chained append-only JSONL store at `~/.factory/events.jsonl`;
nightly Postgres projection. Spec:
`docs/superpowers/specs/2026-07-02-ws11-audit-event-envelope-design.md`.

## CLI

    PYTHONPATH=src .venv-events/bin/python -m factory_events <cmd>

- `emit --actor A --action x.y --result success|failure|unknown --ref NAME
  [--target T] [--correlation-id C] [--evidence-json '{...}']` — append one
  direct event. **This is the WS-1.2 seam:** runtimes/executors declare their
  identity by emitting events with their registered actor id.
- `adapt --source high-power|change-manager|all [--reanchor]` — translate
  source logs (watermarked, idempotent; `--reanchor` accepts a rewritten
  high-power source file and re-ingests with event_id dedupe).
- `verify [--against-anchor]` — walk the hash chain + schema-validate every
  event; `--against-anchor` also requires the last anchored head (chain_heads
  in the projection) to still be present in the chain.
- `ship [--rebuild]` — upsert into the projection + anchor the current head.
  `--rebuild` truncates `factory_events` (never `chain_heads`) and replays.

## Provisional actor vocabulary (until WS-1.2's registry)

| actor | meaning |
|---|---|
| `claude-code-unattributed` | any Claude Code session on the mini — the high-power hook cannot distinguish interactive from headless; `correlation_id` carries the session UUID |
| `change-window-agent` | change-manager `executor` events — conflates the window agent and the 4AM security executor (both run in the window lane); WS-1.2 separates them |
| `drift-reconciler` | change-manager `sync` / `watchdog` events |
| `security-executor` | reserved for direct emits from the 4AM executor |
| `open-engine-runner` | reserved for the WS-0.6 pilot runner |
| `devon` | human decisions (any SSO email — solo operator) |
| `unknown` | unmappable source actors (e.g. change-manager `api`) |

Raw source actor strings are always preserved verbatim in
`evidence[0].record`; the envelope actor is the honest mapping, never a guess.

## Runtime config — `~/.factory/env` (chmod 600, never tracked)

    CM_BASE_URL=https://change-mgr.alobar.net
    CM_M2M_TOKEN=<from BWS — see .bws-secrets.toml>
    FACTORY_DB_DSN=postgresql://factory_events:<from BWS>@127.0.0.1:5545/factory_events
    FACTORY_HC_PING_URL=<healthchecks.io ping url>  # optional

## Nightly

`com.devon.factory-events` (launchd, 03:30) → `scripts/factory-events-nightly.sh`:
adapt all → verify --against-anchor → ship → healthcheck ping with the head hash.
