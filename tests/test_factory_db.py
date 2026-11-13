"""The database chain against a disposable Postgres (`make check-integration`).

FACTORY_TEST_DSN must name a superuser on a throwaway cluster: each test gets its own new
database, set up by the real roles script, and the two roles it creates are cluster-wide.
"""

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from emitter_contract import parse_event_id

from factory_events import chain, db, db_setup, envelope, store
from factory_events.adapters import high_power
from factory_events.cli import main

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "high_power_sample.jsonl"
ROLE_PASSWORD = secrets.token_hex(16)  # throwaway, for this run's disposable cluster only
WALK_EVENTS = 3751  # the Mac file's size on 2026-11-13 (ADR-0055 amendment 24)


def _psycopg() -> Any:
    return import_module("psycopg")


def _conninfo(base: str, **overrides: str) -> str:
    conninfo = import_module("psycopg.conninfo")
    params = conninfo.conninfo_to_dict(base)
    params.update(overrides)
    return conninfo.make_conninfo(**params)


@dataclass(frozen=True)
class ChainDb:
    owner: str
    append: str
    read: str


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_EVENTS_HOME", str(tmp_path / "factory"))
    yield tmp_path


@pytest.fixture()
def chain_db() -> Iterator[ChainDb]:
    base = os.environ.get("FACTORY_TEST_DSN")
    assert base, "FACTORY_TEST_DSN is required (make check-integration sets one)"
    psycopg = _psycopg()
    sql = import_module("psycopg.sql")
    name = f"fe_chain_{secrets.token_hex(6)}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    owner = _conninfo(base, dbname=name)
    try:
        db_setup.setup(owner)
        with psycopg.connect(owner, autocommit=True) as conn:
            for role in ("factory_events_append", "factory_events_read"):
                conn.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(ROLE_PASSWORD)
                    )
                )
        yield ChainDb(
            owner=owner,
            append=_conninfo(owner, user="factory_events_append", password=ROLE_PASSWORD),
            read=_conninfo(owner, user="factory_events_read", password=ROLE_PASSWORD),
        )
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


def _event(n: int, action: str = "test.ping") -> dict:
    return envelope.make_event(
        actor="devon",
        action=action,
        result="success",
        source={"system": "direct", "ref": "test"},
        timestamp="2026-07-02T00:00:00Z",
        event_id=envelope.deterministic_event_id("direct", str(n)),
        evidence=[{"n": n, "big": 1e300, "text": "naïve \u0000 null"}],
    )


def _rows(dsn: str) -> list[tuple]:
    with _psycopg().connect(dsn) as conn:
        return conn.execute(
            "SELECT seq, prev_hash, hash, event_id, event FROM factory_events ORDER BY seq"
        ).fetchall()


def _refused(dsn: str, statement: str) -> str:
    psycopg = _psycopg()
    with pytest.raises(psycopg.Error) as info, psycopg.connect(dsn) as conn:
        conn.execute(statement)
    return type(info.value).__name__


# --- schema, trigger and roles ---------------------------------------------------------


def test_append_links_exactly_as_the_file_does(chain_db):
    file_records = [store.append_event(_event(n)) for n in range(3)]
    db_records = [db.append_event(chain_db.append, _event(n)) for n in range(3)]
    assert db_records == file_records
    rows = _rows(chain_db.read)
    assert [(r[0], r[1], r[2]) for r in rows] == [
        (r["seq"], r["prev_hash"], r["hash"]) for r in file_records
    ]
    # The stored text round-trips byte-stable (a large float and a NUL escape included).
    assert [r[4] for r in rows] == [
        envelope.canonical_json(r["event"]).decode() for r in file_records
    ]
    result = db.verify(chain_db.read)
    assert result.errors == [] and result.count == 3
    assert result.head == (3, file_records[-1]["hash"])


def test_trigger_refuses_update_delete_truncate_even_for_the_owner(chain_db):
    db.append_event(chain_db.append, _event(1))
    for statement in (
        "UPDATE factory_events SET event = '{}'",
        "DELETE FROM factory_events",
        "TRUNCATE factory_events",
    ):
        assert _refused(chain_db.owner, statement) == "InsufficientPrivilege"
    assert len(_rows(chain_db.read)) == 1


