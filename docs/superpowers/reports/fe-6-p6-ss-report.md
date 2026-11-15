Outcome: done

# FE-6 prep PR P6-SS report

Worker W-182. Branch `hq/fe-6-p6-ss`, base `origin/main` `0226b19`. Spec: orchestrator `4644eb1e`,
`docs/superpowers/plans/2026-11-15-fe-6-mac-db-retire.md`, section "2. P6-SS", act step 12, and
open question 4, answered by HQ as "drop the `shipped` and `head_seq` facts".

Pull request: https://github.com/AlobarQuest/security-standards/pull/97 (change commit `10eb1a8`).

**Hold:** the pull request is open and unmerged, with no auto-merge, titled with `hold: merge inside FE-6 step 12`. It
merges inside the act, after step 11 deletes the gitignored `deploy/factory-events-db/.env`.

## What I built

I checked every line number the plan and the handoff cite against `0226b19`. All of them match.

- Deleted `src/factory_events/ship.py`.
- `src/factory_events/cli.py`: deleted `_cmd_ship` and the `ship` parser, and dropped `ship` from
  the module docstring. No import became unused: `chain`, `ChainError`, and `sys` still have
  callers, and ruff and pyright are clean.
- `src/factory_events/store.py`: dropped "ship projects the pre-cut-over file until FE-6" from the
  docstring.
- `src/factory_events/README.md`: deleted the `ship` bullet and the `FACTORY_DB_DSN` example line.
  Rewrote nightly step 5 to "Pings success with the verify output." The observation no longer
  reports `shipped`, so the sentence about it went too. The Recovery section stays, as the plan
  says.
- Deleted `deploy/factory-events-db/docker-compose.yml`, and deleted `.gitignore` lines 22-23 (the
  comment and the `deploy/factory-events-db/.env` entry).
- `.bws-secrets.toml`: deleted the `ea09a782-…` row (`factory-events/POSTGRES_PASSWORD`). I
  rewrote the header and changed `consumption` from `environment-injection` to `code-reference`.
  For the reasoning, see the following Self-review section.
- `scripts/factory-events-nightly.sh`: deleted `SHIPPED=0`, `HEAD_SEQ=0`, and their two
  `observe_fact` calls. Replaced the `_cmd_ship` comment: "The nightly has no projection step: the
  database is the chain of record, so verify is the last step before the success ping." This
  edits the deployed script, so act step 12's `make install` has a change to deploy.
- Deleted `tests/test_factory_ship.py` (3 integration tests).
- `tests/test_factory_chain_mode.py`: dropped `["ship"]` and its `"ship"` id from the parametrize
  (3 cases, one per `chain.RETIRED_VARS` entry), and deleted `test_ship_refuses_in_database_mode`.
- `tests/test_factory_nightly.py`: both tests that asserted `shipped == "0"` now assert that
  `shipped` and `head_seq` are absent. The file-absent test also asserts
  `anchor_verified == "false"`, which proves that the facts file was written, so the absence
  checks aren't vacuous.

## Tests and checks run (with counts)

I ran every command in this worktree, with the worktree's `.venv` (created with `uv sync`;
`uv.lock` is unchanged).

| Check | Before (`0226b19`) | After |
| --- | --- | --- |
| `make check` (ruff, ruff format, pyright, shellcheck, pytest) | exit 0, 268 passed, 25 deselected | exit 0, 264 passed, 22 deselected; pyright 0 errors |
| `make check-integration` | exit 0, 25 passed | exit 0, 22 passed |
| Security scanner, repository root, `--category security` | 0 BLOCK, 4 WARN, 1 INFO, 12 allowlisted | identical: no finding added or removed, and the allowlist is unchanged |
| Manifest drift | declared minus referenced is `{ea09a782-…}` (computed from `declared_uuids` and `referenced_uuids`; `diff()` reports no stale row under `environment-injection`, which skips that check) | `undeclared=set()`, `stale=set()` under `code-reference` |
| `bash -n scripts/factory-events-nightly.sh` | — | exit 0 |
| PR #97 CI | — | all pass: Lint, type-check, and test (2), scan (2), Factory-store integration tests |
| `/code-review` (medium) on the branch diff | — | 4 findings, none confirmed; see the following Self-review section |
| `python -m factory_events ship` | — | `invalid choice: 'ship' (choose from emit, verify, adapt, import-file)`, exit 1 |

