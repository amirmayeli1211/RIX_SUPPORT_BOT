"""Repositories - all SQL lives here.

Every function is a thin, pure data operation: no Telegram calls, no business
rules, no formatting. Handlers and *_manager modules compose these.
Every query is tenant-scoped where a tenant exists - that is the multi-tenant
boundary, and it is enforced here rather than trusted from callers.
"""
from __future__ import annotations

import database as db
from models import Role, Status

# ------------------------------------------------------------------ plans

def list_plans(active_only: bool = True):
    if active_only:
        return db.q("SELECT * FROM plans WHERE active=1 ORDER BY max_shops, id")
    return db.q("SELECT * FROM plans ORDER BY id")


def get_plan(plan_id: int):
    return db.one("SELECT * FROM plans WHERE id=?", (plan_id,))


# ---------------------------------------------------------------- accounts

def create_account(tg_id: int, plan_id: int, name=None) -> int:
    return db.ex(
        "INSERT INTO accounts(tg_id, name, plan_id, created_at) VALUES (?,?,?,?)",
        (tg_id, name, plan_id, db.now()),
    )


def get_account(account_id: int):
    """Account row joined with its plan (so max_shops/plan_name are present)."""
    return db.one(
        "SELECT a.*, p.name AS plan_name, p.max_shops FROM accounts a"
        " LEFT JOIN plans p ON p.id=a.plan_id WHERE a.id=?", (account_id,))


def account_by_tg(tg_id: int):
    """Active (verified) account for this telegram user, newest first."""
    return db.one(
        "SELECT a.*, p.name AS plan_name, p.max_shops FROM accounts a"
        " LEFT JOIN plans p ON p.id=a.plan_id"
        " WHERE a.tg_id=? AND a.status='active' ORDER BY a.id DESC LIMIT 1",
        (tg_id,))


def all_accounts():
    return db.q(
        "SELECT a.*, p.name AS plan_name, p.max_shops FROM accounts a"
        " LEFT JOIN plans p ON p.id=a.plan_id ORDER BY a.id DESC")


def set_account_status(account_id: int, status: str) -> None:
    db.ex("UPDATE accounts SET status=? WHERE id=?", (status, account_id))


def set_account_plan(account_id: int, plan_id: int) -> None:
    db.ex("UPDATE accounts SET plan_id=? WHERE id=?", (plan_id, account_id))


def mark_account_verified(account_id: int) -> None:
    db.ex("UPDATE accounts SET verified_at=?, status='active' WHERE id=?",
          (db.now(), account_id))


def account_shops(account_id: int):
    """Shops (tenants) owned by this account."""
    return db.q(
        "SELECT * FROM tenants WHERE account_id=? ORDER BY id", (account_id,))


def account_shop_count(account_id: int) -> int:
    return int(db.scalar("SELECT COUNT(*) FROM tenants WHERE account_id=?",
                         (account_id,), 0))


# ----------------------------------------------------------------- tenants

def create_tenant(name: str, owner_tg_id: int = 0, slug: str | None = None,
                  account_id: int | None = None) -> int:
    return db.ex(
        "INSERT INTO tenants(name, slug, owner_tg_id, account_id, created_at)"
        " VALUES (?,?,?,?,?)",
        (name, slug, owner_tg_id, account_id, db.now()),
    )


def get_tenant(tenant_id: int):
    return db.one("SELECT * FROM tenants WHERE id=?", (tenant_id,))


def list_tenants(status: str | None = None):
    if status:
        return db.q("SELECT * FROM tenants WHERE status=? ORDER BY id", (status,))
    return db.q("SELECT * FROM tenants ORDER BY id")


def set_tenant_status(tenant_id: int, status: str) -> None:
    db.ex("UPDATE tenants SET status=? WHERE id=?", (status, tenant_id))


def count_tenants() -> int:
    return int(db.scalar("SELECT COUNT(*) FROM tenants"))


# ----------------------------------------------------------------- members

