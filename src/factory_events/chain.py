"""Which chain a command uses: the database when a role's password is set, else the file.

With neither password set, every function here is the file store's, unchanged. With either set,
the database is the chain, and a command missing a setting it needs fails closed: it never
falls back to the file (orchestrator ADR-0055 amendment 24 items 7, 8 and 10).

Each BWS secret holds only its role's password; the address is plain configuration, and this
module builds each connection from those parts (amendment 26). It never formats a URL, so no
string holds a password and an address together, and no message here carries a value.
"""

import json
import os

from factory_events import db, store

APPEND_PASSWORD_VAR = "FACTORY_EVENTS_APPEND_PASSWORD"
READ_PASSWORD_VAR = "FACTORY_EVENTS_READ_PASSWORD"
DB_HOST_VAR = "FACTORY_EVENTS_DB_HOST"
DB_PORT_VAR = "FACTORY_EVENTS_DB_PORT"
DB_NAME_VAR = "FACTORY_EVENTS_DB_NAME"
# The roles chain_schema.sql creates. Constants, not settings: a setting could only name a
# role the schema didn't create.
APPEND_ROLE = "factory_events_append"
READ_ROLE = "factory_events_read"
# Whole-DSN variables, retired by amendment 26. A set one refuses: ignoring it would drop that
# process to the file chain without a word.
RETIRED_VARS = (
    "FACTORY_EVENTS_APPEND_DSN",
    "FACTORY_EVENTS_READ_DSN",
    "FACTORY_EVENTS_IMPORT_DSN",
)
_PASSWORD_VARS = {APPEND_ROLE: APPEND_PASSWORD_VAR, READ_ROLE: READ_PASSWORD_VAR}


def _env(name: str) -> str | None:
    return os.environ.get(name) or None


def _refuse_retired() -> None:
    for name in RETIRED_VARS:
        if _env(name):
            raise db.ChainError(f"{name} is retired: set the role's password and the DB settings")


def database_mode() -> bool:
    """True when either role's password is set. Raises ChainError for a set retired variable."""
    _refuse_retired()
    return bool(_env(APPEND_PASSWORD_VAR) or _env(READ_PASSWORD_VAR))


def _setting(name: str) -> str:
    value = _env(name)
    if not value:
        raise db.ChainError(f"{name} is not set")
    return value


def connection_params(role: str) -> db.ConnectParams:
    """The connection for one role: its password and the three settings, each required."""
    _refuse_retired()
    password = _setting(_PASSWORD_VARS[role])
    return db.ConnectParams(
        host=_setting(DB_HOST_VAR),
        port=_setting(DB_PORT_VAR),
        dbname=_setting(DB_NAME_VAR),
        user=role,
        password=password,
    )


def verify_params() -> db.ConnectParams | None:
    """The connection a verify reads under: the read role's, else the append role's (the
    nightly holds only the append password, and its role can SELECT). None in file mode."""
    if not database_mode():
        return None
    return connection_params(READ_ROLE if _env(READ_PASSWORD_VAR) else APPEND_ROLE)


def append_event(event: dict) -> dict:
    if not database_mode():
        return store.append_event(event)
    return db.append_event(connection_params(APPEND_ROLE), event)


def event_ids() -> set[str]:
    if not database_mode():
        return store.event_ids()
    return db.event_ids(connection_params(APPEND_ROLE))


# The anchor of the database chain's head, kept outside that database: on the verifying
# machine, in the backed-up ~/.factory tree. A rewrite by anyone holding the database's owner
# can't reach it, so a rewritten chain no longer holds the anchored (seq, hash).
def anchor_path():
    return store.state_dir() / "chain-anchor.json"


def read_anchor() -> tuple[int, str] | None:
    path = anchor_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return int(data["seq"]), str(data["hash"])
    except (ValueError, KeyError, TypeError) as exc:
        raise db.ChainError(f"the anchor at {path} is unreadable ({type(exc).__name__})") from exc


def write_anchor(head: tuple[int, str]) -> None:
    path = anchor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as fh:
        fh.write(json.dumps({"seq": head[0], "hash": head[1]}))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
