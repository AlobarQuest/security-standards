# WS-1.2 Agent Identity + Authority Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Versioned YAML agent identities + authority profiles with a validator and lookup CLI in security-standards, plus wiring so every existing runtime/executor declares a registered identity in the events it emits.

**Architecture:** New `registry/` data dir + `src/agent_registry/` package (sibling of `factory_events`) in security-standards; `factory_events.envelope.make_event` gains a strict registry gate; adapters pre-map to registered IDs (never hard-fail); identity is declared via `FACTORY_AGENT_ID` env var for session-spawning runtimes and via in-code actor threading for the two 4AM executors (client → change-manager API → `ChangeEvent.actor`).

**Tech Stack:** Python 3.12, PyYAML, jsonschema (existing), pytest; TypeScript/vitest (infraops-mcp-server); FastAPI/pydantic (change-manager); bash/jq (control-plane hook).

**Spec:** `docs/superpowers/specs/2026-07-03-ws12-agent-registry-design.md` (approved). Read it before starting any task.

## Global Constraints

- Registry is **legibility, not enforcement** — no task may add capability enforcement.
- Direct emits with unregistered actors **hard-fail**; adapters **never hard-fail** on actor problems (fallback + raw preserved in evidence).
- Any registered ID validates regardless of `status` (reserved/retired are documentation).
- The envelope JSON Schema (`factory-event/v1`) is NOT changed — registry validation is library-layer.
- change-manager API stays backward compatible: absent actor ⇒ `"executor"`; the claim endpoint must keep accepting body-less POSTs.
- infraops-mcp-server: `dist/` is tracked — every `src/` change must `npm run build` and commit `dist/` in the same commit.
- PRs are opened but NEVER merged — Devon merges on explicit signal. Merge order at that point: change-manager before infraops.
- Never write a BWS token or any live secret into any file (write-guard will deny).
- Python: follow `~/Developer/code-standards/STANDARDS.md`; repo lint is ruff (line-length 100).
- Working directories vary per task — each task states its repo and branch. security-standards work happens on the existing branch `feat/ws12-agent-registry`.

## Roster note (flagged for Devon at PR review)

The approved 10-actor roster gains an 11th entry discovered during planning:
`infraops-mcp-server-provider-agent`. infraops-mcp-server ships the same
`bin/provider-agent` wrapper as vps-backup (its CLAUDE.md documents it); once the
wrapper stamps `FACTORY_AGENT_ID=<repo>-provider-agent` (Task 10), infraops provider
sessions would emit an unregistered ID and silently degrade to the fallback.
Registering both providers is registry-complete and costs one YAML file.

---

### Task 1: agent_registry loader + validator (TDD, fixtures)

**Repo:** `~/Projects/security-standards`, branch `feat/ws12-agent-registry`

**Files:**
- Modify: `pyproject.toml` (add PyYAML to `dev` and `events` extras)
- Create: `schema/agent-identity.v1.schema.json`
- Create: `schema/authority-profile.v1.schema.json`
- Create: `src/agent_registry/__init__.py`
- Create: `src/agent_registry/registry.py`
- Test: `tests/test_agent_registry.py`

**Interfaces:**
- Produces (used by Tasks 3–6):
  - `agent_registry.registry.validate_registry(registry_dir: Path | None = None) -> list[str]` — empty list = valid
  - `agent_registry.registry.load_agents(registry_dir=None) -> dict[str, dict]` (key = agent_id)
  - `agent_registry.registry.load_profiles(registry_dir=None) -> dict[str, dict]` (key = profile name)
  - `agent_registry.registry.registered_ids() -> frozenset[str]` (default dir, cached)
  - `agent_registry.registry.effective_authority(agent_id: str, registry_dir=None) -> dict` with keys `agent_id, status, authority_profile, capabilities (sorted list), prohibited (sorted list)`
  - `agent_registry.registry.RegistryError(ValueError)`

- [ ] **Step 1: Add PyYAML to pyproject extras**

In `pyproject.toml` change:

```toml
[project.optional-dependencies]
dev = ["pytest>=7.0", "jsonschema>=4.21", "pyyaml>=6.0"]
events = ["jsonschema>=4.21", "psycopg[binary]>=3.1", "pyyaml>=6.0"]
```

Install into the events venv (the runtime the mini uses) and verify:

```bash
cd ~/Projects/security-standards
.venv-events/bin/pip install 'pyyaml>=6.0'
.venv-events/bin/python -c "import yaml; print(yaml.__version__)"
```

Expected: a 6.x version prints.

- [ ] **Step 2: Write the two JSON Schemas**

`schema/agent-identity.v1.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "agent-identity.v1.schema.json",
  "title": "agent-identity/v1",
  "type": "object",
  "required": ["schema", "agent_id", "version", "status", "runtime", "operator",
               "environment", "description", "authority_profile", "capabilities", "prohibited"],
  "additionalProperties": false,
  "properties": {
    "schema": {"const": "agent-identity/v1"},
    "agent_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*[a-z0-9]$"},
    "version": {"type": "integer", "minimum": 1},
    "status": {"enum": ["active", "reserved", "retired"]},
    "runtime": {"enum": ["claude-code", "claude-p-headless", "node-executor", "github-actions", "human", "unknown"]},
    "operator": {"type": "string", "minLength": 1},
    "environment": {"enum": ["mini", "vps", "github-actions", "any"]},
    "description": {"type": "string", "minLength": 1},
    "authority_profile": {"type": "string", "pattern": "^[a-z0-9-]+-v[0-9]+$"},
    "capabilities": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
    "prohibited": {"type": "array", "items": {"type": "string"}, "uniqueItems": true}
  }
}
```

`schema/authority-profile.v1.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "authority-profile.v1.schema.json",
  "title": "authority-profile/v1",
  "type": "object",
  "required": ["schema", "profile", "description", "capabilities", "prohibited"],
  "additionalProperties": false,
  "properties": {
    "schema": {"const": "authority-profile/v1"},
    "profile": {"type": "string", "pattern": "^[a-z0-9-]+-v[0-9]+$"},
    "description": {"type": "string", "minLength": 1},
    "capabilities": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
    "prohibited": {"type": "array", "items": {"type": "string"}, "uniqueItems": true}
  }
}
```

- [ ] **Step 3: Write the failing tests**

`tests/test_agent_registry.py` (fixture registries built in tmp_path; mirror the
style of `tests/test_factory_envelope.py`):

