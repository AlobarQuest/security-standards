"""Structured JSON log records on stdout for the database chain paths.

ADR-0055 amendment 24 item 13: a record names the operation, its outcome, the event id,
the `seq`, a prefix of the head hash and an error's type. Never pass a password, a
connection's parameters or a driver error's text: a connection error can repeat them.
"""

import json
import sys
from datetime import UTC, datetime

HEAD_PREFIX = 12


def log(op: str, outcome: str, **fields: object) -> None:
    record = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "logger": "factory_events",
        "op": op,
        "outcome": outcome,
        **{key: value for key, value in fields.items() if value is not None},
    }
    print(json.dumps(record, sort_keys=True), file=sys.stdout, flush=True)


def head_prefix(hash_hex: str | None) -> str | None:
    return hash_hex[:HEAD_PREFIX] if hash_hex else None
