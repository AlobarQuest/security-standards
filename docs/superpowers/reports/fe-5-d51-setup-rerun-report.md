Outcome: done

# FE-5 D-51 A: the chain setup re-runs on a populated database

Handoff: `sds-hq/state/handoffs/fe-5-d51-setup-rerun.md`. Branch `hq/fe-5-d51-setup-rerun`, base
`origin/main` `4e83d7a8`. Worker W-161.

## What I built

Three integration tests in `tests/test_factory_db.py`, under the existing `integration` mark and
the existing `chain_db` fixture (a new database per test on the disposable cluster). No runtime
code changed: `git diff origin/main -- src` is empty.

Shared helpers, all in the test module:

- `OWNER_DROP_STATEMENT = "DROP TABLE public.factory_events"`: the D-51 A act's exact statement,
  as a module constant the FE-5 plan can quote.
- `_schema_state(owner)`: what the setup builds, read from the catalog: the table's columns,
  constraints and owner; its non-internal triggers (name, function, type bits, enabled state);
  the `factory_events_*` functions (owner, `SECURITY DEFINER` flag, `proconfig` search path,
  body); the table grants for every grantee; and both roles' attributes and `rolconfig`. It reads
  no password or SCRAM verifier, so a failing compare can't print one.
- `_assert_roles_hold_only_their_grants(chain_db)`: the body of the existing
  `test_roles_hold_only_their_grants`, extracted so the new tests reuse it. The existing test calls
  it and keeps its own row-count assert.
- `_assert_owner_refused_changes(chain_db)` and `_assert_role_passwords_work(chain_db)`.

### What each test proves

1. `test_setup_reruns_on_a_populated_chain_and_changes_nothing`: with five appended events,
   `db_setup.setup(owner)` runs again and exits cleanly. Every row is byte-identical (`_rows`
   before equals after). The catalog state is identical. The triggers still refuse `UPDATE`,
   `DELETE` and `TRUNCATE` for the owner (`InsufficientPrivilege`). Each role still holds exactly
   its grants. Both role passwords still log in. The append role appends a sixth event whose
   `prev_hash` is the old head's hash, and `verify` under the read role passes with head seq 6.
2. `test_owner_drop_then_setup_then_reimport_restores_the_chain`: the D-51 A act. The test
   snapshots the catalog state of the fixture's fresh setup, writes a five-event file, and imports
   it through `import-file` as the append role. Then, as the owner, it runs
   `OWNER_DROP_STATEMENT` and `db_setup.setup(owner)`. The table is empty, and the catalog state
   equals the fresh setup's: the same triggers, grants, constraints, owner, functions and role
   attributes. Both role passwords log in with no `ALTER ROLE` since the fixture's. A second
   `import-file` of the same file exits 0 and prints `imported: 5 events, head <file head>`, and
   the rows equal the first import's. `verify` under the read role prints
   `chain ok: 5 events, head <file head>`. After the import, the owner's `UPDATE`, `DELETE` and
   `TRUNCATE` are refused again, and the roles hold only their grants.
3. `test_only_the_owner_can_drop_the_chain`: with five events, the append role's `DROP TABLE` is
   refused with `InsufficientPrivilege`. The read role's is refused with `ReadOnlySqlTransaction`,
   because its sessions default to read-only. In a `SET TRANSACTION READ WRITE` transaction, the
   read role is still refused with `InsufficientPrivilege`, so the refusal doesn't rest on the
   read-only default alone. Afterwards the rows and the catalog state are unchanged.

### The exact owner statement for the act

```sql
DROP TABLE public.factory_events
```

It's run as the owner (the role that ran `db_setup`), followed by
`python -m factory_events.db_setup` under the same owner, then the session's
`import-file`. Nothing else is needed: no schema drop, no role change, and no password reset.
`DROP TABLE` drops the table's triggers, constraints and grants along with it. The two trigger
functions and the two roles survive the drop, and the setup's `CREATE TABLE IF NOT EXISTS`,
`CREATE OR REPLACE` triggers, and `REVOKE`/`GRANT` rebuild the rest.

## Tests and checks run

| Command | Result |
| --- | --- |
| `make check-integration` (throwaway `postgres:16-alpine` container) | 27 passed, 268 deselected. That's 24 before plus the 3 new tests. |
| `make check` (ruff check, ruff format, pyright, pytest) | ruff: all checks passed; format: 66 files already formatted; pyright: 0 errors, 0 warnings; pytest: 268 passed, 27 deselected. |

I created the worktree's `.venv` with `uv venv --clear --python 3.14` and `uv sync --frozen`
(none existed). The `.venv` is gitignored.

### One correction during the build

The first run of test 2 failed: I'd checked the owner's refusals right after the re-setup, on
the empty table. `UPDATE` and `DELETE` on zero rows fire no row-level trigger, so nothing was
refused. That's a test-ordering fault, not a setup gap: the catalog compare in the same test had
already matched the fresh setup's triggers. I moved the refusal check to after the re-import,
where the table holds rows.

## Mutations and their failures

Each mutation was temporary: it pointed `db_setup.SCHEMA_SQL` at a scratch copy of
`chain_schema.sql` under `/tmp` just before the re-run in the target test, or added one statement.
Then I ran `make check-integration` and restored the test file from a saved copy.
`src/factory_events/chain_schema.sql` was never edited. The final tree holds no mutation.

