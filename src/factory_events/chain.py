"""Which chain a command uses: the database when a DSN is set, else the file.

With neither DSN set, every function here is the file store's, unchanged. With either set,
the database is the chain, and a command missing the DSN it needs fails closed: it never
falls back to the file (orchestrator ADR-0055 amendment 24 items 7, 8 and 10).

The DSNs come from the environment only, and nothing here prints one.
"""

import json
import os

from factory_events import db, store

APPEND_DSN_VAR = "FACTORY_EVENTS_APPEND_DSN"
READ_DSN_VAR = "FACTORY_EVENTS_READ_DSN"
# The history import's DSN. Its role is Devon's decision before FE-5, so the import reads
# its own variable and never defaults to the append DSN.
IMPORT_DSN_VAR = "FACTORY_EVENTS_IMPORT_DSN"


def _env(name: str) -> str | None:
    return os.environ.get(name) or None


def database_mode() -> bool:
    return bool(_env(APPEND_DSN_VAR) or _env(READ_DSN_VAR))


def _append_dsn() -> str:
    dsn = _env(APPEND_DSN_VAR)
    if not dsn:
        raise db.ChainError(f"{READ_DSN_VAR} is set but {APPEND_DSN_VAR} isn't: refusing to append")
    return dsn


def verify_dsn() -> str | None:
    """The DSN a verify reads under: the read DSN, else the append DSN (the nightly holds only
    the append DSN, and its role can SELECT). None in file mode."""
    return _env(READ_DSN_VAR) or _env(APPEND_DSN_VAR)


def import_dsn() -> str:
    dsn = _env(IMPORT_DSN_VAR)
    if not dsn:
        raise db.ChainError(f"{IMPORT_DSN_VAR} is not set")
    return dsn


def append_event(event: dict) -> dict:
    if not database_mode():
        return store.append_event(event)
    return db.append_event(_append_dsn(), event)


def event_ids() -> set[str]:
    if not database_mode():
        return store.event_ids()
    return db.event_ids(_append_dsn())


# The anchor of the database chain's head, kept outside that database: on the verifying
# machine, in the backed-up ~/.factory tree. A rewrite by anyone holding the database's owner
# can't reach it, so a rewritten chain no longer holds the anchored (seq, hash).
def anchor_path():
    return store.state_dir() / "chain-anchor.json"


def read_anchor() -> tuple[int, str] | None:
    path = anchor_path()
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return int(data["seq"]), str(data["hash"])


def write_anchor(head: tuple[int, str]) -> None:
    path = anchor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"seq": head[0], "hash": head[1]}))
    os.replace(tmp, path)
