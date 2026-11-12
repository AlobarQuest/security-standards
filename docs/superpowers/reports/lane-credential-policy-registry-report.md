Outcome: blocked

I'm blocked on one wording question, not on a failing check: see `lane-credential-policy-registry-question.md`. Every check passes, and the PR is open and ready.

# Report: the `lane-credential-policy` registry label (plan step 3e-a22-4a)

- PR: [AlobarQuest/security-standards#89](https://github.com/AlobarQuest/security-standards/pull/89), ready, not merged.
- Branch: `hq/lane-credential-policy-registry`. Base: `origin/main` at `31aa7d70`, confirmed at dispatch. It matches the handoff's base.
- Registry commits: `2e97c15` adds the file, and `ebfc165` corrects the description's wording (see "Deviations"). The report is committed on top, so the PR head is the report commit.

## What I built

I added one file, `registry/agents/lane-credential-policy.yaml`, modelled on `deploy-policy.yaml`. It sets
`schema: agent-identity/v1`, `agent_id: lane-credential-policy`, `version: 1`, `status: active`,
`runtime: unknown`, `operator: devon`, `environment: any`, `authority_profile: none-v1`,
`capabilities: []`, and `prohibited: []`. The description covers each point the handoff listed:

- The id is recorded when a proposer-generated revision 1 of a lane credential (a `bws-lane-token` or
  `healthchecks-ping-url` rotation) is approved by conformance to Devon's standing answer of
  2026-11-10 (D-34 A; orchestrator ADR-0055 amendment 22).
- It's a label, not a runtime, the same kind of entry as `deploy-policy`. Nothing runs under it, and
  no credential authenticates as it.
- It appears only as the `actor` on that `package.approved` event.
- The standing answer's date and entry travel in the event detail, not in the id.
- Reissues (revision 2 and later) are never recorded under it; they need Devon by name.
- `runtime: unknown` and `environment: any` are explained the same way `deploy-policy` explains them.

I made no profile, schema, vocabulary, CLI, or test change; validation needed none. I created no
credential, and I took no BWS, Coolify, orchestrator, or credential action.

## Checks

### 1. Validate, show, and authority

I ran these with the worktree's own `.venv` (Python 3.14.3, made with `uv venv --clear --python 3.14`
and `uv pip install -e ".[dev]"`), at `ebfc165`:

- `PYTHONPATH=src .venv/bin/python -m agent_registry validate` → `registry ok: 20 agents, 15 profiles`, rc 0. The base has 19 agents.
- `show lane-credential-policy` prints the agent file as written, with `authority_profile: none-v1`, `capabilities: []`, and `prohibited: []`. rc 0.
- `authority lane-credential-policy --json`, rc 0:

```json
{"agent_id": "lane-credential-policy", "status": "active", "authority_profile": "none-v1", "capabilities": [], "prohibited": []}
```

### 2. The name is new

`git grep -n -e lane-credential-policy -e lane_credential_policy origin/main -- .` returns nothing
(rc 1). No file at the base uses the name. Read-only, I also ran `git grep` on orchestrator
`origin/main` (`4852e0b0`) and intent-packages `origin/main` (`636ceacb`): neither names it.

### 3. The envelope: rejected before, accepted after

The suite's pattern is generic: `tests/test_factory_envelope.py` has one test that rejects an
unregistered actor and one that accepts a registered one (`factory-runner`). It has no per-agent
test. The handoff expects no test-count change, so I used a one-off command instead of a test. The
script calls `factory_events.envelope.make_event(actor="lane-credential-policy",
action="package.approved", result="success", timestamp="2026-11-12T00:00:00Z",
source={"system": "direct", "ref": "w97-check"})` and prints the result.

- I ran it against a `git archive origin/main` extraction, with `python -I` and that tree's `src`
  first on `sys.path`. I confirmed that `envelope` and `registry` loaded from the extraction:
  `REJECTED: actor 'lane-credential-policy' is not a registered agent_id (see registry/agents/)`.
- I ran it against the worktree: `ACCEPTED actor=lane-credential-policy id=evt-0846992b1d18`.

### 4. Tests and the CI registry step

Every run reported **211 collected, 5 deselected, 206 passed**:

