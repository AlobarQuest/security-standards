Outcome: done

# Report: fe-password-only-ss (ADR-0055 amendment 26, increment 1)

PR: https://github.com/AlobarQuest/security-standards/pull/92 (branch `hq/fe-password-only-ss`,
base `cb832f3`). I didn't merge it.

## What I built

Each factory-events BWS secret holds only its role's password. `factory_events.chain` builds every
append-role and read-role connection from five settings: `FACTORY_EVENTS_APPEND_PASSWORD`,
`FACTORY_EVENTS_READ_PASSWORD`, `FACTORY_EVENTS_DB_HOST`, `FACTORY_EVENTS_DB_PORT` and
`FACTORY_EVENTS_DB_NAME`. Host, port, and database name have no default in code. The role names
are the constants `APPEND_ROLE` (`factory_events_append`) and `READ_ROLE` (`factory_events_read`),
and a test pins them to `chain_schema.sql`.

### The public surface for increments 2 and 3

- `chain.connection_params(role) -> db.ConnectParams` is the one builder. It requires the role's
  password and the three settings. Pass `chain.READ_ROLE` for a strict read-role connection, which
  is what `chain_db` and `factory_chain_read` need.
- `chain.verify_params() -> db.ConnectParams | None` returns the read role's connection when the
  read password is set, else the append role's, else `None` (file mode).
- `chain.database_mode() -> bool` is true when either password is set. It raises `ChainError` when
  a retired variable is set.
- `chain.APPEND_PASSWORD_VAR`, `READ_PASSWORD_VAR`, `DB_HOST_VAR`, `DB_PORT_VAR`, `DB_NAME_VAR`,
  `APPEND_ROLE`, `READ_ROLE` and `RETIRED_VARS`.
- `db.ConnectParams` is a frozen dataclass with `host`, `port`, `dbname`, `user` and `password`.
  Its `password` field is `repr=False`, so `repr()` and `str()` leave it out. `as_kwargs()` returns
  the psycopg keyword parameters as a dict. Don't log that dict. `chain.py` adds no top-level
  import, so it still loads only `db` and `store`.

### Behavior (amendment 26, items 3 to 7)

