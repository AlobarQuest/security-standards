Outcome: done

# Report: feed-b-portfolio-scan-append

Step 3f-2-feed (b), ADR-0059 Amendment 11 decision item 2 (D-56 A). Two PRs, both ready for review and unmerged. Both are based on `origin/main` `05963b7626b594d85bcb0d232f54421619ae3fd8`.

| PR | Branch | Base | Content commits | Head |
|---|---|---|---|---|
| [#98](https://github.com/AlobarQuest/security-standards/pull/98) | `hq/feed-b-portfolio-scan-append` | `main` | `7a0a85f9ae8be20ccf9d0d8a292a2bbfa03667df` | `7a0a85f9ae8be20ccf9d0d8a292a2bbfa03667df` |
| [#99](https://github.com/AlobarQuest/security-standards/pull/99) | `hq/feed-b-portfolio-scan-append-adapter` | `hq/feed-b-portfolio-scan-append` | `8590dd2e`, `907f8095`, `2866a00f`, and last `d8cec8944c42147c7291e9e96556940dfc4089aa` | the commit that adds this report, directly on `d8cec894` |

## Merge order: read this first

PR 1 (#98) produces no event. PR 2 (#99) goes live at the first 03:30 nightly after it merges, because `.venv-events` is an editable install of the main checkout (see "Nightly script and install"). That nightly appends a `portfolio.scanned` event at once, provided the scan wrote a feed. Every walker in the following table re-validates each stored event against its own copy of the schema (`store.walk_records`, `src/factory_events/store.py` line 154). A walker whose copy lacks `portfolio-scan` fails every walk from then on, because the chain is append-only.

The handoff's premise that the orchestrator's image takes its schema from `tests/fixtures/security-standards/` doesn't hold for production images. On orchestrator `origin/main`, `.github/workflows/release-image.yml` (lines 88 to 111) reads `security-standards.pin.toml` and checks out security-standards at its `revision`. That revision is `05963b76` today, with `artifact_sha256` `4873d9ab…`. The workflow shapes the checkout with `scripts/shape_registry_context.py` and passes it as the `registry` build context, and the `Dockerfile` copies it into `/app/security-standards/{registry/agents,src,schema}` (lines 42 to 44). Only CI (`quality.yml`) uses `tests/fixtures/security-standards`. Before PR 2 merges, the rollout therefore needs these steps:

1. Merge #98.
2. Bump the orchestrator's `security-standards.pin.toml` to #98's merge commit. Bump `revision` **and** `artifact_sha256` together: the registry bundle changes, because it gains an agent. Then rebuild the image and roll the work carrier onto it.
3. Update the fixture copy for CI. This is step (c)'s work.

This doesn't change the PR split or the event shape, so I didn't stop to ask.

## The verifier list

I read every row first-hand from `origin/main` with `git show` or `git grep`, unless the row says otherwise.

| Process | How it starts | Walks or validates? | Copy of `factory_events`, the schema, and the registry |
|---|---|---|---|
| **Mac nightly** `com.devon.factory-events` (03:30) | launchd → `~/.claude/bin/factory-events-nightly.sh` → `verify --against-anchor` (script line 197) and `verify --record-anchor` (line 219) → `cli._cmd_verify` → `db.verify` → `store.walk_records` | Full walk, validates every event | `~/Projects/security-standards/.venv-events`. The `__editable__.security_scan-0.1.0.pth` file points at `~/Projects/security-standards/src`, so this is the **Mac main working copy**. `envelope.SCHEMA_PATH` resolves to that checkout's `schema/`. The script fast-forwards the checkout first (`activate_checkout`). It learns the value when #98 merges, at its next run. |
| **Work carrier, container** (`scripts/run-work-carrier.sh` lines 350 to 352, 559 to 573; `package_sources.py` line 275) | `orchestrator.factory_chain_read` on every pass, `factory_chain_read.py` line 94 → `store.walk_records` | Full walk, validates | `SECURITY_STANDARDS_DIR=/app/security-standards`: the **image's pinned revision** (`security-standards.pin.toml`), not the fixture and not Mac main. **This one needs the pin bump and a new image before PR 2 merges.** |
| **intent-packages `verify-approval`** inside the carrier container (`package_sources.py` line 170 → `operations.verify_approval` → `chain_db`, `chain_db.py` line 116 → `walk_records`) | A subprocess of the carrier | Full walk, validates | `SECURITY_STANDARDS_DIR`, inherited from the carrier, which is the **image pin**. Same fix as the preceding row. |
| **Work carrier, Mac branch** (`run-work-carrier.sh`, the "THE MAC, unchanged until increment 6" branch) | launchd `com.devon.work-carrier` | Walks through `package_sources` (`factory_chain_read` and `verify-approval`) when it runs | `SECURITY_STANDARDS_DIR` isn't exported on that branch, so `package_sources._security_standards_dir()` falls back to `~/Projects/security-standards`, the **Mac main working copy**. Not confirmed: whether the Mac branch reaches the walk on today's passes, and what `PYTHONPATH="$SECURITY_STANDARDS_DIR/src"` (line 572) resolves to there. |
| **Hand `verify-approval` runs on the Mac** (sds-hq `state/gates/*.md`, `PYTHONPATH=src python3 -m intent_packages verify-approval …`) | By hand | Full walk, validates | `_security_standards_dir()` falls back to `~/Projects/security-standards`, the **Mac main working copy**, unless the shell sets `SECURITY_STANDARDS_DIR`. The interpreter is security-standards' `.venv-events` when it exists (intent-packages `emitter.py` line 110). |
| **HQ standing-approve guard** (sds-hq `standing_approve.py` lines 508 to 511) | `com.devon.sds-hq` cycle | **Reads rows only.** It runs `SELECT event_id, event FROM factory_events ORDER BY seq` with no `walk_records` and no `validate_event`, so an unknown `source.system` doesn't fail it. | HQ's own clone in `~/.local/share/sds-hq/clones/security-standards`. `_pin` (lines 334 to 347) fetches and detaches it at **`origin/main` on every cycle**, with `SECURITY_STANDARDS_MIN = "60ec80f7"`. It would follow #98 at once in any case. |
| **Bump proposer** `com.devon.bump-proposer` | `run-bump-proposer.sh --submit` | **No walk found.** `bump_proposer/standing.py` runs intent-packages `transition` and `approve --by-policy` (lines 424 to 426). `approve` emits through `factory_events emit`, which validates only the new event it builds, against its own schema copy. Neither runs `verify-approval`. | The intent-packages checkout's `.venv`. Emits resolve `factory_events` the same way as `verify-approval`. |
| **Interactive approvals** (`scripts/factory-events-session.sh`) | By hand | **No walk.** Its modes are `approve`, which emits, and `import-file`. `import-file` walks only the file it imports (`db.py` line 205), not the chain. | `~/Projects/security-standards/.venv-events`, the Mac main working copy. |

I found no other caller. I ran `git grep` for `walk_records`, `chain_db`, `factory_chain_read`, `verify-approval`, and `-m factory_events` on `origin/main` of orchestrator, intent-packages, sds-hq, project-standards, vps-backup, change-manager, factory-runner, and infraops-mcp-server. `rotation_proposer/cli.py` `_walk_records` walks rotation records, not the chain. I didn't inspect the `infra-reports`, `rotation-worker`, or `vps-backup` LaunchAgents beyond that grep, and the grep found no chain walk in them. vps-backup only dumps the database.

## What I built

### PR 1 (#98): items 1 and 2

- **`schema/factory-event.v1.schema.json`:** adds `"portfolio-scan"` to the closed `source.system` enum on line 26. Nothing else in the schema changes.
- **`registry/agents/portfolio-scan.yaml`:** `authority_profile: none-v1`, `capabilities: []`, `prohibited: []`, `runtime: unknown`, `environment: any`, `operator: devon`, and `status: active`. Its description says the entry is a label for the `portfolio.scanned` event the nightly appends from the scan's feed (ADR-0059 Amendment 11, D-56 A), that no credential authenticates as it, and that nothing runs under it.
- **Mirroring #89 (`7e6803b`):** #89 touched only the YAML entry plus its report files, and no generator or index file. The registry's own check is `python -m agent_registry validate`, which reports `registry ok: 21 agents, 15 profiles`. pytest runs it too, through `test_real_registry_validates_and_covers_ws11_vocabulary`.
- **Tests:**
  - `test_schema_accepts_the_portfolio_scan_source` and `test_schema_still_refuses_an_unknown_source_system`, in `tests/test_factory_envelope.py`.
  - `test_portfolio_scan_is_a_registered_credential_less_label`, in `tests/test_agent_registry.py`.

### PR 2 (#99): items 3 to 6

- **`src/factory_events/adapters/portfolio_scan.py`:**
  - `feed_path()`: `FACTORY_EVENTS_PORTFOLIO_FEED`, or `~/.portfolio/portfolio-feed.json`.
  - `load_feed()`: validates the whole feed first, then returns `(scanned_at, evidence, result)`.
  - `adapt()`: builds the event with `make_event`, appends nothing when the `event_id` is already in `chain.event_ids()`, and otherwise calls `chain.append_event`.
  - `FeedError`: its message names a field and never a value.
- **What `load_feed` refuses:**
  - A missing file, an unreadable file (`OSError`, `UnicodeDecodeError`), a non-JSON file, or one nested too deeply to parse (`RecursionError`).
  - A non-object, or an object that isn't exactly the four keys.
  - A `schema` other than `portfolio-feed.v1`.
  - A `scanned_at` that fails the `fullmatch` of `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` or isn't a calendar time.
  - A `member_record_unreadable` that is neither `null` nor a string.
  - Rows alongside an unreadable member record, or `repositories` that isn't a list.
  - A row that isn't exactly `repository` and `checks`.
  - A `repository` that isn't a string, doesn't `fullmatch` `[^/\s]+/[^/\s]+`, or isn't lowercased. That is the producer's `repo_slug` shape, lowercased, so the check is never narrower than what the scan writes.
  - A repeated repository.
  - `checks` that isn't an object, holds an id outside the four, or holds a non-string status.
- **Statuses are copied, not checked against a set.**
- **`src/factory_events/cli.py`:** `--source portfolio-scan` joins the choices, and `_cmd_adapt` runs it **last** in `all`. It catches exactly these:
  - `portfolio_scan.FeedError`: prints `portfolio-scan: 0 events appended (feed skipped: <reason>)` and counts no failure. The inline justification cites decision item 6.
  - `(EnvelopeError, ChainError)`: prints `ADAPT FAIL (portfolio-scan): …` to stderr and counts a failure.
- **`tests/conftest.py`:** an autouse floor sets `FACTORY_EVENTS_PORTFOLIO_FEED` to a path under `tmp_path` that doesn't exist, so no test can read the real feed. `test_no_test_reaches_the_real_portfolio_feed` in `tests/test_factory_cli.py` pins it.
- **`tests/test_adapter_portfolio_scan.py`:** 45 tests. The test file writes its feed through the environment path and never through `feed_path()`, for the reason given under Concerns.
- **`src/factory_events/README.md`:** the `adapt` line, a section titled "The portfolio scan's feed", and step 4 of "Nightly".

### Example event (placeholder slugs)

```json
{
  "schema": "factory-event/v1",
  "event_id": "evt-<sha256 of 'portfolio-scan:2026-11-17T08:00:35Z'>",
  "timestamp": "2026-11-17T08:00:35Z",
  "actor": "portfolio-scan",
  "action": "portfolio.scanned",
  "target": null,
  "work_package": null,
  "input_revision": null,
  "result": "success",
  "evidence": [
    {"type": "repository", "repository": "example-owner/repo-a",
     "checks": {"factory.landing_known": "pass", "factory.pat_access": "pass",
                "factory.secrets": "pass", "runner.caller": "pass"}},
    {"type": "repository", "repository": "example-owner/repo-b",
     "checks": {"factory.pat_access": "violation", "runner.caller": "violation"}}
  ],
  "authority_grant": null,
  "correlation_id": null,
  "source": {"system": "portfolio-scan", "ref": "2026-11-17T08:00:35Z"}
}
```

When the member record is unreadable, `"result": "unknown"` and `"evidence": [{"type": "member-record-unreadable", "reason": "<the feed's reason string>"}]`.

## Nightly script and install

- **`scripts/factory-events-nightly.sh` doesn't change.** The adapter runs through the `adapt --source all` the script already runs. Its `EVENTS_APPENDED` `sed` matches both `portfolio-scan: N events appended` and the `… 0 events appended (feed skipped: …)` line, which counts 0.
- **No `make install` is needed**, and no dependency is new.
- **`.venv-events` is an editable install of the main checkout.** `~/Projects/security-standards/.venv-events/lib/python3.14/site-packages/__editable__.security_scan-0.1.0.pth` holds `/Users/devon/Projects/security-standards/src`, and the schema and registry resolve from the same checkout. Each merged PR therefore goes live when the next 03:30 run's `activate_checkout` fast-forwards `main`.

## Tests and checks

- **`make check` at `d8cec894`:** ruff `All checks passed!`, pyright `0 errors, 0 warnings, 0 informations`, and pytest `313 passed, 22 deselected` (`313/335 tests collected (22 deselected)`). The base `05963b7` gives 264 passed. PR 1's head (`7a0a85f`) gives 267.
- **The 22 deselected tests** are the `integration` marker (`addopts = "-m 'not integration'"`), the database tests behind `make check-integration`. I didn't run them locally. CI's "Factory-store integration tests" job runs them, and it passed on both PRs, along with "Lint, type-check, and test" and "scan" (`gh pr checks 98` and `gh pr checks 99`).
- **Security scan from the worktree root:** 0 BLOCK, 4 WARN, 1 INFO.
  - The four WARN findings are `bws.reference-by-stable-uuid` in three June planning docs and `src/security_scan/rules_cache.json`. This diff touches none of them.
  - The INFO finding is `bws.least-privilege-scope`, which needs judgment.
  - The 12 allowlisted entries are the repository's known test fixtures and history.
- **`/code-review` (medium) on `05963b7..2866a00`:** 8 findings, with these dispositions:
  1. `$` matches before a trailing newline. **Fixed** in `2866a00` by switching to `fullmatch`. M24 pins it.
  2. The free-text reason is copied permanently. **Kept**, because the handoff requires a verbatim copy. It's listed under Concerns.
  3. `null` plus `[]` gives `success` with no evidence. **Kept**: that is a scan that measured no repository, and the carrier holds every record. See "For the next steps".
  4. The dedupe isn't atomic. **Kept**, matching `change_manager`. `event_id` is the table's primary key, so a racing second append raises `ChainError` and fails that adapt. It never writes a duplicate.
  5. Seconds 60 and 61 pass `strptime`. **Refuted**: Python's `datetime.strptime` raises `second must be in 0..59` for both. I tested it, and a test case now pins it.
  6. The feed-skip swallow exits 0. **Kept**, as decision item 6 requires.
  7. `--reanchor` is ignored for this source. **Kept**: `change_manager` ignores it too.
  8. Missing test cases. **Added**: a trailing newline in `repository` and in `scanned_at`, and a leap second.
- **Later fixes, from my own self-review against the producer:**
  - A deeply nested feed raised `RecursionError` past `_read`, which would have crashed the adapt. I made it a `FeedError`.
  - The repository pattern was narrower than the producer's `repo_slug`. I widened it.
  - An empty reason string was refused, although the handoff says any string is a reason. I now accept it.
  - These fixes are in `d8cec894`. Under `make check`'s `PATH` the parser reports deep nesting as `JSONDecodeError` rather than `RecursionError`, and the test accepts either reason. M27 proves the `RecursionError` branch is needed under the plain interpreter, which the nightly uses.

### Mutants

I ran each mutant alone on committed content, then ran the adapter, CLI, nightly, envelope, and registry tests, and restored with `git checkout -- <file>` or a saved copy. Every mutant went red, and `git status` was clean afterwards.

**PR 1, at `7a0a85f`:**

| # | Mutant | Red test |
|---|---|---|
| P1 | `portfolio-scan` removed from the enum | `test_schema_accepts_the_portfolio_scan_source` |
| P2 | Enum replaced by `{"type": "string"}` | `test_schema_still_refuses_an_unknown_source_system` |
| P3 | Registry entry deleted | `test_portfolio_scan_is_a_registered_credential_less_label` |
| P4 | `authority_profile: agent-queue-v1` | same |
| P5 | `runtime: launchd` | same, plus `test_real_registry_validates_…` |

**PR 2, final run at `d8cec894`, with `HOME` set to a scratch directory:**

| # | Mutant | Red test or tests |
|---|---|---|
| M1 | `event_id` also depends on the row count | `…rerun_appends_nothing`, `test_the_event_id_depends_only_on_scanned_at` |
| M2 | No dedupe | same two |
| M3 | `result` always `unknown` | `…rerun_appends_nothing` |
| M4 | Unreadable evidence without `type` | `test_an_unreadable_member_record_…` (both reasons) |
| M5 | Rows sorted rather than in feed order | `test_rows_are_copied_in_the_feeds_order` |
| M6 | `schema` not checked | bad feed `other schema` |
| M7 | `scanned_at` pattern dropped | bad feed `scanned_at unpadded` |
| M8 | Calendar check dropped | `scanned_at not a date`, `scanned_at a leap second` |
| M9 | Extra row keys allowed | `row with another key` |
| M10 | Lowercase check dropped | `repository not lowercased` |
| M11 | Duplicates allowed | `duplicate repository` |
| M12 | Check ids outside the four allowed | `check id outside the four` |
| M13 | Status type not checked | `status not a string` |
| M14 | Rows allowed with an unreadable record | `rows with an unreadable record` |
| M15 | Status values closed to `pass` and `violation` | `test_an_unknown_status_value_is_copied_not_refused` |
| M16 | Reason echoes the repository | 4 bad-feed cases (MARKER check) |
| M17 | `FeedError` counted as a failure | 32 tests |
| M18 | `ChainError` not caught | `test_a_chain_error_fails_the_adapt` |
| M19 | `EnvelopeError` treated as a bad feed | `test_an_envelope_error_is_a_failure_not_a_bad_feed` |
| M20 | Not run in `all` | 35 tests |
| M21 | Override ignored | 17 tests |
| M22 | Missing-file branch removed | `cannot_be_read[missing]` |
| M23 | conftest floor removed | `test_no_test_reaches_the_real_portfolio_feed` |
| M24 | `match` rather than `fullmatch` for the repository | `repository with a trailing newline` and 2 more |
| M25 | Repository pattern narrowed to `[a-z0-9-]` | `test_a_repository_name_the_producer_can_write_is_accepted` |
| M26 | Empty reason refused | `test_an_unreadable_member_record_…[]` |
| M27 | `RecursionError` branch removed | `cannot_be_read[nested too deeply]` |
| M28 | Whitespace allowed in the repository | `repository with a space` and 1 more |

## Files changed

- **PR 1:** `schema/factory-event.v1.schema.json`, `registry/agents/portfolio-scan.yaml` (new), `tests/test_factory_envelope.py`, `tests/test_agent_registry.py`.
- **PR 2:** `src/factory_events/adapters/portfolio_scan.py` (new), `src/factory_events/cli.py`, `src/factory_events/README.md`, `tests/conftest.py`, `tests/test_adapter_portfolio_scan.py` (new), `tests/test_factory_cli.py`, and this report.

## Self-review

- The adapter mirrors `change_manager`'s shape: `make_event`, an `event_ids` dedupe, and `append_event`. It is one module-level function plus pure validation.
- Validation finishes before any event is built, so nothing partial can be appended. A bad feed never touches the chain.
- The `_cmd_adapt` tuples are explicit: `FeedError` is swallowed with a justification and a printed reason, and `EnvelopeError` and `ChainError` fail the adapt.
- No owner name appears in code, and the tests use `example-owner`.
- TDD order: PR 1's tests and the adapter tests were red before the code existed, because the module didn't exist. The mutants cover each rule.

## Concerns

- **I wrote to the real `~/.portfolio/` once, by accident, and removed the file again.** On the first mutant run, M21 (the override ignored) made `feed_path()` return the real path. The test helper then wrote its fixture feed through `feed_path()` and created `~/.portfolio/portfolio-feed.json` at 11:45 EST (16:45Z) on 2026-11-16. The following evidence shows that no real feed existed before:
  - project-standards #63, which first writes the feed, merged at 16:17Z.
  - The last scan ran at 03:00 local (`scan.log`: `[2026-11-16 03:00:07] ok`), and the next runs at 03:00 on 2026-11-17.
  - The directory's mtime was 11:45, which means an entry was created, not rewritten.
  - The file held the placeholder fixture (`example-owner/repo-a` and `repo-b`, `scanned_at` `2026-11-17T08:00:35Z`).
  - Nothing reads the feed yet. No adapter is merged, and the carrier still reads `portfolio.json`.

  I deleted the file with `rm`, which restores the prior state, and `ls` confirms it's absent. I then closed the hole in three ways. The helper writes by the environment path and never through `feed_path()`, which is commit `907f8095`. Later mutant runs set `HOME` to a scratch directory. After every run I checked that the real file was still absent. I touched nothing else in `~/.portfolio`, `~/.factory`, or the chain.
- **The event carries the scan's free-text reason permanently.** When the member record is unreadable, the reason string from project-standards is copied into an append-only chain verbatim, as the handoff requires. Today that string is the scan's own message, for example `the orchestrator answered 401 for GET /api/v1/members`, and holds no credential. If the producer ever put an upstream response body there, it would be permanent. I didn't cap or filter it, because that would change "copied without change". HQ can decide whether the producer's contract needs a bound.
- **Rollout depends on the orchestrator pin, not only the fixture.** See "Merge order".
- **Two rows in the verifier list aren't fully confirmed:** whether the Mac branch of the work carrier reaches the walk today, and what its `PYTHONPATH` resolves to. Both are marked in the table.
- **Statuses aren't bounded.** Any string is copied. That is the contract ("the value set isn't closed").

## For the next steps

Step (c), the carrier's reader and the orchestrator's pinned copy, can rely on the following:

- **Selection:** `action == "portfolio.scanned"`, `actor == "portfolio-scan"`, and `source.system == "portfolio-scan"`. `source.ref` and `timestamp` both equal the feed's `scanned_at` (`YYYY-MM-DDTHH:MM:SSZ`, whole seconds). Take the newest by `timestamp`, not by `seq`.
- **`event_id`:** `evt-` followed by the SHA-256 hex of `portfolio-scan:<scanned_at>`, so there is at most one event per scan time. The first feed seen for a scan time wins.
- **`evidence` item types:**
  - `{"type": "repository", "repository": "<lowercased owner/repo>", "checks": {<id>: <status>}}`: one per feed row, in the feed's order (sorted by repository), with at most one per repository. `checks` keys are a subset of `runner.caller`, `factory.secrets`, `factory.landing_known`, and `factory.pat_access`. A missing key means the status is unknown. Status strings aren't a closed set (for example, `not-applicable`). Take only these items as rows.
  - `{"type": "member-record-unreadable", "reason": "<string, possibly empty>"}`: the only item when the member record was unreadable.
- **`result`:**
  - `success`: the member record was read, and `evidence` holds the measured repositories. An empty `evidence` means the scan measured no repository, so every repository-targeted record holds for "no row".
  - `unknown`: the member record was unreadable. The scan measured nothing, so hold every repository-targeted record.
  - `failure`: never produced.
- **Rollout before PR 2:** bump `security-standards.pin.toml` (`revision` and `artifact_sha256`) to #98's merge commit, rebuild and roll the image, and update `tests/fixtures/security-standards/` (schema and `registry/agents/portfolio-scan.yaml`) for CI and the guards.
- **A bad feed** leaves no trace in the chain, only a `feed skipped: <reason>` line in `~/Library/Logs/factory-events.log`. The carrier sees the previous event age past 48 hours.

## Standards followed

- **Code Brain rule 3 (structured JSON logs to stdout in production):** the nightly is a Mac launchd job that logs through its own `log` function to `~/Library/Logs/factory-events.log`. The diff adds no logging. The adapter's only output is the one summary line on stdout, or the `ADAPT FAIL` line on stderr, which the nightly already captures into that log.
- **Code Brain rule 4 (never silently swallow an exception):** the only swallow is `except portfolio_scan.FeedError` in `_cmd_adapt`. It carries an inline justification that cites decision item 6, and it prints the reason. `EnvelopeError` and `ChainError` fail the adapt, as M18 and M19 prove. Nothing uses `except Exception`.
- **Code Brain rule 5 (never log secrets, credentials, tokens):** the event holds repository names, statuses, and the scan's reason string. The printed lines hold counts, field names, and exception type names. No password or token appears in any output. The `MARKER` assertions (M16) prove the skip line never echoes feed content.
- **Infra Brain 591, 592, and 593 (no BWS token in tracked files or history, no inline `BWS_ACCESS_TOKEN` value):** the diff contains no token and no `BWS_ACCESS_TOKEN` assignment. The security scan reports 0 BLOCK. The test placeholder `CM_M2M_TOKEN=placeholder` isn't a credential.
- **Infra Brain 1032 (`cred.exposure-rotate`):** I saw no secret value during this work. I read no env file and fetched no credential.
- **Infra Brain 212 (HTTPS for public FQDNs):** doesn't apply. The diff makes no network change. The tests' `https://change-manager.invalid` is never contacted, because `_http_fetch` is replaced.

## Rebase onto `main` (W-198)

PR #99 was stacked on #98, which squash-merged as `08754a0`. Its branch still carried #98's pre-squash commit `7a0a85f`, so its diff against `main` showed 11 files. W-198 rebased only #99's own commits onto `main`, and PR #100 supersedes #99.

- **Old head:** `2871a92d880bdf860ff9d127aaa98716ef0d61b7` on `hq/feed-b-portfolio-scan-append-adapter`, left untouched.
- **New head before this section:** `cbdc5863c6cefecf6049661105555b3cb0bdea75` on `hq/feed-b2-rebase`.
- **Dropped commit:** `7a0a85f` (#98's content, already on `main` as `08754a0`).
- **Command:** `git rebase --onto origin/main 7a0a85f`. It had no conflicts.
- **`git range-diff 7a0a85f..2871a92 origin/main..cbdc586`:** all six pairs are identical (`=`): `8590dd2→65022c4`, `907f809→dadc10d`, `2866a00→0e32275`, `d8cec89→77c77c9`, `d1bf7ad→12d7b0f`, and `2871a92→cbdc586`.
- **`git diff --stat origin/main...cbdc586`:** 7 files, 734 insertions and 7 deletions:
  - `docs/superpowers/reports/feed-b-portfolio-scan-append-report.md`
  - `src/factory_events/README.md`
  - `src/factory_events/adapters/portfolio_scan.py`
  - `src/factory_events/cli.py`
  - `tests/conftest.py`
  - `tests/test_adapter_portfolio_scan.py`
  - `tests/test_factory_cli.py`

  `registry/agents/portfolio-scan.yaml` and `schema/factory-event.v1.schema.json` no longer differ from `main`.
- **`make check` (local, on `cbdc586`):** ruff, ruff format, and pyright clean; 313 passed, 22 deselected.
- **Security scan (local, worktree root):** BLOCK 0, WARN 4, INFO 1. Every WARN and INFO is in a file outside this diff.
- **Push:** the HQ guard hook denied the `--force-with-lease` push to `hq/feed-b-portfolio-scan-append-adapter`. Following HQ's answer, W-198 pushed the rebased head to `hq/feed-b2-rebase` with a normal push and opened PR #100 from it. #99 is unchanged.
- **CI on `cbdc586`:** every check passed.

  | Workflow | Event | Result | Tests |
  |---|---|---|---|
  | Quality (Lint, type-check, and test) | push | success | collected 335, 22 deselected, 313 passed |
  | Quality (Lint, type-check, and test) | pull_request | success | collected 335, 22 deselected, 313 passed |
  | Security Scan (scan) | push | success | 35 passed; scan BLOCK 0, WARN 4 |
  | Security Scan (scan) | pull_request | success | 35 passed; scan BLOCK 0, WARN 4 |
  | Extended tests (Factory-store integration tests) | pull_request | success | 22 passed, 313 deselected |
