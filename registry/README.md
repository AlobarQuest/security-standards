# Agent-identity registry (WS-1.2)

Versioned YAML identities + authority profiles for every runtime that acts on
Devon's systems. **The registry is a phone book, not a security guard**: it makes
authority legible and auditable; enforcement stays structural (sandboxes,
tool-scoping, change-manager approval). A registry claim can drift from structural
reality — the weekly audit review and later-phase cross-checks are the defense.

## The four-way distinction (companion architecture §3.3)

| Concept | Where it lives |
|---|---|
| **ability** — a tool is technically available | sandboxes / tool-scoping (described here, never implemented here) |
| **policy** — the actor is generally permitted | **this registry** (profile + agent overlay) |
| **task authority** — this package grants use for this work | Phase-2 intent packages (`work_package` / `authority_grant` in events) |
| **approval** — a human approved a sensitive transition | change-manager / Devon |

## Layout

    agents/<agent_id>.yaml     agent-identity/v1  (schema/agent-identity.v1.schema.json)
    profiles/<name>-vN.yaml    authority-profile/v1 (schema/authority-profile.v1.schema.json)
    capabilities.yaml          controlled vocabulary — validator rejects unknown terms

## CLI

    PYTHONPATH=src python3 -m agent_registry validate         # referential validation (also in pytest/CI)
    PYTHONPATH=src python3 -m agent_registry list
    PYTHONPATH=src python3 -m agent_registry show <agent_id>
    PYTHONPATH=src python3 -m agent_registry authority <agent_id> [--json]   # merged effective authority

## Rules

- `factory_events` rejects direct emits whose actor is not a registered agent_id;
  adapters fall back to `claude-code-unattributed` / legacy mappings and preserve
  the raw actor in evidence — attribution degrades, pipelines never break.
- Any registered id validates regardless of `status` (`reserved`/`retired` are
  documentation) — historical replays stay valid forever.
- **Per-provider chore:** every new provider repo adopting `bin/provider-agent`
  needs a `<repo>-provider-agent` entry here, or its events fall back.
- Identity declaration: session-spawning runtimes set `FACTORY_AGENT_ID` (stamped
  into the high-power log by the PostToolUse hook); the two 4AM executors thread
  their actor in-code through the change-manager API.
- `registered_ids()` is process-cached; long-lived consumers must call
  `agent_registry.registry.registered_ids.cache_clear()` after a registry edit
  (the nightly adapter is a fresh process each run and is unaffected).
- change-manager accepts any client-declared actor string unvalidated (M2M
  trust boundary); the registry labels, it does not authenticate — a
  misdeclared actor is caught by audit review, not by the API.