def add_member(tenant_id: int, tg_id: int, role: str = Role.AGENT, name=None,
               username=None, capacity: int = 10) -> int:
    db.ex(
        "INSERT INTO members(tenant_id, tg_id, role, name, username, capacity, created_at)"
        " VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(tenant_id, tg_id) DO UPDATE SET role=excluded.role, active=1,"
        " capacity=excluded.capacity",
        (tenant_id, tg_id, role, name, username, capacity, db.now()),
    )
    return int(db.scalar("SELECT id FROM members WHERE tenant_id=? AND tg_id=?",
                         (tenant_id, tg_id), 0))


def member(tenant_id: int, tg_id: int):
    return db.one("SELECT * FROM members WHERE tenant_id=? AND tg_id=?", (tenant_id, tg_id))


def memberships(tg_id: int):
    """All active memberships of a telegram user, best role first."""
    return db.q(
        "SELECT m.*, t.name AS tenant_name, t.status AS tenant_status"
        " FROM members m JOIN tenants t ON t.id=m.tenant_id"
        " WHERE m.tg_id=? AND m.active=1 ORDER BY"
        " CASE m.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1"
        " WHEN 'agent' THEN 2 ELSE 3 END, m.id",
        (tg_id,),
    )


def best_membership(tg_id: int):
    rows = memberships(tg_id)
    return rows[0] if rows else None


def list_members(tenant_id: int, roles=None, active_only: bool = True):
    sql = "SELECT * FROM members WHERE tenant_id=?"
    args: list = [tenant_id]
    if active_only:
        sql += " AND active=1"
    if roles:
        marks = ",".join("?" for _ in roles)
        sql += f" AND role IN ({marks})"
        args.extend(roles)
    return db.q(sql + " ORDER BY role, id", tuple(args))


def set_member_role(tenant_id: int, tg_id: int, role: str) -> None:
    db.ex("UPDATE members SET role=? WHERE tenant_id=? AND tg_id=?", (role, tenant_id, tg_id))


def set_member_capacity(tenant_id: int, tg_id: int, capacity: int) -> None:
    db.ex("UPDATE members SET capacity=? WHERE tenant_id=? AND tg_id=?",
          (capacity, tenant_id, tg_id))


def set_member_active(tenant_id: int, tg_id: int, active: int) -> None:
    db.ex("UPDATE members SET active=? WHERE tenant_id=? AND tg_id=?",
          (1 if active else 0, tenant_id, tg_id))


# --------------------------------------------------------------- customers

def add_customer(tenant_id: int, tg_id: int, name=None, username=None, verified_at=None) -> int:
    db.ex(
        "INSERT INTO customers(tenant_id, tg_id, name, username, verified_at, created_at)"
        " VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(tenant_id, tg_id) DO UPDATE SET"
        " name=COALESCE(excluded.name, customers.name),"
        " username=COALESCE(excluded.username, customers.username)",
        (tenant_id, tg_id, name, username, verified_at, db.now()),
    )
    return int(db.scalar("SELECT id FROM customers WHERE tenant_id=? AND tg_id=?",
                         (tenant_id, tg_id), 0))


def get_customer(customer_id: int):
    return db.one("SELECT * FROM customers WHERE id=?", (customer_id,))


def customer_by_tg(tg_id: int, tenant_id: int | None = None):
    """Verified customer record. With tenant_id, scoped to that tenant."""
    if tenant_id:
        return db.one(
            "SELECT * FROM customers WHERE tg_id=? AND tenant_id=? AND verified_at IS NOT NULL"
            " ORDER BY id LIMIT 1", (tg_id, tenant_id))
    return db.one(
        "SELECT c.*, t.name AS tenant_name FROM customers c"
        " JOIN tenants t ON t.id=c.tenant_id"
        " WHERE c.tg_id=? AND c.verified_at IS NOT NULL ORDER BY c.id LIMIT 1",
        (tg_id,),
    )


def mark_customer_verified(tenant_id: int, tg_id: int) -> None:
    db.ex("UPDATE customers SET verified_at=? WHERE tenant_id=? AND tg_id=?",
          (db.now(), tenant_id, tg_id))


