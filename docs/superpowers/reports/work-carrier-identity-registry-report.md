Outcome: done

# Report: the work carrier's registry identity (plan step 3e-cid-1)

- PR: [AlobarQuest/security-standards#86](https://github.com/AlobarQuest/security-standards/pull/86), ready, not merged.
- Branch: `hq/work-carrier-identity-registry`. Base: `origin/main` at `4987197` (confirmed at dispatch).
- Registry commit: `9420aa5`. This report is committed on top of it, so the PR head is the report commit.

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

No schema, vocabulary, CLI, or test change was needed. I created no credential and took no BWS,
Coolify, or orchestrator action.

## Checks

### 1. Validate, show, and authority

Run with the worktree's own `.venv` (Python 3.14.3, made with `uv venv --clear --python 3.14`):

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

- `make test` in both venvs. Each run: **206 passed, 5 deselected**.
  - `.venv` with `.[dev]`.
  - `.venv-events` with `.[events,dev]`, the second venv the repo's `CLAUDE.md` names.
- The base (`git archive origin/main`, the same interpreter) also collects 206 passed, 5 deselected, so the test count didn't change.
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
    `SOURCE_REVISION`, so the merge commit gives a different one.

### 5. What the orchestrator needs next (3e-cid-2)

The handoff's description of the pin is slightly off. The orchestrator `Dockerfile` takes
`SECURITY_STANDARDS_REVISION` and `REGISTRY_ARTIFACT_SHA256` as build args, but the production
values live in one file, **`security-standards.pin.toml`** (`revision`, `artifact_sha256`). The
release workflow (`.github/workflows/release-image.yml` ~93-193) reads that file and passes the values on.
`tests/fixtures/` holds a *synthetic* registry: `tests/fixtures/security-standards/` with a
placeholder revision `0123…4567`, `tests/fixtures/registry-bundle.json`, and quality.yml's fixed
digest `258e47…fbce`. That fixture isn't a production pin. Neither fact is wrong enough to block this
step, so I went ahead.

In order:

1. Bump `security-standards.pin.toml` to this PR's **merge commit** and recompute
   `artifact_sha256` with `scripts/shape_registry_context.py` and then `build_registry_bundle.py`'s
   `artifact_digest`, as the file's header says. Then rebuild and redeploy the image. `agent_id`
   resolves against the bundle baked into the image.
2. The pin is at `64b7186` (PR #79), behind PR #83, which retired `security-executor`. So this
   bump also drops `security-executor` from the bundle. `git grep security-executor` over orchestrator
   `src`, `scripts`, and `*.toml` returns nothing, but confirm that no live credential still names it, or boot
   resolution fails for that credential.
3. Add the boot check: a `WORK_CARRIER_PROFILE = "work-carrier-observer-v1"` entry checked like
   `_require_rotation_executors` (`src/orchestrator/main.py` 226-250, called at ~135) against
   `ORCHESTRATOR_WORK_CARRIER_AGENT_ID`. If its tests resolve the agent, add `work-carrier` to the
   synthetic fixture (`tests/fixtures/security-standards/agents/`, `registry-bundle.json`, and
   quality.yml's fixture digest), as `tests/identity/test_rotation_executor_boot.py` does for the executors.
4. The image ships only `registry/agents`, `src/agent_registry`, `src/factory_events`, and `schema`
   (`shape_registry_context._MAP`, `Dockerfile` 42-44). Profiles aren't in the image. The boot check
   compares the agent's `authority_profile` *string*, so that's enough; it never reads the profile's capabilities.

Other orchestrator reads of this repository:

- `package_sources.py` 180-230 reads `registry/agents/<id>.yaml` and `factory_events` through `SECURITY_STANDARDS_DIR`.
- `scripts/run-bump-driver.sh` puts this repository's `src` on `PYTHONPATH`.
- `.cred-consumers.toml` names this repository twice.

None of these needs a change for this step. The credential deployment order and the
`.cred-consumers.toml` row for `work-carrier-observer` are in the increment 3 report's identity
design (items 5-7) and are Devon's.

### Security scan and code review

- Security scan from the worktree root, run as the handoff gives it: **BLOCK 0**, WARN 4, INFO 1, rc 0.
  All the findings and allowlisted entries are in files this diff doesn't touch.
- `/code-review` (low) on `origin/main...HEAD`: no findings.

## Files changed

- `registry/agents/work-carrier.yaml` (new, 11 lines)
- `registry/profiles/work-carrier-observer-v1.yaml` (new, 27 lines)
- `docs/superpowers/reports/work-carrier-identity-registry-report.md` (this report)

## Self-review

- The profile's authority equals `observer-v1`'s; the only difference is the name, which is the point.
- `environment: any` matches `orchestrator-observer` and is in the schema's enum (validation passes).
- The files hold names and ids only: no secret value, no BWS UUID.

## Deviations

None from the build itself. The handoff described the orchestrator's pin as living in the Dockerfile
and `tests/fixtures/`. The production pin is in `security-standards.pin.toml`, and the fixture is
synthetic. Check 5 has the details.

## Concerns and follow-ups

- 3e-cid-2 (orchestrator): the pin bump (it also drops `security-executor`), the image rebuild, and the boot check, as listed in check 5.
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