- `make test` (`.venv`, which has `.[dev]`).
- `make test PYBIN=.venv-events/bin/python` (`.venv-events`, which has `.[events,dev]`; it's the second venv the repo's `CLAUDE.md` names).
- `make check`, rc 0: ruff check ("All checks passed!"), ruff format ("58 files already formatted"), pyright ("0 errors, 0 warnings, 0 informations"), and pytest (206 passed, 5 deselected).
- The base (`git archive origin/main`, run with `.venv/bin/python -m pytest -q`) also gives 206 passed and 5 deselected, so the test count didn't change.
- The CI registry step in `.github/workflows/security-scan.yml` is `python -m agent_registry validate` after `pip install -e ".[dev]"`. On the editable install, `.venv/bin/python -m agent_registry validate` → `registry ok: 20 agents, 15 profiles`, rc 0.

### 5. What consumers need next (read only, not changed)

**(a) The orchestrator.** I read these at orchestrator `origin/main` `4852e0b0`, without a fetch:

- The bundle pin is in `security-standards.pin.toml`: `revision` `31aa7d70…` and `artifact_sha256`
  `b11a9e9c…16b9`. PR #666 (`671acd1d`) bumped both values for `work-carrier`. The release workflow
  reads that file and passes `SECURITY_STANDARDS_REVISION` and `REGISTRY_ARTIFACT_SHA256` to the Docker
  build. The build's gate (`build_registry_bundle.py --artifact-sha256`) fails closed on a mismatch.
- PR #666 didn't change `tests/fixtures/security-standards/`. That fixture holds only `devon.yaml` and
  `worker.yaml`, and `quality.yml`'s fixture build uses a fixed revision and digest. A bump for this
  agent doesn't touch it either.
- Nothing in the orchestrator reads this agent. The bundle feeds `load_auth_config` (M2M credentials,
  email-to-actor mapping, and the rotation-executor and work-carrier boot checks), and this label has
  no credential.
- The approval readers are `package_sources._approval_event_to_verified` and
  `work_carrier.standing._verified_approval`. They match a `package.approved` event on its event id,
  `source.ref`, and the evidence's hash, revision, approver, and commit. Neither reads the event's
  `actor`. The approver they match is the `policy:<profile>@v<N>` string (`work_carrier/standing.py`
  docstring).
- On read, the orchestrator doesn't check the actor against the registry.
  `package_sources._verify_factory_chain` runs `python -m factory_events verify` with the
  security-standards checkout's `src` (`$SECURITY_STANDARDS_DIR` or `~/Projects/security-standards`),
  not the bundle. In this repo, `store.verify_chain` and `store.append` call only `validate_event`,
  which checks the JSON Schema. Only `make_event` calls `_assert_registered_actor`
  (`envelope.py:87`), so the actor is checked once, at emit.
- `_is_human_operator` reads agent YAML from the same checkout's `registry/`, not the bundle, and
  it's only reached for a human approver.
- So no orchestrator change is needed for the event to work. A pin bump to the merge commit is
  optional and only keeps the bundle current. If someone does it, they bump both values together and
  recompute the digest with `scripts/shape_registry_context.py`, then `build_registry_bundle.py`, as
  #666 did.

**(b) The intent-packages emitter.** I read these at intent-packages `origin/main` `636ceacb`:

- `FactoryEventsEmitter.emit` (`src/intent_packages/emitter.py`) shells out to `python -m factory_events emit`.
  It doesn't import an installed copy.
- The checkout comes from `_security_standards_dir()`: `$SECURITY_STANDARDS_DIR` if set. If it isn't
  set, `registry.registry_dir().parent` gives `~/Projects/security-standards`.
- The interpreter is that checkout's `.venv-events/bin/python`. If that interpreter doesn't exist,
  the emitter falls back to the caller's `sys.executable`.
- `PYTHONPATH` is prefixed with `<checkout>/src`, so `factory_events` and `agent_registry` load from
  that checkout's source tree. `agent_registry.registry.REGISTRY_DIR` resolves from the module file
  (`Path(__file__).parents[2] / "registry"`), so the registry it checks is also that checkout's
  `registry/agents/`.