def ensure_invite_code(tenant_id: int) -> str:
    """Stable per-tenant invite code, generated once."""
    row = db.one("SELECT invite_code FROM tenants WHERE id=?", (tenant_id,))
    code = (row or {}).get("invite_code")
    if not code:
        import secrets
        code = secrets.token_urlsafe(8)
        db.ex("UPDATE tenants SET invite_code=? WHERE id=?", (code, tenant_id))
    return code


def ensure_staff_code(tenant_id: int) -> str:
    """Stable per-tenant staff invite code, generated once."""
    row = db.one("SELECT staff_code FROM tenants WHERE id=?", (tenant_id,))
    code = (row or {}).get("staff_code")
    if not code:
        import secrets
        code = secrets.token_urlsafe(8)
        db.ex("UPDATE tenants SET staff_code=? WHERE id=?", (code, tenant_id))
    return code


def bind_group(tenant_id: int, group_chat_id: int) -> None:
    db.ex("UPDATE tenants SET group_chat_id=? WHERE id=?", (group_chat_id, tenant_id))


def unbind_group(tenant_id: int, group_chat_id: int) -> None:
    db.ex("UPDATE tenants SET group_chat_id=NULL WHERE id=? AND group_chat_id=?",
          (tenant_id, group_chat_id))


def tenant_by_group(group_chat_id: int):
    return db.one("SELECT * FROM tenants WHERE group_chat_id=?", (group_chat_id,))


def customer_any(tenant_id: int, tg_id: int):
    """Customer row regardless of verification (group members are pre-trusted)."""
    return db.one(
        "SELECT * FROM customers WHERE tg_id=? AND tenant_id=? ORDER BY id LIMIT 1",
        (tg_id, tenant_id))


def mark_ticket_group(ticket_id: int, group_chat_id: int, msg_id: int) -> None:
    db.ex("UPDATE tickets SET group_chat_id=?, last_group_msg_id=? WHERE id=?",
          (group_chat_id, msg_id, ticket_id))


def broadcast_targets(tenant_id: int, tag: str | None = None):
    """Verified, unblocked customers to receive a broadcast."""
    if tag:
        return db.q("SELECT tg_id FROM customers WHERE tenant_id=? AND verified_at IS NOT NULL"
                    " AND blocked=0 AND tag=?", (tenant_id, tag))
    return db.q("SELECT tg_id FROM customers WHERE tenant_id=? AND verified_at IS NOT NULL"
                " AND blocked=0", (tenant_id,))


def customer_tags(tenant_id: int) -> list[str]:
    return [r["tag"] for r in db.q(
        "SELECT DISTINCT tag FROM customers WHERE tenant_id=? AND tag IS NOT NULL"
        " AND tag != '' ORDER BY tag", (tenant_id,))]


def set_customer_blocked(customer_id: int, blocked: int) -> None:
    db.ex("UPDATE customers SET blocked=? WHERE id=?", (1 if blocked else 0, customer_id))


def delete_ticket(ticket_id: int) -> None:
    db.ex("DELETE FROM tickets WHERE id=?", (ticket_id,))


def set_customer_tag(customer_id: int, tag) -> None:
    db.ex("UPDATE customers SET tag=? WHERE id=?", (tag, customer_id))


def delete_customer(customer_id: int) -> None:
    db.ex("DELETE FROM customers WHERE id=?", (customer_id,))


def list_customers(tenant_id: int, limit: int = 50, offset: int = 0):
    return db.q(
        "SELECT c.*, (SELECT COUNT(*) FROM tickets tk WHERE tk.customer_id=c.id) AS ticket_count"
        " FROM customers c WHERE c.tenant_id=? ORDER BY c.id DESC LIMIT ? OFFSET ?",
        (tenant_id, limit, offset))


def find_customers(tenant_id: int, needle: str):
    like = f"%{needle}%"
    return db.q(
        "SELECT c.*, (SELECT COUNT(*) FROM tickets tk WHERE tk.customer_id=c.id) AS ticket_count"
        " FROM customers c WHERE c.tenant_id=? AND (c.name LIKE ? OR c.username LIKE ?"
        " OR CAST(c.tg_id AS TEXT) LIKE ? OR c.tag LIKE ?) ORDER BY c.id DESC LIMIT 20",
        (tenant_id, like, like, like, like))


