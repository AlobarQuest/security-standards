Outcome: done

# FE-5 R-SS: remove the file path from factory_events

Worker W-165. Branch `hq/fe-5-r-ss`, base `origin/main` `237e422`. PR:
https://github.com/AlobarQuest/security-standards/pull/95. The PR body's first line is
`hold: merge inside FE-5 step 10`. It isn't merged.

## What I built

With neither chain password set, `emit`, `adapt`, and `verify` refuse with
`no chain password is set` instead of writing or verifying `~/.factory/events.jsonl`. The nightly
has no file mode and no `ship` stage, and with no `~/.factory/chain-db.env` it fails by name.

### Changes by file

The following lines are at `HEAD` of the branch.

- `src/factory_events/chain.py`
  - Lines 52-54: a new `_require_password()` raises `db.ChainError("no chain password is set")`
    when `database_mode()` is false. The text is the plan's, verbatim.
  - Lines 77-91: `verify_params`, `append_event`, and `event_ids` call it in place of
    `store.append_event` and `store.event_ids`. `verify_params` no longer returns `None`.
  - `database_mode()` (line 46) stays. Two things still need it: `_cmd_ship`, and the order of the
    checks, because it runs `_refuse_retired()` before the password check. That keeps a set retired
    variable refusing by name. `_refuse_retired` (line 40) is unchanged.
  - The module docstring (lines 1-5) and the `RETIRED_VARS` comment are rewritten. Neither
    describes a file fallback any more.
- `src/factory_events/cli.py`
  - Lines 51-76: `_cmd_verify` is the former `_verify_database`. `verify_params()` moved inside its
    `try`. The file branch, the file-only `--record-anchor` refusal, and the
    `--tolerate-torn-tail` refusal are gone.
  - The `--tolerate-torn-tail` argument is removed from the parser. The unused `store` import is
    removed.
  - `ship` is unchanged in behavior: it refuses while a password is set. Its message now says
    "pre-cut-over file". `import-file` is unchanged.
  - The help strings and the docstring name the database chain.
- `src/factory_events/store.py`: only the docstring changes (lines 1-13). It states that `emit` and
  `adapt` never reach `append_event`, and names the helpers `import-file` and `ship` still read.
  The functions stay; see Concerns.
- `src/factory_events/ship.py`, `db.py`, `db_setup.py`, and both adapters: docstrings and comments
  only, with no file-chain wording left.
- `scripts/factory-events-nightly.sh`
  - Header lines 2-3 and 6-10 are rewritten. `FACTORY_DB_DSN` is no longer listed as this script's
    config, because only `ship` used it.
  - Lines 116-131: the mode switch is gone. A missing `chain-db.env` fails the run with
    `missing <path>: the database chain's settings (no file chain since FE-5)` (line 130), which
    pings `/fail`.
  - The former database-mode block (settings parse and password fetch) is unindented and
    otherwise unchanged.
  - `run_factory_events` always passes the four variables.
  - The pre-adapt verify runs unconditionally, and the second verify always uses
    `--record-anchor`.
  - The `ship` stage is gone (line 238 onward). The `shipped` and `head_seq` observation facts
    stay, at 0, exactly as in P-SS's database mode.
- `src/factory_events/README.md`: the intro, the CLI list (`emit`, `verify`, `ship`), "The
  database chain", "Recovery", and "Nightly" are rewritten. The "File mode" section and the
  `--tolerate-torn-tail` recovery procedure are gone. `FACTORY_DB_DSN` is marked "ship only, until
  FE-6".
- `.bws-secrets.toml`: the comment no longer calls the append-password fetch conditional on
  database mode.
- `tests/conftest.py` lines 57-109: `MemoryChain` and the `memory_chain` fixture.
  - The fixture fakes `db.append_event` and `db.event_ids` with the same link formula. The fake
    append asserts that it receives the append role.
  - The fixture also sets the append password and disposable settings.
  - It patches `db`, not `chain`, so `chain.py`'s changed routing still runs in every test that
    uses it.

### Callers outside this repository

I checked callers outside this repository with `git grep` on each repository's `origin/main`. I
didn't check out or pull anything.

- **intent-packages:** `operations.py` `_verify_chain_integrity` runs file-mode `verify`. After this
  PR it gets a refusal, and `verify_approval` returns False, which fails closed. R-IP removes this
  call.
- **orchestrator:** `package_sources.py` `_verify_factory_chain` gets the same fail-closed result,
  and R-OR covers it.
