"""The consumer side of `factory_events emit`'s stdout, vendored for tests."""

import json


def parse_event_id(stdout: str) -> str | None:
    """intent-packages `_parse_event_id`, verbatim from src/intent_packages/emitter.py lines
    40-67 at intent-packages d9f96e2 (the emitter's parse of `factory_events emit` stdout)."""
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]

    for line in lines:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "event_id" in data:
            return data["event_id"]

    if not lines:
        return None

    tokens = lines[-1].split()
    if not tokens:
        return None
    token = tokens[-1]
    return token if len(token) > 3 else None
