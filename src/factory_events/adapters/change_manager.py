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
    "devon": "devon",
}
# What each change-manager event type says about the change it is recorded against, in the
# envelope's `result` vocabulary. ONE RULE, so the table can be re-derived rather than trusted:
#
#   success -- an act on the record concluded: it was created, updated, decided or completed;
#   failure -- the change's own work failed, or an approval or resolution stopped holding;
#   unknown -- the work is still in flight, or the event type alone does not say which.
#
# That is the precedent this repository already set for other producers (`queue.claim` ->
# unknown, `queue.done` -> success, `queue.blocked` -> failure; the high-power adapter's pre-call
# record is unknown and its post-call record success).
#
# THE KEYS ARE CHANGE-MANAGER'S OWN `event_type` VALUES, every one it emits and nothing else.
# Until 2026-09-28 this map was keyed {applied, approved, failed}, of which only `approved` was
# ever emitted, so every other type -- `attempt_failed` included -- reached the chain as
# `unknown`. The set is pinned by `tests/test_adapter_change_manager.py`, which says where it was
# read from. A type missing here still maps to `unknown` rather than raising: this adapter runs
# nightly and a halt would lose the rest of the page, so the pin, not the runtime, is what
# notices a new type.
_RESULT_MAP = {
    # The record's lifecycle: created, updated, decided.
    "proposed": "success",
    "ingested": "success",
    "criteria_refreshed": "success",
    "approved": "success",
    "deferred": "success",
    "wontfixed": "success",
    "resolved": "success",
    "reactivated": "success",
    "settled": "success",
    # An approval or a resolution that did not hold: the policy withdrew an approval the record
    # no longer earns, drift reappeared after the record was closed, or a handoff went
    # unresolved long enough for the watchdog to take it back.
    "policy_revoked": "failure",
    "regression_reopened": "failure",
    "handoff_watchdog_reverted": "failure",
    # ONE TYPE, TWO OPPOSITE OUTCOMES. The deploy lane retires a record whose pull request closed
    # unmerged (the change can no longer happen); the work lane retires one whose work is done.
    "retired": "unknown",
    # Work passed on or under way, not yet concluded.
    "handed_off": "unknown",
    "pr_linked": "unknown",
    "claimed": "unknown",
    # An executor's attempt, concluded.
    "attempt_done": "success",
    "attempt_failed": "failure",
    "attempt_blocked": "failure",
    # A rollout observation. Its verdict (success, failed, unknown or absent) is in the event's
    # prose `detail`, not its type, and parsing prose would make the chain's `result` depend on
    # wording nobody versions.
    "deploy_observed": "unknown",
}
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
    from agent_registry.registry import registered_ids

    if raw_actor in registered_ids():
        return raw_actor  # WS-1.2 threaded identity — verbatim
    if raw_actor in _ACTOR_MAP:
        return _ACTOR_MAP[raw_actor]  # legacy/pre-split strings
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
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "factory-events-adapter/1 (+security-standards WS-1.1)",
        },
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
