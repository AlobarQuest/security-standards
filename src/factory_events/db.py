"""The factory-events chain of record in Postgres (orchestrator ADR-0055 amendment 24).

Rows link as the file's lines do (store.line_hash), so store.walk_records verifies both.
chain_schema.sql holds the table, its triggers and its two roles; this module runs no DDL.

Every failure surfaces as ChainError, whose text names only the operation and the error's
type: a driver error's text can repeat its DSN, so it's never logged, printed or chained.
psycopg is imported lazily, so the file chain never loads it.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from factory_events import store
from factory_events.envelope import canonical_json, validate_event
from factory_events.jsonlog import head_prefix, log

# Every append takes this transaction-level advisory lock before it reads the head (item 6).
APPEND_LOCK_KEY = 0x6661637465767473  # "factevts"
CONNECT_TIMEOUT_SECONDS = 10
LOCK_TIMEOUT = "10s"

_HEAD = "SELECT seq, hash FROM factory_events ORDER BY seq DESC LIMIT 1"
_INSERT = (
    "INSERT INTO factory_events (event_id, seq, prev_hash, hash, event) VALUES (%s, %s, %s, %s, %s)"
)
_WALK = "SELECT seq, prev_hash, hash, event_id, event FROM factory_events ORDER BY seq"


class ChainError(RuntimeError):
    """The database chain refused or failed an operation; nothing was written."""


@dataclass(frozen=True)
class WalkResult:
    errors: list[str]
    head: tuple[int, str] | None
    count: int
    anchor_hash: str | None = None


def _connect(dsn: str) -> Any:
    import psycopg  # lazy: the file chain must not require it

    return psycopg.connect(
        dsn, connect_timeout=CONNECT_TIMEOUT_SECONDS, application_name="factory_events"
    )


def _lock(conn: Any) -> None:
    conn.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (APPEND_LOCK_KEY,))


def _append_in_tx(conn: Any, event: dict) -> dict:
    """Link one event to the head inside the caller's transaction, which holds the lock."""
    validate_event(event)
    row = conn.execute(_HEAD).fetchone()
    seq, prev_hash = (row[0] + 1, row[1]) if row else (1, store.GENESIS)
    record = {
        "seq": seq,
        "prev_hash": prev_hash,
        "hash": store.line_hash(seq, prev_hash, event),
        "event": event,
    }
    conn.execute(
        _INSERT,
        (event["event_id"], seq, prev_hash, record["hash"], canonical_json(event).decode()),
    )
    return record


def append_event(dsn: str, event: dict) -> dict:
    """Append one event in one transaction (items 6 and 7): any failure writes nothing."""
    try:
        with _connect(dsn) as conn:  # commits on a clean exit, rolls back on an exception
            _lock(conn)
            record = _append_in_tx(conn, event)
    except Exception as exc:
        # Not swallowed: logged by type and raised as ChainError. `from None` keeps the
        # driver's text, which can repeat the DSN, out of every traceback.
        log("append", "failure", event_id=event.get("event_id"), error_type=type(exc).__name__)
        raise ChainError(f"append failed ({type(exc).__name__})") from None
    log(
        "append",
        "ok",
        event_id=event["event_id"],
        seq=record["seq"],
        head=head_prefix(record["hash"]),
    )
    return record


def event_ids(dsn: str) -> set[str]:
    try:
        with _connect(dsn) as conn:
            return {row[0] for row in conn.execute("SELECT event_id FROM factory_events")}
    except Exception as exc:
        log("event_ids", "failure", error_type=type(exc).__name__)  # logged, then raised
        raise ChainError(f"reading event ids failed ({type(exc).__name__})") from None


def _rows_as_records(rows: Iterator[tuple], anchor: dict) -> Iterator[dict]:
    for seq, prev_hash, hash_hex, event_id, event_text in rows:
        if seq == anchor.get("seq"):
            anchor["hash"] = hash_hex
        try:
            event = json.loads(event_text)
        except json.JSONDecodeError:
            event = None  # the walker reports it as a tampered row
        yield {
            "seq": seq,
            "prev_hash": prev_hash,
            "hash": hash_hex,
            "event_id": event_id,
            "event": event,
        }


def verify(dsn: str, anchor_seq: int | None = None) -> WalkResult:
    """Walk every row from seq 1 in one read-only repeatable-read transaction (item 8).

    When anchor_seq is given, also return the hash the chain holds at that seq, read in the
    same snapshot as the walk.
    """
    anchor: dict = {"seq": anchor_seq}
    try:
        from psycopg import IsolationLevel  # lazy, inside the try: a missing driver fails closed

        with _connect(dsn) as conn:
            conn.read_only = True
            conn.isolation_level = IsolationLevel.REPEATABLE_READ
            with conn.transaction(), conn.cursor(name="factory_events_walk") as cur:
                cur.execute(_WALK)
                errors, last, count = store.walk_records(_rows_as_records(iter(cur), anchor))
    except Exception as exc:
        log("verify", "failure", error_type=type(exc).__name__)  # logged, then raised
        raise ChainError(f"verify failed ({type(exc).__name__})") from None
    head = (last["seq"], last["hash"]) if last else None
    log(
        "verify",
        "broken" if errors else "ok",
        seq=head[0] if head else 0,
        head=head_prefix(head[1] if head else None),
        events=count,
    )
    return WalkResult(errors, head, count, anchor.get("hash"))


def _replay(conn: Any, records: list[dict]) -> None:
    """Re-append each file record through the append routine; refuse on any divergence."""
    if conn.execute(_HEAD).fetchone() is not None:
        raise ChainError("import refused: the database chain is not empty")
    for rec in records:
        appended = _append_in_tx(conn, rec["event"])
        if (appended["seq"], appended["hash"]) != (rec["seq"], rec["hash"]):
            raise ChainError(f"import refused: seq {rec['seq']} does not reproduce the file")
    row = conn.execute(_HEAD).fetchone()
    file_head = (records[-1]["seq"], records[-1]["hash"]) if records else None
    if (tuple(row) if row else None) != file_head:
        raise ChainError("import refused: the imported head does not equal the file's head")


def import_file(dsn: str, path: Path) -> tuple[int, str] | None:
    """Replay a verified events file into an empty database chain, in order, in one transaction.

    Commits only when the imported head equals the file's head, so a refused import writes
    nothing. The caller chooses the DSN, and with it the role (Devon's decision before FE-5).
    """
    if not path.exists():
        raise ChainError(f"import refused: {path} does not exist")
    # Read once: the records verified are the records replayed.
    try:
        records = list(store.iter_records(path))
    except json.JSONDecodeError:
        raise ChainError("import refused: the file has an unparseable line") from None
    file_errors, _last, _count = store.walk_records(records)
    if file_errors:
        raise ChainError(f"import refused: the file does not verify: {file_errors[0]}")
    ids = [rec["event"]["event_id"] for rec in records]
    if len(set(ids)) != len(ids):
        # The file never enforced unique ids; the table's primary key does.
        raise ChainError("import refused: the file holds a duplicate event_id")
    try:
        with _connect(dsn) as conn:
            _lock(conn)
            _replay(conn, records)
    except ChainError:
        log("import", "refused", error_type="ChainError")
        raise
    except Exception as exc:
        log("import", "failure", error_type=type(exc).__name__)  # logged, then raised
        raise ChainError(f"import failed ({type(exc).__name__})") from None
    head = (records[-1]["seq"], records[-1]["hash"]) if records else None
    log("import", "ok", seq=head[0] if head else 0, head=head_prefix(head[1] if head else None))
    return head