```python
"""agent_registry: load, validate, effective authority."""

import pytest
import yaml

from agent_registry.registry import (
    RegistryError,
    effective_authority,
    load_agents,
    load_profiles,
    validate_registry,
)

VOCAB = {"schema": "capability-vocabulary/v1",
         "terms": {"repository_read": "read repo files", "repository_write": "write repo files",
                   "merge_to_main": "merge PRs to a default branch"}}
PROFILE = {"schema": "authority-profile/v1", "profile": "test-base-v1",
           "description": "test baseline", "capabilities": ["repository_read"], "prohibited": ["merge_to_main"]}
AGENT = {"schema": "agent-identity/v1", "agent_id": "test-agent", "version": 1,
         "status": "active", "runtime": "claude-code", "operator": "devon",
         "environment": "mini", "description": "a test agent",
         "authority_profile": "test-base-v1", "capabilities": ["repository_write"], "prohibited": []}


def write_registry(root, vocab=VOCAB, profiles=(PROFILE,), agents=(AGENT,)):
    (root / "agents").mkdir(parents=True)
    (root / "profiles").mkdir()
    (root / "capabilities.yaml").write_text(yaml.safe_dump(vocab))
    for p in profiles:
        (root / "profiles" / f"{p['profile']}.yaml").write_text(yaml.safe_dump(p))
    for a in agents:
        (root / "agents" / f"{a['agent_id']}.yaml").write_text(yaml.safe_dump(a))
    return root


def test_valid_registry_has_no_errors(tmp_path):
    assert validate_registry(write_registry(tmp_path / "reg")) == []


def test_load_agents_and_profiles_key_by_id(tmp_path):
    reg = write_registry(tmp_path / "reg")
    assert list(load_agents(reg)) == ["test-agent"]
    assert list(load_profiles(reg)) == ["test-base-v1"]


def test_schema_violation_reported(tmp_path):
    bad = {**AGENT, "status": "bogus"}
    errors = validate_registry(write_registry(tmp_path / "reg", agents=(bad,)))
    assert len(errors) == 1 and "status" in errors[0]


def test_unresolved_profile_reference_reported(tmp_path):
    bad = {**AGENT, "authority_profile": "missing-v1"}
    errors = validate_registry(write_registry(tmp_path / "reg", agents=(bad,)))
    assert errors and "missing-v1" in errors[0]


def test_unknown_capability_term_reported(tmp_path):
    bad = {**AGENT, "capabilities": ["invent_time_travel"]}
    errors = validate_registry(write_registry(tmp_path / "reg", agents=(bad,)))
    assert errors and "invent_time_travel" in errors[0]


def test_grant_prohibit_overlap_reported(tmp_path):
    bad = {**AGENT, "capabilities": ["merge_to_main"]}  # profile prohibits it
    errors = validate_registry(write_registry(tmp_path / "reg", agents=(bad,)))
    assert errors and "merge_to_main" in errors[0]


def test_filename_must_match_agent_id(tmp_path):
    reg = write_registry(tmp_path / "reg")
    (reg / "agents" / "wrong-name.yaml").write_text(yaml.safe_dump(AGENT))
    errors = validate_registry(reg)
    assert errors and "wrong-name" in errors[0]


def test_effective_authority_merges_profile_and_overlay(tmp_path):
    reg = write_registry(tmp_path / "reg")
    auth = effective_authority("test-agent", reg)
    assert auth["capabilities"] == ["repository_read", "repository_write"]
    assert auth["prohibited"] == ["merge_to_main"]
    assert auth["authority_profile"] == "test-base-v1"


def test_effective_authority_unknown_agent_raises(tmp_path):
    reg = write_registry(tmp_path / "reg")
    with pytest.raises(RegistryError):
        effective_authority("nobody", reg)
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
cd ~/Projects/security-standards
.venv-events/bin/python -m pytest tests/test_agent_registry.py -v
```

Expected: FAIL / errors — `ModuleNotFoundError: No module named 'agent_registry'`.

- [ ] **Step 5: Implement the package**

`src/agent_registry/__init__.py`:

```python
"""Agent-identity registry (WS-1.2): versioned YAML identities + authority profiles.

The registry is legibility, not enforcement — see registry/README.md.
"""
```

`src/agent_registry/registry.py`:

```python
"""Load + validate registry/ YAML; answer effective authority per agent.

registry/agents/<agent_id>.yaml   agent-identity/v1 (schema/agent-identity.v1.schema.json)
registry/profiles/<name>.yaml     authority-profile/v1 (schema/authority-profile.v1.schema.json)
registry/capabilities.yaml        controlled vocabulary of capability terms
"""

import json
from functools import cache
from pathlib import Path

import jsonschema
import yaml

_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = _ROOT / "registry"
_AGENT_SCHEMA_PATH = _ROOT / "schema" / "agent-identity.v1.schema.json"
_PROFILE_SCHEMA_PATH = _ROOT / "schema" / "authority-profile.v1.schema.json"


class RegistryError(ValueError):
    """Registry is malformed or the agent_id is unknown."""


@cache
def _validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(json.loads(schema_path.read_text()))


def _load_yaml(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict):
        raise RegistryError(f"{path}: not a YAML mapping")
    return doc


def load_vocabulary(registry_dir: Path | None = None) -> dict[str, str]:
    doc = _load_yaml((registry_dir or REGISTRY_DIR) / "capabilities.yaml")
    return doc.get("terms", {})


def load_profiles(registry_dir: Path | None = None) -> dict[str, dict]:
    base = registry_dir or REGISTRY_DIR
    return {p.stem: _load_yaml(p) for p in sorted((base / "profiles").glob("*.yaml"))}


def load_agents(registry_dir: Path | None = None) -> dict[str, dict]:
    base = registry_dir or REGISTRY_DIR
    return {p.stem: _load_yaml(p) for p in sorted((base / "agents").glob("*.yaml"))}


def _schema_errors(doc: dict, schema_path: Path, where: str) -> list[str]:
    errors = sorted(_validator(schema_path).iter_errors(doc), key=lambda e: list(e.absolute_path))
    return [f"{where}: {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in errors]


def validate_registry(registry_dir: Path | None = None) -> list[str]:
    """Full referential validation; returns [] when the registry is valid."""
    base = registry_dir or REGISTRY_DIR
    errors: list[str] = []
    try:
        vocabulary = set(load_vocabulary(base))
        profiles = load_profiles(base)
        agents = load_agents(base)
    except (RegistryError, OSError, yaml.YAMLError) as exc:
        return [str(exc)]

    for stem, profile in profiles.items():
        errors += _schema_errors(profile, _PROFILE_SCHEMA_PATH, f"profiles/{stem}.yaml")
        if profile.get("profile") != stem:
            errors.append(f"profiles/{stem}.yaml: filename does not match profile {profile.get('profile')!r}")
        for field in ("capabilities", "prohibited"):
            for term in profile.get(field, []):
                if term not in vocabulary:
                    errors.append(f"profiles/{stem}.yaml: unknown {field} term {term!r}")

    for stem, agent in agents.items():
        where = f"agents/{stem}.yaml"
        errors += _schema_errors(agent, _AGENT_SCHEMA_PATH, where)
        if agent.get("agent_id") != stem:
            errors.append(f"{where}: filename does not match agent_id {agent.get('agent_id')!r}")
        profile_name = agent.get("authority_profile")
        if profile_name and profile_name not in profiles:
            errors.append(f"{where}: authority_profile {profile_name!r} does not resolve")
        for field in ("capabilities", "prohibited"):
            for term in agent.get(field, []):
                if term not in vocabulary:
                    errors.append(f"{where}: unknown {field} term {term!r}")
        profile = profiles.get(profile_name, {})
        granted = set(agent.get("capabilities", [])) | set(profile.get("capabilities", []))
        denied = set(agent.get("prohibited", [])) | set(profile.get("prohibited", []))
        for term in sorted(granted & denied):
            errors.append(f"{where}: {term!r} is both granted and prohibited")
    return errors


@cache
def registered_ids() -> frozenset[str]:
    """Agent ids in the default registry (cached; any status counts)."""
    return frozenset(load_agents())


def effective_authority(agent_id: str, registry_dir: Path | None = None) -> dict:
    """Merged profile + agent overlay: the mechanical 'what may this actor do?'."""
    agents = load_agents(registry_dir)
    if agent_id not in agents:
        raise RegistryError(f"unknown agent_id {agent_id!r}")
    agent = agents[agent_id]
    profile = load_profiles(registry_dir).get(agent["authority_profile"], {})
    return {
        "agent_id": agent_id,
        "status": agent["status"],
        "authority_profile": agent["authority_profile"],
        "capabilities": sorted(set(agent["capabilities"]) | set(profile.get("capabilities", []))),
        "prohibited": sorted(set(agent["prohibited"]) | set(profile.get("prohibited", []))),
    }
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
.venv-events/bin/python -m pytest tests/test_agent_registry.py -v
```

