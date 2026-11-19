Outcome: done

# Report: security-standards side of change-window's move (ADR-0059 increment 8, PR (3))

Worker W-239. Branch `hq/change-window-move`, base `origin/main` `9563e9ea`.
Draft PR: [AlobarQuest/security-standards#105](https://github.com/AlobarQuest/security-standards/pull/105).
It isn't marked ready and isn't merged.

## What I built

1. `registry/agents/change-window-agent.yaml:7`: `environment: mini` becomes `environment: vps`.
   `vps` comes from the enum in `schema/agent-identity.v1.schema.json:16`
   (`mini`, `vps`, `github-actions`, `isolated-vm`, `any`). `runtime: node-executor`,
   `authority_profile: infra-window-v1`, and `version: 1` are unchanged. No agent has ever
   bumped its version. The description is unchanged because it doesn't name the Mac, and
   "4AM" stays true (04:00 New York).
2. `governance-map.toml:173-193`: the infraops-mcp-server `owns` list becomes these entries:
   `infraops MCP server`, `drift-audit.sh`,
   `change-mgr-cli run-window (the change-window executor)`,
   `change-window.sh (the Mac launcher, kept for rollback)`, and `security-drift subsystem`.
   A new `[[repo]]` entry follows it:
   `orchestrator`, `class = "tool-home"`, `lane = "execute"`,
   `owns = ["change-window lane launcher (scripts/run-change-window.sh, lanes/change-window/)"]`,
   with a two-line comment citing ADR-0059 amendments 14 and 15 and D-66 A. I kept
   `change-window.sh` under infraops because infraops `origin/main` still has
   `scripts/change-window.sh` and its plist template, and the orchestrator launcher's header
   says the Mac job stays until rollback ends (options report section 7, item 7, removes it later).
   No tracked file in this repository is generated from the map, so I regenerated nothing.
   `~/.claude/OWNERSHIP.md` is generated outside the repository, and I didn't run `make ownership`.
3. `src/factory_events/adapters/mac_conformance.py:40-52`: `WIRING` drops
   `launchagent:com.devon.change-window`. The comment now says that project-standards and
   security-standards declare these four, and that change-manager's entry left with the move.
   `tests/test_adapter_mac_conformance.py`:
   - At line 176, the rerun-with-changed-wiring case wires `com.devon.portfolio-scan`, which is
     still in the list.
   - At lines 512-516, the "present only as a plist file" case wires `com.devon.portfolio-scan`,
     `com.devon.change-window`, and `com.devon.vps-backup`. It expects only `portfolio-scan` to be
     present, so the test also checks that a change-window plist is no longer reported.
   - In `MEMBER_DECLARATIONS`, the change-manager row is removed, the "declare none" comment
     names change-manager, and the bound goes from 5 to 4.

   This test is why the PR merges with PR (5). Until change-manager's required-check deletion
   merges, change-manager still declares `launchagent:com.devon.change-window` (at `89f87345`).
   This adapter no longer reports that check, so its evidence is missing, which the container
   reads as not wired.
4. I grepped the repository for other `com.devon.change-window` and window-tied
   `environment: mini` references, leaving out `docs/superpowers/`. I didn't edit these:
   - `docs/security-environment-overview.md:229`: "the executor (`change-window.sh`,
     `com.devon.change-window` @ 04:00)". This text describes the Mac job and goes stale at
     cut-over.
   - `governance-map.toml:243`: the `~/infra-drift/reports` runtime_dir note says it holds the
     "change-window digests". The lane writes its digest to its own pass directory, so the note
     goes stale once the Mac job stops.
   - `governance-map.toml:5` and `registry/profiles/infra-window-v1.yaml:3`, plus
     `registry/README.md:41`, say "4am" or "4AM". These are still true, so I left them.
   - `src/factory_events/adapters/change_manager.py:6,27` and the change-manager adapter and
     registry tests name `change-window-agent`, which is the agent id, not the host. They stay.
   - No other agent file ties `environment: mini` to the window.

## Tests and checks

