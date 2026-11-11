Outcome: done

# Report: the work carrier's registry identity (plan step 3e-cid-1)

- PR: [AlobarQuest/security-standards#86](https://github.com/AlobarQuest/security-standards/pull/86), ready, not merged.
- Branch: `hq/work-carrier-identity-registry`. Base: `origin/main` at `4987197` (confirmed at dispatch).
- Registry commits: `9420aa5` (both files) and `3fa7638` (the profile description cut to what exists, after review). The report is committed on top, so the PR head is the report commit.

## What I built

I added two registry files, modelled on PR #79 (`64b7186`):

- `registry/agents/work-carrier.yaml`: `schema: agent-identity/v1`, `agent_id: work-carrier`,
  `version: 1`, `status: active`, `runtime: node-executor`, `operator: devon`, `environment: any`,
  `authority_profile: work-carrier-observer-v1`, `capabilities: []`, `prohibited: []`. The
  description covers each point the handoff listed:
  - The identity uses an OBSERVER-only M2M credential with key id `work-carrier-observer`.
  - It records one observation per standing-approval check before an intake (amendment 22 item 3), and nothing else.
  - Its intakes keep the shared `orchestrator-system` SYSTEM credential.
  - The decomposition gate trusts the observation only when `recorded_by` is this id, so no other caller may hold it.
  - It runs on the Mac today and moves to a container in ADR-0059 increment 4, which is why `environment` is `any`.
- `registry/profiles/work-carrier-observer-v1.yaml`: `schema: authority-profile/v1`,
  `capabilities: [event_emit]`, and a `prohibited` list identical to `observer-v1`'s 14 terms. The
  description traces `event_emit` to amendment 22 item 3. It also says why this is a distinct profile: the
  orchestrator's boot check (3e-cid-2, mirroring `_require_rotation_executors`) has to be able to name it.
  It doesn't describe that unbuilt check's behavior.

No schema, vocabulary, CLI, or test change was needed. I created no credential and took no BWS,
Coolify, or orchestrator action.

## Checks

### 1. Validate, show, and authority

Run with the worktree's own `.venv` (Python 3.14.3, made with `uv venv --clear --python 3.14`), at
`9420aa5` and again at `3fa7638` with the same output:

- `PYTHONPATH=src .venv/bin/python -m agent_registry validate` → `registry ok: 19 agents, 15 profiles`, rc 0.
- `show work-carrier` prints the agent file as written.
- `authority work-carrier --json`:

```json
{"agent_id": "work-carrier", "status": "active", "authority_profile": "work-carrier-observer-v1", "capabilities": ["event_emit"], "prohibited": ["change_approval", "change_filing", "credential_create", "credential_revoke", "data_delete", "email_send", "external_system_write", "infra_mutation", "merge_to_main", "outward_publish", "pr_open", "repository_write", "secret_write", "task_claim"]}
```

### 2. The names are new

`git grep -n -e work-carrier -e work_carrier origin/main -- .` returns nothing (rc 1). No agent or
profile at the base uses either name.

### 3. The vocabulary

`registry/capabilities.yaml` defines `event_emit` ("append events to the factory-events store") and
all 14 `prohibited` terms; I checked each term by name. A `diff` of the two profiles' `prohibited`
blocks shows they're identical to `observer-v1`'s list.

### 4. Tests and the CI registry step

Every run reported **206 passed, 5 deselected**:

- `.venv/bin/python -m pytest -q` (`.venv` has `.[dev]`).
- `PYTHONPATH=src .venv-events/bin/python -m pytest -q` (`.venv-events` has `.[events,dev]`, the second venv the repo's `CLAUDE.md` names).
- `make test PYBIN=.venv-events/bin/python`.
- `make check` at `3fa7638`: ruff check ("All checks passed!"), ruff format ("58 files already formatted"), pyright ("0 errors"), and pytest (211 collected, 5 deselected, 206 selected and passed). rc 0.
- The base (`git archive origin/main`, run with `.venv/bin/python -m pytest -q`) also gives 206 passed, 5 deselected, so the test count didn't change.
- CI registry step (`.github/workflows/security-scan.yml`: `python -m agent_registry validate` after
  `pip install -e ".[dev]"`): `.venv/bin/python -m agent_registry validate` on the editable install
  → `registry ok: 19 agents, 15 profiles`, rc 0.
- Orchestrator compatibility (read-only, in a scratch directory; the orchestrator tree was untouched):
  1. I extracted orchestrator `origin/main` (`f6c5d47e`) `scripts/` and `src/orchestrator/` with `git archive`.
  2. I ran `shape_registry_context.py --source <this worktree> --revision 9420aa5…`.
  3. I ran `build_registry_bundle.build_bundle_from_artifact` on the result.
  - The bundle builds with 19 actors, including
    `{'agent_id': 'work-carrier', 'version': 1, 'status': 'active', 'runtime': 'node-executor', 'authority_profile': 'work-carrier-observer-v1'}`.
    The artifact digest at `9420aa5` is `d5e37d6a…f633`. It's an illustration only: the digest covers
    `SOURCE_REVISION`, so the merge commit gives a different one. `3fa7638` changed only a profile,
    and profiles aren't in the shaped context, so the bundle's content is the same.

### 5. What the orchestrator needs next (3e-cid-2)

The pin facts in the handoff check out. The orchestrator `Dockerfile` takes
`SECURITY_STANDARDS_REVISION` and `REGISTRY_ARTIFACT_SHA256` as build args (lines 4-5, 18-19), and
`tests/fixtures/` holds a registry fixture. One addition: the production values live in
**`security-standards.pin.toml`** (`revision = 64b7186…`, `artifact_sha256`). The release workflow
(`.github/workflows/release-image.yml` ~93-193) reads that file and passes both values to the build.
The `tests/fixtures/` registry is synthetic: placeholder revision `0123…4567`, agents `devon` and
`worker` only, and quality.yml's fixed digest `258e47…fbce`. It isn't a production pin.

In order:

1. Bump `security-standards.pin.toml` to this PR's **merge commit**, and recompute
   `artifact_sha256` with `scripts/shape_registry_context.py` and then `build_registry_bundle.py`'s
   `artifact_digest`, as the file's header says. Then rebuild and redeploy the image. `agent_id`
   resolves against the bundle baked into the image.
2. The bump carries more than this agent. `git diff --stat 64b7186..origin/main` over the four
   shaped paths (`registry/agents`, `src/agent_registry`, `src/factory_events`, `schema`) shows one
   other change: `registry/agents/security-executor.yaml` (PR #83, `25ffc84`), whose `status` goes
   from `active` to `retired`. The entry stays in the bundle. `git grep security-executor` over
   orchestrator `src`, `scripts`, and `*.toml` returns nothing, but confirm that no live M2M credential
   names `security-executor`, because the bundled actor becomes `retired`.
3. Add the boot check, keyed on `authority_profile == "work-carrier-observer-v1"` and
   `ORCHESTRATOR_WORK_CARRIER_AGENT_ID`, mirroring `_require_rotation_executors`
   (`src/orchestrator/main.py` 230-250, called at ~135). Its tests don't need a fixture-file change:
   `tests/identity/test_rotation_executor_boot.py` (lines 21-42) loads
   `tests/fixtures/registry-bundle.json` and appends the executor actors in the test, and a
   work-carrier test can do the same.
4. The image ships only `registry/agents`, `src/agent_registry`, `src/factory_events`, and `schema`
   (`shape_registry_context._MAP`, `Dockerfile` 42-44). Profiles aren't in the image. The bundle
   carries the agent's `authority_profile` *string*, which is what a boot check compares.

Other orchestrator reads of this repository, none of which this step needs to change:

- `package_sources.py` (175-235) reads `registry/agents/<id>.yaml` only to check for
  `human-operator-v1` (`_is_human_operator`), and `src` for the factory-events chain. It uses
  `SECURITY_STANDARDS_DIR`, falling back to `~/Projects/security-standards`, the main checkout.
  A host-side caller without that variable reads the main checkout, which updates only when someone
  syncs `main` there. Nothing in this step reads `work-carrier` through that path.
- `scripts/run-bump-driver.sh` puts this repository's `src` on `PYTHONPATH`.
- `.cred-consumers.toml` names this repository twice.

The credential deployment order and the `.cred-consumers.toml` row for `work-carrier-observer` are
in the increment 3 report's identity design (items 5-7) and are Devon's.

### Security scan and code review

- Security scan from the worktree root, run as the handoff gives it, at `9420aa5`: **BLOCK 0**,
  WARN 4, INFO 1, rc 0. All the findings and allowlisted entries are in files this diff doesn't
  touch. A control run on a `git archive` copy of the base returned rc 1. That copy has no `.git`,
  which the scanner's history rules expect, so I didn't treat it as a comparison. The rerun at the PR head is under "Final checks".
- `/code-review` (low) on `origin/main...HEAD` at `9420aa5`: the skill returned `(none)`.

### Final checks

Run at `3fa7638`, with the revised report in the working tree:

- Security scan: BLOCK 0, WARN 4, INFO 1, rc 0, the same findings as before.
- `make check`: rc 0. Check 4 lists its results.

## Files changed

- `registry/agents/work-carrier.yaml` (new, 11 lines)
- `registry/profiles/work-carrier-observer-v1.yaml` (new, 26 lines)
- `docs/superpowers/reports/work-carrier-identity-registry-report.md` (this report)

## Self-review

- The profile's authority equals `observer-v1`'s; the only difference is the name, which is the point.
- `environment: any` matches `orchestrator-observer` and is in the schema's enum (validation passes).
- The files hold names and ids only: no secret value, no BWS UUID.

## Deviations

None.

## Concerns and follow-ups

- 3e-cid-2 (orchestrator): the pin bump (it also carries `security-executor` to `retired`), the image rebuild, and the boot check, as listed in check 5.
- The worktree's `.venv` and `.venv-events` are gitignored local environments, not committed.

## Standards followed

- **Code Brain rule 3 (structured JSON logs to stdout):** no logging change; the diff is two YAML files.
- **Code Brain rule 4 (never swallow an exception silently):** the diff adds no code, so there's no exception handling to check.
- **Code Brain rule 5 (never log secrets):** the files carry names and ids only (`work-carrier`,
  `work-carrier-observer-v1`, key id `work-carrier-observer`), no token.
- **Infra Brain 591, 592, 593 (no BWS token in tracked files or history, no inline bootstrap
  token):** the registry names no secret value or UUID. The scan reports 0 BLOCK findings, and none of its findings is in the diff.
- **Infra Brain 1032 (cred.exposure-rotate):** no credential exists yet and none was surfaced, so
  there's no exposure entry.
- **Infra Brain 212 (HTTPS for public FQDNs):** not applicable; no domain change.