def count_customers(tenant_id: int) -> int:
    return int(db.scalar("SELECT COUNT(*) FROM customers WHERE tenant_id=?", (tenant_id,)))


def count_unverified(tenant_id: int) -> int:
    return int(db.scalar(
        "SELECT COUNT(*) FROM customers WHERE tenant_id=? AND verified_at IS NULL",
        (tenant_id,)))


# ----------------------------------------------------------------- tickets

def next_ticket_number(tenant_id: int) -> int:
    return int(db.scalar("SELECT COALESCE(MAX(number),0)+1 FROM tickets WHERE tenant_id=?",
                         (tenant_id,), 1))


def create_ticket(tenant_id: int, customer_id: int, subject: str, priority: str = "normal") -> int:
    now = db.now()
    number = next_ticket_number(tenant_id)
    return db.ex(
        "INSERT INTO tickets(tenant_id, customer_id, number, subject, priority, created_at,"
        " last_customer_msg_at) VALUES (?,?,?,?,?,?,?)",
        (tenant_id, customer_id, number, subject, priority, now, now),
    )


def get_ticket(ticket_id: int):
    return db.one(
        "SELECT tk.*, c.tg_id AS customer_tg_id, c.name AS customer_name,"
        " c.username AS customer_username, c.verified_at AS customer_verified,"
        " c.blocked AS customer_blocked, t.name AS tenant_name"
        " FROM tickets tk"
        " JOIN customers c ON c.id=tk.customer_id"
        " JOIN tenants t ON t.id=tk.tenant_id WHERE tk.id=?",
        (ticket_id,),
    )


def list_tickets(tenant_id: int, status: str | None = None, assigned_to: int | None = None,
                 limit: int = 50, offset: int = 0):
    sql = ("SELECT tk.*, c.tg_id AS customer_tg_id, c.name AS customer_name,"
           " c.username AS customer_username FROM tickets tk"
           " JOIN customers c ON c.id=tk.customer_id WHERE tk.tenant_id=?")
    args: list = [tenant_id]
    if status:
        sql += " AND tk.status=?"
        args.append(status)
    if assigned_to:
        sql += " AND tk.assigned_to=?"
        args.append(assigned_to)
    sql += " ORDER BY tk.id DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    return db.q(sql, tuple(args))


def count_tickets(tenant_id: int, status: str | None = None, assigned_to: int | None = None) -> int:
    sql = "SELECT COUNT(*) FROM tickets WHERE tenant_id=?"
    args: list = [tenant_id]
    if status:
        sql += " AND status=?"
        args.append(status)
    if assigned_to:
        sql += " AND assigned_to=?"
        args.append(assigned_to)
    return int(db.scalar(sql, tuple(args)))


def customer_tickets(customer_id: int, limit: int = 20):
    return db.q("SELECT * FROM tickets WHERE customer_id=? ORDER BY id DESC LIMIT ?",
                (customer_id, limit))


def open_ticket_for(customer_id: int):
    return db.one(
        "SELECT * FROM tickets WHERE customer_id=? AND status!=? ORDER BY id DESC LIMIT 1",
        (customer_id, Status.CLOSED))


def set_ticket_status(ticket_id: int, status: str) -> None:
    if status == Status.CLOSED:
        db.ex("UPDATE tickets SET status=?, closed_at=? WHERE id=?", (status, db.now(), ticket_id))
    else:
        db.ex("UPDATE tickets SET status=?, closed_at=NULL WHERE id=?", (status, ticket_id))


def set_assignee(ticket_id: int, tg_id: int | None) -> None:
    db.ex("UPDATE tickets SET assigned_to=? WHERE id=?", (tg_id, ticket_id))


def set_priority(ticket_id: int, priority: str) -> None:
    db.ex("UPDATE tickets SET priority=? WHERE id=?", (priority, ticket_id))


def set_rating(ticket_id: int, rating: int) -> None:
    db.ex("UPDATE tickets SET rating=? WHERE id=?", (rating, ticket_id))