Expected: 9 passed.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml schema/agent-identity.v1.schema.json schema/authority-profile.v1.schema.json src/agent_registry/ tests/test_agent_registry.py
git commit -m "feat(agent-registry): loader + referential validator (WS-1.2)"
```

---

### Task 2: Real registry data + README

**Repo:** `~/Projects/security-standards`, branch `feat/ws12-agent-registry`

**Files:**
- Create: `registry/capabilities.yaml`
- Create: `registry/profiles/` — 9 files listed below
- Create: `registry/agents/` — 11 files listed below
- Create: `registry/README.md`
- Test: append one test to `tests/test_agent_registry.py`

**Interfaces:**
- Consumes: `validate_registry` from Task 1.
- Produces: the canonical registry content every later task's actors must exist in. Exact agent_ids: `devon`, `claude-code-interactive`, `claude-code-unattributed`, `unknown`, `drift-reconciler`, `change-window-agent`, `security-executor`, `open-engine-runner`, `vps-backup-provider-agent`, `infraops-mcp-server-provider-agent`, `factory-runner`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_registry.py`:

```python
def test_real_registry_validates_and_covers_ws11_vocabulary():
    assert validate_registry() == []
    from agent_registry.registry import registered_ids
    # one-for-one supersession of the WS-1.1 provisional vocabulary
    assert {"devon", "claude-code-unattributed", "change-window-agent", "security-executor",
            "drift-reconciler", "open-engine-runner", "unknown"} <= registered_ids()
```

Run: `.venv-events/bin/python -m pytest tests/test_agent_registry.py::test_real_registry_validates_and_covers_ws11_vocabulary -v`
Expected: FAIL (no `registry/` directory yet).

- [ ] **Step 2: Write `registry/capabilities.yaml`**

```yaml
schema: capability-vocabulary/v1
terms:
  repository_read: read code/files in a repo working tree
  repository_write: create or modify files and commits in a repo working tree
  test_execution: run test suites and linters
  pr_open: open pull requests (never merge)
  merge_to_main: merge PRs / push to a default branch
  event_emit: append events to the factory-events store
  infra_mutation: mutate live infrastructure (Coolify, VPS, DNS, Hetzner) via gated tools
  drift_detection: scan live infra/config and detect drift against standards
  change_filing: file change items into change-manager for approval
  change_approval: approve or reject change-manager items
  secret_read: read secrets from BWS/Keychain at runtime
  secret_write: write or update secrets in BWS
  credential_create: mint new credentials at a provider console
  credential_revoke: revoke credentials at a provider console
  email_send: send outbound email
  outward_publish: publish outward-facing content (listings, posts, public docs)
  task_claim: claim work items from a queue (Linear Agent Queue, orchestrator)
```

- [ ] **Step 3: Write the 9 profile files**

`registry/profiles/human-operator-v1.yaml`:

```yaml
schema: authority-profile/v1
profile: human-operator-v1
description: Devon — the human root of authority; approvals, merges, credential lifecycle.
capabilities:
  - repository_read
  - repository_write
  - test_execution
  - pr_open
  - merge_to_main
  - event_emit
  - infra_mutation
  - drift_detection
  - change_filing
  - change_approval
  - secret_read
  - secret_write
  - credential_create
  - credential_revoke
  - email_send
  - outward_publish
  - task_claim
prohibited: []
```

`registry/profiles/interactive-dev-v1.yaml`:

```yaml
schema: authority-profile/v1
profile: interactive-dev-v1
description: Claude Code sessions on the mini — full dev loop + gated infra tools; merges and approvals stay with Devon.
capabilities:
  - repository_read
  - repository_write
  - test_execution
  - pr_open
  - event_emit
  - infra_mutation
  - drift_detection
  - change_filing
  - secret_read
  - secret_write
  - email_send
prohibited:
  - merge_to_main
  - change_approval
  - credential_create
  - credential_revoke
```

`registry/profiles/none-v1.yaml`:

```yaml
schema: authority-profile/v1
profile: none-v1
description: No authority claims — label-only identities (unmappable source actors).
capabilities: []
prohibited: []
```

`registry/profiles/drift-sync-v1.yaml`:

```yaml
schema: authority-profile/v1
profile: drift-sync-v1
description: Deterministic drift detection + filing; observes and proposes, never mutates.
capabilities:
  - drift_detection
  - change_filing
  - email_send
  - event_emit
prohibited:
  - infra_mutation
  - merge_to_main
  - change_approval
  - secret_write
  - credential_create
  - credential_revoke
```

`registry/profiles/infra-window-v1.yaml`:

```yaml
schema: authority-profile/v1
profile: infra-window-v1
description: 4AM change-window execution of Devon-approved infra changes; approval and credential lifecycle excluded.
capabilities:
  - infra_mutation
  - event_emit
prohibited:
  - repository_write
  - merge_to_main
  - change_approval
  - credential_create
  - credential_revoke
  - outward_publish
```

`registry/profiles/security-window-v1.yaml`:

```yaml
schema: authority-profile/v1
profile: security-window-v1
description: Plan-hash-gated security execution (WS-0.7 rotation lane) — BWS updates + verification; create/revoke stay with Devon.
capabilities:
  - infra_mutation
  - secret_read
  - secret_write
  - email_send
  - event_emit
prohibited:
  - repository_write
  - merge_to_main
  - change_approval
  - credential_create
  - credential_revoke
  - outward_publish
```

`registry/profiles/agent-queue-v1.yaml`:

```yaml
schema: authority-profile/v1
profile: agent-queue-v1
description: Open Engine pilot runner — proposal-only work off the Linear Agent Queue; nothing outward, nothing infra.
capabilities:
  - repository_read
  - task_claim
  - event_emit
prohibited:
  - infra_mutation
  - merge_to_main
  - change_approval
  - secret_write
  - credential_create
  - credential_revoke
  - outward_publish
```

`registry/profiles/provider-agent-v1.yaml`:

```yaml
schema: authority-profile/v1
profile: provider-agent-v1
description: Gated claude -p provider agents — extend their own repo on review branches; must not touch live infrastructure.
capabilities:
  - repository_read
  - repository_write
  - test_execution
  - event_emit
prohibited:
  - infra_mutation
  - merge_to_main
  - change_approval
  - secret_write
  - credential_create
  - credential_revoke
  - outward_publish
```

`registry/profiles/factory-runner-v1.yaml`:

```yaml
schema: authority-profile/v1
profile: factory-runner-v1
description: Phase-4 sandboxed GitHub Actions runner — tool-scoped work units ending in a PR; reserved until Phase 4.
capabilities:
  - repository_read
  - repository_write
  - test_execution
  - pr_open
  - event_emit
prohibited:
  - infra_mutation
  - merge_to_main
  - change_approval
  - secret_write
  - credential_create
  - credential_revoke
  - outward_publish
```

- [ ] **Step 4: Write the 11 agent files**

`registry/agents/devon.yaml`:

```yaml
schema: agent-identity/v1
agent_id: devon
version: 1
status: active
runtime: human
operator: devon
environment: any
description: Devon Watkins — solo operator; any SSO email maps here. Human decisions only.
authority_profile: human-operator-v1
capabilities: []
prohibited: []
```

`registry/agents/claude-code-interactive.yaml`:

```yaml
schema: agent-identity/v1
agent_id: claude-code-interactive
version: 1
status: active
runtime: claude-code
operator: devon
environment: mini
description: A Claude Code session launched from Devon's shell (FACTORY_AGENT_ID set in ~/.zshenv). Identifies the launch channel, not the work done.
authority_profile: interactive-dev-v1
capabilities: []
prohibited: []
```

`registry/agents/claude-code-unattributed.yaml`:

```yaml
schema: agent-identity/v1
agent_id: claude-code-unattributed
version: 1
status: active
runtime: claude-code
operator: devon
environment: mini
description: Honest fallback — a Claude Code session on the mini that declared no identity. All pre-WS-1.2 high-power events carry this label; session UUID in correlation_id.
authority_profile: interactive-dev-v1
capabilities: []
prohibited: []
```