- Before an event naming this actor is accepted, the checkout the emitter resolves must contain this
  file. With the default, that's the main checkout `~/Projects/security-standards`, which needs a
  `git sync` to a `main` that includes this merge. No venv reinstall is needed, because the `src`
  prefix wins over any installed copy. `governance-map.toml` has no `factory_events` or `registry`
  entry (a `grep` returns nothing), so `make install` deploys neither, and this needs no `make install`.
- The emitter takes the actor from `FACTORY_AGENT_ID`, and its default is `claude-code-interactive`.
  So the HQ cycle that records the approval must set `FACTORY_AGENT_ID=lane-credential-policy` for
  that one `approve` call. Otherwise the event is attributed to the default actor.

## Security scan

I ran `PYTHONPATH="$HOME/Projects/security-standards/src" ~/Projects/security-standards/.venv/bin/python -m security_scan.cli . --category security`
from the worktree root, rc 0. Summary: **BLOCK 0, WARN 4, INFO 1**, with 12 allowlisted.

- The allowlisted entries are the known test-fixture token shapes, the scanner plan, five history
  commits, and `hooks/bws-write-guard.sh:33`.
- The four WARNs (`bws.reference-by-stable-uuid`) are in `docs/superpowers/plans/…`,
  `docs/superpowers/specs/…`, and `src/security_scan/rules_cache.json`. This diff touches none of
  those files.

## Code review

`/code-review low origin/main...HEAD` returned no findings.

## Files changed

- `registry/agents/lane-credential-policy.yaml` (new)
- `docs/superpowers/reports/lane-credential-policy-registry-report.md` (new; this report)
- `docs/superpowers/reports/lane-credential-policy-registry-question.md` (new; the wording question)

## Self-review and deviations

- **The description says "actor", not "the policy approver".** The handoff's brief said the id
  appears "as the `actor` on that `package.approved` event and the policy approver". I read
  intent-packages `approval_policy.py`: the policy approver is the string `policy:<profile>@v<N>`,
  a shape no agent id can take. The orchestrator matches the approval on that string, not on the
  actor. So I wrote that the id is the `actor`, beside the `policy:` approver in the evidence. I also
  opened the description with "The actor recorded" instead of the handoff's "the approver recorded",
  for the same reason. `ebfc165` makes that correction. A `none-v1` id also can't be a recognized
  ledger approver: `_is_recognised_approver` accepts only `human-operator-v1` or a `policy:` string.
  The handoff says to stop when a fact is wrong at its source, so I asked HQ to confirm the wording.
  The question file lists the options; option B reverts `ebfc165`.
- **The description is longer than `deploy-policy`'s and stays inside the brief.** It doesn't
  describe any unbuilt behavior. "Reissues need Devon by name" is the handoff's statement of the
  standing answer's scope, and I didn't verify it against the proposer code.
- The worktree venvs `.venv` and `.venv-events` are gitignored and untracked.

## Follow-ups (not mine to change)

1. HQ's approval call must set `FACTORY_AGENT_ID=lane-credential-policy`, and the emitter's checkout
   (by default `~/Projects/security-standards`) must be synced past this merge first (check 5b).
2. The orchestrator pin bump is optional, because nothing there reads this actor (check 5a).

## Standards followed

- **Code Brain rule 3 (structured JSON logs to stdout):** the diff has no logging change. It adds
  one YAML data file.
- **Code Brain rule 4 (never swallow an exception silently):** the diff adds no code. My one-off
  check script caught only `EnvelopeError` and printed it, and it ran outside the repo.
- **Code Brain rule 5 (never log secrets):** the file carries names only: the agent id, profile, and
  rotation kinds. It has no token or secret.
- **Infra Brain 591, 592, 593 (no BWS token in tracked files or history, no inline bootstrap
  token):** the registry entry names no secret value or UUID. The scan reports 0 BLOCK findings, and
  the BWS write-guard passed both writes.
- **Infra Brain 1032 (cred.exposure-rotate):** no credential exists for this identity, and none will.
  It's a label with the `none-v1` profile, and nothing was exposed, so nothing needs rotation.
- **Infra Brain 212 (HTTPS for public FQDNs):** not applicable. The diff has no domain change.
