import os

import pytest

from factory_events import envelope, ship, store
from factory_events.cli import main

DSN = os.environ.get("FACTORY_TEST_DSN")
needs_pg = pytest.mark.skipif(not DSN, reason="FACTORY_TEST_DSN not set")


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path))
    yield tmp_path


def _seed(n: int) -> None:
    for i in range(n):
        store.append_event(envelope.make_event(
            actor="devon", action="test.ping", result="success",
            source={"system": "direct", "ref": "test"},
            timestamp="2026-07-02T00:00:00Z",
            event_id=envelope.deterministic_event_id("direct", str(i)),
        ))


@pytest.fixture()
def pg(monkeypatch):
    monkeypatch.setenv("FACTORY_DB_DSN", DSN)
    assert DSN is not None
    import psycopg

    with psycopg.connect(DSN) as conn:
        conn.execute("DROP TABLE IF EXISTS factory_events, chain_heads")
    yield DSN


@needs_pg
def test_ship_inserts_and_anchors(pg):
    _seed(3)
    inserted, head = ship.ship()
    head_val = store.head()
    assert head_val is not None
    assert inserted == 3 and head == head_val
    assert ship.last_anchor() == head
    # idempotent: nothing new
    inserted2, _ = ship.ship()
    assert inserted2 == 0
    # anchors accumulate (a second head row, same head)
    import psycopg

    with psycopg.connect(pg) as conn:
        chain_heads_count = conn.execute("SELECT count(*) FROM chain_heads").fetchone()
        assert chain_heads_count is not None
        assert chain_heads_count[0] == 2


@needs_pg
def test_ship_rebuild_replays_but_keeps_anchors(pg):
    _seed(2)
    ship.ship()
    inserted, _ = ship.ship(rebuild=True)
    import psycopg

    with psycopg.connect(pg) as conn:
        events_count = conn.execute("SELECT count(*) FROM factory_events").fetchone()
        assert events_count is not None
        assert events_count[0] == 2
        heads_count = conn.execute("SELECT count(*) FROM chain_heads").fetchone()
        assert heads_count is not None
        assert heads_count[0] == 2
    assert inserted == 2


@needs_pg
def test_ship_promotes_query_columns(pg):
    _seed(1)
    ship.ship()
    import psycopg

    with psycopg.connect(pg) as conn:
        row = conn.execute(
            "SELECT actor, action, result, source_system FROM factory_events"
        ).fetchone()
    assert row == ("devon", "test.ping", "success", "direct")


def test_verify_against_anchor_passes_and_fails(monkeypatch):
    _seed(3)
    head = store.head()
    assert head is not None
    seq, head_hash = head
    monkeypatch.setattr(ship, "last_anchor", lambda dsn=None: (seq, head_hash))
    assert main(["verify", "--against-anchor"]) == 0
    monkeypatch.setattr(ship, "last_anchor", lambda dsn=None: (seq, "f" * 64))
    assert main(["verify", "--against-anchor"]) == 1


def test_verify_against_anchor_with_no_anchor_yet_passes(monkeypatch):
    _seed(1)
    monkeypatch.setattr(ship, "last_anchor", lambda dsn=None: None)
    assert main(["verify", "--against-anchor"]) == 0