| # | Target test | Mutation | Result |
| --- | --- | --- | --- |
| M1 | 1 | The `DO` block's conditional `CREATE ROLE` replaced with unconditional `CREATE ROLE` for both roles (not idempotent) | Test 1 failed: `psycopg.errors.DuplicateObject: role "factory_events_append" already exists`. |
| M2 | 1 | `GRANT SELECT, INSERT, UPDATE` to the append role instead of `SELECT, INSERT` | Test 1 failed on the `_schema_state` compare (the `grants` item differed). |
| M3 | 2 | The read role's `GRANT SELECT` removed from the re-run's schema | Test 2 failed (`verify failed (InsufficientPrivilege)` and the state compare). |
| M4 | 2 | The `factory_events_no_truncate` trigger removed from the re-run's schema | Test 2 failed on the `_schema_state` compare (the `triggers` item differed). |
| M5 | 3 | The owner runs `ALTER TABLE factory_events OWNER TO factory_events_append` before the refusal checks | Test 3 failed: `DID NOT RAISE Error` on the append role's drop. |

The scratch mutations assigned the module attribute without restoring it, so later tests in the
same run also set up from the mutated schema. M1 also produced three fixture errors, and M3 also
failed `test_verify_walk_of_a_mac_sized_chain`. Each target test failed as listed, and the
unmutated suite passes.

## Whether CI runs these tests

Yes, but not as a required check. `.github/workflows/extended-tests.yml` job `integration` runs
`make check-integration` against a `postgres:16-alpine` service container on every pull request
and on every push to `main`. The workflow's header says it isn't a required status check. The
default gate (`quality.yml` → `make check`) deselects them through
`addopts = "-m 'not integration'"`. I didn't change CI.

## Files changed

- `tests/test_factory_db.py`: the three tests, the constant, four helpers, and the extraction of
  `_assert_roles_hold_only_their_grants` from `test_roles_hold_only_their_grants`.
- `docs/superpowers/reports/fe-5-d51-setup-rerun-report.md`: this report.

## Self-review

- Each new test asserts behavior (refusal types, rows, logins, the import's and verify's output)
  and the catalog, so a schema change that breaks the re-run fails at least one of them. M1 to M5
  show each test can fail.
- The catalog snapshot leaves out `pg_authid.rolpassword` on purpose. The password check is a
  real login as each role, which is what D-51 A needs, and keeps any verifier out of an assert
  message.
- The extraction of `_assert_roles_hold_only_their_grants` keeps the existing test's statements
  and order. The one behavior difference: the existing test's final row-count assert moved from
  the helper's end into the test, unchanged.
- I added no fixture. Every new test uses `chain_db` as is, so each still gets its own database.

## Findings

None. The setup restores everything the drop removed: the triggers, the constraints, the grants,
and the table's owner. It leaves what the drop didn't touch: the functions, their ownership, and
the roles with their passwords. The act needs only the owner's `DROP TABLE` and the setup.

## Concerns

- In the tests the owner is the cluster's superuser (`postgres`), because the harness connects as
  one. On the VPS the owner is the role that ran `db_setup` and owns the table. Owning the table is
  enough for `DROP TABLE`. The re-run also runs `REVOKE CREATE ON SCHEMA public` and
  `REVOKE TEMPORARY ON DATABASE`, which need the schema's and the database's owner. The first
  setup on the VPS already ran both as that owner, so the re-run needs nothing new. The tests
  don't prove a non-superuser owner, though.
- The act runs on a table whose rows are an imported copy. Any rows a holder appended after the
  import would go with the drop. The plan's rollback point (no holder has appended) is the
  precondition, and the act would need to check it, for example by checking that the database head
  equals the file's head before the drop. That check belongs in the FE-5 plan's step, not in these
  tests.
- `chain_schema.sql` assumes the trigger functions live in `public`. If someone ever drops the
  schema instead of the table, the roles survive but the setup's `REVOKE CREATE ON SCHEMA public`
  would need the schema to exist. D-51 A names only the table drop, so this doesn't apply.

## Standards followed

- **Code Brain rule 5 (never log secrets):** no DSN or password reaches an assert, a log, or this
  report. The owner connects through the redacting `Dsn` class, each role through
  `db.ConnectParams` (whose repr leaves the password out), and the throwaway `ROLE_PASSWORD`. The
  catalog snapshot reads no password or verifier. The harness never prints the container's DSN.
- **Code Brain rule 4 (never silently swallow an exception):** every expected refusal goes
  through `_refused`, which catches only `psycopg.Error` and returns its type, and each new test
  asserts that type (`InsufficientPrivilege` or `ReadOnlySqlTransaction`).
- **Code Brain rule 3 (structured logs to stdout):** the tests add no logging and no log file.
- **Infra Brain 591, 592, 593 (no BWS token in tracked files or commits, no inline
  `BWS_ACCESS_TOKEN`):** I ran no `bws`, read no Keychain item, and wrote no token. The change
  holds no secret.
- **Infra Brain 1032 (a credential in a transcript is exposed):** no credential appeared in this
  session. The container's random password stayed in the harness's environment, never printed.
- **Infra Brain 212 (HTTPS for public FQDNs):** doesn't apply. The tests connect only to a local
  throwaway container on `127.0.0.1`.
- **Workspace invariant (SQLite doesn't enforce what Postgres does):** all three tests run on
  Postgres 16 through `make check-integration`. None uses SQLite.
- **Construction mode:** this change adds tests and a report only, on a branch, with a PR that I
  don't merge. It takes no production action and never connects to the VPS chain database.
