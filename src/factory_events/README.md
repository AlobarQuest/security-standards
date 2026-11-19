# factory_events — common audit-event envelope (WS-1.1)

One envelope (`factory-event/v1`, JSON Schema in `schema/`) across all factory
systems, appended to the Postgres chain of record (see "The database chain").
The chain began as a hash-chained JSONL file, `~/.factory/events.jsonl`; the
FE-5 cut-over imported it into the database and sealed it, and no command
writes or verifies a file since. Spec:
`docs/superpowers/specs/2026-07-02-ws11-audit-event-envelope-design.md`.

## CLI

    PYTHONPATH=src .venv-events/bin/python -m factory_events <cmd>

- `emit --actor A --action x.y --result success|failure|unknown --ref NAME
  [--target T] [--correlation-id C] [--evidence-json '{...}']` — append one
  direct event. Runtimes/executors declare identity by emitting with their
  registered actor id (validated against `registry/`). Refuses with
  `no chain password is set` when neither password is set.
- `adapt --source high-power|change-manager|mac-conformance-facts|portfolio-scan|all [--reanchor]` —
  translate source logs (watermarked, idempotent; `--reanchor` accepts a
  rewritten high-power source file and re-ingests with event_id dedupe). `all`
  runs the four in that order. Each prints `<source>: N events appended`.
  `mac-conformance-facts` appends one `mac_conformance.reported` event per
  infra-drift report (see "The Mac's conformance facts").
  `portfolio-scan` appends one `portfolio.scanned` event per scan from the
  portfolio scan's feed (see "The portfolio scan's feed").
- `verify [--against-anchor | --record-anchor]` — walk the database chain's
  hash links + schema-validate every event (see "Anchor" below for the flags).
  Refuses with `no chain password is set` when neither password is set.
- `import-file --path FILE` — replay a verified events file, in order, into an
  empty database chain in one transaction; commits only if the imported head
  equals the file's head. Connects as the append role, from
  `FACTORY_EVENTS_APPEND_PASSWORD` and the three DB settings.

## The portfolio scan's feed (orchestrator ADR-0059 Amendment 11)

`adapt --source portfolio-scan` reads `~/.portfolio/portfolio-feed.json`, which
the 03:00 portfolio scan writes (project-standards `src/portfolio/feed.py`).
`FACTORY_EVENTS_PORTFOLIO_FEED` names another path; the tests use it. The
adapter only copies the feed. It reads no member record and changes no row or
status.

It appends one event per scan, with these fields:

- `action` `portfolio.scanned`, `actor` `portfolio-scan` (a registry label that
  no credential authenticates as), and `target` `null`.
- `timestamp` and `source.ref` are the feed's `scanned_at`, verbatim, and
  `source.system` is `portfolio-scan`.
- `event_id` is `deterministic_event_id("portfolio-scan", scanned_at)`, so a
  run that finds the same feed again appends nothing.
- When the member record was read, `evidence` holds one
  `{"type": "repository", "repository": "<owner/repo>", "checks": {...}}` per
  feed row, in the feed's order, and `result` is `success`.
- When the feed's `member_record_unreadable` is a reason string, `evidence` is
  exactly `[{"type": "member-record-unreadable", "reason": "<the string>"}]` and
  `result` is `unknown`.

The adapter checks the whole feed before it builds the event. A missing,
unreadable, non-JSON or malformed feed appends nothing: `adapt` prints
`portfolio-scan: 0 events appended (feed skipped: <reason>)`, where the reason
names a field and never its content, and the exit doesn't change (decision
item 6). The work carrier holding its repository-targeted records is the
signal. An `EnvelopeError` or a `ChainError` fails the adapt, as the other
sources' errors do.

## The Mac's conformance facts (orchestrator ADR-0059 Amendment 13)

`adapt --source mac-conformance-facts` records the three inputs of the bump
driver's conformance claim that only the Mac has, ids and statuses only, for the
bump driver's container to read. It reads them as project-standards'
compliance matrix does, from the same paths and override variables:

- The newest `YYYY-MM-DD.json` in `~/infra-drift/reports`
  (`INFRADRIFT_REPORT_DIR`).
- Each executor in `WIRING` (`adapters/mac_conformance.py`): a `launchagent:`
  label is present when `~/Library/LaunchAgents/<label>.plist` is a file
  (`LAUNCHAGENTS_DIR`); a `hook:` name is present when a token of a hook command
  in `~/.claude/settings.json` (`CLAUDE_SETTINGS_JSON`) has that basename.
  `WIRING` is every `launchagent:` and `hook:` entry a member declares in its
  `PROJECT.md` `required_checks`, and nothing else. A member that declares a new
  one must add it there.

