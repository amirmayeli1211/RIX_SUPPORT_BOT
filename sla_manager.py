"""SLA rules: deadline per ticket, overdue detection, working hours.

Defaults: 60 minutes to first reply, configurable per tenant. A ticket that
gets a customer message after the reminder resets its clock (sla_notified_at
must be older than the latest customer message to fire again).
"""
from __future__ import annotations

import datetime as dt

import database as db
import notifications
import repositories as repo
from models import Status

DEFAULT_SLA_MINUTES = 60


def sla_minutes(tenant_id: int) -> int:
    raw = repo.get_setting(tenant_id, "sla_minutes", str(DEFAULT_SLA_MINUTES))
    try:
        value = int(str(raw).strip())
    except ValueError:
        return DEFAULT_SLA_MINUTES
    return value if 1 <= value <= 1440 else DEFAULT_SLA_MINUTES


def seconds_left(ticket) -> int:
    """Negative when already overdue."""
    anchor = ticket["last_customer_msg_at"] or ticket["created_at"]
    elapsed = db.now() - int(anchor or db.now())
    if ticket["first_reply_at"]:
        return 10**9  # answered; SLA no longer applies
    return sla_minutes(ticket["tenant_id"]) * 60 - elapsed


def is_overdue(ticket) -> bool:
    return ticket["status"] == Status.OPEN and seconds_left(ticket) < 0


def check_and_alert() -> int:
    """Scan open tickets, alert once per overdue window. Returns count."""
    fired = 0
    for tenant in repo.list_tenants("active"):
        cutoff = db.now() - sla_minutes(tenant["id"]) * 60
        for t in repo.overdue_open_tickets(tenant["id"], cutoff):
            minutes = (db.now() - int(t["last_customer_msg_at"] or t["created_at"])) / 60
            notifications.sla_warning(t, minutes)
            repo.mark_sla_notified(t["id"])
            fired += 1
    return fired


# ------------------------------------------------------------ work hours

def is_open_now(tenant_id: int) -> bool:
    """True when inside business hours (or when hours are not configured)."""
    raw = repo.get_setting(tenant_id, "business_hours", "").strip()
    if not raw or "-" not in raw:
        return True
    start_s, end_s = raw.split("-", 1)
    try:
        sh, sm = (int(x) for x in start_s.strip().split(":"))
        eh, em = (int(x) for x in end_s.strip().split(":"))
    except ValueError:
        return True  # misconfigured -> never block a customer
    now = dt.datetime.now()
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    if end <= start:  # overnight window, e.g. 22:00-06:00
        return now >= start or now <= end
    return start <= now <= end


def outside_hours_notice(tenant_id: int) -> str:
    text = repo.get_setting(tenant_id, "outside_hours_text", "")
    if text:
        return text
    hours = repo.get_setting(tenant_id, "business_hours", "")
    return f"خارج از ساعت کاری ({hours}) هستیم؛ پیامتون ثبت می‌شه و در اولین ساعت کاری پاسخ می‌دیم."
