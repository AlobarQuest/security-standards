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
    return [
        f"{where}: {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in errors
    ]


def _validate_profile(stem: str, profile: dict, vocabulary: set[str]) -> list[str]:
    errors = _schema_errors(profile, _PROFILE_SCHEMA_PATH, f"profiles/{stem}.yaml")
    if profile.get("profile") != stem:
        errors.append(
            f"profiles/{stem}.yaml: filename does not match profile {profile.get('profile')!r}"
        )
    for field in ("capabilities", "prohibited"):
        for term in profile.get(field, []):
            if term not in vocabulary:
                errors.append(f"profiles/{stem}.yaml: unknown {field} term {term!r}")
    return errors


def _validate_agent(
    stem: str, agent: dict, profiles: dict[str, dict], vocabulary: set[str]
) -> list[str]:
    where = f"agents/{stem}.yaml"
    errors = _schema_errors(agent, _AGENT_SCHEMA_PATH, where)
    if agent.get("agent_id") != stem:
        errors.append(f"{where}: filename does not match agent_id {agent.get('agent_id')!r}")
    profile_name = agent.get("authority_profile")
    if profile_name and profile_name not in profiles:
        errors.append(f"{where}: authority_profile {profile_name!r} does not resolve")
    for field in ("capabilities", "prohibited"):
        for term in agent.get(field, []):
            if term not in vocabulary:
                errors.append(f"{where}: unknown {field} term {term!r}")
    profile = profiles.get(profile_name, {}) if profile_name else {}
    granted = set(agent.get("capabilities", [])) | set(profile.get("capabilities", []))
    denied = set(agent.get("prohibited", [])) | set(profile.get("prohibited", []))
    for term in sorted(granted & denied):
        errors.append(f"{where}: {term!r} is both granted and prohibited")
    return errors


def validate_registry(registry_dir: Path | None = None) -> list[str]:
    """Full referential validation; returns [] when the registry is valid."""
    base = registry_dir or REGISTRY_DIR
    try:
        vocabulary = set(load_vocabulary(base))
        profiles = load_profiles(base)
        agents = load_agents(base)
    except (RegistryError, OSError, yaml.YAMLError) as exc:
        return [str(exc)]

    errors: list[str] = []
    for stem, profile in profiles.items():
        errors += _validate_profile(stem, profile, vocabulary)
    for stem, agent in agents.items():
        errors += _validate_agent(stem, agent, profiles, vocabulary)
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