- `make check` exits 0. ruff found no issues, ruff format reported 68 files already formatted,
  and pyright reported 0 errors and 0 warnings. pytest **collected 388, passed 366, and
  deselected 22** (the deselected tests are the integration marker). The worktree had no
  `.venv`, so I ran `uv venv --clear --python 3.14` and `uv sync` first.
- `tests/test_agent_registry.py::test_real_registry_validates_and_covers_ws11_vocabulary`
  validates the edited agent against the schema, and it passes.
- I rendered `render_ownership(load_map("governance-map.toml"))` in memory, without writing it.
  The infraops line lists the five entries, and an `orchestrator (execute)` line lists the
  launcher.
- `/code-review` (low effort) on the diff returned no findings.

## Files changed

- `governance-map.toml`
- `registry/agents/change-window-agent.yaml`
- `src/factory_events/adapters/mac_conformance.py`
- `tests/test_adapter_mac_conformance.py`
- `docs/superpowers/reports/security-standards-change-window-move-report.md` (this report)

## Self-review

- The diff stays within the four build items. It makes no credential, BWS, Coolify, network,
  `launchctl`, or other-repository change. I read the orchestrator and infraops repositories only
  with `git show origin/main:` and `git ls-tree`.
- The test coverage doesn't shrink: each test that used the removed label now uses a label that
  is still in the list, and one test checks that the removed label isn't reported.

## Concerns

1. **The handoff's premise about the map doesn't hold.** The handoff says to follow "how the
   map already lists orchestrator lane launchers", but the map lists none. Before this change,
   `orchestrator` appeared only as a factory-runner consumer. Adding a `[[repo]]` entry needs no
   schema change (`loader.py` takes any `class`, `lane`, and `owns`), so this isn't the handoff's
   stop point. I added one and reused the map's existing `execute` lane (factory-runner's)
   instead of inventing a lane name. I left `uses_bws` unset so that `make ownership` doesn't
   write a `.bws-secrets.toml` into `~/Projects/orchestrator`. `make strip-stanzas`, the one-shot
   migration, would now also read the orchestrator's `CLAUDE.md`. If HQ wants different
   wording or a different lane for the orchestrator entry, it's a one-line change.
2. **`vps` is the schema's value, but no agent has used it before.** The closest sibling,
   work-carrier, chose `any` because it runs on the Mac and then moves to a container. After
   cut-over, change-window runs in one place, the VPS lane, so `vps` fits better than `any`.
3. **Merge timing.** See build item 3: merge with PR (5), not before it.
4. **Standards coverage.** The handoff's standards don't cover the governance map's lane
   vocabulary. Concern 1 records the choice I made.

## Follow-ups

- After this PR merges, `~/.claude/OWNERSHIP.md` stays stale until someone runs
  `make ownership` (or `make install`) from an up-to-date `main`. Until then, `make verify`
  reports ownership drift.
- `docs/security-environment-overview.md:229` and `governance-map.toml:243` describe the Mac
  job. Update them at cut-over or when rollback ends.
- When rollback ends (options report section 7, item 7), drop
  `change-window.sh (the Mac launcher, kept for rollback)` from infraops' `owns`.

## Standards followed

- **Code Brain 3 (structured JSON logs to stdout, no file logging):** the change adds no
  logging. The adapter change edits only a constant tuple.
- **Code Brain 4 (never silently swallow an exception):** the change adds no `try` or `except`.
- **Code Brain 5 (never log secrets):** the change adds no logging, and the adapter's output
  shape is unchanged.
- **Infra Brain 591, 592, and 593 (no BWS token in tracked files, git history, or inline):** the
  change adds no token or token-shaped string. The BWS write-guard hook didn't trigger on any
  edit, and the session-end scan gate runs at exit.
- **Infra Brain 1032 (`cred.exposure-rotate`):** the change doesn't touch `.cred-consumers.toml`
  or any credential.
- **Infra Brain 212 (HTTPS for public FQDNs):** doesn't apply, because nothing served changes.
