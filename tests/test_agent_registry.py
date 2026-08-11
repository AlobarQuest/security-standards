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

VOCAB = {
    "schema": "capability-vocabulary/v1",
    "terms": {
        "repository_read": "read repo files",
        "repository_write": "write repo files",
        "merge_to_main": "merge PRs to a default branch",
    },
}
PROFILE = {
    "schema": "authority-profile/v1",
    "profile": "test-base-v1",
    "description": "test baseline",
    "capabilities": ["repository_read"],
    "prohibited": ["merge_to_main"],
}
AGENT = {
    "schema": "agent-identity/v1",
    "agent_id": "test-agent",
    "version": 1,
    "status": "active",
    "runtime": "claude-code",
    "operator": "devon",
    "environment": "mini",
    "description": "a test agent",
    "authority_profile": "test-base-v1",
    "capabilities": ["repository_write"],
    "prohibited": [],
}


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


def test_real_registry_validates_and_covers_ws11_vocabulary():
    assert validate_registry() == []
    from agent_registry.registry import registered_ids

    # one-for-one supersession of the WS-1.1 provisional vocabulary
    assert {
        "devon",
        "claude-code-unattributed",
        "change-window-agent",
        "security-executor",
        "drift-reconciler",
        "open-engine-runner",
        "unknown",
    } <= registered_ids()


def test_the_change_manager_event_actors_resolve_to_themselves() -> None:
    """ADR-0019 increment 5a. Without these entries the chain attributes them to nobody.

    `change.approved` is the only event change-manager emits that becomes an `authority_grant`,
    and the grant's approver is the event's actor — so `deploy-policy` failing to resolve would
    put the one authorization permitting an autonomous production deploy into the tamper-evident
    chain as `unknown`. That chain visibility is the argument that decided increment 5a's central
    fork, which makes this the fork's own property rather than housekeeping.

    Asserted through `_map_actor` rather than `registered_ids()`, because resolution is what the
    adapter actually does and a registered id that failed to map would satisfy the weaker check.
    The final case is the control: without it this test passes on an adapter that returns its
    argument unchanged for everything.
    """
    from factory_events.adapters.change_manager import _map_actor

    assert _map_actor("deploy-policy") == "deploy-policy"
    assert _map_actor("change-proposer") == "change-proposer"
    assert _map_actor("an-id-nobody-registered") == "unknown"