The counts drop exactly as the plan predicts: unit -4 (3 parametrize cases and
`test_ship_refuses_in_database_mode`) and integration -3 (`test_factory_ship.py`). Dropping the
facts changes no count, because I converted those two asserts in place.

Notes on the checks:

- **The integration run didn't use Docker.** The handoff forbids `docker`, and
  `scripts/check-integration.sh` starts a Docker container when `FACTORY_TEST_DSN` is unset. So I
  ran `make check-integration` with `FACTORY_TEST_DSN` pointing at a throwaway Homebrew
  PostgreSQL 16 cluster. The harness was a script outside the repo (`/tmp/w182-it.sh`): `initdb`
  in a `mktemp -d` directory with SCRAM auth and a random password that was never printed,
  listening on 127.0.0.1 on a random port, and stopped and deleted on exit. My first try used
  trust auth, and it failed
  `test_one_wrong_part_fails_closed_and_prints_no_password[wrong-password]`, because trust accepts
  any password. That was the harness's fault, not the code's. With SCRAM, both runs passed in full.
- **`ship` exits 1, not 2.** `cli.main()` catches argparse's `SystemExit` and returns 1 for every
  usage error, which is existing behavior (`python -m factory_events bogus` also exits 1). The
  error message is argparse's.
- **The absence asserts catch a regression.** I temporarily added `observe_fact shipped 0` back to
  the nightly. Both converted tests failed, then passed again after I restored the file from a
  copy.
- **Test names in manifests and evidence:** I grepped every tracked file for
  `test_factory_ship`, its three test names, `test_ship_refuses_in_database_mode`, and
  `test_a_set_retired_variable_refuses_every_command`. Hits are only in `docs/superpowers` history:
  the 2026-07-02 WS-11 plan, the 2026-07-03 WS-12 plan, and `fe-5-r-ss-report.md`. No manifest,
  registry, governance file, CI workflow, or evidence file names them.

### Re-grep for `shipped`, `head_seq`, `SHIPPED`, `HEAD_SEQ`

The following matches remain:

- `tests/test_factory_nightly.py` lines 218-219 and 242-243: the new absence asserts.
- `docs/superpowers` history only: the WS-11 plan (`shipped=`/`head_seq=` in the old `_cmd_ship`
  code), `fe-5-r-ss-report.md` lines 54, 187, and 220-221, and unrelated uses of "shipped"
  (meaning "released") in the 2026-06-17 read-guard plan and specs.

`git grep -w ship` outside `docs/superpowers` hits only two unrelated uses of the English verb, in
`docs/2026-06-19-*.md`. The test name `test_file_present_verifies_adapts_and_records_the_anchor_without_ship`
keeps the word; I left it, because the name still describes the test.

The act step 15 patterns (`:5545\b`, `5545:5432`, `FACTORY_DB_DSN`, `ea09a782`, excluding
`*.lock`) now hit only `docs/superpowers` plans and reports.

## Files changed

- `.bws-secrets.toml`
- `.gitignore`
- `deploy/factory-events-db/docker-compose.yml` (deleted)
- `scripts/factory-events-nightly.sh`
- `src/factory_events/README.md`
- `src/factory_events/cli.py`
- `src/factory_events/ship.py` (deleted)
- `src/factory_events/store.py`
- `tests/test_factory_chain_mode.py`
- `tests/test_factory_nightly.py`
- `tests/test_factory_ship.py` (deleted)
- `docs/superpowers/reports/fe-6-p6-ss-report.md` (this report)

## Self-review

- **The `consumption` mode.** The plan says line 7's mode is "whatever the scanner accepts for the
  remaining rows". Both modes come back clean, so I picked `code-reference`, because it's the true
  one and the stricter one. `manifest.py` skips the stale-row check for `environment-injection`
  and `coolify-env`, and that skip had been hiding `ea09a782-…`, which no runtime code names. All
  three remaining rows are UUIDs that runtime code fetches (`scripts/observe-run.sh` and the
  nightly), and `referenced_uuids` finds exactly those three. Under `code-reference`, the drift
  check now reports both directions: a declared row no runtime code names, and a runtime UUID no
  row declares. I rewrote the header to match. The old header said the secrets were provisioned
  into `~/.factory/env`, and that's no longer true of any row.
- **`make install` and the manifest.** `governance ownership` (`ensure_bws_manifest`) writes
  `.bws-secrets.toml` only when the file is missing, and nothing else in `src`, `scripts`,
  `hooks`, or `skill` reads `consumption` except `manifest.py`. So step 12 keeps the explicit
  `code-reference`.