`registry/agents/unknown.yaml`:

```yaml
schema: agent-identity/v1
agent_id: unknown
version: 1
status: active
runtime: unknown
operator: devon
environment: any
description: Fallback for source actors that cannot be mapped (e.g. change-manager's generic api actor). A label, not a runtime.
authority_profile: none-v1
capabilities: []
prohibited: []
```

`registry/agents/drift-reconciler.yaml`:

```yaml
schema: agent-identity/v1
agent_id: drift-reconciler
version: 1
status: active
runtime: node-executor
operator: devon
environment: mini
description: change-manager sync/watchdog — deterministic drift detection and item filing (no LLM).
authority_profile: drift-sync-v1
capabilities: []
prohibited: []
```

`registry/agents/change-window-agent.yaml`:

```yaml
schema: agent-identity/v1
agent_id: change-window-agent
version: 1
status: active
runtime: node-executor
operator: devon
environment: mini
description: The Sonnet tool-use agent executing Devon-approved Coolify changes in the 4AM window (curated tool loop, pre-validate, post-verify-or-revert). Until WS-1.2, change-manager events conflated this with security-executor.
authority_profile: infra-window-v1
capabilities: []
prohibited: []
```

`registry/agents/security-executor.yaml`:

```yaml
schema: agent-identity/v1
agent_id: security-executor
version: 1
status: active
runtime: node-executor
operator: devon
environment: mini
description: The no-LLM, plan-hash-gated executor for approved security changes (WS-0.7 credential-rotation lane), sharing the 4AM window process with change-window-agent.
authority_profile: security-window-v1
capabilities: []
prohibited: []
```

`registry/agents/open-engine-runner.yaml`:

```yaml
schema: agent-identity/v1
agent_id: open-engine-runner
version: 1
status: active
runtime: claude-code
operator: devon
environment: mini
description: WS-0.6 Open Engine pilot runner working the Linear Agent Queue (one task per run). Packet-internal agent_code devon-primary-agent maps to this registry id.
authority_profile: agent-queue-v1
capabilities: []
prohibited: []
```

`registry/agents/vps-backup-provider-agent.yaml`:

```yaml
schema: agent-identity/v1
agent_id: vps-backup-provider-agent
version: 1
status: active
runtime: claude-p-headless
operator: devon
environment: mini
description: The gated provider agent inside vps-backup (bin/provider-agent) — extends the backup system on review branches for consumer agents.
authority_profile: provider-agent-v1
capabilities: []
prohibited: []
```

`registry/agents/infraops-mcp-server-provider-agent.yaml`:

```yaml
schema: agent-identity/v1
agent_id: infraops-mcp-server-provider-agent
version: 1
status: active
runtime: claude-p-headless
operator: devon
environment: mini
description: The gated provider agent inside infraops-mcp-server (bin/provider-agent) — adds/extends MCP tools on review branches; must not run against live infrastructure.
authority_profile: provider-agent-v1
capabilities: []
prohibited: []
```

`registry/agents/factory-runner.yaml`:

```yaml
schema: agent-identity/v1
agent_id: factory-runner
version: 1
status: reserved
runtime: github-actions
operator: devon
environment: github-actions
description: Phase-4 factory runner (generalized conformance runner) — identity shape defined by WS-1.2; wiring lands with Phase 4 (master plan WS-4.1).
authority_profile: factory-runner-v1
capabilities: []
prohibited: []
```

- [ ] **Step 5: Write `registry/README.md`**

```markdown
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
```

- [ ] **Step 6: Run the tests**

```bash
.venv-events/bin/python -m pytest tests/test_agent_registry.py -v
```

Expected: 10 passed (including the real-registry test).

- [ ] **Step 7: Commit**

```bash
git add registry/ tests/test_agent_registry.py
git commit -m "feat(agent-registry): canonical registry data — 11 agents, 9 profiles, vocabulary (WS-1.2)"
```

---

### Task 3: Lookup CLI

**Repo:** `~/Projects/security-standards`, branch `feat/ws12-agent-registry`

**Files:**
- Create: `src/agent_registry/cli.py`
- Create: `src/agent_registry/__main__.py`
- Test: `tests/test_agent_registry_cli.py`

**Interfaces:**
- Consumes: Task 1 functions.
- Produces: `python3 -m agent_registry {validate,list,show,authority}`; `validate` exits 1 with one error per line on invalid, prints `registry ok: N agents, M profiles` on success; `authority --json` prints the `effective_authority` dict as JSON.

- [ ] **Step 1: Write the failing tests**

`tests/test_agent_registry_cli.py` (mirror `tests/test_factory_cli.py` style — invoke `cli.main([...])` and capture with `capsys`):

```python
"""agent_registry CLI: validate / list / show / authority."""

import json

import pytest

from agent_registry import cli


def test_validate_ok_on_real_registry(capsys):
    assert cli.main(["validate"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("registry ok:")


def test_list_names_all_agents(capsys):
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "change-window-agent" in out and "factory-runner" in out


def test_show_prints_record(capsys):
    assert cli.main(["show", "security-executor"]) == 0
    out = capsys.readouterr().out
    assert "security-window-v1" in out


def test_authority_json_merges(capsys):
    assert cli.main(["authority", "security-executor", "--json"]) == 0
    auth = json.loads(capsys.readouterr().out)
    assert "secret_write" in auth["capabilities"]
    assert "credential_revoke" in auth["prohibited"]


def test_unknown_agent_exits_nonzero(capsys):
    assert cli.main(["show", "nobody"]) == 1
```

Run: `.venv-events/bin/python -m pytest tests/test_agent_registry_cli.py -v`
Expected: FAIL — `cannot import name 'cli'`.

- [ ] **Step 2: Implement**

`src/agent_registry/cli.py`:

```python
"""CLI: validate / list / show / authority."""

import argparse
import json

import yaml

from agent_registry.registry import (
    RegistryError,
    effective_authority,
    load_agents,
    load_profiles,
    validate_registry,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_registry", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="referential validation of registry/")
    sub.add_parser("list", help="all agents with status + profile")
    for name in ("show", "authority"):
        p = sub.add_parser(name)
        p.add_argument("agent_id")
        if name == "authority":
            p.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        errors = validate_registry()
        for error in errors:
            print(error)
        if errors:
            return 1
        print(f"registry ok: {len(load_agents())} agents, {len(load_profiles())} profiles")
        return 0

    if args.cmd == "list":
        for agent_id, agent in load_agents().items():
            print(f"{agent_id}\t{agent['status']}\t{agent['authority_profile']}")
        return 0

    try:
        if args.cmd == "show":
            agent = load_agents().get(args.agent_id)
            if agent is None:
                raise RegistryError(f"unknown agent_id {args.agent_id!r}")
            print(yaml.safe_dump(agent, sort_keys=False), end="")
            return 0
        auth = effective_authority(args.agent_id)
        print(json.dumps(auth, indent=None if args.as_json else 2))
        return 0
    except RegistryError as exc:
        print(f"error: {exc}")
        return 1
```

`src/agent_registry/__main__.py`:

```python
import sys

from agent_registry.cli import main

sys.exit(main())
```

- [ ] **Step 3: Run tests**

```bash
.venv-events/bin/python -m pytest tests/test_agent_registry_cli.py -v
```

Expected: 5 passed. Also spot-check by hand:

```bash
PYTHONPATH=src .venv-events/bin/python -m agent_registry authority change-window-agent
```

Expected: JSON-ish dict with `"infra_mutation"` in capabilities, `"credential_revoke"` in prohibited.

- [ ] **Step 4: Commit**

```bash
git add src/agent_registry/cli.py src/agent_registry/__main__.py tests/test_agent_registry_cli.py
git commit -m "feat(agent-registry): lookup CLI — validate/list/show/authority (WS-1.2)"
```

