# WS-1.2 — Agent Identity + Authority Profiles — Design

**Date:** 2026-07-03
**Status:** APPROVED (design brainstormed with Devon 2026-07-03; all sections approved)
**Workstream:** Phase 1 / WS-1.2 of the software-factory master plan
(`~/docs/software-delivery-system/2026-07-02-software-factory-master-plan.md`)
**Companion architecture:** `~/docs/software-delivery-system/2026-06-30-foundation-intent-orchestration-architecture.md` §3.3 (+ §3.5 for the envelope it binds to)
**Supersedes:** the provisional actor vocabulary in `src/factory_events/README.md` (lines 25–38 as of WS-1.1)

## Purpose

Versioned YAML identities per runtime + a validator + a lookup CLI, and wiring so the
existing runtimes and executors DECLARE their identity in the events they emit.
Enforcement stays structural (sandboxing / tool-scoping): **the registry is a phone
book, not a security guard** — it makes authority legible and auditable; it never
grants or removes any capability. The cost of a registry mistake is mislabeled
history, not a breach.

The four-way distinction (companion §3.3) is kept explicit throughout:

| Concept | Where it lives |
|---|---|
| **ability** — a tool is technically available | structural: sandboxes, tool-scoping, withheld tools (the registry *describes* it, never implements it) |
| **policy** — the actor is generally permitted | **this registry** (profiles + agent overlays) |
| **task authority** — this package grants use for this work | Phase-2 intent packages; binds via the envelope's `work_package` / `authority_grant` fields |
| **approval** — a human approved a sensitive transition | change-manager / Devon (unchanged) |

## Decisions made in brainstorming (Devon, 2026-07-03)

1. **Home: security-standards module** (not a new repo). Cohesion with the `emit`
   seam it validates; the governance/control-plane machinery is already here; the
   README vocabulary it supersedes is in-repo. Cross-repo path coupling rejected.
2. **Profiles are first-class documents** — `registry/profiles/*.yaml` define named,
   versioned capability baselines; agents reference one and may overlay
   agent-specific `capabilities` / `prohibited`.
3. **Strict at emit, registry-complete** — `make_event` validates actor against the
   registry; every vocabulary actor becomes a registry entry. Direct emits with an
   unregistered actor hard-fail. Adapters never hard-fail on actor problems
   (graceful fallback, §4 below) so the nightly pipeline cannot be blocked by an
   attribution mistake.
4. **Full executor split this session** — the change-window agent / 4AM security
   executor conflation is resolved end-to-end (infraops-mcp-server client +
   change-manager API), not deferred.
5. **Interactive identity: shell-env default + launcher overrides** —
   `FACTORY_AGENT_ID=claude-code-interactive` in `~/.zshenv`; launchers that spawn
   other runtimes override with their own registered ID; `claude-code-unattributed`
   remains the honest fallback for anything with no var.

## 1. Registry data model

Layout (in security-standards):

    registry/
      agents/<agent_id>.yaml        # one file per identity
      profiles/<name>-v<N>.yaml     # named, versioned authority baselines
      capabilities.yaml             # controlled vocabulary of capability/prohibition terms
    src/agent_registry/             # loader, validator, lookup CLI

**Agent YAML** (`agent-identity/v1`):

```yaml
schema: agent-identity/v1
agent_id: change-window-agent
version: 1                      # bumped on change; git history is the audit trail
status: active                  # active | reserved | retired
runtime: node-executor          # e.g. claude-code, claude-p-headless, node-executor, human
operator: devon
environment: mini               # mini | vps | github-actions | ...
description: one-line role statement
authority_profile: infra-window-v1
capabilities: []                # agent-specific ADDITIONS to the profile
prohibited: []                  # agent-specific additions
```

**Profile YAML**: name + version in the filename; `capabilities` + `prohibited`
lists drawn from `capabilities.yaml`'s controlled vocabulary. Effective authority =
profile baseline merged with agent overlays — so "what may this actor do?" is
mechanically answerable and free-string capability drift is impossible (the
validator rejects unknown terms).

**Initial roster (10 entries, reviewed and approved by Devon):**