def test_roles_hold_only_their_grants(chain_db):
    db.append_event(chain_db.append, _event(1))
    for statement in (
        "UPDATE factory_events SET event = '{}'",
        "DELETE FROM factory_events",
        "TRUNCATE factory_events",
        "CREATE TABLE sneaky (id int)",
        "ALTER TABLE factory_events DISABLE TRIGGER USER",
    ):
        _refused(chain_db.append, statement)
    for statement in (
        "INSERT INTO factory_events VALUES ('x', 2, repeat('a', 64), repeat('b', 64), '{}')",
        "CREATE TABLE sneaky (id int)",
    ):
        _refused(chain_db.read, statement)
    with pytest.raises(db.ChainError):
        db.append_event(chain_db.read, _event(2))
    assert len(_rows(chain_db.owner)) == 1


def test_a_row_that_does_not_link_is_refused_whatever_the_role(chain_db):
    db.append_event(chain_db.append, _event(1))
    head = _rows(chain_db.read)[-1][2]
    for seq, prev in ((3, head), (2, "c" * 64), (1, store.GENESIS)):
        _refused(
            chain_db.owner,
            "INSERT INTO factory_events VALUES "
            f"('evt-x', {seq}, '{prev}', repeat('d', 64), '{{}}')",
        )
    assert len(_rows(chain_db.read)) == 1


def test_duplicate_event_id_fails_and_writes_nothing(chain_db):
    db.append_event(chain_db.append, _event(1))
    with pytest.raises(db.ChainError, match="UniqueViolation"):
        db.append_event(chain_db.append, _event(1))
    assert len(_rows(chain_db.read)) == 1


