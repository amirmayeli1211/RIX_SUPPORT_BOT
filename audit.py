"""Audit trail - an append-only record of every consequential action.

Who did what, to which tenant, when. The owner panel reads this back; nothing
in the app ever deletes or updates rows here.
"""
from __future__ import annotations

import database as db
from formatters import esc, human_dt


# Canonical action names. Keeping them in one place makes panel filters and a
# future log export stable.
class Act:
    TENANT_CREATE = "tenant.create"
    TENANT_STATUS = "tenant.status"
    MEMBER_ADD = "member.add"
    MEMBER_ROLE = "member.role"
    MEMBER_REMOVE = "member.remove"
    CUSTOMER_ADD = "customer.add"
    CUSTOMER_VERIFY = "customer.verify"
    CUSTOMER_TAG = "customer.tag"
    CUSTOMER_DELETE = "customer.delete"
    TICKET_CREATE = "ticket.create"
    TICKET_REPLY = "ticket.reply"
    TICKET_ASSIGN = "ticket.assign"
    TICKET_STATUS = "ticket.status"
    TICKET_PRIORITY = "ticket.priority"
    TICKET_NOTE = "ticket.note"
    TICKET_CLOSE = "ticket.close"
    TICKET_RATE = "ticket.rate"
    SETTING_SET = "setting.set"
    LOGIN = "panel.login"
    ERROR = "app.error"
    BACKUP = "backup.run"


def log(tenant_id, actor_tg_id, action: str, target="", detail="") -> None:
    """Write an audit row. Never raises - auditing must not break the action."""
    try:
        db.ex(
            "INSERT INTO audit(tenant_id, actor_tg_id, action, target, detail, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (tenant_id, actor_tg_id, action, str(target or ""), str(detail or ""), db.now()),
        )
    except Exception:
        pass


def recent(tenant_id=None, limit: int = 20):
    if tenant_id:
        return db.q(
            "SELECT * FROM audit WHERE tenant_id=? ORDER BY id DESC LIMIT ?",
            (tenant_id, limit),
        )
    return db.q("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))


def render(rows, limit: int = 20) -> str:
    if not rows:
        return "لاگی ثبت نشده."
    lines = ["<b>تاریخچه اقدامات</b>"]
    for r in rows[:limit]:
        when = human_dt(r["created_at"])
        who = r["actor_tg_id"] or "-"
        tgt = f" -> {esc(r['target'])}" if r["target"] else ""
        detail = f" <i>({esc(r['detail'])})</i>" if r["detail"] else ""
        lines.append(f"<code>{when}</code> | {esc(r['action'])} | {who}{tgt}{detail}")
    return "\n".join(lines)
