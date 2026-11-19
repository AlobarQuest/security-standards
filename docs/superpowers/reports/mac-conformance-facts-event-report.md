Outcome: done

# Build report: mac-conformance-facts-event (W-219)

- **PR:** AlobarQuest/security-standards#101, ready for review, not merged.
- **Branch:** `hq/mac-conformance-facts-event`, based on `origin/main` `23854235`.
- **Content commits:** `93d4cc9` (the change) and `0deaa24` (a fix that review found: an
  over-long JSON integer). The report commits follow them; the branch head is the last report
  commit.
- **Source:** orchestrator ADR-0059 Amendment 13 (D-62 C) at `90f26ecd`, decision items 2, 3, 5,
  6 and 7 and the verify items.

## Merge order: read this first

Don't merge #101 until the orchestrator image pins a security-standards revision whose schema
holds `mac-conformance-facts`.

The work carrier's container verifies the whole chain on every pass. It runs
`orchestrator.factory_chain_read` → `factory_events.store.walk_records` → `validate_event` with
`SECURITY_STANDARDS_DIR=/app/security-standards`, which is the image's pinned copy
(orchestrator `security-standards.pin.toml`, `revision` `08754a0f` today; `Dockerfile` lines
42-44). intent-packages' `verify-approval` inside the carrier inherits the same copy.

Once #101 is on the Mac checkout's `main`, the next 03:30 nightly appends a
`mac_conformance.reported` event whose `source.system` the pinned schema rejects. Every carrier
pass then fails its verify with a schema violation until the pin moves. The security-standards
`SessionStart` hook fast-forwards the Mac's `main` on its own, so the gap between merge and the
first append can be short.