- Mode selection (item 4):
  - A set password selects the database chain.
  - An append with only the read password refuses with `FACTORY_EVENTS_APPEND_PASSWORD is not
    set`. That wording is correct whichever variables are set (follow-up 5 on orchestrator PR
    #699).
  - A verify uses the read password, else the append password.
  - The three settings with no password set stay on the file chain, and a test pins this.
- Fail closed by name (item 5):
  - Each missing setting, unset or empty, raises `ChainError("<VAR> is not set")`.
  - A set `FACTORY_EVENTS_APPEND_DSN`, `FACTORY_EVENTS_READ_DSN` or `FACTORY_EVENTS_IMPORT_DSN`
    raises `ChainError("<VAR> is retired: …")` on every command: emit, adapt, verify, ship and
    import-file. This holds even with no password set, so a stale holder can't drop silently to
    the file chain.
  - `cli.py`'s `verify` and `ship` mode checks were outside any `try`. They now catch
    `ChainError` and print `VERIFY FAIL` or `SHIP FAIL` without a traceback.
- Item 7: `import-file` connects with `connection_params(APPEND_ROLE)`, and
  `FACTORY_EVENTS_IMPORT_DSN` is retired.
- One addition the amendment doesn't name: a `FACTORY_EVENTS_DB_PORT` that isn't decimal digits
  refuses with `FACTORY_EVENTS_DB_PORT is not a port number`. Without this check it failed as an
  opaque driver error that looks like an unreachable database. The amendment's fail-closed rule
  already covers it, and the message carries no value.

## Tests and checks

| Check | Result |
|---|---|
| `make check` baseline at `cb832f3` | 221 passed, 21 deselected |
| `make check` (ruff check, ruff format --check, pyright, pytest) | 249 passed, 24 deselected (272 collected); ruff and pyright clean |
| `make check-integration` baseline at `cb832f3`, disposable `postgres:16-alpine` from `scripts/check-integration.sh` | 21 passed |
| `make check-integration` | 24 passed, 249 deselected |
| Security scanner from the worktree root (`--category security`) | rc 0; BLOCK 0, WARN 4, INFO 1 |

The scanner's WARN and INFO findings are all in files this change doesn't touch: the
2026-06-12 plans and specs and `rules_cache.json`. Its allowlisted entries are the repo's
existing test fixtures and history, and the scanner prints them truncated.

### New and changed tests

- `tests/test_factory_chain_mode.py`:
  - The builder: exact keyword parameters for each role, and a repr and str without the password.
  - The role constants match `chain_schema.sql`.
  - Each missing setting refuses by name, unset and empty: 4 settings × 2 cases.
  - Each retired variable refuses emit, verify, ship and adapt: 3 × 4 cases. A retired variable
    beside a password refuses `import-file`.
  - A malformed port refuses by name (3 cases).
  - Mode selection: settings with no password stay in file mode, and the verify role is picked
    for read-only, append-only, and both.
  - `import-file` with only the read password refuses.
  - Every refusal test uses the placeholder password `sentinel-pw-7f3a9c`. It asserts the value
    is absent from the exception text and from captured stdout and stderr. `jsonlog` writes its
    JSON records to stdout, so captured stdout is the captured log stream. The existing
    unreachable-database subprocess tests for emit, verify and import keep the same assertion
    against the driver path.
- `tests/test_factory_db.py` (integration):
  - Each role connects from `ConnectParams` built from `FACTORY_TEST_DSN`'s host and port. The
    owner stays a DSN for `db_setup`.
  - CLI tests set the four variables through `ChainDb.env()`.
  - Added a wrong-port case and a wrong-password case. Each changes one part and fails closed
    without printing either password.
  - Added a verify under the read password.
- `tests/conftest.py`: the autouse scrub covers the five settings, the three retired names, and
  `FACTORY_EVENTS_OWNER_DSN`.

## Files changed

- `src/factory_events/chain.py`: the settings, role constants, builder, mode selection and
  retired-variable refusal.
- `src/factory_events/db.py`: adds `ConnectParams`. `_connect` takes it, as do `append_event`,
  `event_ids`, `verify` and `import_file`. Docstrings no longer say "DSN".
- `src/factory_events/cli.py`: the module docstring, `ChainError` handling around the
  verify and ship mode checks, `import-file` as the append role, and the help text.
- `src/factory_events/jsonlog.py`: docstring wording only.
- `src/factory_events/README.md`: the variable table, the database-chain paragraph, and the
  `import-file` line.
- `tests/conftest.py`, `tests/test_factory_chain_mode.py`, `tests/test_factory_db.py`.
- `docs/superpowers/reports/fe-password-only-ss-report.md` (this file).

## Self-review

I ran `/code-review` at medium on `main...HEAD` and acted on 2 of its 7 findings:

- Acted on: a malformed port now refuses by name (the check is described in "Behavior").
- Acted on: the `import-file` comment now says why it uses the append role.
- Not acted on: `database_mode()` raises. The amendment requires the retired refusal on every
  path, file mode included, and every CLI caller catches `ChainError`. The adapters call
  `chain.event_ids()` before they write anything.
- Not acted on: `_PASSWORD_VARS[role]` raises `KeyError` for an unknown role. Only the two
  constants are valid, so an unknown role is a programming error, not a setting.
- Not acted on: `_refuse_retired()` runs twice on some paths. It's harmless and keeps each public
  function safe to call alone.
- Not acted on: `_connect` lists the fields instead of using `**as_kwargs()`. Pyright rejects
  `**dict[str, str]` against `psycopg.connect`'s typed parameters. Naming the five fields keeps
  the type checker on the production path.
- Out of scope: the README's `FACTORY_DB_DSN` example. That's the Mac projection's setting, and it
  retires in FE-6 (amendment 26 item 9).

## Concerns

- As the amendment's "Increments" section expects, the intent-packages and orchestrator
  integration suites fail against this checkout until increments 2 and 3 land, because they still
  set the retired variables. With a retired variable set, `factory_events` refuses rather than
  ignoring it.
- `ConnectParams.as_kwargs()` returns a plain dict, whose repr includes the password. Increments 2
  and 3 must pass it straight to `psycopg.connect` and never log it. The dataclass itself is safe
  to repr.
- The handoff's standards don't cover input validation of non-secret settings. The port check is
  my reading of item 5's fail-closed rule.
- No tool showed me a credential value. I fetched no BWS secret and called no infraops tool.

## Standards followed

- **Code Brain rule 5 (never log secrets).** No log record, exception message or repr holds a
  password. `ConnectParams` leaves out the password in its repr. Refusals name only variables. The
  driver error path still logs only the error's type and raises `from None`. Tests assert that the
  placeholder password is absent from exceptions, stdout (the JSON log stream), and stderr.
- **Code Brain rule 4 (never silently swallow).** Every missing or retired setting raises
  `ChainError`. The two new `except ChainError` blocks in `cli.py` print the refusal and return 1.
  No exception is swallowed.
- **Code Brain rule 3 (structured JSON logs to stdout).** I kept the existing `jsonlog` use
  unchanged and added no logging and no file logging.
- **Infra Brain 591, 592 and 593 (no BWS token in tracked files).** No token appears anywhere in
  this change. The test passwords are a fixed placeholder and a per-run `secrets.token_hex` for
  the disposable cluster. The scanner found 0 BLOCK findings.
- **Infra Brain 1032 (exposed credential: stop and report).** No credential value appeared in this
  session, so nothing needed reporting.
- **Infra Brain 3035 `bws.secret-holds-value-only` and `docs/build-agent-secrets.md` rule 7.**
  This PR implements that rule for factory-events. The code reads a bare password per role,
  takes the address from plain settings, and accepts no whole-DSN variable for either role, tests
  included.