- **Shared helpers:** both repositories import only `store.walk_records` and
  `chain.connection_params`, and both stay.
- **sds-hq:** `check_chain` reads the file itself and never calls `factory_events`, so it is open
  question 1, not this PR. Its tests stub the approve child.
- **vps-backup:** it doesn't call `--tolerate-torn-tail` or file-mode `verify`.
- **Lifecycle commands:** intent-packages `transition`, `revise`, and `supersede` also emit, so
  they now need a password too. The rotation proposer runs `revise` and `transition` with none.
  The plan settles that case as by design (open question 7).
- **Attributes:** no outside repository calls `database_mode`, `verify_params`,
  `chain.append_event`, or `chain.event_ids`.

So I found no unnamed caller that breaks, and I wrote no question file.

## Tests and checks

| Gate | At `237e422` | At `HEAD` | Result |
| --- | --- | --- | --- |
| `make check` (ruff, ruff format, pyright, shellcheck, pytest) | 268 collected, 268 passed, 27 deselected | 268 collected, 268 passed, 25 deselected | Green both times |
| `make check-integration` (throwaway `postgres:16-alpine` container) | 27 passed | 25 passed | Green both times |
| Security scanner (`security_scan.cli . --category security`) | — | Exit 0; WARN and INFO only, all in files this PR doesn't touch | No BLOCK |

The counts come from the pytest summary lines. I compared the before and after node-ID lists
(`pytest --collect-only`) with `comm`.

### The act-step-11 test fails on `237e422`

I wrote `test_emit_with_no_chain_variable_refuses_and_creates_no_file`
(`tests/test_factory_chain_mode.py` line 130) before I changed `src/`. It ran against the
untouched source and failed:

```
>       assert proc.returncode == 1, proc.stdout
E       AssertionError: evt-075493023df04d598d58c6a8a0ae1d7d
E       assert 0 == 1
... stderr='seq=1 head=fd327e22a9c3047511c68331a4693fea5eb559c8d55ad9720173ecdb31e04bc4\n'
```

At `237e422`, `emit` with no chain variable exited 0 and appended seq 1 to the scratch file. At
`HEAD` it exits 1 with `emit failed: no chain password is set`, and the scratch
`FACTORY_EVENTS_HOME` stays empty: no `events.jsonl`, no lock file, no `state/`.

### CI

All checks on PR #95 at `c4419e2` passed. I read the following counts from the job logs:

- **Quality, "Lint, type-check, and test"** (run 43661750918): `collected 293 items / 25
  deselected / 268 selected`, then `268 passed, 25 deselected`.
- **Extended tests, "Factory-store integration tests"** (run 43661750988): `25 passed, 268
  deselected`.
- **Security Scan, "scan"** (run 43661750935): `35 passed` (the read-guard tests). Its scanner
  step passed.

The `push` event triggered a duplicate Quality run and a duplicate Security Scan run (43661736579
and 43661736577). Both passed.

### Removed tests

The following tests were removed, each with what replaces its coverage.

| Test | Why it went | Where its coverage is now |
| --- | --- | --- |
| `test_factory_chain_mode.py::test_settings_without_a_password_stay_on_the_file_chain` | It asserted the file fallback this PR removes. | Replaced by `test_settings_without_a_password_refuse`, which uses the same settings and asserts the refusal. |
| `test_factory_chain_mode.py::test_file_mode_emit_is_unchanged_and_never_loads_psycopg` | It asserted that file-mode `emit` succeeds. | The stdout parse contract stays covered by `test_emit_stdout_parses_when_json_logs_share_stdout` (unit) and `test_factory_db.py::test_emit_stdout_parses_to_the_emitted_id` (integration). The subprocess `emit` path is covered by the act-step-11 test. |
| `test_factory_chain_mode.py::test_database_verify_rejects_file_only_flag` | The flag it rejected no longer exists. | Replaced by `test_verify_no_longer_takes_tolerate_torn_tail`, which asserts a usage error. |
| `test_factory_chain_mode.py::test_file_verify_rejects_record_anchor` | File-mode `verify` no longer exists. | Replaced by `test_verify_with_no_chain_password_refuses[plain, against-anchor, record-anchor]`. |
| `test_factory_cli.py::test_verify_ok_and_failure` | It tested file-mode `verify` passing, then failing on a tampered line. | Tamper detection on the database chain: `test_factory_db.py::test_verify_finds_a_tampered_row`. The same walk over a file: `test_factory_store.py`'s `walk_records` tests, unchanged. |
| `test_factory_cli.py::test_verify_tolerate_torn_tail_cli_path` | The flag is gone. | The flag's absence: `test_verify_no_longer_takes_tolerate_torn_tail`. The store's own torn-tail tests still run (see Concerns). |
| `test_factory_nightly.py::test_file_absent_runs_adapt_verify_ship_as_before` | The file mode is gone. | Replaced by `test_file_absent_fails_by_name_and_runs_nothing`. |
| `test_factory_nightly.py::test_file_absent_fetches_nothing_through_the_nightly_item` | The file mode is gone. | The no-fetch half is asserted in `test_file_absent_fails_by_name_and_runs_nothing`: no `security` call and no append-password `bws` call. |
| `test_factory_ship.py::test_verify_against_anchor_passes_and_fails` (integration) | It tested file-mode `verify --against-anchor` against the projection's `chain_heads` anchor. That anchor check left with the file branch. | The database anchor: `test_factory_db.py::test_verify_anchor_round_trip`. |
| `test_factory_ship.py::test_verify_against_anchor_with_no_anchor_yet_passes` (integration) | The same reason. | `test_factory_db.py::test_verify_anchor_round_trip` covers the first `--record-anchor` with no anchor yet. |

