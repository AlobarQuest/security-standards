Outcome: done

# Report: split the mac-conformance-facts schema and registry entry out of PR #101

Worker W-220, 2026-11-18. Goal step 3g-3 (3g-3-inputs, ADR-0059 Amendment 13 decision item 6,
D-62 C).

## What I built

| PR | Branch | Base | Head |
|----|--------|------|------|
| #102 (new, schema and registry) | `hq/mac-conformance-facts-schema` | `main` (`2385423`) | `a8dcdea` before this report; the report commit follows it |
| #101 (adapter) | `hq/mac-conformance-facts-event` | retargeted to `hq/mac-conformance-facts-schema` | `42bc209` |

The following files make up #102's diff. I checked them out from #101's head `f3defd0`, so the
content is unchanged:

- `schema/factory-event.v1.schema.json`: the `source.system` enum gains `mac-conformance-facts`.
- `registry/agents/mac-conformance-facts.yaml`: the `none-v1` label.
- `tests/test_agent_registry.py`: `test_mac_conformance_facts_is_a_registered_credential_less_label`.
- `tests/test_factory_envelope.py`: `test_schema_accepts_the_mac_conformance_facts_source`.
- `docs/superpowers/reports/mac-conformance-facts-schema-report.md`: this report.

The following files make up #101's diff against its new base:

- `docs/superpowers/reports/mac-conformance-facts-event-report.md`
- `src/factory_events/README.md`
- `src/factory_events/adapters/mac_conformance.py`
- `src/factory_events/cli.py`
- `tests/conftest.py` (the autouse fixture that points the adapter's inputs at absent paths; it
  belongs to the adapter, so it stays in #101)
- `tests/test_adapter_mac_conformance.py`
- `tests/test_adapter_portfolio_scan.py`
- `tests/test_factory_nightly.py`

#101's body has a "Merge order: read this first" section at its top giving the order: #102, then
the orchestrator pin bump shipped and the carrier rolled, then #101. Its summary bullet about the
registry and schema now says those moved to #102.

### Deviation: merge instead of rebase

The handoff asked me to rebase #101's branch onto the new branch. A rebase rewrites #101's
published commits and needs a force push, which the worker rules forbid. Instead, I merged
`hq/mac-conformance-facts-schema` into #101's head (merge commit `42bc209`) and pushed it as a
fast-forward. The result is the same as a rebase for the purpose that matters: against its new
base, #101's diff holds only the adapter, the CLI step, their tests, and the README. The cost is
one merge commit in #101's history.

I did this on a detached `HEAD` in this worktree because the W-219 worktree has the branch
checked out. That worktree's local `hq/mac-conformance-facts-event` is now one commit behind
origin. If W-219 resumes, it needs a fast-forward pull first.

## Tests and checks

`make check` (ruff check, ruff format --check, pyright, pytest) on each branch before pushing:

| Tree | Result |
|------|--------|
| `main` (`2385423`), from #101's report | 313 passed, 22 deselected |
| #102 (`a8dcdea`) | ruff and pyright clean; 337 collected, 315 passed, 22 deselected; exit 0 |
| #101 (`42bc209`) | ruff and pyright clean; 388 collected, 366 passed, 22 deselected |

The 366 matches #101's own report, so the split lost no test. Each PR is green on its own.

Security scan (`security_scan.cli . --category security`) on #102: 0 BLOCK, 4 WARN, 1 INFO. All
four WARNs are in files neither PR touches.

CI started on both PRs. At the time of writing, #102's checks were pending and #101's earlier
run had passed lint, tests, integration tests, and scan, with a fresh run pending for the new
head. I didn't merge either PR.

## Registry bundle effect

#102 adds an agent to `registry/agents/`, so the registry bundle changes. When the orchestrator
pin (`security-standards.pin.toml`) moves to #102's merge commit, it must bump `revision` and
`artifact_sha256` together. I didn't compute the new hash; that's orchestrator work.

## Self-review

- The schema value and registry file are byte-identical to #101's: `git diff #102 #101-head`
  lists neither file.
- #102's two new tests depend only on the schema and the registry file, not on the adapter.
- #101's `test_portfolio_scan_runs_last_in_all` expects the `mac-conformance-facts` CLI line, so
  that test change correctly stays with the CLI step in #101.

## Concerns

- The rebase-to-merge deviation, described in the preceding "Deviation" section.
- #101's base is a feature branch. When #102 merges and its branch is deleted, GitHub retargets
  #101 to `main` automatically. If the branch is kept, retarget #101 to `main` by hand before
  merging it.

## Standards followed

- **Code Brain 3 (structured JSON logs to stdout in production):** #102 changes no logging. It
  holds a schema enum value, a YAML registry entry, and two tests.
- **Code Brain 4 (never silently swallow an exception):** #102 adds no exception handling.
- **Code Brain 5 (never log secrets):** the registry file and schema hold no secret. The registry
  entry declares no credential, and `capabilities` is empty.
- **Infra Brain 591, 592, 593 (no BWS token in a tracked file or history; no inline
  `BWS_ACCESS_TOKEN`):** neither PR adds a token or a `BWS_ACCESS_TOKEN` assignment. The security
  scan reports 0 BLOCK findings.
- **Infra Brain 1032 (`cred.exposure-rotate`):** doesn't apply. No credential was surfaced,
  exposed, or changed.
- **Infra Brain 212 (HTTPS):** doesn't apply. Neither PR adds or changes a network endpoint or a
  URL.