def test_concurrent_appends_stay_linear(chain_db):
    errors: list[BaseException] = []

    def writer(base: int) -> None:
        for n in range(10):
            try:
                db.append_event(chain_db.append, _event(base * 100 + n))
            except BaseException as exc:  # collected and asserted on below
                errors.append(exc)

    threads = [threading.Thread(target=writer, args=(w,)) for w in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    result = db.verify(chain_db.read)
    assert result.errors == [] and result.count == 40


def test_verify_finds_a_tampered_row(chain_db):
    for n in range(3):
        db.append_event(chain_db.append, _event(n))
    with _psycopg().connect(chain_db.owner) as conn:  # only the owner can lift the trigger
        conn.execute("ALTER TABLE factory_events DISABLE TRIGGER factory_events_no_update_delete")
        conn.execute(
            "UPDATE factory_events SET event = replace(event, 'naïve', 'naive') WHERE seq = 2"
        )
    result = db.verify(chain_db.read)
    assert result.errors == ["seq 2: hash mismatch (line tampered)"]
    assert result.count == 1


# --- the CLI against the database ------------------------------------------------------


def _cli(args: list[str], env_extra: dict[str, str], home: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("FACTORY_")}
    env.update(PYTHONPATH=str(REPO / "src"), FACTORY_EVENTS_HOME=str(home), **env_extra)
    return subprocess.run(
        [sys.executable, "-m", "factory_events", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_emit_stdout_parses_to_the_emitted_id(chain_db, tmp_path):
    args = ["emit", "--actor", "devon", "--action", "package.approved", "--result", "success"]
    proc = _cli([*args, "--ref", "test"], {chain.APPEND_DSN_VAR: chain_db.append}, tmp_path)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert json.loads(lines[0])["outcome"] == "ok"  # a JSON log record shares stdout
    emitted = parse_event_id(proc.stdout)
    assert emitted == lines[-1]
    assert [r[3] for r in _rows(chain_db.read)] == [emitted]
    assert not (tmp_path / "events.jsonl").exists()  # no file in database mode
    assert ROLE_PASSWORD not in proc.stdout + proc.stderr


def test_verify_anchor_round_trip(chain_db, monkeypatch, capsys):
    monkeypatch.setenv(chain.APPEND_DSN_VAR, chain_db.append)  # the nightly's one DSN
    for n in range(3):
        db.append_event(chain_db.append, _event(n))
    assert main(["verify", "--record-anchor"]) == 0
    anchored = chain.read_anchor()
    assert anchored is not None and anchored[0] == 3
    db.append_event(chain_db.append, _event(9))
    capsys.readouterr()
    assert main(["verify", "--against-anchor"]) == 0
    out = capsys.readouterr().out
    assert "anchor ok: seq 3 present" in out
    assert any(line.startswith("chain ok: 4 events, head ") for line in out.splitlines())
    # A chain that no longer holds the anchored head refuses.
    chain.write_anchor((3, "e" * 64))
    assert main(["verify", "--against-anchor"]) == 1
    assert "anchored head (seq 3) not in chain" in capsys.readouterr().err


def test_adapt_rerun_skips_held_events(chain_db, tmp_path, monkeypatch, capsys):
    source = tmp_path / "hp.jsonl"
    source.write_text(FIXTURE.read_text())
    monkeypatch.setattr(high_power, "DEFAULT_SOURCE", source)
    monkeypatch.setenv(chain.APPEND_DSN_VAR, chain_db.append)
    assert main(["adapt", "--source", "high-power"]) == 0
    assert "high-power: 3 events appended" in capsys.readouterr().out
    # Lose the watermark: the re-run replays every line, and the deterministic ids dedupe
    # against the database instead of failing the night on the primary key.
    (store.state_dir() / "high-power.json").unlink()
    assert main(["adapt", "--source", "high-power"]) == 0
    assert "high-power: 0 events appended" in capsys.readouterr().out
    assert main(["adapt", "--source", "high-power", "--reanchor"]) == 0
    assert len(_rows(chain_db.read)) == 3
    assert not store.events_path().exists()


# --- the history import ----------------------------------------------------------------


def test_import_reproduces_the_file_chain(chain_db, monkeypatch, capsys):
    records = [store.append_event(_event(n)) for n in range(5)]
    monkeypatch.setenv(chain.IMPORT_DSN_VAR, chain_db.append)
    assert main(["import-file", "--path", str(store.events_path())]) == 0
    assert f"imported: 5 events, head {records[-1]['hash']}" in capsys.readouterr().out
    assert [(r[0], r[1], r[2], r[3]) for r in _rows(chain_db.read)] == [
        (r["seq"], r["prev_hash"], r["hash"], r["event"]["event_id"]) for r in records
    ]
    # A second import refuses: the database chain is no longer empty.
    assert main(["import-file", "--path", str(store.events_path())]) == 1
    assert "not empty" in capsys.readouterr().err


def test_import_refuses_a_tampered_file_and_writes_nothing(chain_db):
    for n in range(3):
        store.append_event(_event(n))
    lines = store.events_path().read_text().splitlines()
    lines[1] = lines[1].replace("naïve", "naive")
    store.events_path().write_text("\n".join(lines) + "\n")
    with pytest.raises(db.ChainError, match="does not verify"):
        db.import_file(chain_db.append, store.events_path())
    assert _rows(chain_db.read) == []


# --- the verify walk's cost ------------------------------------------------------------


def _synthetic_chain(path: Path, count: int) -> tuple[int, str]:
    prev = store.GENESIS
    with path.open("wb") as fh:
        for seq in range(1, count + 1):
            event = _event(seq, action="synthetic.walk")
            digest = store.line_hash(seq, prev, event)
            fh.write(
                envelope.canonical_json(
                    {"seq": seq, "prev_hash": prev, "hash": digest, "event": event}
                )
                + b"\n"
            )
            prev = digest
    return count, prev


def test_verify_walk_of_a_mac_sized_chain(chain_db, tmp_path):
    """Synthetic: never a copy of ~/.factory/events.jsonl. Prints the timing for the report."""
    path = tmp_path / "synthetic.jsonl"
    head = _synthetic_chain(path, WALK_EVENTS)
    started = time.perf_counter()
    assert db.import_file(chain_db.append, path) == head
    imported = time.perf_counter() - started
    started = time.perf_counter()
    result = db.verify(chain_db.read)
    walked = time.perf_counter() - started
    assert result.errors == [] and result.count == WALK_EVENTS and result.head == head
    print(f"\nwalk: {WALK_EVENTS} events, import {imported:.2f}s, verify {walked:.2f}s")
    assert walked < 30