---

### Task 4: Strict registry gate in factory_events

**Repo:** `~/Projects/security-standards`, branch `feat/ws12-agent-registry`

**Files:**
- Modify: `src/factory_events/envelope.py`
- Test: `tests/test_factory_envelope.py` (append)

**Interfaces:**
- Consumes: `agent_registry.registry.registered_ids` (lazy import — factory_events paths that never build events stay PyYAML-free).
- Produces: `make_event(actor="...")` raises `EnvelopeError` for unregistered actors. Tasks 5–6 rely on this being strict; their adapters must pre-map.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_factory_envelope.py` (match its existing imports/style; it already imports `make_event` and `EnvelopeError`):

```python
def test_make_event_rejects_unregistered_actor():
    with pytest.raises(EnvelopeError, match="not a registered agent_id"):
        make_event(
            actor="totally-invented",
            action="tool.test",
            result="unknown",
            timestamp="2026-07-03T00:00:00Z",
            source={"system": "direct", "ref": "test"},
        )


def test_make_event_accepts_registered_actor_any_status():
    event = make_event(
        actor="factory-runner",  # status: reserved — must still validate
        action="tool.test",
        result="unknown",
        timestamp="2026-07-03T00:00:00Z",
        source={"system": "direct", "ref": "test"},
    )
    assert event["actor"] == "factory-runner"
```

Run: `.venv-events/bin/python -m pytest tests/test_factory_envelope.py -v`
Expected: the two new tests FAIL (no gate yet); existing tests may also fail if they use unregistered actor strings — note which.

- [ ] **Step 2: Implement the gate**

In `src/factory_events/envelope.py`, add after `validate_event` (line 46):

```python
def _assert_registered_actor(actor: str) -> None:
    # Lazy import: registry lookup (PyYAML) only loads on event construction.
    from agent_registry.registry import registered_ids

    if actor not in registered_ids():
        raise EnvelopeError(
            f"actor {actor!r} is not a registered agent_id (see registry/agents/)"
        )
```

and in `make_event`, immediately before `validate_event(event)`:

```python
    _assert_registered_actor(actor)
```

- [ ] **Step 3: Fix any existing tests using unregistered actors**

Re-run the full factory suite:

```bash
.venv-events/bin/python -m pytest tests/test_factory_envelope.py tests/test_factory_store.py tests/test_factory_cli.py tests/test_factory_ship.py -v
```

Any test that constructed events with an invented actor string must switch to a
registered id (`devon` or `claude-code-unattributed`). Change only actor strings —
no behavioral edits.

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/factory_events/envelope.py tests/
git commit -m "feat(factory-events): strict registry gate on actor at make_event (WS-1.2)"
```

---

### Task 5: High-power adapter — stamped-actor with fallback

**Repo:** `~/Projects/security-standards`, branch `feat/ws12-agent-registry`

**Files:**
- Modify: `src/factory_events/adapters/high_power.py:82-104`
- Test: `tests/test_adapter_high_power.py` (append)

**Interfaces:**
- Consumes: source records that MAY carry an `actor` field (stamped by the hook, Task 11); `registered_ids()`.
- Produces: adapted events whose actor = stamped id if registered, else `claude-code-unattributed`. Raw record (including any bogus stamp) already lands in `evidence[0].record` — no extra work needed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_adapter_high_power.py` (mirror its existing fixture style — it writes JSONL lines to a tmp source and calls `adapt(source=...)`; reuse its helpers):

```python
def test_stamped_registered_actor_is_used(tmp_path, monkeypatch):
    line = json.dumps({"timestamp": "2026-07-03T04:00:00Z", "tool": "vps_exec",
                       "session_id": "s1", "args_summary": "{}",
                       "actor": "vps-backup-provider-agent", "provenance": "unknown"})
    events = adapt_lines(tmp_path, monkeypatch, [line])
    assert events[0]["actor"] == "vps-backup-provider-agent"


def test_stamped_unregistered_actor_falls_back(tmp_path, monkeypatch):
    line = json.dumps({"timestamp": "2026-07-03T04:00:00Z", "tool": "vps_exec",
                       "session_id": "s1", "args_summary": "{}",
                       "actor": "typo-agent", "provenance": "unknown"})
    events = adapt_lines(tmp_path, monkeypatch, [line])
    assert events[0]["actor"] == "claude-code-unattributed"
    assert events[0]["evidence"][0]["record"]["actor"] == "typo-agent"  # raw preserved


def test_unstamped_record_falls_back(tmp_path, monkeypatch):
    line = json.dumps({"timestamp": "2026-07-03T04:00:00Z", "tool": "vps_exec",
                       "session_id": "s1", "args_summary": "{}", "provenance": "unknown"})
    events = adapt_lines(tmp_path, monkeypatch, [line])
    assert events[0]["actor"] == "claude-code-unattributed"
```

If the file has no `adapt_lines`-style helper, add one modeled on its existing
tests (write lines to `tmp_path / "src.jsonl"`, point the store env at `tmp_path`
via the same monkeypatching its other tests use, run `adapt(source=...)`, read
events back from the store).

Run: `.venv-events/bin/python -m pytest tests/test_adapter_high_power.py -v`
Expected: new tests FAIL (stamped actor ignored).

- [ ] **Step 2: Implement**

In `src/factory_events/adapters/high_power.py`, add above `_map_line`:

```python
def _actor(raw: dict) -> str:
    """Stamped identity if registered; honest fallback otherwise (raw stays in evidence)."""
    from agent_registry.registry import registered_ids

    stamped = raw.get("actor")
    if isinstance(stamped, str) and stamped in registered_ids():
        return stamped
    return "claude-code-unattributed"
```

and replace `actor="claude-code-unattributed",` with `actor=_actor(raw),` in BOTH
branches of `_map_line` (the `"tool"` branch at line 85 and the `"action"`
governance branch at line 97).

- [ ] **Step 3: Run tests**

```bash
.venv-events/bin/python -m pytest tests/test_adapter_high_power.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/factory_events/adapters/high_power.py tests/test_adapter_high_power.py
git commit -m "feat(factory-events): high-power adapter honors stamped registered actor (WS-1.2)"
```

---

### Task 6: change-manager adapter — registered pass-through

**Repo:** `~/Projects/security-standards`, branch `feat/ws12-agent-registry`

**Files:**
- Modify: `src/factory_events/adapters/change_manager.py:53-58`
- Test: `tests/test_adapter_change_manager.py` (append)

**Interfaces:**
- Consumes: ChangeEvent records whose `actor` may now be a registered id (Task 8/9 threading) or the legacy strings (`sync`, `watchdog`, `executor`, an SSO email).
- Produces: `_map_actor` order — registered pass-through → legacy `_ACTOR_MAP` → `@` ⇒ `devon` → `unknown`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_adapter_change_manager.py`:

```python
def test_registered_actor_passes_through():
    assert _map_actor("security-executor") == "security-executor"
    assert _map_actor("change-window-agent") == "change-window-agent"


def test_legacy_executor_still_maps_to_window_agent():
    assert _map_actor("executor") == "change-window-agent"


def test_unregistered_unmapped_actor_is_unknown():
    assert _map_actor("api") == "unknown"
```

Add `from factory_events.adapters.change_manager import _map_actor` to the file's
imports if not present.

Run: `.venv-events/bin/python -m pytest tests/test_adapter_change_manager.py -v`
Expected: `test_registered_actor_passes_through` FAILS (`security-executor` → `unknown` today).

- [ ] **Step 2: Implement**

Replace `_map_actor` in `src/factory_events/adapters/change_manager.py`:

```python
def _map_actor(raw_actor: str) -> str:
    from agent_registry.registry import registered_ids

    if raw_actor in registered_ids():
        return raw_actor  # WS-1.2 threaded identity — verbatim
    if raw_actor in _ACTOR_MAP:
        return _ACTOR_MAP[raw_actor]  # legacy/pre-split strings
    if "@" in raw_actor:
        return "devon"  # solo operator: any SSO email is Devon
    return "unknown"
```

- [ ] **Step 3: Run tests**

```bash
.venv-events/bin/python -m pytest tests/test_adapter_change_manager.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/factory_events/adapters/change_manager.py tests/test_adapter_change_manager.py
git commit -m "feat(factory-events): change-manager adapter passes registered actors through (WS-1.2)"
```

---

### Task 7: README supersession + full-repo gate

**Repo:** `~/Projects/security-standards`, branch `feat/ws12-agent-registry`

**Files:**
- Modify: `src/factory_events/README.md:25-38` (the "Provisional actor vocabulary" section) and lines 12–17 (emit doc)

- [ ] **Step 1: Replace the provisional-vocabulary section**

Replace the whole section (heading at line 25 through the verbatim-preservation
note at line 38) with:

```markdown
## Actor identity — the agent registry (WS-1.2)

Actors are validated against the agent-identity registry at `registry/`
(`PYTHONPATH=src python3 -m agent_registry list|authority <id>`), which
supersedes the provisional vocabulary this section used to hold. Direct emits
with an unregistered actor are rejected; adapters fall back to
`claude-code-unattributed` / legacy mappings and always preserve the raw source
actor verbatim in `evidence[0].record`. See `registry/README.md` for the
authority model (ability / policy / task-authority / approval).
```

Also update the emit bullet (lines 12–17): change "**This is the WS-1.2 seam:**
runtimes/executors declare their identity by emitting events with their
registered actor id." to "Runtimes/executors declare identity by emitting with
their registered actor id (validated against `registry/`)."

- [ ] **Step 2: Run the full repo suite (all standards self-hosting)**

```bash
cd ~/Projects/security-standards
make test
.venv-events/bin/python -m pytest -q
PYTHONPATH=src .venv-events/bin/python -m agent_registry validate
```

Expected: full suite green in both interpreters that matter (the `make test` PY and
the events venv); `registry ok: 11 agents, 9 profiles`.

- [ ] **Step 3: Commit**

```bash
git add src/factory_events/README.md
git commit -m "docs(factory-events): registry supersedes provisional actor vocabulary (WS-1.2)"
```

---

### Task 8: change-manager API accepts a declared actor

**Repo:** `~/Projects/change-manager`, new branch `feat/ws12-actor-threading` off current `main` (`git sync` first)

**Files:**
- Modify: `app/schemas.py:45-49` (OutcomeIn; add ClaimIn)
- Modify: `app/api.py:126-179` (claim + outcome endpoints)
- Test: `tests/test_api_actor.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `POST /api/items/{id}/claim` accepts optional JSON body `{"actor": "..."}`; `POST /api/items/{id}/outcome` accepts optional `actor` in OutcomeIn; both default to `"executor"`; the value lands on `ChangeEvent.actor`. Task 9's client sends these.

- [ ] **Step 1: Write the failing tests**

`tests/test_api_actor.py` (seeding helper copied from `tests/test_api_lifecycle.py`):

```python
import app.auth as auth
from app.models import ChangeEvent, ChangeItem

H = {"Authorization": "Bearer t"}
ESC = {
    "proposal_id": "571:r1",
    "instance": "prod",
    "target": {"provider": "coolify", "resource_type": "application", "uuid": "a1", "name": "app1"},
    "risk": "caution",
    "kind": "remediation",
    "reasoning": "rule #571",
    "plan": {"root_cause": "x"},
    "note": None,
}
BODY = {"generated_at": "t", "source_report": "2026-07-03.json", "escalations": [ESC]}


def _approved(client, db):
    auth.settings.m2m_token = "t"
    client.post("/api/sync", json=BODY, headers=H)
    it = db.query(ChangeItem).one()
    it.status = "approved"
    db.commit()
    return it.id


def test_claim_records_declared_actor(client, db):
    iid = _approved(client, db)
    r = client.post(f"/api/items/{iid}/claim", headers=H, json={"actor": "security-executor"})
    assert r.status_code == 200
    ev = db.query(ChangeEvent).filter_by(item_id=iid, event_type="claimed").one()
    assert ev.actor == "security-executor"


def test_claim_without_body_defaults_to_executor(client, db):
    iid = _approved(client, db)
    assert client.post(f"/api/items/{iid}/claim", headers=H).status_code == 200
    ev = db.query(ChangeEvent).filter_by(item_id=iid, event_type="claimed").one()
    assert ev.actor == "executor"


def test_outcome_records_declared_actor(client, db):
    iid = _approved(client, db)
    client.post(f"/api/items/{iid}/claim", headers=H, json={"actor": "change-window-agent"})
    r = client.post(
        f"/api/items/{iid}/outcome",
        headers=H,
        json={"outcome": "done", "detail": "applied", "actor": "change-window-agent"},
    )
    assert r.status_code == 200
    ev = db.query(ChangeEvent).filter_by(item_id=iid, event_type="attempt_done").one()
    assert ev.actor == "change-window-agent"


def test_outcome_without_actor_defaults_to_executor(client, db):
    iid = _approved(client, db)
    client.post(f"/api/items/{iid}/claim", headers=H)
    client.post(f"/api/items/{iid}/outcome", headers=H, json={"outcome": "done", "detail": "x"})
    ev = db.query(ChangeEvent).filter_by(item_id=iid, event_type="attempt_done").one()
    assert ev.actor == "executor"
```

Run: `cd ~/Projects/change-manager && python -m pytest tests/test_api_actor.py -v`
(use the repo's venv the same way its other tests run — check for `.venv/`).
Expected: the two "declared actor" tests FAIL (actor hardcoded to "executor").

- [ ] **Step 2: Implement**

`app/schemas.py` — add `actor` to `OutcomeIn` and a new `ClaimIn` next to it:

```python
class ClaimIn(BaseModel):
    actor: str = "executor"  # WS-1.2: executors declare a registry identity


class OutcomeIn(BaseModel):
    outcome: str  # done | failed | blocked | skipped_conformant
    detail: str | None = None
    tool_calls: dict[str, Any] | None = None
    rollback: dict[str, Any] | None = None
    actor: str = "executor"  # WS-1.2: executors declare a registry identity
