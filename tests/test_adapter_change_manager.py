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


def test_actor_and_result_mapping_table():
    pages = {
        0: [
            _raw(1, "applied", "executor"),
            _raw(2, "failed", "executor"),
            _raw(3, "pr_linked", "api"),
            _raw(4, "stale_handoff", "watchdog"),
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
    assert [e["result"] for e in events] == ["success", "failure", "unknown", "unknown", "success"]
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
