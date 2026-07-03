"""Ship the JSONL store to the local Postgres projection + anchor the head.

The projection is disposable (--rebuild replays the JSONL). chain_heads is the
tamper-evidence anchor: --rebuild NEVER touches it, and verify --against-anchor
checks the chain still contains the last anchored (seq, head_hash).
"""

import os

from factory_events import store

DDL = """
CREATE TABLE IF NOT EXISTS factory_events (
    event_id       text PRIMARY KEY,
    seq            bigint NOT NULL,
    ts             timestamptz NOT NULL,
    actor          text NOT NULL,
    action         text NOT NULL,
    target         text,
    work_package   text,
    input_revision text,
    result         text NOT NULL,
    source_system  text NOT NULL,
    correlation_id text,
    event          jsonb NOT NULL,
    hash           text NOT NULL,
    prev_hash      text NOT NULL
);
CREATE TABLE IF NOT EXISTS chain_heads (
    id          bigserial PRIMARY KEY,
    anchored_at timestamptz NOT NULL DEFAULT now(),
    seq         bigint NOT NULL,
    head_hash   text NOT NULL
);
"""

INSERT = """
INSERT INTO factory_events (event_id, seq, ts, actor, action, target, work_package,
    input_revision, result, source_system, correlation_id, event, hash, prev_hash)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (event_id) DO NOTHING
"""


def _dsn(dsn: str | None) -> str:
    resolved = dsn or os.environ.get("FACTORY_DB_DSN", "")
    if not resolved:
        raise RuntimeError("FACTORY_DB_DSN not set (source ~/.factory/env)")
    return resolved


def _connect(dsn: str | None):
    import psycopg  # lazy: emit/adapt/verify must not require it

    return psycopg.connect(_dsn(dsn))


def last_anchor(dsn: str | None = None) -> tuple[int, str] | None:
    with _connect(dsn) as conn:
        conn.execute(DDL)
        row = conn.execute(
            "SELECT seq, head_hash FROM chain_heads ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return (row[0], row[1]) if row else None


def ship(dsn: str | None = None, rebuild: bool = False) -> tuple[int, tuple[int, str] | None]:
    from psycopg.types.json import Json  # lazy, with psycopg

    inserted = 0
    with _connect(dsn) as conn:
        conn.execute(DDL)
        if rebuild:
            conn.execute("TRUNCATE factory_events")  # never chain_heads
        with conn.cursor() as cur:
            for rec in store.iter_records():
                ev = rec["event"]
                cur.execute(INSERT, (
                    ev["event_id"], rec["seq"], ev["timestamp"], ev["actor"], ev["action"],
                    ev["target"], ev["work_package"], ev["input_revision"], ev["result"],
                    ev["source"]["system"], ev["correlation_id"], Json(ev),
                    rec["hash"], rec["prev_hash"],
                ))
                inserted += cur.rowcount
        current = store.head()
        if current:
            conn.execute(
                "INSERT INTO chain_heads (seq, head_hash) VALUES (%s, %s)", current
            )
        conn.commit()
    return inserted, current