It appends one event per report, with these fields:

- `action` `mac_conformance.reported`, `actor` `mac-conformance-facts` (a
  registry label that no credential authenticates as), and `target` `null`.
- `source.system` is `mac-conformance-facts`. For a readable report,
  `timestamp` and `source.ref` are its `generated_at`, written in UTC with `Z`.
- `event_id` is `deterministic_event_id("mac-conformance-facts", source.ref)`,
  so a run that finds the same report again appends nothing, even when the
  wiring changed since. One event per report keeps one event per `timestamp`.
- `evidence` holds, in order:
  - `{"type": "infra-drift-report", "generated_at": "<time>"}`;
  - `{"type": "infra-drift-instance", "name": "<name>", "ok": true|false}` per
    instance, where `ok` is false for any instance the matrix calls unusable;
  - `{"type": "infra-drift-proposal", "instance": "<name>", "id": "<id>",
    "target": {"uuid": "<uuid>", "name": "<name>"}}` per proposal, with `null`
    for any of the three that isn't a string;
  - `{"type": "wiring", "executor": "<kind>:<name>", "status": "present"|"absent"}`
    per `WIRING` entry, in `WIRING`'s order.
- `result` is `success` when every instance is ok, else `unknown`.

No description, reasoning, question, error, path, command line or settings
content is copied.

A newest report the matrix calls unreadable (unreadable, not JSON, not an
object with `generated_at` and `instances`, `instances` not an object, or
`generated_at` not an ISO time) is recorded, not skipped. Its record has
`source.ref` `unreadable:<file name>`, `timestamp` the run time, `result`
`unknown`, and `{"type": "infra-drift-report-unreadable", "reason": "<field>"}`
in place of the report's items; the wiring items follow. The run time is later
than any earlier report's `generated_at`, so a reader taking the newest event by
`timestamp` takes this record. With no report at all, `adapt` prints
`mac-conformance-facts: 0 events appended (report skipped: <reason>)`, appends
nothing, and the exit doesn't change (decision item 5). An `EnvelopeError` or a
`ChainError` fails the adapt, as the other sources' errors do.

## The database chain (orchestrator ADR-0055 amendment 24)

`emit`, `adapt` and `verify` use the Postgres chain of record, and each refuses
with `no chain password is set` when neither role's password is set. A command
that lacks a setting it needs fails and names the variable. None of them falls
back to a file. Each BWS secret holds only its role's
password (orchestrator ADR-0055 amendment 26). `factory_events.chain` builds
each connection from the password, the three settings and the role name, and
passes them to psycopg as keyword parameters, never as a URL. Values come from
the environment only and are never printed or logged.

| Variable | Secret | Used by |
|---|---|---|
| `FACTORY_EVENTS_APPEND_PASSWORD` | Yes: role `factory_events_append` | `emit`, `adapt`, `import-file`; `verify` when no read password is set |
| `FACTORY_EVENTS_READ_PASSWORD` | Yes: role `factory_events_read` | `verify` |
| `FACTORY_EVENTS_DB_HOST` | No | every database command; no default |
| `FACTORY_EVENTS_DB_PORT` | No | every database command; no default |
| `FACTORY_EVENTS_DB_NAME` | No | every database command; no default |
| `FACTORY_EVENTS_OWNER_DSN` | The database owner's DSN, not a BWS secret | `python -m factory_events.db_setup` |

The role names are constants in `chain.py`, beside the schema that creates
them, not settings. `FACTORY_EVENTS_APPEND_DSN`, `FACTORY_EVENTS_READ_DSN` and
`FACTORY_EVENTS_IMPORT_DSN` are retired: any command refuses while one is set,
and names it.

- **Table** (`chain_schema.sql`): `factory_events(event_id PK, seq UNIQUE,
  prev_hash UNIQUE, hash, event)`. `event` is the event's canonical JSON text,
  and `hash` uses the file's formula, so `store.walk_records` verifies both
  chains. Triggers refuse every `UPDATE`, `DELETE` and `TRUNCATE`, whatever
  the role, and an `INSERT` that doesn't link to the row before it.
- **Append** (`db.append_event`): one transaction that takes a shared advisory
  lock, reads the head, and inserts the next row. Any failure rolls back, logs
  the error's type, and raises.
- **Verify** (`db.verify`): one read-only repeatable-read transaction that
  walks every row from `seq` 1. Readers in other repositories select
  `seq, prev_hash, hash, event_id, event ORDER BY seq`.
