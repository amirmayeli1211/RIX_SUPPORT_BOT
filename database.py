"""SQLite connection management.

WAL mode because the long-polling bot thread and the background scheduler
thread write concurrently. Connections are short-lived: open -> work -> commit
-> close, so nothing ever holds a lock across a network call.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterable

import config
import migrations


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def tx():
    """One transaction, committed only if the block succeeds."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> list[int]:
    """Create directories and apply migrations. Returns applied versions."""
    config.ensure_dirs()
    with tx() as conn:
        return migrations.migrate(conn)


def q(sql: str, args: Iterable[Any] = ()) -> list[dict]:
    """Rows as plain dicts: sqlite3.Row has no .get(), and every caller
    (formatters especially) treats rows as mappings."""
    with tx() as conn:
        cur = conn.execute(sql, tuple(args))
        return [dict(r) for r in cur.fetchall()]


def one(sql: str, args: Iterable[Any] = ()) -> dict | None:
    with tx() as conn:
        row = conn.execute(sql, tuple(args)).fetchone()
        return dict(row) if row is not None else None


def scalar(sql: str, args: Iterable[Any] = (), default=0):
    # Raw tuple access: the selected column is unnamed (COUNT(*), AVG(...)).
    conn = connect()
    try:
        conn.row_factory = None
        row = conn.execute(sql, tuple(args)).fetchone()
    finally:
        conn.close()
    if row is None or row[0] is None:
        return default
    return row[0]


def ex(sql: str, args: Iterable[Any] = ()) -> int:
    """Execute a write; returns lastrowid (0 for non-inserts)."""
    with tx() as conn:
        cur = conn.execute(sql, tuple(args))
        return int(cur.lastrowid or 0)


def now() -> int:
    return int(time.time())


def healthy() -> bool:
    """Cheap probe used by /health - must never raise."""
    try:
        return one("SELECT 1 AS ok") is not None
    except Exception:
        return False