| agent_id | what it is |
|---|---|
| `devon` | Human decisions (SSO-traced approvals). runtime: human. |
| `claude-code-interactive` | A Claude Code session launched from a shell on the mini. |
| `claude-code-unattributed` | Honest fallback: a Claude Code session that didn't declare identity. All historical high-power events keep this label. |
| `unknown` | Fallback for unmappable source actors (e.g. change-manager `api`). |
| `drift-reconciler` | change-manager sync/watchdog (deterministic, no LLM). |
| `change-window-agent` | The Sonnet infra-change executor in the 4AM window. |
| `security-executor` | The no-LLM plan-hash-gated security executor (WS-0.7 lane), split from the above. |
| `open-engine-runner` | The WS-0.6 Linear Agent Queue runner. Its packet-internal `agent_code: devon-primary-agent` stays an Open-Engine-internal name (referenced in the YAML description); the registry ID keeps continuity with the reserved WS-1.1 vocabulary. |
| `vps-backup-provider-agent` | The gated `claude -p` provider agent in vps-backup. First instance of the `<repo>-provider-agent` pattern — each future provider repo adds its own entry (a known, accepted per-provider chore; forgetting it degrades that provider's events to the fallback, never breaks anything). |
| `factory-runner` | **status: reserved.** Phase-4 GitHub Actions runner — identity shape defined now, zero wiring until Phase 4. |

Deliberate exclusions (add when they start emitting): the weekly security-scan
LaunchAgent, the nightly factory-events job, vps-backup's nightly run — deterministic
housekeeping that writes to neither audited source today.

Roster supersession is one-for-one with the WS-1.1 provisional vocabulary, so no
historical event becomes orphaned.

## 2. Validator + lookup CLI

New zero-install package `src/agent_registry/` (sibling of `factory_events`;
`PYTHONPATH=src python3 -m agent_registry <cmd>`; deps: PyYAML for the registry
loader + the `jsonschema` already used by `factory_events`, same venv pattern).
Subcommands:

- `validate` — schema-valid YAML; unique agent_ids; every `authority_profile`
  reference resolves; every capability/prohibition term exists in
  `capabilities.yaml`; no agent both grants and prohibits the same term.
  Wired into repo CI and `make check` — a broken registry cannot merge.
- `list` — all agents with status + profile.
- `show <agent_id>` — one agent's full record.
- `authority <agent_id>` — merged effective authority (profile + overlays), text or
  JSON. This is the mechanical answer to "what may this actor do?".

**Status rule:** any registered ID validates regardless of `status` —
`reserved`/`retired` are documentation, not gates. Historical replays
(`ship --rebuild`) must stay valid forever.

## 3. Emit-time validation (the strict gate)

Enforcement point: `factory_events` `envelope.py:make_event` — the single chokepoint
every event path (CLI `emit` and both adapters) flows through. Registry lookup is
lazy-loaded from the in-repo `registry/` directory (no new runtime dependency for
paths that never construct events).

- **Direct emits** (`emit --actor X`): unregistered `X` → hard error. The caller
  made a mistake and must see it.
- **Adapters** (nightly 03:30 job): never hard-fail on actor problems — see §4.
  A typo'd env var or missing provider YAML degrades attribution gracefully; it can
  never break the chain, trip the Healthchecks dead-man, or block a rebuild.

The envelope JSON Schema's `actor` field stays a free string (`minLength: 1`) —
registry validation is a library-layer check, not a schema change, so `factory-event/v1`
needs no version bump and historical events remain schema-valid.

## 4. Wiring — five seams

Identity is *declared*; no seam changes what any runtime can do.

**Seam 1 — high-power hook** (`~/.claude/hooks/high-power-audit-log.sh:37-39`):
stamp `actor` from `$FACTORY_AGENT_ID` into the JSONL record (field absent when
unset). **Ownership note (found in exploration):** this hook is a *hosted* artifact
of the `~/.claude` control-plane repo (`governance-map.toml` `[[hosted]]`), NOT
deployed by security-standards' `make install` — the edit is committed in the
control-plane repo directly. Adapter change
(`src/factory_events/adapters/high_power.py:85,97`, which currently hardcode the
actor): read the stamped field; registered → use it; unregistered/absent →
`claude-code-unattributed` (raw value preserved in the evidence source-record,
per the WS-1.1 honest-mapping principle).

**Seam 2 — interactive sessions:** `FACTORY_AGENT_ID=claude-code-interactive` in
`~/.zshenv` (GUI-launched apps convention per Projects CLAUDE.md). Launchers
override; no var → fallback.

**Seam 3 — provider agents** (`provider-agent-pattern` repo, propagated to the
vps-backup + infraops copies of `bin/provider-agent`): set
`FACTORY_AGENT_ID=<repo>-provider-agent` in the child env the wrapper already
builds (vps-backup `bin/provider-agent:174`, currently sets only the depth guard).
Every high-power record from a spawned provider session then carries the provider's
name — one line, ties seam 3 to seam 1.

**Seam 4 — Open Engine runner** (`~/.config/open-engine/runner-prompt.md`): add
protocol instructions to emit `factory_events emit --actor open-engine-runner` at
the claim and done points; launcher sets the env var too. First consumer of the
direct-emit seam. (The runner is currently manual; the instruction travels with the
prompt when it's scheduled.)

**Seam 5 — the executor split** (resolves conflation #2):

- Today: both 4AM executors call change-manager through the same client
  (infraops-mcp-server `src/change-manager/api-client.ts:66-71`) whose claim/outcome
  bodies carry **no actor**; change-manager stamps `ChangeEvent.actor="executor"`
  server-side (`app/api.py:137,171`); the adapter maps `executor →
  change-window-agent` for both.
- Change: the two window entry points (`change-mgr-cli.ts:66 doRunWindow`, `:85
  doRunSecurityWindow`) construct their client with their own actor
  (`change-window-agent` / `security-executor`); the client sends it in claim +
  outcome bodies; change-manager's endpoints + `OutcomeIn` schema accept an optional
  `actor`, **defaulting to `"executor"` when absent** (old clients keep working; the
  `ChangeEvent.actor` column already exists — no DB migration).
- Adapter (`src/factory_events/adapters/change_manager.py:27,53-58`): registered
  actor on the record → pass through; keep the legacy `executor →
  change-window-agent` mapping for historical records.
- A single env var cannot do this split — both executors share one 4AM process env;
  identity must be set in-code at the two entry points.

**Seam 0 (definition only) — factory-runner:** registry entry with
`status: reserved`; no wiring (Phase 4).

## 5. Documentation supersession

- `src/factory_events/README.md` "Provisional actor vocabulary" section → replaced
  by a pointer to `registry/` + the lookup CLI (exit criterion).
- New `registry/README.md`: the four-way distinction table, the roster, the
  per-provider chore, the drift caveat (the YAML describes policy and can drift
  from structural reality — the weekly audit review and later-phase cross-checks
  are the defense; the registry is legibility, not enforcement).

## 6. Testing

- **agent_registry pytest:** schema validation, uniqueness, reference resolution,
  vocabulary enforcement, grant/prohibit overlap, merge logic (`authority`), and
  "all real registry YAML validates."
- **factory_events pytest:** registered actor passes `make_event`; unregistered
  direct emit fails; high-power adapter uses stamped registered actor, falls back
  on unregistered/absent (raw preserved); change-manager adapter pass-through +
  legacy mapping.
- **change-manager:** accept-actor with default `"executor"`; existing suite green.
- **infraops-mcp-server:** client threading; existing 406-test suite stays green.
- **CI:** `agent_registry validate` joins security-standards CI + `make check`.

## 7. End-to-end verification (before /save)

1. `validate` green on the real registry.
2. Direct `emit --actor claude-code-interactive` lands in the chain;
   `verify --against-anchor` still passes.
3. A real provider-agent invocation produces a high-power record carrying
   `vps-backup-provider-agent`, and `adapt` maps it through.
4. A stamped-but-unregistered actor demonstrably falls back (no `adapt` failure).
5. Executor split: proven by tests at build time; the first post-merge 4AM window
   is the live evidence (day-2 pattern, same as WS-1.1's anchor check).

## 8. Deliverables

| Repo | Change | Lane |
|---|---|---|
| security-standards | `registry/` + `src/agent_registry/` + adapter changes + README supersession + CI | PR, Devon merges |
| infraops-mcp-server | client actor threading (2 entry points, client bodies) | PR, Devon merges |
| change-manager | claim/outcome accept optional `actor` (default `executor`) | PR, Devon merges; deploys via normal CI on merge |
| provider-agent-pattern | wrapper sets `FACTORY_AGENT_ID` (propagate to vps-backup, infraops copies) | PR, Devon merges |
| ~/.claude (control-plane) | hook stamps `actor` from env var | direct commit in control-plane repo |
| config edits | `~/.zshenv` line; open-engine runner prompt | direct edits |

## Exit criteria (kickoff → this design)

- Identities + authority profiles exist and validate ✓ (§1, §2)
- "What may this actor do?" mechanically answerable ✓ (`authority`, §2)
- Named runtimes/executors declare registry identities in emitted events ✓ (§4;
  factory-runner deliberately reserved)
- WS-1.1 README provisional-vocabulary section superseded ✓ (§5)
