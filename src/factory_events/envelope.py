"""factory-event/v1 envelope: canonicalization, ids, validation.

The JSON Schema at schema/factory-event.v1.schema.json is the published
contract; this module is the runtime enforcement of it.
"""

import hashlib
import json
import uuid
from functools import cache
from pathlib import Path

import jsonschema

SCHEMA_VERSION = "factory-event/v1"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "factory-event.v1.schema.json"


class EnvelopeError(ValueError):
    """Event does not conform to factory-event/v1."""


def canonical_json(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def deterministic_event_id(system: str, payload: str) -> str:
    return "evt-" + hashlib.sha256(f"{system}:{payload}".encode()).hexdigest()


def new_event_id() -> str:
    return "evt-" + uuid.uuid4().hex


@cache
def _validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text())
    return jsonschema.Draft202012Validator(schema)


def validate_event(event: dict) -> None:
    errors = sorted(_validator().iter_errors(event), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.absolute_path) or "<root>"
        raise EnvelopeError(f"invalid factory-event at {where}: {first.message}")


def _assert_registered_actor(actor: str) -> None:
    # Lazy import: registry lookup (PyYAML) only loads on event construction.
    from agent_registry.registry import registered_ids

    if actor not in registered_ids():
        raise EnvelopeError(f"actor {actor!r} is not a registered agent_id (see registry/agents/)")


def make_event(
    *,
    actor: str,
    action: str,
    result: str,
    source: dict,
    timestamp: str,
    target: str | None = None,
    work_package: str | None = None,
    input_revision: str | None = None,
    evidence: list[dict] | None = None,
    authority_grant: dict | str | None = None,
    correlation_id: str | None = None,
    event_id: str | None = None,
) -> dict:
    event = {
        "schema": SCHEMA_VERSION,
        "event_id": event_id or new_event_id(),
        "timestamp": timestamp,
        "actor": actor,
        "action": action,
        "target": target,
        "work_package": work_package,
        "input_revision": input_revision,
        "result": result,
        "evidence": evidence or [],
        "authority_grant": authority_grant,
        "correlation_id": correlation_id,
        "source": source,
    }
    _assert_registered_actor(actor)
    validate_event(event)
    return event
