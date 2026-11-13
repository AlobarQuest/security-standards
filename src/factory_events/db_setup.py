"""Create the chain's table, triggers and two roles: the roles script for FE-4.

    FACTORY_EVENTS_OWNER_DSN=... python -m factory_events.db_setup

The database owner runs this once, by hand, as the announced act ADR-0059 amendment 7 names
(act 2). It never runs in an image build step or at start-up, and nothing else in
factory_events runs DDL. It applies chain_schema.sql in one transaction and sets no password:
set each role's password afterwards with psql's `\\password <role>`.
"""

import os
import sys
from pathlib import Path

from factory_events.jsonlog import log

OWNER_DSN_VAR = "FACTORY_EVENTS_OWNER_DSN"
SCHEMA_SQL = Path(__file__).with_name("chain_schema.sql")


def setup(owner_dsn: str) -> None:
    import psycopg  # lazy: the file chain must not require it

    with psycopg.connect(owner_dsn, connect_timeout=10, application_name="factory_events") as conn:
        conn.execute(SCHEMA_SQL.read_bytes())  # one transaction: committed on a clean exit


def main() -> int:
    dsn = os.environ.get(OWNER_DSN_VAR)
    if not dsn:
        print(f"setup failed: {OWNER_DSN_VAR} is not set", file=sys.stderr)
        return 1
    try:
        setup(dsn)
    except Exception as exc:  # reported by type only: the driver's text can hold the DSN
        log("setup", "failure", error_type=type(exc).__name__)
        print(f"setup failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    log("setup", "ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
