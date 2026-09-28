import pytest

from factory_events import store
from factory_events.adapters import change_manager
from factory_events.adapters.change_manager import _map_actor


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def _raw(id_: int, event_type: str = "created", actor: str = "sync") -> dict:
    return {
        "id": id_,
        "item_id": 7,
        "at": "2026-07-01T04:00:00+00:00",
        "actor": actor,
        "event_type": event_type,
        "from_status": None,
        "to_status": "pending",
        "detail": None,
        "attempt_id": None,
        "window_run_id": None,
        "item_identity": "db-backup-x",
        "item_rule_key": "backup.configured",
        "item_instance": "prod",
    }


def _fake_fetch(pages: dict[int, list[dict]]):
    def fetch(after_id: int, limit: int) -> list[dict]:
        return pages.get(after_id, [])

    return fetch


def test_adapt_maps_fields_and_paginates():
    pages = {0: [_raw(1), _raw(2, "approved", "devon@example.com")], 2: []}
    count = change_manager.adapt(fetch=_fake_fetch(pages))
    assert count == 2
    records = list(store.iter_records())
    ev1, ev2 = records[0]["event"], records[1]["event"]
    assert ev1["action"] == "change.created"
    assert ev1["actor"] == "drift-reconciler"  # "sync" mapped
    assert ev1["timestamp"] == "2026-07-01T04:00:00Z"  # Z-normalized
    assert ev1["target"] == "db-backup-x"
    assert ev1["correlation_id"] == "change-item:7"
    assert ev1["source"] == {"system": "change-manager", "ref": "change-event:1"}
    assert ev2["actor"] == "devon"  # email mapped
    assert ev2["authority_grant"] == {
        "system": "change-manager",
        "item_id": 7,
        "approver": "devon@example.com",
    }
    assert ev2["result"] == "success"


# Every `event_type` change-manager emits, read from its source on 2026-09-28 (change-manager
# `origin/main` f3f98ee). No cross-repo read happens here, so this list goes stale when
# change-manager adds a type; re-derive it with
#
#   grep -rn 'event_type=\|_EVENT = \|_OUTCOME_STATUS\|_ACTIONS\|_decide(' app/
#
# in a change-manager checkout. Most are literals passed as `event_type=` to `record_event` or
# `decide`. The rest are indirect: `_OUTCOME_STATUS` in app/api.py (attempt_done, attempt_failed,
# attempt_blocked, resolved), the `_decide` routes and web `_ACTIONS` (approved, deferred,
# wontfixed, resolved), and the module constants OBSERVED_EVENT (deploy_observed),
# SETTLED_EVENT (settled) and RETIRED_EVENT (retired, in two modules).
CHANGE_MANAGER_EVENT_TYPES = frozenset(
    {
        "proposed",
        "ingested",
        "criteria_refreshed",
        "approved",
        "policy_revoked",
        "deferred",
        "wontfixed",
        "resolved",
        "reactivated",
        "retired",
        "settled",
        "pr_linked",
        "handed_off",
        "regression_reopened",
        "handoff_watchdog_reverted",
        "claimed",
        "attempt_done",
        "attempt_failed",
        "attempt_blocked",
        "deploy_observed",
    }
)


def test_every_emitted_event_type_is_classified_and_nothing_else_is():
    """A type change-manager emits that the map does not know reaches the chain as `unknown`
    with nothing saying so. That is how 19 of the 20 did, `attempt_failed` among them. A key
    it never emits is a classification of nothing, which is what hid it."""
    assert set(change_manager._RESULT_MAP) == CHANGE_MANAGER_EVENT_TYPES


def test_every_classification_is_in_the_envelope_vocabulary():
    assert set(change_manager._RESULT_MAP.values()) <= {"success", "failure", "unknown"}


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("attempt_failed", "failure"),
        ("attempt_blocked", "failure"),
        ("attempt_done", "success"),
        ("claimed", "unknown"),
        ("regression_reopened", "failure"),
        ("handoff_watchdog_reverted", "failure"),
        ("deploy_observed", "unknown"),
        ("proposed", "success"),
        ("policy_revoked", "failure"),
        ("retired", "unknown"),
        ("handed_off", "unknown"),
        ("pr_linked", "unknown"),
    ],
)
def test_the_result_an_event_type_reaches_the_chain_with(event_type, expected):
    pages = {0: [_raw(1, event_type, "executor")], 1: []}
    change_manager.adapt(fetch=_fake_fetch(pages))
    [record] = list(store.iter_records())
    assert record["event"]["result"] == expected


def test_a_type_the_map_does_not_know_is_recorded_as_unknown_rather_than_halting():
    pages = {0: [_raw(1, "not_a_real_type", "executor")], 1: []}
    assert change_manager.adapt(fetch=_fake_fetch(pages)) == 1
    [record] = list(store.iter_records())
    assert record["event"]["result"] == "unknown"


def test_actor_and_result_mapping_table():
    pages = {
        0: [
            _raw(1, "attempt_done", "executor"),
            _raw(2, "attempt_failed", "executor"),
            _raw(3, "pr_linked", "api"),
            _raw(4, "handoff_watchdog_reverted", "watchdog"),
            _raw(5, "approved", "devon"),
        ],
        5: [],
    }
    change_manager.adapt(fetch=_fake_fetch(pages))
    events = [r["event"] for r in store.iter_records()]
    assert [e["actor"] for e in events] == [
        "change-window-agent",
        "change-window-agent",
        "unknown",
        "drift-reconciler",
        "devon",
    ]
    assert [e["result"] for e in events] == ["success", "failure", "unknown", "failure", "success"]
    assert events[4]["authority_grant"]["approver"] == "devon"
    assert all(e["authority_grant"] is None for e in events[:4])


def test_watermark_resumes_from_last_id():
    pages = {0: [_raw(1)], 1: []}
    assert change_manager.adapt(fetch=_fake_fetch(pages)) == 1
    pages2 = {1: [_raw(2)], 2: []}
    assert change_manager.adapt(fetch=_fake_fetch(pages2)) == 1
    assert change_manager._load_watermark() == {"last_id": 2}


def test_missing_config_fails_loudly(monkeypatch):
    monkeypatch.delenv("CM_BASE_URL", raising=False)
    monkeypatch.delenv("CM_M2M_TOKEN", raising=False)
    with pytest.raises(change_manager.ConfigError):
        change_manager.adapt()


def test_normalize_ts_converts_non_utc_offsets():
    pages = {0: [dict(_raw(1), at="2026-07-01T04:00:00+05:00")], 1: []}
    change_manager.adapt(fetch=_fake_fetch(pages))
    ev = list(store.iter_records())[0]["event"]
    assert ev["timestamp"] == "2026-06-30T23:00:00Z"


def test_non_advancing_page_raises():
    def bad_fetch(after_id: int, limit: int) -> list[dict]:
        return [_raw(0)]  # id never exceeds cursor

    with pytest.raises(RuntimeError, match="did not advance"):
        change_manager.adapt(fetch=bad_fetch)


def test_registered_actor_passes_through():
    assert _map_actor("security-executor") == "security-executor"
    assert _map_actor("change-window-agent") == "change-window-agent"


def test_legacy_executor_still_maps_to_window_agent():
    assert _map_actor("executor") == "change-window-agent"


def test_unregistered_unmapped_actor_is_unknown():
    assert _map_actor("api") == "unknown"
