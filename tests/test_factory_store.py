import json

import pytest

from factory_events import envelope, store


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def _event(n: int) -> dict:
    return envelope.make_event(
        actor="devon",
        action="test.ping",
        result="success",
        source={"system": "direct", "ref": "test"},
        timestamp="2026-07-02T00:00:00Z",
        event_id=envelope.deterministic_event_id("direct", str(n)),
    )


def test_append_builds_genesis_then_chains(tmp_path):
    line1 = store.append_event(_event(1))
    line2 = store.append_event(_event(2))
    assert line1["seq"] == 1 and line1["prev_hash"] == store.GENESIS
    assert line2["seq"] == 2 and line2["prev_hash"] == line1["hash"]
    assert store.head() == (2, line2["hash"])


def test_append_rejects_invalid_event():
    with pytest.raises(envelope.EnvelopeError):
        store.append_event({"schema": "factory-event/v1"})


def test_event_ids_and_iter_records():
    store.append_event(_event(1))
    store.append_event(_event(2))
    ids = store.event_ids()
    assert len(ids) == 2
    assert [r["seq"] for r in store.iter_records()] == [1, 2]


def test_verify_chain_clean():
    for n in range(5):
        store.append_event(_event(n))
    assert store.verify_chain() == []


def test_verify_chain_detects_tampered_middle_line(tmp_path):
    for n in range(5):
        store.append_event(_event(n))
    path = store.events_path()
    lines = path.read_text().splitlines()
    doctored = json.loads(lines[2])
    doctored["event"]["actor"] = "mallory"
    lines[2] = json.dumps(doctored, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")
    errors = store.verify_chain()
    assert errors and "seq 3" in errors[0]


def test_verify_chain_detects_deleted_line(tmp_path):
    for n in range(5):
        store.append_event(_event(n))
    path = store.events_path()
    lines = path.read_text().splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n")
    assert store.verify_chain() != []


def test_empty_store_verifies_and_has_no_head():
    assert store.verify_chain() == []
    assert store.head() is None
    assert store.event_ids() == set()