```

`app/api.py` — claim endpoint (import `ClaimIn` alongside the existing schema imports):

```python
@router.post("/items/{item_id}/claim")
def claim(item_id: int, body: ClaimIn | None = None, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    if it.status != "approved":
        raise HTTPException(status_code=409, detail=f"not approved (status={it.status})")
    it.status = "in_progress"
    record_event(
        db,
        it,
        actor=body.actor if body else "executor",
        event_type="claimed",
        from_status="approved",
        to_status="in_progress",
    )
    db.commit()
    return _item_dict(it)
```

outcome endpoint — change only the `record_event` call: `actor="executor",` →
`actor=body.actor,`.

- [ ] **Step 3: Run the full suite**

```bash
python -m pytest -q
```

Expected: all pass (existing lifecycle tests prove backward compatibility).

- [ ] **Step 4: Commit + open PR (do not merge)**

```bash
git add app/schemas.py app/api.py tests/test_api_actor.py
git commit -m "feat(api): claim/outcome accept a declared actor, default executor (WS-1.2)"
git push -u origin feat/ws12-actor-threading
gh pr create --title "WS-1.2: claim/outcome accept a declared actor identity" --body "Executors declare their registry identity (change-window-agent / security-executor) in claim+outcome; absent actor defaults to 'executor' so old clients keep working. No DB migration (ChangeEvent.actor exists). Part of the WS-1.2 agent-identity registry (spec in security-standards docs/superpowers/specs/2026-07-03-ws12-agent-registry-design.md).

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 9: infraops client threads the actor + provider-agent env var

**Repo:** `~/Projects/infraops-mcp-server`, new branch `feat/ws12-actor-threading` off current `main` (`git sync` first)

**Files:**
- Modify: `src/change-manager/api-client.ts` (constructor + claim + postOutcome)
- Modify: `src/cli/change-mgr-cli.ts` (client() + the two window functions)
- Modify: `bin/provider-agent` (child_env line — same edit as Task 10's other copies)
- Test: `tests/change-manager-api-client.test.ts` (append)
- Rebuild: `dist/` (tracked — same commit)

**Interfaces:**
- Consumes: Task 8's API contract (`{"actor": ...}` in claim/outcome bodies).
- Produces: `new ChangeMgrClient(base, token, actor?)` — actor defaults to `"executor"`; `client(actor?: string)` in the CLI.

- [ ] **Step 1: Write the failing tests**

Append to `tests/change-manager-api-client.test.ts` inside the existing `describe`:

```typescript
  it("claim sends the declared actor in the body", async () => {
    fetchMock.mockResolvedValue(ok({ id: 1, status: "in_progress" }));
    const c = new ChangeMgrClient("https://cm.example", "tok", "security-executor");
    await c.claim(1);
    const [, opts] = fetchMock.mock.calls[0];
    expect(JSON.parse(opts.body)).toEqual({ actor: "security-executor" });
  });

  it("postOutcome merges the declared actor into the body", async () => {
    fetchMock.mockResolvedValue(ok({ id: 1 }));
    const c = new ChangeMgrClient("https://cm.example", "tok", "change-window-agent");
    await c.postOutcome(1, { outcome: "done", detail: "applied" });
    const [, opts] = fetchMock.mock.calls[0];
    expect(JSON.parse(opts.body)).toEqual({ outcome: "done", detail: "applied", actor: "change-window-agent" });
  });

  it("defaults the actor to executor for backward compatibility", async () => {
    fetchMock.mockResolvedValue(ok({ id: 1 }));
    const c = new ChangeMgrClient("https://cm.example", "tok");
    await c.claim(1);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ actor: "executor" });
  });
```

Run: `cd ~/Projects/infraops-mcp-server && npx vitest run tests/change-manager-api-client.test.ts`
Expected: FAIL (constructor takes 2 args; claim sends no body).

- [ ] **Step 2: Implement the client**

`src/change-manager/api-client.ts`:

```typescript
export class ChangeMgrClient {
  constructor(private base: string, private token: string, private actor: string = "executor") {}
```

and:

```typescript
  claim(id: number): Promise<ApprovedItem> {
    return this.req<ApprovedItem>(`/api/items/${id}/claim`, { method: "POST", body: JSON.stringify({ actor: this.actor }) });
  }
  postOutcome(id: number, body: OutcomeBody): Promise<unknown> {
    return this.req(`/api/items/${id}/outcome`, { method: "POST", body: JSON.stringify({ ...body, actor: this.actor }) });
  }
```

- [ ] **Step 3: Thread identity at the two window entry points**

`src/cli/change-mgr-cli.ts`:

```typescript
function client(actor: string = "executor"): ChangeMgrClient {
  const base = process.env.CHANGE_MGR_API_BASE ?? "";
  const token = process.env.CHANGE_MGR_M2M_TOKEN ?? "";
  if (!base || !token) throw new Error("CHANGE_MGR_API_BASE and CHANGE_MGR_M2M_TOKEN must be set");
  return new ChangeMgrClient(base, token, actor);
}
```

In `doRunWindow`: `const c = client();` → `const c = client("change-window-agent");`
In `doRunSecurityWindow`: `const c = client();` → `const c = client("security-executor");`
(`doSync` keeps the bare `client()` — sync events are stamped server-side.)

- [ ] **Step 4: Provider-agent env var (this repo's copy)**

In `bin/provider-agent`, find the child-env line (same construct as vps-backup's
`bin/provider-agent:174` — locate with `grep -n "child_env" bin/provider-agent`):

```python
    child_env = {**os.environ, DEPTH_ENV: str(depth + 1)}
```

becomes:

```python
    child_env = {
        **os.environ,
        DEPTH_ENV: str(depth + 1),
        # WS-1.2: the spawned session's high-power records carry the provider identity
        "FACTORY_AGENT_ID": f"{REPO_ROOT.name}-provider-agent",
    }
```

(`REPO_ROOT.name` here is `infraops-mcp-server` → `infraops-mcp-server-provider-agent`, registered in Task 2.)

- [ ] **Step 5: Full suite + build + commit + PR (do not merge)**

```bash
npx vitest run
npm run build
git status --porcelain dist/   # must show the rebuilt files
git add src/change-manager/api-client.ts src/cli/change-mgr-cli.ts bin/provider-agent dist/ tests/change-manager-api-client.test.ts
git commit -m "feat(change-manager): window executors declare registry identities; provider-agent stamps FACTORY_AGENT_ID (WS-1.2)"
git push -u origin feat/ws12-actor-threading
gh pr create --title "WS-1.2: executor identity threading + provider-agent identity stamp" --body "doRunWindow claims/reports as change-window-agent, doRunSecurityWindow as security-executor (resolves the WS-1.1 'executor' conflation); bin/provider-agent stamps FACTORY_AGENT_ID into spawned sessions. Requires change-manager PR feat/ws12-actor-threading to be deployed FIRST (absent-actor default keeps this safe either way). Spec: security-standards docs/superpowers/specs/2026-07-03-ws12-agent-registry-design.md.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

Expected: vitest fully green (406+ tests); `dist/` diff present in the commit.

---

### Task 10: Provider-agent wrapper — canonical pattern + vps-backup copy

**Repos:** `~/Projects/provider-agent-pattern` (canonical) and `~/Projects/vps-backup` — new branch `feat/ws12-agent-identity` in each (`git sync` first)

**Files:**
- Modify: `~/Projects/provider-agent-pattern/bin/provider-agent` (locate the exact file with `grep -rn "DEPTH_ENV" ~/Projects/provider-agent-pattern` — the wrapper is documented as identical across providers; if the pattern repo stores it under another path, edit that copy)
- Modify: `~/Projects/vps-backup/bin/provider-agent:174`

**Interfaces:**
- Consumes: nothing.
- Produces: every spawned provider session has `FACTORY_AGENT_ID=<repo>-provider-agent` in its environment (consumed by the hook, Task 11).

- [ ] **Step 1: Apply the same child_env edit as Task 9 Step 4 to both copies**

In each repo's wrapper:

```python
    child_env = {
        **os.environ,
        DEPTH_ENV: str(depth + 1),
        # WS-1.2: the spawned session's high-power records carry the provider identity
        "FACTORY_AGENT_ID": f"{REPO_ROOT.name}-provider-agent",
    }
```

- [ ] **Step 2: Verify the derived id for vps-backup**

```bash
cd ~/Projects/vps-backup && python3 - <<'EOF'
from pathlib import Path
print(Path.cwd().name + "-provider-agent")
EOF
```

Expected: `vps-backup-provider-agent` (matches the registry entry). If either repo
has wrapper tests (`grep -rn "provider-agent" tests/ 2>/dev/null || true`), run them.

- [ ] **Step 3: Commit + PR in each repo (do not merge)**

```bash
# in each repo
git add -A
git commit -m "feat(provider-agent): stamp FACTORY_AGENT_ID=<repo>-provider-agent into spawned sessions (WS-1.2)"
git push -u origin feat/ws12-agent-identity
gh pr create --title "WS-1.2: provider-agent declares registry identity" --body "Spawned provider sessions carry FACTORY_AGENT_ID so their high-power audit records attribute to <repo>-provider-agent instead of claude-code-unattributed. Spec: security-standards docs/superpowers/specs/2026-07-03-ws12-agent-registry-design.md.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 11: Control-plane hook stamp + ~/.zshenv + open-engine prompt

**Repo:** `~/.claude` (control-plane git repo — direct commit, no PR) + two config edits

**Files:**
- Modify: `~/.claude/hooks/high-power-audit-log.sh:36-39`
- Modify: `~/.zshenv` (append)
- Modify: `~/.config/open-engine/runner-prompt.md` (append)

- [ ] **Step 1: Stamp the actor in the hook**

Replace lines 36–39 of `~/.claude/hooks/high-power-audit-log.sh`:

```bash
  TS="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  AGENT="${FACTORY_AGENT_ID:-}"
  jq -nc --arg ts "$TS" --arg tool "$TOOL" --arg sid "$SID" --arg args "$ARGS" --arg agent "$AGENT" \
     '{timestamp:$ts, tool:$tool, session_id:$sid, args_summary:$args, provenance:"unknown (confirm at review: direct request vs inferred from read content)"}
      + (if $agent != "" then {actor:$agent} else {} end)' \
     >> "$LOG" 2>/dev/null
```

The hook's contract (always exit 0, never block) is unchanged — an unset var
yields a record identical to today's shape.

- [ ] **Step 2: Test the hook against a throwaway HOME**

```bash
TMP=$(mktemp -d)
printf '%s' '{"tool_name":"vps_exec","session_id":"test-s1","tool_input":{"command":"uptime"}}' \
  | HOME="$TMP" FACTORY_AGENT_ID=claude-code-interactive bash ~/.claude/hooks/high-power-audit-log.sh
cat "$TMP/.claude/audit/high-power-actions.jsonl"
printf '%s' '{"tool_name":"vps_exec","session_id":"test-s2","tool_input":{"command":"uptime"}}' \
  | HOME="$TMP" bash ~/.claude/hooks/high-power-audit-log.sh
cat "$TMP/.claude/audit/high-power-actions.jsonl"
rm -rf "$TMP"
```

Expected: first record has `"actor":"claude-code-interactive"`; second record has
NO `actor` key; both exit 0.

- [ ] **Step 3: Commit in the control-plane repo**

```bash
cd ~/.claude && git add hooks/high-power-audit-log.sh && git commit -m "feat(audit): stamp actor from FACTORY_AGENT_ID into high-power records (WS-1.2)"
```

(Note: the security-drift Check-13 control-plane git-drift monitor will see this
tracked-file change as committed — expected and clean.)

- [ ] **Step 4: ~/.zshenv default**

Append to `~/.zshenv` (idempotently — check first with `grep -n FACTORY_AGENT_ID ~/.zshenv`):

```bash
# WS-1.2 agent registry: sessions launched from a shell attribute as interactive.
# Launchers that spawn other runtimes (provider-agent, open-engine) override this.
export FACTORY_AGENT_ID=claude-code-interactive
```

Verify: `zsh -c 'source ~/.zshenv; echo $FACTORY_AGENT_ID'` → `claude-code-interactive`.

- [ ] **Step 5: Open Engine runner prompt**

Append to `~/.config/open-engine/runner-prompt.md`:

```markdown
## Identity declaration (WS-1.2 agent registry)

You are registered as `open-engine-runner` in the agent registry
(security-standards `registry/agents/open-engine-runner.yaml`). Declare identity
in the factory event store at two protocol points:

- **On CLAIM** (right after moving the issue to In Progress):

      cd ~/Projects/security-standards && set -a && source ~/.factory/env && set +a && \
      PYTHONPATH=src .venv-events/bin/python -m factory_events emit \
        --actor open-engine-runner --action queue.claim --result unknown \
        --ref open-engine-runner --target "<ISSUE-ID>" --correlation-id "linear:<ISSUE-ID>"

- **On DONE/BLOCKED** (after posting the receipt comment), same command with
  `--action queue.done --result success` (or `--action queue.blocked --result failure`).

These emits are the audit trail; they do not replace Linear receipt comments.
```

- [ ] **Step 6: Verify one real emit + chain integrity**

```bash
cd ~/Projects/security-standards && set -a && source ~/.factory/env && set +a && \
PYTHONPATH=src .venv-events/bin/python -m factory_events emit \
  --actor open-engine-runner --action queue.claim --result unknown \
  --ref ws12-wiring-test --target "WS-1.2-selftest" --correlation-id "ws12:selftest"
PYTHONPATH=src .venv-events/bin/python -m factory_events verify --against-anchor
```

Expected: emit succeeds; `anchor ok` + `chain ok` with event count +1.

---

### Task 12: End-to-end verification (spec §7)

**Repo:** `~/Projects/security-standards` (+ vps-backup for the provider run)

- [ ] **Step 1: Registry + suite green**

```bash
cd ~/Projects/security-standards
PYTHONPATH=src .venv-events/bin/python -m agent_registry validate
.venv-events/bin/python -m pytest -q
```

Expected: `registry ok: 11 agents, 9 profiles`; suite green.

- [ ] **Step 2: Strict gate demonstrably rejects**

```bash
set -a && source ~/.factory/env && set +a
PYTHONPATH=src .venv-events/bin/python -m factory_events emit \
  --actor not-a-real-agent --action tool.test --result unknown --ref ws12-negative-test; echo "exit=$?"
```

Expected: non-zero exit, error naming the unregistered actor; NO event appended
(`verify` count unchanged).

- [ ] **Step 3: Provider identity end-to-end (hook → log → adapter)**

Run a real provider-agent invocation that triggers at least one gated tool, then
confirm the stamped record. If no natural provider task exists, verify the seam
synthetically instead: with `FACTORY_AGENT_ID=vps-backup-provider-agent` exported,
run the hook test from Task 11 Step 2 against the REAL `$HOME` once (one
harmless extra audit record), then:

```bash
tail -1 ~/.claude/audit/high-power-actions.jsonl   # expect "actor":"vps-backup-provider-agent"
cd ~/Projects/security-standards && set -a && source ~/.factory/env && set +a
PYTHONPATH=src .venv-events/bin/python -m factory_events adapt --source high-power
PYTHONPATH=src .venv-events/bin/python -m factory_events verify --against-anchor
```

Expected: adapt appends ≥1 event; the new event's actor is
`vps-backup-provider-agent`; chain + anchor OK.

- [ ] **Step 4: Fallback demonstrably safe**

Repeat Step 3's synthetic record with `FACTORY_AGENT_ID=totally-bogus-agent`, then
`adapt` again. Expected: adapt succeeds (no error), the new event's actor is
`claude-code-unattributed`, and `evidence[0].record.actor` is `totally-bogus-agent`.

- [ ] **Step 5: Ship the projection + wrap up**

```bash
PYTHONPATH=src .venv-events/bin/python -m factory_events ship
PYTHONPATH=src .venv-events/bin/python -m factory_events verify --against-anchor
```

Expected: ship OK; anchor + chain OK.

- [ ] **Step 6: Push the security-standards branch + open PR (do not merge)**

```bash
cd ~/Projects/security-standards
git push -u origin feat/ws12-agent-registry
gh pr create --title "WS-1.2: agent-identity registry + authority profiles" --body "registry/ (11 agents, 9 profiles, controlled vocabulary) + agent_registry validator/lookup CLI + strict actor gate at make_event + adapter identity handling + README supersession. Spec: docs/superpowers/specs/2026-07-03-ws12-agent-registry-design.md. Reviewer focus: registry/agents/*.yaml and registry/profiles/*.yaml — the authority claims are the judgment content.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 7: Executor-split live evidence is day-2**

The first post-merge 4AM window (after Devon merges change-manager THEN infraops)
produces the first `security-executor` / split `change-window-agent` ChangeEvents;
next session confirms via `adapt` + a look at the newest events. Record this as
the WS-1.2 day-2 check in the session summary.
