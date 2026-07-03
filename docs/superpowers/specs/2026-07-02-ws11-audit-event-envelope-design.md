# WS-1.1 — Common Audit-Event Envelope — Design

**Date:** 2026-07-02
**Status:** Approved by Devon (brainstorm session 2026-07-02)
**Workstream:** Phase 1 / WS-1.1 of the software-factory master plan
(`~/docs/software-delivery-system/2026-07-02-software-factory-master-plan.md`, decision D6)
**Companion architecture:** `~/docs/software-delivery-system/2026-06-30-foundation-intent-orchestration-architecture.md` §3.5

## Purpose

One common audit-event envelope across all factory systems, so any higher layer can
mechanically answer "what happened?" without knowing each system's private log format.
This is the keystone of Phase 1: WS-1.2 agent identities declare themselves *in* these
events, and Phase 3 evidence records bind to the same envelope.

Per D6: adapters over rewrites. Existing loggers (`high-power-actions.jsonl`,
change-manager `ChangeEvent`) keep working untouched; thin adapters translate them
into a single append-only store.

## Decisions made in brainstorming

1. **Projection lives in a local OrbStack Postgres** on the mini (dedicated container,
   own compose — not piggybacked on email-capture's DB). The JSONL is the source of
   record; the projection is disposable/rebuildable and can move to a prod DB at
   Phase 3 when the orchestrator/status-ledger consumes it.
2. **The JSONL store is hash-chained** for tamper-evidence. Exploration found the
   existing high-power log has no integrity linkage (plain JSONL + rotating `.bak`
   snapshots); the master plan's "tamper-evidenced" description is aspirational.
   The factory store closes that gap at the keystone layer.
3. **Approach A:** new `factory_events` package in security-standards (sibling of
   `security_scan`), plus one small read-only events endpoint added to change-manager.
   Direct DB pulls from the mini were rejected (bypasses change-manager's auth/service
   boundary); adapter-only-no-library was rejected (WS-1.2 needs the `emit` seam).

## 1. Envelope schema — `factory-event/v1`

JSON Schema (draft 2020-12) at `schema/factory-event.v1.schema.json`.
Companion §3.5 fields plus `schema` and `source`:

| Field | Type | Semantics |
|---|---|---|
| `schema` | const string | `"factory-event/v1"` — version travels with every record |
| `event_id` | string, required | Deterministic for adapted events: `sha256(source_system + canonical source record)`, hex, prefixed `evt-`. UUIDv4 (same prefix) for direct emits. Deduplication key everywhere. |
| `timestamp` | string, required | ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`) |
| `actor` | string, required | Agent-id from the **provisional vocabulary** (below). WS-1.2 replaces the vocabulary with registry-validated IDs; field shape is stable. |
| `action` | string, required | Dotted verb. High-power: `tool.<tool_name>` (e.g. `tool.vps_exec`, MCP prefix stripped). change-manager: `change.<event_type>` (e.g. `change.approved`, `change.handoff`). Direct emits: caller-defined dotted form. |
| `target` | string, nullable | What was acted on. High-power: best-effort target from args (host, resource, recipient) or the tool name. change-manager: the item's `identity` string. |
| `work_package` | string, nullable | Intent-package ref. Null until Phase 2; in schema now so evidence binds later without a v2. |
| `input_revision` | string, nullable | Approved-revision hash. Null until Phase 2. |
| `result` | enum, required | `success \| failure \| unknown`. High-power events are `unknown` (the PostToolUse hook proves execution, not outcome). change-manager: derived from `event_type` where determinate, else `unknown`. |
| `evidence` | array, required (may be empty) | Refs/objects. Adapted events carry `{type: "source-record", record: <raw source>}` (already secret-redacted at source for high-power; ChangeEvent contains no secrets). |
| `authority_grant` | object/string, nullable | First real values: change-manager approval events (`{system: "change-manager", item_id, approver}`). Otherwise null. |
| `correlation_id` | string, nullable | Groups related events. High-power: the Claude session UUID. change-manager: `change-item:<item_id>`. |
| `source` | object, required | `{system, ref}` provenance. `system` ∈ `high-power-audit \| change-manager \| direct`; `ref` = line number/id or emitter name. |

**Provisional actor vocabulary** (documented in the package README, replaced by the
WS-1.2 registry): `interactive-claude-code`, `change-window-agent`, `security-executor`,
`drift-reconciler`, `open-engine-runner`, `devon`, `unknown`.
Adapter mapping: high-power records → `interactive-claude-code` (its hook only fires in
interactive sessions). ChangeEvent → its own `actor` column mapped onto the vocabulary
(`devon` for GUI decisions, `drift-reconciler` for reconcile, `change-window-agent` for
window runs), `unknown` where unmappable.

**Key decision:** the envelope stays pure semantics. Integrity fields (`seq`,
`prev_hash`, `hash`) belong to the store layer, so the identical event object is valid
in JSONL, Postgres, or an API payload.

## 2. Store — hash-chained JSONL

- **Path:** `~/.factory/events.jsonl` (state dir `~/.factory/state/`).
- **Line format:** `{"seq": N, "prev_hash": "...", "hash": "...", "event": {...}}`.
- **Chain:** `hash = sha256(canonical_json({seq, prev_hash, event}))` where
  `canonical_json` = sorted keys, no whitespace, UTF-8. Genesis `prev_hash` = 64 zeros.
- **Append:** `fcntl` exclusive lock; write + flush; only then report success.
  Duplicate `event_id`s are *tolerated* in the JSONL (chain integrity is per-line) but
  *prevented* by adapter watermarks and deduped by the projection's PK.
- **Verify:** `python3 -m factory_events verify` walks the whole chain, recomputes
  every hash, schema-validates every event; first break → non-zero exit + report.
- **Governance:** the store path and LaunchAgent get entries in
  `governance-map.toml` (this repo owns them); the file is added to vps-backup's
  mini config-tree coverage during build.

## 3. Package + CLI

New package `src/factory_events/` in security-standards, zero-install
(`PYTHONPATH=src python3 -m factory_events ...`), stdlib + `jsonschema` + `psycopg`
only (the latter imported lazily by `ship` so `emit/adapt/verify` run dependency-free).

Subcommands:

- `emit` — append one validated event (args or stdin JSON). The WS-1.2 seam: future
  runtimes/executors call this (or the library function) to declare identity in events.
- `adapt --source high-power|change-manager|all` — run adapters (below).
- `verify` — chain + schema verification of the full store.
- `ship [--rebuild]` — upsert new events into the Postgres projection;
  `--rebuild` truncates and replays the whole JSONL.

Module layout: `envelope.py` (model, canonicalization, validation), `store.py`
(chain append/verify), `adapters/high_power.py`, `adapters/change_manager.py`,
`ship.py`, `cli.py`, `__main__.py`.

## 4. Adapters (nightly pull, watermarked, idempotent)

**high-power** (`~/.claude/audit/high-power-actions.jsonl`, read directly):
- Watermark in `~/.factory/state/high-power.json`: `{line_count, last_line_sha256}`.
- On run: if the watermark line's hash mismatches (file rewritten/rotated/truncated),
  **error loudly** and stop — no silent re-ingestion. Explicit
  `adapt --source high-power --reanchor` accepts the new baseline.
- Map: `timestamp`→`timestamp`; `tool`→`action` (`tool.<name>`, MCP prefix stripped);
  `session_id`→`correlation_id`; `args_summary` + `provenance` → `evidence` source-record;
  `result: unknown`; `actor: interactive-claude-code`.
- `event_id` = sha256 of `high-power-audit:<raw source line>` (per the §1 rule) →
  re-runs and re-anchors dedupe in the projection even if the JSONL gains duplicates.
- Watermark advances only after all appends succeed.

**change-manager** (via its API — requires a small PR in that repo, see §7):
- `GET /api/events?after_id=<n>&limit=<m>` with existing M2M auth; response joins
  `change_items.identity` (+ `rule_key`, `provider`) so `target` is meaningful;
  cursor = autoincrement `ChangeEvent.id`, ascending, stable.
- Watermark in `~/.factory/state/change-manager.json`: `{last_id}`.
- Map: `at`→`timestamp`; `event_type`→`action` (`change.<event_type>`);
  `actor`→vocabulary-mapped `actor`; item identity→`target`;
  `item_id`→`correlation_id` (`change-item:<id>`); `from_status/to_status/detail/
  attempt_id/window_run_id`→`evidence` source-record; approvals→`authority_grant`.
- `event_id` = sha256 of `change-manager:<ChangeEvent.id>`.

Existing loggers are not modified (D6). Historical backfill = first adapter run
(both sources adapt from record zero).

## 5. Projection + scheduling

**DB:** dedicated `factory-events-db` Postgres container on the mini's OrbStack
*host* Docker engine (own `docker-compose.yml` in this repo under `deploy/`,
distinct published port — not email-capture's container). Password lives in BWS,
referenced by UUID in `.bws-secrets.toml`, loaded at runtime from a gitignored env
file per the build-agent secrets quickstart. Registered with vps-backup (Recipe F,
local `pg_dump`) via the backup-integration skill during build.

**Table `factory_events`:** promoted columns (`event_id` PK, `seq`, `ts`, `actor`,
`action`, `target`, `work_package`, `input_revision`, `result`, `source_system`,
`correlation_id`) + `event JSONB` (full envelope) + `hash`, `prev_hash`.
Insert = `ON CONFLICT (event_id) DO NOTHING`. The projection is disposable:
`ship --rebuild` reproduces it from the JSONL at any time.

**Scheduling:** LaunchAgent `com.devon.factory-events`, nightly ~03:30 (after
portfolio-scan at 03:00), running `adapt all → verify → ship` via a repo script
(`scripts/factory-events-nightly.sh`). Success pings a Healthchecks.io dead-man
check (same pattern as the backup jobs); any step failing = non-zero exit, no ping,
stderr in the LaunchAgent log.

## 6. Testing & failure posture

- **TDD throughout.** Unit: canonicalization, chain append/verify/tamper-detection
  (mutate a middle line → verify fails at that seq), watermark advance/mismatch/
  reanchor, adapter field-mapping via golden fixtures of both source formats,
  deterministic event_id stability. Integration: `ship` idempotency + `--rebuild`
  against a local Postgres (test gated on availability, skipped otherwise).
- **Fail loud, fail safe:** non-zero exits; watermarks never advance past a failure;
  chain break is an alert (missed healthcheck + log), never a warning; `ship` failures
  don't affect the store.

## 7. Cross-repo touch: change-manager events endpoint

One read-only endpoint (`GET /api/events`) with cursor pagination + item-identity
join, using the existing M2M auth dependency. Separate small PR in
`~/Projects/change-manager`, with tests, deployed through its normal CI (merge →
GHCR → Coolify webhook). No schema or logger changes there.

## 8. Out of scope (YAGNI)

- Live tailing / hook-based dual-writes (nightly batch only).
- Additional sources: read-guard audit log, runner evidence, WS-0.6 receipts —
  Phase 3 wires those through the same adapters pattern.
- Retention/rotation policy for the JSONL (revisit when size hurts).
- Remote hash anchoring / HMAC / signatures (chain only).
- Any GUI or query API; Coolify/prod deployment of the projection.
- Retrofitting the chain onto `high-power-actions.jsonl` itself.

## 9. Success criteria

1. Both historical streams fully adapted; `verify` green over the whole chain.
2. Nightly LaunchAgent run completes adapt→verify→ship with a healthcheck ping.
3. "What happened?" answerable in one SQL query across both systems (e.g. all
   `vps_exec` calls and all change approvals for a given day, with actors).
4. `emit` + provisional actor vocabulary documented as the WS-1.2 binding seam.
5. Schema, store path, LaunchAgent, and DB registered in governance/backup maps.
