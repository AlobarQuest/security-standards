Outcome: done

# Build report: FE-1, the factory-events database store

Handoff: `lanes-inc-4-fe-1-factory-events-store` (goal step 3f-fe, FE-1, fix round 0).
Branch: `hq/lanes-inc-4-fe-1-factory-events-store`, from `origin/main` `1baec77`.
Sources: orchestrator `4953fe10`, ADR-0055 amendment 24 and ADR-0059 amendment 7.

## Names that FE-2 and FE-3 depend on

The ADRs name no variables, so FE-1 chose the following names. FE-2 (intent-packages) and FE-3
(orchestrator) must use them.

| Variable | Role | Read by |
|---|---|---|
| `FACTORY_EVENTS_APPEND_DSN` | Append-only | `emit` and `adapt`. Also `verify` when no read DSN is set. |
| `FACTORY_EVENTS_READ_DSN` | Read-only | `verify` |
| `FACTORY_EVENTS_IMPORT_DSN` | Not chosen here (Devon's decision) | `import-file` only. It never falls back to the append DSN. |
| `FACTORY_EVENTS_OWNER_DSN` | The database owner | `python -m factory_events.db_setup` only |

- **Roles:** `factory_events_append` and `factory_events_read`.
- **Table:** `public.factory_events(event_id text PK, seq bigint UNIQUE, prev_hash text UNIQUE, hash
  text, event text)`.
- **Reader query:** `SELECT seq, prev_hash, hash, event_id, event FROM factory_events ORDER BY seq`,
  in one read-only repeatable-read transaction.
- **Storage format:** `event` holds the event's canonical JSON *text*, not `jsonb`. A reader runs
  `json.loads(event)` and recomputes `hash` with `store.line_hash`'s formula.

## What I built

1. **Schema, triggers, roles** (`src/factory_events/chain_schema.sql`):
   - **Keys:** `event_id` is the primary key, and `seq` and `prev_hash` are each unique. CHECK
     constraints require `seq >= 1` and 64-hex hashes.
   - **Append-only trigger:** a row trigger refuses `UPDATE` and `DELETE`, and a statement trigger
     refuses `TRUNCATE`. Both fire for every role, the owner included.
   - **Link trigger:** a `BEFORE INSERT` trigger refuses a row that doesn't link to the row before
     it. Seq 1 must link to the genesis hash.
   - **Hash trigger:** the same `BEFORE INSERT` trigger refuses a row whose `hash` isn't sha256
     of `{"event":<stored text>,"prev_hash":...,"seq":...}`. For the canonical text the append
     path writes, that's `line_hash`'s formula. The trigger can't check that a direct `INSERT`'s
     text is canonical; the verify walk, which re-canonicalizes, catches one that isn't.
   - **Roles:** the script creates both roles with `LOGIN`, `NOSUPERUSER`, `NOCREATEDB`,
     `NOCREATEROLE`, `NOINHERIT`, `NOREPLICATION`, and `NOBYPASSRLS`. The read role also gets
     `default_transaction_read_only`.
   - **Grants:** `REVOKE CREATE ON SCHEMA public FROM PUBLIC` and `REVOKE TEMPORARY` on the
     database from PUBLIC, then `REVOKE ALL` on the table, then append gets `SELECT, INSERT` and
     read gets `SELECT`.
   - **Passwords:** the script sets none. The owner sets each one afterwards with psql's
     `\password`, which sends a SCRAM verifier.
2. **The roles script for FE-4** (`src/factory_events/db_setup.py`): run as
   `FACTORY_EVENTS_OWNER_DSN=... python -m factory_events.db_setup`. It applies the SQL in one
   transaction, it's idempotent, and it runs only by hand. Nothing else in the package runs DDL,
   and no build step or start-up path calls it (Infra Brain Database 6).
3. **The append function** (`db.append_event`, items 4, 6, and 7). It runs one transaction:
   - `SET LOCAL lock_timeout = '10s'`
   - `pg_advisory_xact_lock(<constant key>)`
   - read the head, insert `seq + 1`, and commit.

   Any exception rolls the transaction back, logs `{op: append, outcome: failure, event_id,
   error_type}`, and raises `ChainError("append failed (<Type>)") from None`. No retry, no fallback.
4. **The database verify** (`db.verify`, item 8): one read-only transaction at repeatable read,
   streamed through a server-side cursor in `seq` order. It runs through `store.walk_records`, the
   walker the file verify uses, so one walker verifies both chains. The walker also checks that a
   row's `event_id` column equals its event's id. Any error raises `ChainError`.
5. **The history import** (`db.import_file`, `factory_events import-file --path FILE`). It runs in
   these steps:
   1. Parse the file once, walk the parsed records, and refuse a file that holds a duplicate
      `event_id` (the file store never enforced uniqueness, but the primary key does).
   2. Take the append lock and refuse unless the database chain is empty.
   3. Replay each record through the append routine (`_append_in_tx`) in one transaction. Each
      replayed `(seq, hash)` must equal the file's.
   4. Commit only if the imported head equals the file's head.

   Any refusal writes nothing. The DSN comes from `FACTORY_EVENTS_IMPORT_DSN`, which names no
   role. Code and docs name no actor and no role for the import.
6. **Mode selection** (`src/factory_events/chain.py`):
   - **Neither DSN set:** `emit`, `adapt`, and `verify` call the file store exactly as before.
     They don't import `psycopg`, and a subprocess test asserts it. `emit`'s stdout is still one
     bare id.
   - **Either DSN set:** the database is the chain. `emit` and `adapt` need the append DSN and fail
     closed without it, with no file write. `verify` reads the read DSN, else the append DSN.
     `ship` refuses, because projecting the file would ship a stale copy.
   - **Adapters:** both swap `store.event_ids` and `store.append_event` for the `chain`
     dispatchers. `_cmd_adapt` catches `ChainError`.
7. **`make check-integration`** (`scripts/check-integration.sh`). It already existed at `1baec77`
   and required `FACTORY_TEST_DSN` (see Concerns). It now works in two modes:
   - **`FACTORY_TEST_DSN` set:** it uses that DSN, as CI's `extended-tests.yml` does.
   - **`FACTORY_TEST_DSN` unset:** it starts a uniquely named `--rm` `postgres:16-alpine`
     container on a random `127.0.0.1` port, with a random password passed by name. It waits for
     `pg_isready`, runs `pytest -m integration`, and removes the container on every exit path. It
     never prints the DSN.

   `make check` still needs no Postgres. Each integration test gets its own new database, set up
   by the real roles script, and drops it afterwards.
8. **Logging** (`src/factory_events/jsonlog.py`): each append, verify, import, and setup writes one
   JSON record to stdout. A record holds `ts`, `logger`, `op`, `outcome`, `event_id`, `seq`,
   `head` (a 12-hex prefix), `events`, and `error_type`. It never holds a DSN or a driver's error
   text.

## Open before building: settlements

### Where the anchor lives

The anchor is a head file on the verifying machine, at
`$FACTORY_EVENTS_HOME/state/chain-anchor.json`, outside the chain database. On the Mac that path
is `~/.factory/state/chain-anchor.json`, which the Mac's nightly backup already covers.

- **`verify --record-anchor`** checks the existing anchor, walks the chain, and then writes the
  verified head with fsync and `os.replace`.
- **`verify --against-anchor`** refuses a chain that no longer holds the anchored `(seq, hash)`.
  It reads the anchor's hash in the same snapshot as the walk.
- **Absent anchor:** prints no `anchor ok:` line, as the file path does today. The nightly's
  `anchor_verified` fact reports it as false.
- **Corrupt anchor:** fails verify with a `VERIFY FAIL` line, not a traceback.
- **What it guards:** a rewrite by anyone who holds the database's owner, or anyone else on the
  VPS. The rewritten chain no longer holds the Mac's anchored head.
- **What it doesn't guard:** a person on the Mac who edits the anchor file. The nightly's
  `chain:factory-events` observation still records the head in the orchestrator, which serves as a
  second off-box witness for a person to compare by hand.

**Why not read the observation back:** the nightly posts with the `orchestrator-drift-reporter`
bearer. That's the observer role, and its only write route is `POST /api/v1/observations`
(orchestrator `src/orchestrator/api/dependencies.py:36` at `4953fe10`; `observe-run.sh` says it
403s every other route). Reading the observation back would need a new credential or grant, which
is a stop point. The head file needs no credential, no secret, no grant, and no outside write.

**FE-5 wiring (not in this PR):** the nightly's verify becomes `verify --against-anchor
--record-anchor` under the append DSN, and `ship` drops out. At the cut-over, run one
`verify --record-anchor` after the import to seed the anchor.

### The adapters' dedupe

A re-run against the database skips an event the database already holds. `chain.event_ids()` reads
`SELECT event_id FROM factory_events` under the append role, and the deterministic ids
(`high_power.py:93`, `change_manager.py:130`) are checked before each append.

Two tests cover it, one per adapter:

- **`test_adapt_rerun_skips_held_events`** (high-power) adapts 3 events, deletes the watermark,
  and re-runs: 0 appended, exit 0. A `--reanchor` re-run is also 0, and the database still holds
  3 rows.
- **`test_change_manager_rerun_skips_held_events`** adapts 2 events, deletes the cursor, and
  replays from id 0: 0 appended, and the database still holds 2 rows. `emit` still fails on a duplicate id
(`test_duplicate_event_id_fails_and_writes_nothing`).

### The verify walk's cost

I measured a synthetic chain of 3,751 events, built in the test and never copied from
`~/.factory/events.jsonl`. It ran in a local throwaway `postgres:16-alpine` container on this Mac,
under the read role, as one streamed query, three runs each:

| Measurement | Runs |
|---|---|
| `db.verify` walk | 0.17 s to 0.27 s across eight runs (the higher figures while the Mac was loaded) |
| The import of the same chain, one transaction | 1.33 s to 2.30 s |

**The bound:** the walk is linear, about 50–70 µs per event of local CPU (hashing plus schema
validation), plus network round trips. psycopg's named cursor fetches 100 rows per round trip, so
3,751 rows is 38 round trips. Over the tailnet from the Mac, add 38 × RTT. At an assumed 20–40 ms
RTT to `prod-vps`, that's about 0.8–1.5 s, which I didn't measure.

Each carry walks three times, so the estimate is a few seconds per carry at today's size. It
grows linearly at about 0.05 ms per event plus 1 RTT per 100 events. These timings are
local-container latency, and the synthetic events are smaller than real high-power events, whose
evidence records are larger. The narrowing to an anchored head isn't needed at this size.

### `emit`'s stdout

In database mode, `emit` prints these lines to stdout:

1. One JSON record, `{"op":"append","outcome":"ok","event_id":<the emitted id>,...}`.
2. The bare id, as the last line.

`_parse_event_id`'s first rule (the first JSON line with `event_id`) and its fallback (the last
token of the last line) yield the same id. In file mode, stdout is unchanged: the bare id only. A
failed emit exits 1, so the emitter raises before it parses.

- **`tests/emitter_contract.py`** vendors `_parse_event_id` verbatim from intent-packages
  `src/intent_packages/emitter.py`, lines 40-67, at `d9f96e2`.
- **`test_emit_stdout_parses_to_the_emitted_id`** (integration) runs a real `emit` subprocess
  against the database and parses its stdout.
- **`test_emit_stdout_parses_when_json_logs_share_stdout`** (default suite) checks both parse rules
  with a fake append.
- **`test_file_mode_emit_is_unchanged_and_never_loads_psycopg`** pins file mode.

A search of `~/Projects` found no other consumer of `emit`'s stdout.

## Tests and checks run

| Check | Result |
|---|---|
| `make check` (ruff, ruff format, pyright, shellcheck, pytest) in the worktree | Green. pyright 0 errors; **221 passed**, 19 deselected (baseline at `1baec77`: 206 passed, 5 deselected). |
| `make check-integration` in the worktree (throwaway container) | Green. **21 passed**: 16 new, 5 existing `test_factory_ship`. |
| CI on PR #90 | All green. "Factory-store integration tests" (`extended-tests.yml`, the `FACTORY_TEST_DSN` branch of `check-integration.sh`, Postgres 16 service): **21 passed**, 221 deselected. "Lint, type-check, and test" (`quality.yml`): collected 242, **221 passed**, 21 deselected. Both scans pass. |
| A forced failing assert under `-vv` with a fixture DSN in the expression | The DSN shows only as `<dsn redacted>`, and the throwaway password appears nowhere but the probe's own print line. Probe deleted. |
| Throwaway containers left after the runs | 0 (`docker ps -a` filter). |
| Security scanner (`security_scan.cli . --category security`) from the worktree root | No BLOCK. Four WARN `bws.reference-by-stable-uuid` findings, all in files this change doesn't touch. |
| `/code-review` (medium) on `main...HEAD` | 8 findings: 5 fixed, 3 left with reasons (see Self-review). |
| Advisor review before the PR | 7 points: change-manager dedupe test, DSN redaction in test output, duplicate-id import refusal, `TEMPORARY` revoke, and the trigger's wording are all fixed. The `\password` point is a concern. CI's `FACTORY_TEST_DSN` branch is checked on the PR. |

New default-suite tests (`tests/test_factory_chain_mode.py`) cover the following:

- **File mode:** stdout and records are unchanged, and `psycopg` isn't loaded.
- **Failing closed:** a read DSN alone refuses `emit` and `adapt` without writing a file.
- **No DSN leak:** unreachable and malformed DSNs carrying a sentinel password never reach
  stdout or stderr, and no traceback prints. This holds for emit, verify, and import.
- **Import:** it never falls back to the append DSN.
- **Flags:** `--tolerate-torn-tail` and `--record-anchor` are rejected in the wrong mode.
- **Anchor:** a corrupt anchor fails cleanly, and the anchor round-trips.
- **`ship`:** refuses in database mode.
- **The stdout contract:** both parse rules yield the emitted id.

New integration tests (`tests/test_factory_db.py`) cover the following:

- **Linking:** the database appends link byte-for-byte as the file does, including a `1e300`
  float, a NUL escape, and non-ASCII text.
- **Triggers:** they refuse `UPDATE`, `DELETE`, and `TRUNCATE` even for the owner.
- **Role privileges:** the append role can't `UPDATE`, `DELETE`, `TRUNCATE`, `CREATE`, create a
  temporary table, or disable triggers. The read role can't `INSERT`, `CREATE`, create a temporary
  table, or append.
- **Unlinked and forged rows:** they're refused for every role, with
  `IntegrityConstraintViolation` for the forged hash.
- **Duplicates:** a duplicate id writes nothing.
- **Concurrency:** 4 concurrent writers of 10 appends each under the append role leave a linear
  chain of 40.
- **Tampering:** verify finds a tampered row.
- **`emit`:** its stdout parses to the emitted id.
- **Anchor:** the record, check, and refuse round trip passes under the append DSN alone.
- **Adapt dedupe:** for both adapters, described in the preceding settlement.
- **Import:** it reproduces the file, refuses a second time, and refuses a tampered file and a
  file with a duplicate id, each with nothing written.
- **The 3,751-event walk:** described in the preceding settlement.

## Files changed

The following files are new:

- `src/factory_events/chain_schema.sql`: the table, triggers, and roles.
- `src/factory_events/db_setup.py`: the roles script runner.
- `src/factory_events/db.py`: append, `event_ids`, verify, and import.
- `src/factory_events/chain.py`: mode selection, the DSN variables, and the anchor file.
- `src/factory_events/jsonlog.py`: JSON log records on stdout.
- `scripts/check-integration.sh`: the disposable-Postgres runner.
- `tests/test_factory_chain_mode.py`, `tests/test_factory_db.py`, `tests/emitter_contract.py`.

The following files are modified:

- `src/factory_events/store.py`: `_line_hash` is now public as `line_hash`. The walk is extracted
  into `walk_records` and `_record_error`, behavior unchanged, plus the optional row `event_id`
  check.
- `src/factory_events/cli.py`: database paths for emit, verify, and adapt, plus `import-file`,
  `--record-anchor`, and the `ship` refusal.
- `src/factory_events/adapters/high_power.py` and `change_manager.py`: `store.*` becomes `chain.*`
  for ids and appends.
- `Makefile`: `check-integration` calls the script.
- `tests/conftest.py`: an autouse fixture unsets every chain DSN variable, so a shell that holds a
  real DSN can't reach it from a test.
- `src/factory_events/README.md`: the database chain, the variables, setup, and integration tests.

## Self-review

The `/code-review` pass found 8 issues. I fixed these five:

- **Forged hash:** the link trigger now also checks the hash.
- **Corrupt anchor:** it now fails cleanly, and the anchor write is fsynced.
- **Import read:** import parses the file once, so the records verified are the records replayed.
- **`ship` in database mode:** it now refuses.
- **Lazy import:** verify's `psycopg` import moved inside its fail-closed `try`.

I left these three, for the following reasons:

- **An absent anchor passes `--against-anchor`.** That matches the file path today. The nightly
  keys `anchor_verified` on the `anchor ok:` line, so an absent anchor is already reported as not
  verified.
- **`emit`'s stdout gains a JSON line in database mode.** The ADR names `_parse_event_id` as the
  contract, and a search of `~/Projects` found no other consumer.
- **A read DSN alone makes `adapt` fail.** That's the intended fail-closed behavior, since `adapt`
  appends.

The trigger's hash check rebuilds the canonical record by string concatenation. That's correct
only because the append path stores `canonical_json(event)`, sorted keys and no spaces. The
integration tests append events with a NUL escape, a large float, and non-ASCII text through the
trigger, and all pass, so the formula matches `line_hash` for them.

## Concerns

- **The handoff is wrong about `check-integration`.** It says the target doesn't exist at
  `1baec77`, but it does: it required `FACTORY_TEST_DSN` and runs in CI (`extended-tests.yml`).
  I extended it (a throwaway container when the variable is unset) rather than adding a second
  target. This doesn't change what FE-1 builds.
- **The nightly verifies under the append DSN.** ADR-0055 a24 item 8 says each verifier reads
  under the read-only role. Item 11's table gives the nightly only the append DSN, yet ADR-0059 a7
  item 2 says the nightly verifies the chain. FE-1 resolves the gap without granting anything:
  `verify` uses the read DSN when set, else the append DSN, whose role holds `SELECT`, still in a
  read-only transaction. If HQ wants the nightly to hold the read DSN too, that's a grant for
  Devon's FE-4 decision.
- **Role passwords aren't set by the roles script.** The owner sets them afterwards, so no password
  sits in a file, a statement, or the server log. FE-4's act 2 must include that step. psql's
  `\password` prompts on a TTY, which an unattended HQ act may not have. The alternative is
  psycopg's `PGconn.encrypt_password(password, role, b"scram-sha-256")`, which exists in the
  installed psycopg and builds the SCRAM verifier on the client, then
  `ALTER ROLE ... PASSWORD '<verifier>'`. FE-4 picks one; FE-1 builds neither.
- **The import refuses a file with a duplicate `event_id`.** The file store never enforced unique
  ids, and the table's primary key does. If the Mac file holds one, act 5's import stops with
  nothing written, and the duplicate needs a decision before the cut-over can continue.
- **The schema needs Postgres 14 or later** (`CREATE OR REPLACE TRIGGER`). FE-4's resource must be
  14 or later; the tests run on 16.
- **The import holds the append lock for its whole transaction:** about 1.5 s at 3,751 events
  locally. FE-5 pauses the writers first, so nothing contends.
- **Logging standard.** The handoff gives the rule (JSON to stdout), not a Code Brain road. I used
  a small `print(json.dumps(...))` helper rather than the stdlib `logging` module. A
  `StreamHandler` binds `sys.stdout` once, which breaks capture under pytest. If Code Brain's
  logging road names a library, the helper is one function to swap.
- **The repo's `CLAUDE.md` invariant is out of date.** It says `quality.yml`'s `make check` doesn't exist here and CI never runs the pytest suite. On PR #90, `quality.yml` ran `make check` and passed 221 tests. I didn't edit `CLAUDE.md` in this PR, because it's out of scope.
- **Not live yet.** Nothing here is wired into `scripts/factory-events-nightly.sh`, deployed, or
  pointed at a live database. No DSN is set anywhere.

## Standards followed

- **Code Brain 3 (logging):** each append, verify, import, and setup writes one structured JSON
  record to stdout (`jsonlog.log`), never to a file. `emit`'s id stays within the
  `_parse_event_id` contract: every JSON record `emit` prints carries the emitted id, and the bare
  id is the last line. Tests run the vendored parser on real `emit` output.
- **Code Brain 4 (error handling):** no exception is swallowed silently. Every database failure is
  logged by type and raised as `ChainError`, and the CLI turns it into a non-zero exit with a
  `... failed` line. An append failure rolls back and writes nothing, as the duplicate and role
  tests show. `db_setup.main`'s broad `except` logs the type and returns 1, with an inline
  justification.
- **Code Brain 5 (security):** no DSN, password, or driver error text is logged or printed. Errors
  carry only the exception type, and they're raised `from None`, so no traceback carries the
  driver's text. Tests use a sentinel password in unreachable and malformed DSNs and assert that
  it never appears in stdout or stderr. The parametrized test ids are names, not DSNs, and the
  integration fixture wraps every DSN in a `str` subclass whose `repr` is redacted, so a failing
  assert can't print one (checked with a forced failure).
- **Infra Brain Database 6 (no schema setup at build time):** the roles script is a hand-run module
  (`python -m factory_events.db_setup`). No build step, image, or start-up path calls it, and the
  append and verify paths run no DDL. `ship`'s per-call DDL isn't carried over.
- **Infra Brain Security 591, 592, 593 (no BWS tokens, no inline `BWS_ACCESS_TOKEN`):** no token
  or secret is in any tracked file. DSNs come only from the environment. Tests and
  `check-integration.sh` use a random throwaway password for a disposable container, passed to
  `docker` by variable name. The scanner reports no BLOCK.
- **Infra Brain Security 1032 (an exposed credential must rotate):** no DSN is printed anywhere,
  including in test output, `check-integration.sh`, and the README. No real credential was read,
  created, or exposed in this session, so nothing needs rotating.
- **security-standards `CLAUDE.md`:**
  - Integration tests stay out of `make check`, consistent with
    `docs/decisions/2026-07-06-factory-store-integration-gate.md`.
  - `psycopg` is imported lazily, so the default gate and file mode never load it.
  - No `make install` was run, and no deployed artifact changed.
- **`~/Developer/code-standards/STANDARDS.md`:**
  - `make check` is green, and `/code-review` ran.
  - The walk logic is shared rather than duplicated (`walk_records`).
  - Functions stay under the repo's complexity limit of 10.
  - No new suppression comments: the one `noqa: BLE001` moved with the walker code it already
    annotated.
