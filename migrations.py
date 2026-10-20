"""Ordered schema migrations.

Rules:
  * Never edit a released step - history must stay reproducible.
  * Append a new (version, [statements]) tuple instead.
  * Each step runs inside the caller's transaction: a failing statement rolls
    the whole step back, so a half-applied schema can never happen.
"""
from __future__ import annotations

import time

# (version, [sql, ...])
MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, [
        """CREATE TABLE IF NOT EXISTS tenants (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL,
            slug         TEXT    UNIQUE,
            owner_tg_id  INTEGER,
            status       TEXT    NOT NULL DEFAULT 'active',
            created_at   INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS members (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            tg_id       INTEGER NOT NULL,
            role        TEXT    NOT NULL DEFAULT 'agent',
            name        TEXT,
            username    TEXT,
            capacity    INTEGER NOT NULL DEFAULT 10,
            active      INTEGER NOT NULL DEFAULT 1,
            created_at  INTEGER NOT NULL,
            UNIQUE (tenant_id, tg_id)
        )""",
        """CREATE TABLE IF NOT EXISTS customers (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id    INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            tg_id        INTEGER NOT NULL,
            name         TEXT,
            username     TEXT,
            tag          TEXT,
            verified_at  INTEGER,
            created_at   INTEGER NOT NULL,
            UNIQUE (tenant_id, tg_id)
        )""",
        """CREATE TABLE IF NOT EXISTS tickets (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id            INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            customer_id          INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            number               INTEGER NOT NULL,
            subject              TEXT,
            priority             TEXT    NOT NULL DEFAULT 'normal',
            status               TEXT    NOT NULL DEFAULT 'open',
            assigned_to          INTEGER,
            rating               INTEGER,
            sla_notified_at      INTEGER,
            created_at           INTEGER NOT NULL,
            first_reply_at       INTEGER,
            last_customer_msg_at INTEGER,
            closed_at            INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id   INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            sender_type TEXT    NOT NULL,
            sender_id   INTEGER,
            body        TEXT,
            file_id     TEXT,
            file_type   TEXT,
            is_internal INTEGER NOT NULL DEFAULT 0,
            created_at  INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS settings (
            tenant_id INTEGER NOT NULL,
            key       TEXT    NOT NULL,
            value     TEXT,
            PRIMARY KEY (tenant_id, key)
        )""",
        """CREATE TABLE IF NOT EXISTS verify_codes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   INTEGER,
            tg_id       INTEGER NOT NULL,
            code        TEXT    NOT NULL,
            purpose     TEXT    NOT NULL,
            created_at  INTEGER NOT NULL,
            consumed_at INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS fsm_states (
            tg_id      INTEGER PRIMARY KEY,
            tenant_id  INTEGER,
            state      TEXT,
            data       TEXT,
            updated_at INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS audit (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   INTEGER,
            actor_tg_id INTEGER,
            action      TEXT    NOT NULL,
            target      TEXT,
            detail      TEXT,
            created_at  INTEGER NOT NULL
        )""",
    ]),
    (2, [
        "CREATE INDEX IF NOT EXISTS idx_tickets_tenant ON tickets(tenant_id, status, id)",
        "CREATE INDEX IF NOT EXISTS idx_tickets_customer ON tickets(customer_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_tickets_assigned ON tickets(assigned_to, status)",
        "CREATE INDEX IF NOT EXISTS idx_messages_ticket ON messages(ticket_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_customers_tenant ON customers(tenant_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_members_tenant ON members(tenant_id, active)",
        "CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit(tenant_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_verify_live ON verify_codes(tg_id, purpose, consumed_at)",
    ]),
]


def migrate(conn) -> list[int]:
    """Apply pending steps; return the versions applied. Idempotent."""
    applied: list[int] = []
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
    )
    seen = {int(r[0]) for r in conn.execute("SELECT version FROM schema_version")}
    for version, statements in MIGRATIONS:
        if version in seen:
            continue
        for sql in statements:
            conn.execute(sql)
        conn.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
            (version, int(time.time())),
        )
        applied.append(version)
    return applied