def touch_customer_msg(ticket_id: int) -> None:
    db.ex("UPDATE tickets SET last_customer_msg_at=? WHERE id=?", (db.now(), ticket_id))


def mark_first_reply(ticket_id: int) -> None:
    db.ex("UPDATE tickets SET first_reply_at=COALESCE(first_reply_at,?) WHERE id=?",
          (db.now(), ticket_id))


def mark_sla_notified(ticket_id: int) -> None:
    db.ex("UPDATE tickets SET sla_notified_at=? WHERE id=?", (db.now(), ticket_id))


def overdue_open_tickets(tenant_id: int, older_than_ts: int):
    """Open tickets whose last customer message is older than the cutoff and
    that were not already reminded."""
    return db.q(
        "SELECT tk.*, c.tg_id AS customer_tg_id, c.name AS customer_name,"
        " c.username AS customer_username, t.name AS tenant_name"
        " FROM tickets tk JOIN customers c ON c.id=tk.customer_id"
        " JOIN tenants t ON t.id=tk.tenant_id"
        " WHERE tk.tenant_id=? AND tk.status=?"
        " AND COALESCE(tk.last_customer_msg_at, tk.created_at) < ?"
        " AND (tk.sla_notified_at IS NULL OR tk.sla_notified_at <"
        "      COALESCE(tk.last_customer_msg_at, tk.created_at))"
        " ORDER BY tk.id LIMIT 50",
        (tenant_id, Status.OPEN, older_than_ts))


def first_reply_seconds(tenant_id: int) -> float:
    """Average first-reply time in seconds across answered tickets."""
    return float(db.scalar(
        "SELECT AVG(first_reply_at - created_at) FROM tickets"
        " WHERE tenant_id=? AND first_reply_at IS NOT NULL", (tenant_id,), 0) or 0)


# ---------------------------------------------------------------- messages

def add_message(ticket_id: int, sender_type: str, sender_id, body=None, file_id=None,
                file_type=None, internal: bool = False) -> int:
    return db.ex(
        "INSERT INTO messages(ticket_id, sender_type, sender_id, body, file_id, file_type,"
        " is_internal, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (ticket_id, sender_type, sender_id, body, file_id, file_type,
         1 if internal else 0, db.now()),
    )


def list_messages(ticket_id: int, include_internal: bool = False, limit: int = 200):
    if include_internal:
        return db.q("SELECT * FROM messages WHERE ticket_id=? ORDER BY id LIMIT ?",
                    (ticket_id, limit))
    return db.q("SELECT * FROM messages WHERE ticket_id=? AND is_internal=0 ORDER BY id LIMIT ?",
                (ticket_id, limit))


def last_customer_message_body(ticket_id: int):
    return db.one(
        "SELECT * FROM messages WHERE ticket_id=? AND sender_type='customer'"
        " AND is_internal=0 ORDER BY id DESC LIMIT 1", (ticket_id,))


# --------------------------------------------------------------- settings

DEFAULT_SETTINGS = {
    "welcome_text": "سلام، به پشتیبانی خوش آمدی. از منوی زیر انتخاب کن:",
    "business_hours": "",          # "" = 24/7, else HH:MM-HH:MM
    "outside_hours_text": "",
    "sla_minutes": "60",
    "support_url": "",
}


def seed_settings(tenant_id: int) -> None:
    for key, value in DEFAULT_SETTINGS.items():
        db.ex("INSERT OR IGNORE INTO settings(tenant_id, key, value) VALUES (?,?,?)",
              (tenant_id, key, value))


def get_setting(tenant_id: int, key: str, default: str = "") -> str:
    row = db.one("SELECT value FROM settings WHERE tenant_id=? AND key=?", (tenant_id, key))
    return default if row is None or row["value"] is None else str(row["value"])


def set_setting(tenant_id: int, key: str, value: str) -> None:
    db.ex(
        "INSERT INTO settings(tenant_id, key, value) VALUES (?,?,?)"
        " ON CONFLICT(tenant_id, key) DO UPDATE SET value=excluded.value",
        (tenant_id, key, value),
    )