- **`/code-review` findings.** I checked all four, and none called for a change:
  - The removed `.gitignore` entry: `.env` and `*.env` still ignore the file (Concern 1).
  - The dropped facts: HQ found no reader, and open question 4 settles it.
  - A `.cred-consumers.toml` row: that row is from #96, not this branch. The local `main` was at
    `e905304`, behind `origin/main`; `git diff origin/main...HEAD` shows only this change.
  - `code-reference` strictness: `referenced_uuids` finds all three UUIDs, and `diff()` is empty.
- **Projection leftovers.** A grep for `5545`, `chain_heads`, `projection`, and `docker compose`
  outside history docs finds only the nightly's new comment and unrelated uses of "projection" in
  `docs/2026-06-19-governance-realignment-review.md`. The projection's DDL lived only in
  `ship.py`.
- **Scope.** I built only the plan's section and the facts drop from open question 4. Dead helpers
  stay where they are (see the following Follow-ups section).
- **Secrets.** I read no secret value. I didn't open any `.env` or `~/.factory/env*` file, and I
  ran no `docker`, `bws`, `security`, `make install`, or nightly command.

## Standards followed

- **Code Brain 5 (BLOCK), never log secrets:** the change prints nothing new. The removed
  `_cmd_ship` printed only counts and a hash. The test-database password was random, passed only
  inside `FACTORY_TEST_DSN` in the harness's environment, never printed, and deleted with the
  cluster.
- **Code Brain 4 (BLOCK), never swallow an error:** the nightly keeps `set -euo pipefail`, every
  `fail` path, and its `finish` trap. The edit removes two variables, two `observe_fact` lines,
  and one comment. Deleting `_cmd_ship` also removes a `# noqa: BLE001` broad `except`. I added no
  `except` clause.
- **Code Brain 3 (BLOCK), structured logs to stdout:** the nightly's `log()` format is unchanged,
  and I added no log file.
- **Infra Brain 591, 592, 593 (BLOCK), no BWS token in a tracked file or history:** the change
  adds no token and no inline bootstrap token. The scanner's BLOCK count and allowlist are
  identical before and after. The manifest's prose describes the access token by its Keychain
  location only.
- **Infra Brain 1032 (BLOCK), rotate any credential seen in a transcript:** no credential value
  appeared in this session. The only password involved was the throwaway test cluster's, which was
  generated at random, never printed, and deleted with the cluster.
- **Infra Brain 212 (HTTPS for public FQDNs):** not applicable. No app or domain changed.
- **Repo rule, `.bws-secrets.toml` lists the UUIDs the repo consumes:** after the change, the
  manifest lists exactly the three UUIDs that runtime code references. Under `code-reference`,
  `manifest.diff` reports no undeclared and no stale UUID, and the scanner reports no
  manifest-drift finding.

## Concerns

1. **The `.env` stays ignored after the merge, through other patterns.** `.gitignore` line 2
   (`.env`) and line 3 (`*.env`) both match `deploy/factory-events-db/.env`. `git check-ignore -v`
   on this branch reports line 3. So the deleted lines 22-23 were redundant, and an early merge
   wouldn't have made the file visible to `git status`. I kept the hold as the handoff orders. Act
   step 12's check still applies: `git status --porcelain --ignored deploy/` prints nothing only
   if the file is gone. With the compose file deleted, `deploy/factory-events-db/` holds only the
   `.env`, so after step 11 the directory is empty and git doesn't list it.
2. **`ship` exits 1, not argparse's 2.** The plan says "an argparse error". It is one (argparse's
   message), but `cli.main()` maps every usage error to exit 1. A step that asserts on exit code 2
   would fail.
3. **The integration run used a local cluster, not the repository's Docker path.** The tests and
   the target are the same, and only the database host differs. CI's `extended-tests.yml` runs
   against its own service container when the PR's CI runs.

## Follow-ups

- Dead code left from `ship`, outside this plan's scope: `store.py`'s `append_event` (with its lock
  file), `event_ids`, `verify_chain`, `parsed_records`, and `_parse_records` have no caller in
  `src/`, only in tests (`fe-5-r-ss-report.md` concern 1). `ship.last_anchor` went with
  `ship.py`. A later cleanup can remove the `store.py` helpers and their tests.
- The deployed `~/.claude/bin/factory-events-nightly.sh` changes only at act step 12's
  `make install`. Until then, the deployed nightly keeps posting `shipped=0` and `head_seq=0`.
