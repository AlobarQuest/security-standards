"""Append-only hash-chained JSONL store at ~/.factory/events.jsonl.

Line format: {"seq": N, "prev_hash": h, "hash": h, "event": {...}}
hash = sha256(canonical_json({"seq", "prev_hash", "event"})). The chain
evidences edits/deletions; the nightly anchor (ship.py) evidences rewrites.
"""

import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path

from factory_events.envelope import canonical_json, validate_event

GENESIS = "0" * 64


def factory_home() -> Path:
    return Path(os.environ.get("FACTORY_EVENTS_HOME", str(Path.home() / ".factory")))


def events_path() -> Path:
    return factory_home() / "events.jsonl"


def state_dir() -> Path:
    return factory_home() / "state"


def _line_hash(seq: int, prev_hash: str, event: dict) -> str:
    return hashlib.sha256(
        canonical_json({"seq": seq, "prev_hash": prev_hash, "event": event})
    ).hexdigest()


def iter_records(path: Path | None = None) -> Iterator[dict]:
    path = path or events_path()
    if not path.exists():
        return
    with path.open() as fh:
        for raw in fh:
            raw = raw.strip()
            if raw:
                yield json.loads(raw)


def event_ids() -> set[str]:
    return {rec["event"]["event_id"] for rec in iter_records()}


def head() -> tuple[int, str] | None:
    last = None
    for rec in iter_records():
        last = rec
    return (last["seq"], last["hash"]) if last else None


def append_event(event: dict) -> dict:
    validate_event(event)
    path = events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = head()
        seq = current[0] + 1 if current else 1
        prev_hash = current[1] if current else GENESIS
        record = {
            "seq": seq,
            "prev_hash": prev_hash,
            "hash": _line_hash(seq, prev_hash, event),
            "event": event,
        }
        with path.open("ab") as fh:
            fh.write(canonical_json(record) + b"\n")
            fh.flush()
            os.fsync(fh.fileno())
    return record


def _parse_records(path: Path, tolerate_torn_tail: bool = False) -> tuple[list[dict], list[str]]:
    """Parse records from path, handling unparseable lines.

    Returns (records, errors). If errors is non-empty, records is incomplete.
    If tolerate_torn_tail is True, silently drops one unparseable final line.
    """
    errors: list[str] = []
    raw_lines = []
    with path.open() as fh:
        for raw in fh:
            raw = raw.strip()
            if raw:
                raw_lines.append(raw)

    records = []
    for i, raw in enumerate(raw_lines):
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            # If this is the last line and tolerate_torn_tail is set, drop it silently.
            if tolerate_torn_tail and i == len(raw_lines) - 1:
                break
            # Any other unparseable line is an error.
            errors.append(f"line {i + 1}: unparseable JSON ({exc})")
            break
    return records, errors


def verify_chain(path: Path | None = None, tolerate_torn_tail: bool = False) -> list[str]:
    errors: list[str] = []
    path = path or events_path()
    if not path.exists():
        return errors

    records, parse_errors = _parse_records(path, tolerate_torn_tail=tolerate_torn_tail)
    if parse_errors:
        return parse_errors

    # Verify the parsed chain.
    expected_seq, expected_prev = 1, GENESIS
    for rec in records:
        seq = rec.get("seq")
        if not isinstance(seq, int) or seq != expected_seq:
            errors.append(f"seq {seq}: expected seq {expected_seq} (line missing or reordered)")
            return errors
        if rec.get("prev_hash") != expected_prev:
            errors.append(f"seq {seq}: prev_hash mismatch (chain broken)")
            return errors
        event = rec.get("event")
        if not isinstance(event, dict):
            errors.append(f"seq {seq}: event missing or not an object (line tampered)")
            return errors
        if rec.get("hash") != _line_hash(seq, rec["prev_hash"], event):
            errors.append(f"seq {seq}: hash mismatch (line tampered)")
            return errors
        try:
            validate_event(event)
        except Exception as exc:  # noqa: BLE001 — report, don't crash the walk
            errors.append(f"seq {seq}: schema violation: {exc}")
            return errors
        expected_seq, expected_prev = seq + 1, rec["hash"]
    return errors