def all_settings(tenant_id: int) -> dict:
    return {r["key"]: r["value"] for r in db.q(
        "SELECT key, value FROM settings WHERE tenant_id=?", (tenant_id,))}


# ------------------------------------------------------------ verify codes

def issue_code(tenant_id: int, tg_id: int, purpose: str, account_id: int | None = None) -> str:
    """Issue a fresh 6-digit code, invalidating any earlier live one."""
    import secrets
    db.ex("UPDATE verify_codes SET consumed_at=? WHERE tg_id=? AND purpose=?"
          " AND consumed_at IS NULL", (db.now(), tg_id, purpose))
    code = f"{secrets.randbelow(900000) + 100000}"
    db.ex("INSERT INTO verify_codes(tenant_id, tg_id, code, purpose, account_id, created_at)"
          " VALUES (?,?,?,?,?,?)", (tenant_id, tg_id, code, purpose, account_id, db.now()))
    return code


def consume_code(tg_id: int, code: str, purpose: str, ttl_seconds: int = 900):
    """Validate + burn the newest live code. Returns the verify_codes row
    (has tenant_id and account_id) or None."""
    row = db.one(
        "SELECT * FROM verify_codes WHERE tg_id=? AND purpose=? AND consumed_at IS NULL"
        " ORDER BY id DESC LIMIT 1", (tg_id, purpose))
    if row is None or row["code"] != str(code).strip():
        return None
    if db.now() - row["created_at"] > ttl_seconds:
        return None
    db.ex("UPDATE verify_codes SET consumed_at=? WHERE id=?", (db.now(), row["id"]))
    return row


def purge_expired_codes(older_than_ts: int) -> int:
    return db.ex("DELETE FROM verify_codes WHERE created_at < ?", (older_than_ts,))


# ------------------------------------------------------------------- fsm

def set_state(tg_id: int, state: str, tenant_id=None, data=None) -> None:
    db.ex(
        "INSERT INTO fsm_states(tg_id, tenant_id, state, data, updated_at) VALUES (?,?,?,?,?)"
        " ON CONFLICT(tg_id) DO UPDATE SET tenant_id=excluded.tenant_id, state=excluded.state,"
        " data=excluded.data, updated_at=excluded.updated_at",
        (tg_id, tenant_id, state, data, db.now()),
    )


def get_state(tg_id: int):
    return db.one("SELECT * FROM fsm_states WHERE tg_id=?", (tg_id,))


def clear_state(tg_id: int) -> None:
    db.ex("DELETE FROM fsm_states WHERE tg_id=?", (tg_id,))


def purge_stale_states(older_than_ts: int) -> int:
    return db.ex("DELETE FROM fsm_states WHERE updated_at < ?", (older_than_ts,))


# ----------------------------------------------------------------- stats

def tenant_stats(tenant_id: int) -> dict:
    rating = db.scalar(
        "SELECT AVG(rating) FROM tickets WHERE tenant_id=? AND rating IS NOT NULL",
        (tenant_id,), 0) or 0
    return {
        "total": count_tickets(tenant_id),
        "open": count_tickets(tenant_id, Status.OPEN),
        "pending": count_tickets(tenant_id, Status.PENDING),
        "closed": count_tickets(tenant_id, Status.CLOSED),
        "customers": count_customers(tenant_id),
        "unverified": count_unverified(tenant_id),
        "rating": round(float(rating), 2),
        "first_reply_min": round(first_reply_seconds(tenant_id) / 60, 1),
    }


def platform_stats() -> dict:
    return {
        "tenants": count_tenants(),
        "active_tenants": int(db.scalar("SELECT COUNT(*) FROM tenants WHERE status='active'")),
        "customers": int(db.scalar("SELECT COUNT(*) FROM customers")),
        "tickets": int(db.scalar("SELECT COUNT(*) FROM tickets")),
        "open": int(db.scalar("SELECT COUNT(*) FROM tickets WHERE status='open'")),
        "members": int(db.scalar("SELECT COUNT(*) FROM members WHERE active=1")),
    }
