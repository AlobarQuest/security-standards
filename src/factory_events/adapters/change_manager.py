"""Adapter: change-manager /api/events -> factory-events store.

Cursor = ChangeEvent.id (watermark {"last_id": N}); the endpoint is added by
the WS-1.1 change-manager PR. Raw actor strings are preserved verbatim inside
evidence[0].record; the envelope actor is the provisional-vocabulary mapping.
"executor" covers both window-lane executors, so it maps to change-window-agent
(conflation documented in the README; WS-1.2 fixes identity properly).
"""

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from factory_events import store
from factory_events.envelope import deterministic_event_id, make_event

SYSTEM = "change-manager"
PAGE_LIMIT = 500

_ACTOR_MAP = {
    "sync": "drift-reconciler",
    "watchdog": "drift-reconciler",
    "executor": "change-window-agent",
}
_RESULT_MAP = {"applied": "success", "approved": "success", "failed": "failure"}
_GRANT_TYPES = {"approved"}


class ConfigError(RuntimeError):
    """CM_BASE_URL / CM_M2M_TOKEN missing from the environment."""


def _watermark_path() -> Path:
    return store.state_dir() / "change-manager.json"


def _load_watermark() -> dict | None:
    path = _watermark_path()
    return json.loads(path.read_text()) if path.exists() else None


def _save_watermark(last_id: int) -> None:
    path = _watermark_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_id": last_id}))


def _map_actor(raw_actor: str) -> str:
    if raw_actor in _ACTOR_MAP:
        return _ACTOR_MAP[raw_actor]
    if "@" in raw_actor:
        return "devon"  # solo operator: any SSO email is Devon
    return "unknown"


def _normalize_ts(raw: str) -> str:
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo:
        ts = ts.astimezone(UTC).replace(tzinfo=None)
    # naive timestamps are trusted as UTC (change-manager writes datetime.now(UTC))
    suffix = f".{ts.microsecond:06d}" if ts.microsecond else ""
    return ts.strftime("%Y-%m-%dT%H:%M:%S") + suffix + "Z"


def _map_event(raw: dict) -> dict:
    event_type = raw["event_type"]
    grant = None
    if event_type in _GRANT_TYPES:
        grant = {"system": SYSTEM, "item_id": raw["item_id"], "approver": raw["actor"]}
    return make_event(
        event_id=deterministic_event_id(SYSTEM, str(raw["id"])),
        timestamp=_normalize_ts(raw["at"]),
        actor=_map_actor(raw["actor"]),
        action=f"change.{event_type}",
        target=raw.get("item_identity"),
        result=_RESULT_MAP.get(event_type, "unknown"),
        evidence=[{"type": "source-record", "record": raw}],
        authority_grant=grant,
        correlation_id=f"change-item:{raw['item_id']}",
        source={"system": SYSTEM, "ref": f"change-event:{raw['id']}"},
    )


def _http_fetch(after_id: int, limit: int) -> list[dict]:
    base_url = os.environ.get("CM_BASE_URL", "")
    token = os.environ.get("CM_M2M_TOKEN", "")
    if not base_url or not token:
        raise ConfigError("CM_BASE_URL and CM_M2M_TOKEN must be set (source ~/.factory/env)")
    query = urllib.parse.urlencode({"after_id": after_id, "limit": limit})
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/events?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # https URL from config
        return json.loads(resp.read())["events"]


def adapt(fetch: Callable[[int, int], list[dict]] | None = None) -> int:
    if fetch is None:
        if not (os.environ.get("CM_BASE_URL") and os.environ.get("CM_M2M_TOKEN")):
            raise ConfigError("CM_BASE_URL and CM_M2M_TOKEN must be set (source ~/.factory/env)")
        fetch = _http_fetch
    mark = _load_watermark()
    after_id = mark["last_id"] if mark else 0
    known = store.event_ids()
    appended = 0
    while True:
        page = fetch(after_id, PAGE_LIMIT)
        if not page:
            break
        for raw in page:
            event = _map_event(raw)
            if event["event_id"] not in known:
                store.append_event(event)
                known.add(event["event_id"])
                appended += 1
        last_id = page[-1]["id"]
        if last_id <= after_id:
            raise RuntimeError(
                f"events page did not advance cursor (after_id={after_id}, last id={last_id})"
            )
        after_id = last_id
        _save_watermark(after_id)
    return appended