- **Anchor**: `verify --record-anchor` checks the existing anchor, then writes
  the verified head to `$FACTORY_EVENTS_HOME/state/chain-anchor.json` on the
  verifying machine, outside the database. `verify --against-anchor` refuses a
  chain that no longer holds the anchored `(seq, hash)`.
- **Logs**: JSON records on stdout, one per append, verify or import. `emit`
  prints the bare event id as stdout's last line, and every JSON record it
  prints carries that same id.

### Set up the database (the database owner, once)

Run this by hand as an announced act. Never run it in an image build step or at
start-up:

    FACTORY_EVENTS_OWNER_DSN=... python -m factory_events.db_setup

It creates the table, its triggers, and the roles `factory_events_append` and
`factory_events_read`, with no password. Then set each role's password with
psql's `\password factory_events_append` (and `_read`), which sends only a
SCRAM verifier.

## Integration tests

The default repository gate excludes the database integration tests so
`make check` needs no Postgres. `make check-integration` runs them against
`FACTORY_TEST_DSN` when it's set (CI), or else against a throwaway
`postgres:16-alpine` container that it starts on a random local port and
removes on exit. `FACTORY_TEST_DSN` must name a superuser on a disposable
cluster: the tests create databases and roles and drop tables.

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
    FACTORY_HC_PING_URL=<healthchecks.io ping url>  # optional

`CM_M2M_TOKEN` isn't in this file. `scripts/factory-events-nightly.sh` fetches it from BWS
(`change-manager/M2M_TOKEN`, see `.bws-secrets.toml`) with the broad account on every run, and
fails the run when the fetch comes back empty. The rotation executor rotates that bearer, so a
copy here would keep the old value after the rotation retired it. To run `adapt` by hand, export
it in that shell from BWS first.

## Recovery

The chain of record is the database, backed up with the other Coolify databases
(vps-backup `backup.sh`). `~/.factory/` is in the nightly mini-host backup (dir
tree; env EXCLUDED by policy — BWS is the secrets source of record). It holds the
adapters' watermarks, the database chain's anchor (`state/chain-anchor.json`),
and the sealed pre-cut-over file. To recover the Mac side: restore the tree from
restic, re-materialize `~/.factory/env` from BWS per the config section
(chmod 600), and run the nightly, whose first verify checks the restored anchor.

## Nightly

`com.devon.factory-events` (launchd, 03:30) runs `scripts/factory-events-nightly.sh`, deployed
to `~/.claude/bin/` by `make install`. It runs on the database chain, from the settings in
`~/.factory/chain-db.env`. With no such file, it fails the run and pings `/fail`, naming the
missing file; it runs no `factory_events` command and fetches no chain password.

### The switch file

`~/.factory/chain-db.env` holds no secret. It's exactly three lines, in `KEY=value` form with no
quoting:

    FACTORY_EVENTS_DB_HOST=<host>
    FACTORY_EVENTS_DB_PORT=<port>
    FACTORY_EVENTS_DB_NAME=<database>

The nightly parses the file and never sources it. It fails the run, and pings `/fail`, if the
path isn't a readable regular file (for example, a directory or a symlink), or if the file has
an unknown, missing, or duplicated key, an empty value, a blank line, or a value with a quote or
a space. Its failure message
names the line number and key, never a value.

The staging copy `~/.factory/chain-db.env.pending` holds the same three lines. Only the
orchestrator's session wrapper reads it, for the one-time `import-file`; the nightly never does.
The FE-5 cut-over renamed it to `chain-db.env` after the import, and that rename switched every
holder at once.

### The run

1. Reads the three settings from the switch file.
2. Reads the `factory-events-nightly` account's access token from Keychain `Claude` /
   `BWS_ACCESS_TOKEN_FACTORY_EVENTS_NIGHTLY`, and fetches `factory-events-append-password`
   (see `.bws-secrets.toml`) with it. The change-manager bearer comes through its own
   identity.
3. Runs verify --against-anchor, before anything appends: it checks
   `$FACTORY_EVENTS_HOME/state/chain-anchor.json` when that file exists, and is a plain
   database verify when it doesn't.
4. Runs adapt all (high-power, change-manager, the Mac's conformance facts, then the portfolio
   scan's feed), then verify --record-anchor, which checks the anchor again and anchors the
   verified head. A bad feed or a missing infra-drift report appends nothing and doesn't fail
   the run (see "The portfolio scan's feed" and "The Mac's conformance facts").
5. Pings success with the verify output.

The password and the three settings reach only the `python -m factory_events` children, as an
assignment prefix on each command line: never exported, never in argv, never logged. The access
token reaches only its `bws` process the same way. The script unsets the password after the
last command. Any failed step fails the run through `fail`; nothing falls back to a file.