### Added tests

All the added tests are in `tests/test_factory_chain_mode.py`, except the last.

- `test_emit_with_no_chain_variable_refuses_and_creates_no_file` (line 130): act step 11's check.
- `test_settings_without_a_password_refuse` (line 140): all three `chain` functions raise exactly
  `no chain password is set`, and `emit` refuses without writing a file.
- `test_verify_with_no_chain_password_refuses[plain|against-anchor|record-anchor]` (line 156): no
  anchor is written.
- `test_adapt_with_no_chain_password_refuses_and_keeps_no_watermark` (line 162): covers both
  adapters, and checks that no `state/` directory appears.
- `test_verify_no_longer_takes_tolerate_torn_tail` (line 179).
- `test_factory_nightly.py::test_file_absent_fails_by_name_and_runs_nothing` (line 208).

### Moved tests (same node IDs, different chain)

- **Adapter tests:** all 13 in `test_adapter_high_power.py` and all 23 in
  `test_adapter_change_manager.py` keep their names and assertions. They read the events back from
  `memory_chain`, not `store.iter_records()`. They stay in CI's collected set, because no CI job
  needs Postgres for them.
- **CLI tests:** `test_emit_appends_valid_event`, `test_emit_json_payload`,
  `test_emit_rejects_bad_action`, and `test_adapt_high_power_via_cli` in `test_factory_cli.py` move
  the same way. `test_emit_rejects_bad_action` now also asserts that nothing was appended, so a
  refusal for a missing password can't pass it.
- **Unchanged files:** `test_factory_store.py` and `test_factory_db.py` need no change. They call
  the store's read and write helpers directly to build fixture files, and never go through `emit`
  or `adapt`. `FACTORY_EVENTS_HOME` stays in them, because it locates `state/`.

## Self-review

I ran `/code-review` at high effort on `237e422..HEAD`. I acted on its findings as follows:

- **Fixed:** the stale "database mode" comment in `.bws-secrets.toml` (commit `c4419e2`).
- **Intended behavior:** "every `emit` caller without a password now fails" is the act's
  fail-closed design. I checked each outside caller (see the earlier section).
- **Left, and listed under Concerns:** dead code that remains in `store.py` and `ship.last_anchor`;
  `shipped` and `head_seq` posted as a constant 0; and `ship` running without a password.
- **Not changed:**
  - `_refuse_retired()` runs twice per call (once in `database_mode`, once in
    `connection_params`). That's harmless, and it was already the case before this PR.
  - The nightly still fetches the change-manager bearer before it checks for `chain-db.env`. I
    kept the order to keep the diff small. The run still fails before any `factory_events`
    command and before any append-password fetch.

## Concerns

1. **Dead code left in `store.py`.** The plan says the write path must be "no longer reachable",
   not removed, so I left the module's functions in place. After this PR, the following have no
   caller in `src/`:
   - `append_event` (and its lock file)
   - `event_ids`
   - `verify_chain`
   - `parsed_records`
   - `_parse_records`, with its `tolerate_torn_tail`

   Only tests use them: `test_factory_store.py`, and the fixture builders in `test_factory_db.py`
   and `test_factory_ship.py`. `ship.last_anchor` is in the same state: only
   `test_factory_ship.py` calls it. These could go in FE-6 along with `ship`.
