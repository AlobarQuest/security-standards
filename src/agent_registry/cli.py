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


def _cmd_validate() -> int:
    """Validate registry; print errors and status."""
    errors = validate_registry()
    for error in errors:
        print(error)
    if errors:
        return 1
    agents = load_agents()
    profiles = load_profiles()
    print(f"registry ok: {len(agents)} agents, {len(profiles)} profiles")
    return 0


def _cmd_list() -> int:
    """List all agents with status and authority profile."""
    for agent_id, agent in load_agents().items():
        print(f"{agent_id}\t{agent['status']}\t{agent['authority_profile']}")
    return 0


def _cmd_show(agent_id: str) -> int:
    """Show an agent's full record as YAML."""
    agent = load_agents().get(agent_id)
    if agent is None:
        raise RegistryError(f"unknown agent_id {agent_id!r}")
    print(yaml.safe_dump(agent, sort_keys=False), end="")
    return 0


def _cmd_authority(agent_id: str, as_json: bool) -> int:
    """Show effective authority for an agent as JSON."""
    auth = effective_authority(agent_id)
    print(json.dumps(auth, indent=None if as_json else 2))
    return 0


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

    try:
        if args.cmd == "validate":
            return _cmd_validate()
        if args.cmd == "list":
            return _cmd_list()
        if args.cmd == "show":
            return _cmd_show(args.agent_id)
        return _cmd_authority(args.agent_id, args.as_json)
    except RegistryError as exc:
        print(f"error: {exc}")
        return 1