This is the hazard Amendment 11 avoided by landing its schema and registry change (#98) before
its adapter (#100); see `feed-b-portfolio-scan-append-report.md`, "Merge order". The handoff
asked for one PR, so I kept one. HQ has two safe orders:

1. **Split (the precedent's order).** Land the schema value and the registry file alone first.
   Bump the orchestrator pin (`revision` and `artifact_sha256` together, since the registry
   bundle gains an agent), rebuild, and roll the carrier. Then land the adapter. I can split
   #101 into those two PRs on request.
2. **One PR, nightly held.** Merge #101, bump the pin to its merge commit, and roll the carrier
   before any 03:30 nightly runs on that `main`.

Also update orchestrator's `tests/fixtures/security-standards/` (schema and
`registry/agents/mac-conformance-facts.yaml`) for its CI and guards, as feed b did.

## What I built

The security-standards pieces that decision item 6 names:

1. **The adapter**, `src/factory_events/adapters/mac_conformance.py`. It reads the Mac's three
   inputs the way project-standards' matrix reads them at `4673d726`, from the same paths and
   the same override variables:
   - `INFRADRIFT_REPORT_DIR` (default `~/infra-drift/reports`).
   - `LAUNCHAGENTS_DIR` (default `~/Library/LaunchAgents`).
   - `CLAUDE_SETTINGS_JSON` (default `~/.claude/settings.json`).

   The newest report is picked by file name among `YYYY-MM-DD.json` files, as
   `_latest_infra_report` picks it. Every check the matrix makes is mirrored:
   - "Infra report unreadable": an OS or UTF-8 error, not JSON, not an object holding
     `generated_at` and `instances`, `instances` not an object, or `generated_at` that
     `fromisoformat` refuses.
   - "Instance unusable": not an object, `ok` falsy, or `proposals` not a list.
   - "Hook registered": the basename of any token of any hook command.
   - "LaunchAgent present": the `.plist` is a file.

   It doesn't import project-standards. Reading the wiring has no error path: unreadable or
   oddly shaped settings read as absent, as the matrix reads them.
2. **The `adapt --source all` step** in `cli.py`. It runs after change-manager and before
   portfolio-scan, so portfolio-scan stays last. It's also available alone as
   `--source mac-conformance-facts`. Each of the two input-skipping steps is now a helper
   (`_adapt_mac_conformance` and `_adapt_portfolio_scan`); a single function exceeded ruff's
   C901 limit, and I chose the split over a suppression.
3. **The registry and schema entries.**
   - `registry/agents/mac-conformance-facts.yaml`: `none-v1`, empty `capabilities` and
     `prohibited`, `runtime: unknown`, `environment: any`, the same kind as `portfolio-scan`.
   - The schema's `source.system` enum gains `mac-conformance-facts`.
   - The action is `mac_conformance.reported`.

`src/factory_events/README.md` documents the step and the event layout. `tests/conftest.py`
gains an autouse fixture that keeps every test away from the real report directory,
LaunchAgents, and settings.

## The event's layout

The envelope:

- `actor` is `mac-conformance-facts`, `action` is `mac_conformance.reported`, and `target` is
  `null`.
- `source.system` is `mac-conformance-facts`.
- `event_id` is `deterministic_event_id("mac-conformance-facts", source.ref)`.

The following table shows the fields that differ between a readable and an unreadable report.

| Field | Readable report | Unreadable newest report |
|---|---|---|
| `source.ref` | `generated_at` in UTC `Z` form | `unreadable:<YYYY-MM-DD.json>` |
| `timestamp` | `generated_at` (equal to the ref) | the nightly's run time, whole seconds, UTC |
| `result` | `success` if every instance is ok, else `unknown` | `unknown` |

`evidence` lists its items in this order:

1. One report item, either `{"type": "infra-drift-report", "generated_at": "<time>"}` or
   `{"type": "infra-drift-report-unreadable", "reason": "<field-only reason>"}`.
2. For a readable report only, one `{"type": "infra-drift-instance", "name": "<key>", "ok":
   true|false}` per instance, in the report's order. `ok` is the matrix's usability, not the raw
   field.
3. For a readable report only, one `{"type": "infra-drift-proposal", "instance": "<key>", "id":
   "<id>", "target": {"uuid": "<uuid>", "name": "<name>"}}` per object proposal. Any of the three
   values that isn't a string is `null`.
4. One `{"type": "wiring", "executor": "<kind>:<name>", "status": "present"|"absent"}` per
   `WIRING` entry, in `WIRING`'s order.

The event copies nothing else from the inputs.

`generated_at` is converted to UTC and written as isoformat plus `Z`, with microseconds only when
the report has a fraction. A naive time is taken as system-local, which is how `check_infra`
reads it. This keeps a `+00:00` or naive value from failing the envelope pattern and the nightly.

**Why the run time works for an unreadable report.** The run time is later than any earlier
report's `generated_at`, so a reader that takes the newest event by `timestamp` takes this
record. The ref is keyed on the file name, so a rerun on the same unreadable file appends
nothing. The next day's report has a later `generated_at` than this run time, so it wins in turn.

**One event per report.** The ref is `generated_at` alone. Adding a wiring digest would give two
events with one `timestamp`, which a newest-by-timestamp reader can't order. Because of this, a
wiring change on the Mac reaches the chain only with the next report, up to about a day later.

**No report at all** (no directory, no `YYYY-MM-DD.json`, or a directory that can't be listed):
`adapt` prints `mac-conformance-facts: 0 events appended (report skipped: <reason>)` and appends
nothing. Decision item 3 records only a newest report that can't be read or parsed. When there's
no newest report, the container keeps the newest event until it ages out, as decision item 3
describes for "a day with no new report".

## The wiring set and its source

`WIRING` is a constant in the adapter:

- `hook:bws-scan-gate.sh`
- `launchagent:com.devon.change-window`
- `launchagent:com.devon.factory-events`
- `launchagent:com.devon.portfolio-scan`
- `launchagent:com.devon.security-scan`

**Source.** I read the 13 repositories of orchestrator `docs/operations/membership-seed.toml`
at their `main` on 2026-11-18 (`gh api` contents of `PROJECT.md`):

- change-manager `89f87345` declares `launchagent:com.devon.change-window`.
- project-standards `4673d726` declares `launchagent:com.devon.portfolio-scan`.
- security-standards `23854235` declares the hook and two LaunchAgents.
- brain `8aeea718`, orchestrator `90f26ecd`, infraops-mcp-server `c3359bf1`, intent-packages
  `134b4c95`, and factory-runner `08dc5aa3` declare none.
- rtk, claude-octopus, rea, n8n-as-code, and n8n-manager have no `PROJECT.md`.

alobar-id and vps-backup also declare LaunchAgents (`com.devon.portfolio-scan`, and
`com.devon.vps-backup` and `com.devon.vps-backup-verify`). They aren't members, so the set leaves
their `vps-backup` labels out.

**Why a constant.** The nightly can't read the member record without a new network path or
credential, which is a stop point. The Mac's working copies aren't necessarily `main`.

**How each bound is held.**

- Upper bound (names nothing no member declares):
  `test_the_wiring_set_holds_every_declared_entry_and_nothing_else` asserts that `WIRING`
  equals the union of the recorded per-member declarations (`MEMBER_DECLARATIONS`, with the
  commit SHAs) and has exactly five distinct entries.
- Lower bound (holds every declared entry): the same test, plus
  `test_this_repositorys_own_declarations_are_in_the_set`. That second test parses this
  repository's own `PROJECT.md` and asserts its `launchagent:` and `hook:` entries equal its
  recorded row and are in `WIRING`. It's a live check for the one member whose declarations
  this repository holds.

**Limit.** A future declaration in another member isn't caught here. In the container, a missing
entry reads as not wired (`violation`). That's stricter than the Mac, never looser. Follow-up 3
covers it.

## Tests and checks

**`make check` on the clean base:** 313 passed, 22 deselected.

**`make check` on the branch:** ruff, format, and type checks pass, and pytest reports
**366 passed, 22 deselected** in 15 s (53 new tests). CI on #101 passed (lint, type-check,
and test; factory-store integration tests; scan) at the first content commit.

The security scan ran from the worktree root:
`PYTHONPATH=$PWD/src .venv/bin/python -m security_scan.cli . --category security`. It reported
0 BLOCK, 4 WARN, and 1 INFO, all in files this branch doesn't touch, plus 12 allowlisted items
that predate this branch.

The following list maps each test the handoff asked for to where it lives:

- **Exit and ping unchanged with the step's inputs missing and malformed.**
  - Python side (`test_adapter_mac_conformance.py`): `adapt --source all` exits 0 with no
    report, an empty directory, only sibling files, a directory whose entries can't be examined,
    or an unlistable directory. It also exits 0 for all 11 unreadable-report cases, and prints
    no `ADAPT FAIL`. The 10 odd-settings cases run `--source mac-conformance-facts` and exit 0.
  - Shell side (`test_factory_nightly.py::test_the_mac_conformance_step_leaves_the_exit_and_ping_alone`):
    with the step's skip line or its unreadable-record line in the adapt output, the nightly
    exits 0, pings `/start` then success, and sums `events_appended` as before.
- **An unreadable report is newer than the previous day's event.**
  `test_an_unreadable_record_is_newer_than_the_previous_days_event` places the previous report
  late in its day (`2026-11-18T07:59:59Z`). The newest event by `timestamp` is the unreadable
  record. All 11 unreadable cases also assert the record is newer than the previous event.
- **No free text.** In `test_the_event_carries_no_free_text_from_the_report_or_the_settings`,
  every free-text field carries a marker: `description`, `reasoning`, `question`,
  `planned_action`, `source`, `errors`, `standards_source`, `delta`, and the settings `env`. The
  test asserts:
  - the marker appears in neither the event nor the output;
  - each evidence item holds exactly its layout's keys;
  - no path appears.
- **Same inputs twice append one event.** This is covered by the first test, which also shows a
  wiring change under the same report appends nothing. The unreadable test covers a rerun at a
  later run time.
- **The wiring set's two bounds.** Covered as described in the preceding section.

The following tests go beyond the handoff's list:

- Sibling files such as `.remediation.json`, `.md`, and a directory named like a report are
  never picked.
- `generated_at` normalization: `+00:00`, `-05:00`, fractions, and naive times.
- Four kinds of unusable instance, odd proposal shapes, and basename-only hook matching.
- A LaunchAgent counts only as a plist file.
- A chain error fails the adapt while the other steps still run; an envelope error is a failure,
  not a skip.
- The step order in `all`.
- The registry label and the schema value.

## Files changed

- `src/factory_events/adapters/mac_conformance.py` (new)
- `src/factory_events/cli.py`
- `src/factory_events/README.md`
- `schema/factory-event.v1.schema.json`
- `registry/agents/mac-conformance-facts.yaml` (new)
- `tests/test_adapter_mac_conformance.py` (new)
- `tests/conftest.py`
- `tests/test_adapter_portfolio_scan.py` (the step-order lines)
- `tests/test_factory_nightly.py` (a stub control for the adapt output, plus one test)
- `tests/test_agent_registry.py`
- `tests/test_factory_envelope.py`

## Self-review

I ran `/code-review` (medium) on `main...HEAD`. It found no correctness bug and raised six
lower-confidence points. The following list gives my response to each:

1. **Wiring changes after a report aren't appended until the next report.** This is deliberate,
   to keep one event per `timestamp`; see "One event per report". The age-out still applies,
   because the bound keys on the report's `generated_at`. A stalled infra-drift job therefore
   ages the whole event out and the driver holds.
2. **Instance names and proposal ids are arbitrary strings.** Amendment 13 decision item 3 names
   exactly these ids for the event. They're the report's keys and identifiers, not its prose.
   I kept them.
3. **An empty `instances` object gives `success`.** The matrix reads the same report as `pass`
   (no failed instance, no proposal), so the event matches the Mac.
4. **A corrupt file that stays newest for days keeps its first-run timestamp.** The reader holds
   on an unreadable record whatever its age, and holds on a stale event, so the result is a hold
   either way, as on the Mac.
5. **`OSError` could escape the adapter.** On Python 3.14, `Path.is_dir` and `Path.is_file`
   return False on `OSError`. The adapter catches errors from `iterdir`, the report read, and
   the settings read. Tests cover an unlistable directory, a directory whose entries can't be
   examined (mode `0o600`), and an unreadable file.

A second review pass found one real gap, fixed in `0deaa24`. `json` raises a plain `ValueError`,
not `JSONDecodeError`, for an integer longer than its digit limit. That escaped `_read_report`,
which would have failed the nightly and skipped `portfolio-scan`. The read now catches
`ValueError`, and a test case covers it.
6. **The hard-coded `WIRING` can drift.** I accept that, as discussed in "The wiring set and its
   source": it fails closed. Follow-up 3 covers it.

No `noqa` or `type: ignore` was added. An earlier draft had two `noqa: N818` suppressions; I
removed them by renaming the exceptions to `NoReportError` and `UnreadableError`.

## Concerns

- **Merge order.** See "Merge order: read this first". This is the concern that matters most.
- **A transient fault keeps the hold until the next report.** If the newest file is unreadable
  at 03:30 (for example, still being written) and a rerun later reads it, the readable event's
  `timestamp` is the report's `generated_at`, which is earlier than the unreadable record's run
  time. The reader keeps taking the unreadable record and holds until the next day's report.
  That fails closed. A person can clear it only by a newer report.
- **Missing report versus unreadable report.** Amendment 13 has the unreadable record cover "a
  newest report that can't be read or parsed". I read a directory with no report as having no
  newest report, so the step appends nothing, and the container reads the previous event until
  it ages out (at most 36 hours after its `generated_at`). The Mac reads `unknown` at once in
  that case, so for that window the container is looser than the Mac. The window opens only
  when every report file is gone. If HQ wants that case recorded too, it needs a run-date ref
  (for example `missing:<date>`); I didn't invent one.
- **Wiring lag.** A plist or hook that disappears after the day's report reads `present` in the
  container until the next report, up to about a day later. The Mac reads it at once. This
  follows from one event per report.
- **Forged events.** Amendment 13 decision item 7 accepts this: any append holder can write this
  event. Nothing in this PR changes that.

## Follow-ups for the orchestrator reader

1. **Choosing the newest event.** Take the newest `mac_conformance.reported` event by
   `timestamp`, never by `seq`. Every readable report gives one event per `generated_at`, so the
   choice has no ties.
2. **When to hold.** Hold when any of the following is true:
   - the evidence's first item is `infra-drift-report-unreadable`;
   - any `infra-drift-instance` has `ok: false`, or `result` is `unknown`;
   - the readable report's `generated_at` is more than 36 hours old. Use the `generated_at`
     item, not the append time.
3. **Wiring entries the event doesn't list.** If a member declares a `launchagent:` or `hook:`
   entry that the event's wiring items don't list, the container reads `violation`. Consider
   having the reader compare the members' declarations with the event's `executor` list. It
   could then alert, or hold, with a clear key instead of proposing a non-green decomposition.
   Adding the entry to `WIRING` here is the fix.
4. **Materializing the files.**
   - Write the report file from the event's instances (`ok`, and `proposals` with `id`,
     `target.uuid`, `target.name`).
   - Write one empty plist per `present` LaunchAgent.
   - Write a settings file whose hook commands carry each `present` hook name as a token.

   `_infra_proposal_message` falls back to the id, as Amendment 13 notes.
5. **Wiring changes.** A wiring change reaches the chain only with the next infra-drift report.
   If a faster refresh matters, the reader would need a tie-break rule first.
6. **A transient unreadable record.** It outranks a later readable event for the same report
   (see Concerns). The reader holds; the next report clears it.

## Standards followed

- **Code Brain 3 (structured JSON logs to stdout in production).** The step keeps the adapters'
  existing plain-line form: `mac-conformance-facts: N events appended` on stdout, and
  `ADAPT FAIL (mac-conformance-facts): …` on stderr. The nightly script parses that form: its
  `sed` sums `N events appended` across lines. A JSON line would break the
  `events_appended` fact the nightly test asserts. The nightly writes those lines into its own
  log.
- **Code Brain 4 (never silently swallow an exception).** There's exactly one deliberate
  swallow, `NoReportError` in `cli._adapt_mac_conformance`. It carries an inline justification
  naming ADR-0059 Amendment 13 decision item 5, and prints the reason. The other places where
  an input can't be read aren't swallows:
  - An unreadable report becomes the recorded `infra-drift-report-unreadable` item, with its
    reason.
  - Unreadable settings read as `absent`, which is the matrix's own reading, commented in
    `_registered_hooks`.

  `EnvelopeError` and `ChainError` fail the adapt.
- **Code Brain 5 (never log secrets).** The adapter reads no secret. Printed and recorded
  reasons are fixed strings naming a field or an exception type. Tests assert that a marker
  placed in every free-text field never reaches the event, stdout, or stderr.
- **Infra Brain 591, 592, and 593 (BWS token handling).** The diff holds no BWS token, no
  token-shaped string, and no inline `BWS_ACCESS_TOKEN`. The nightly test's stubs remain the
  existing obviously fake values. The scan reports 0 BLOCK.
- **Infra Brain 1032 (`cred.exposure-rotate`).** It doesn't apply: no credential was read,
  surfaced, or exposed in this work, and none was printed into the transcript, so there's
  nothing to rotate. I made no Keychain or BWS read.
- **Infra Brain 212 (HTTPS).** It doesn't apply: the change adds no network endpoint or client.
  The adapter reads local files only, and the chain append uses the existing database
  connection unchanged.