2. **No command verifies a file by itself any more.** The README's recovery steps used
   `verify --tolerate-torn-tail` on a restored `events.jsonl`. After this PR, the only file check
   is inside `import-file`, which refuses an unparseable or broken file. The sealed file's
   integrity check then rests on step 4's `shasum` and P-VB's backup check.
3. **`ship` without a password still runs.** Until FE-6, `ship` in a shell with no password
   projects whatever `events.jsonl` holds. After the seal the file is absent, so `ship` inserts
   nothing, and `ship --rebuild` truncates the projection's `factory_events` (never
   `chain_heads`). The plan keeps `ship` until FE-6, and the nightly no longer runs it. I didn't
   change it.
4. **Observation facts.** The `chain:factory-events` observation still posts `shipped=0` and
   `head_seq=0` every night, as P-SS's database mode already did. I didn't check whether the
   orchestrator's observation intake reads either one, so I kept the shape unchanged.
5. **Interactive lifecycle commands need the password.** intent-packages `transition`, `revise`,
   and `supersede` emit too, so after R-SS they refuse in a shell with no password. The
   orchestrator's session wrapper wraps only `approve` and `import-file`. The plan treats the
   rotation proposer's emits as failing by design (open question 7), but it doesn't mention
   interactive `transition`, `revise`, or `supersede`.
6. **The refusal text is the plan's verbatim string.** `no chain password is set` names no value.
   It doesn't name the two variables either. Code Brain rule 5 asks a refusal not to log a value,
   which it doesn't. If HQ wants the variable names in the text, they'd be a suffix, and every
   test here matches the prefix except one. `test_settings_without_a_password_refuse` matches the
   whole string (`^...$`) and would need its pattern changed.
7. **CLAUDE.md is stale.** The repo's `CLAUDE.md` says `make check` doesn't exist here and that CI
   never runs the pytest suite. Both are out of date: the vendored `check` target exists and runs
   268 tests, and `quality.yml` runs it. I didn't edit `CLAUDE.md`, which is outside this
   handoff's scope.

## Standards followed

- **Code Brain rule 3 (structured logs to stdout, not files).** The PR adds no log file. The
  nightly keeps its existing `~/Library/Logs/factory-events.log` and `log()`. No Python logging
  changed.
- **Code Brain rule 4 (never swallow an exception).** Every new refusal either raises `ChainError`
  or exits 1 with a message on stderr:
  - `emit failed:`, `VERIFY FAIL:`, and `ADAPT FAIL (...):` for the CLI commands.
  - The nightly's missing-file case goes through `fail`, which logs, pings `/fail`, and exits 1.

  Nothing falls back to the file.
- **Code Brain rule 5 (never log secrets).** The refusal text has no value in it. The nightly's
  password handling is the P-SS code, unindented: an assignment prefix only, `unset` after the
  last command, and never logged. The existing nightly tests for that pass unedited, for example
  `test_file_present_keeps_the_password_and_token_out_of_argv_and_the_log`. The fake's password
  in `conftest.py` is a placeholder string.
- **Infra Brain 591, 592, and 593 (no BWS token in tracked files, no inline `BWS_ACCESS_TOKEN`).**
  No token or token-shaped value was added. The scanner exits 0 with no BLOCK finding. The only
  UUID touched is the existing append-secret ID, in an existing comment.
- **Infra Brain 1032 (a credential seen in a transcript is exposed).** No credential appeared in
  this session. I didn't run `bws`, read the Keychain, or connect to the VPS database. The
  integration tests used a throwaway local container with a random password, which the script
  never prints.
- **Infra Brain 212 (HTTPS for public FQDNs).** It doesn't apply: this PR adds and changes no
  public endpoint.
- **Workspace invariant #22 (`--color no` on every parsed `bws` call).** Both `bws` calls in the
  nightly keep `--color no` and the `env -u FORCE_COLOR -u CLICOLOR_FORCE` prefix. The PR adds no
  `bws` call.
- **The repo's `CLAUDE.md` and `make check`.** `make check` passes, and so do `make
  check-integration` and the security scanner. `/code-review` ran; see Self-review. I didn't run
  `make install`, and I didn't touch `~/.factory`, the deployed nightly, or any LaunchAgent.
- **Construction mode.** The PR follows the repo's coding rules, green gates with real collected
  counts, and a PR held for a human merge inside the act. The guard is shown to fire: the
  act-step-11 test failed on `237e422` and passes at `HEAD`. I didn't take a production action.
