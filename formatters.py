"""HTML formatting helpers for Telegram messages (parse_mode=HTML).

Everything user-supplied goes through esc() - Telegram rejects a message whose
HTML is malformed, so an unescaped '<' would silently swallow the rest of the
text and the operator would never see why.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Optional

from models import PRIORITY_LABEL, ROLE_LABEL, STATUS_LABEL


def esc(text: Any) -> str:
    return (str(text) if text is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def g(obj: Any, key: str, default=None):
    """Row/dict-safe .get(): sqlite3.Row has no .get method."""
    if obj is None:
        return default
    try:
        value = obj[key]
    except (KeyError, IndexError, TypeError):
        try:
            value = obj.get(key, default)  # type: ignore[union-attr]
        except Exception:
            return default
    return default if value is None else value


def mention(tg_id: Optional[int], name: Optional[str] = None, username: Optional[str] = None) -> str:
    label = esc(name or (f"@{username}" if username else str(tg_id or "?")))
    if not tg_id:
        return label
    return f'<a href="tg://user?id={tg_id}">{label}</a>'


def code(text: Any) -> str:
    return f"<code>{esc(text)}</code>"


def bold(text: Any) -> str:
    return f"<b>{esc(text)}</b>"


def human_dt(ts: Optional[int]) -> str:
    if not ts:
        return "-"
    return dt.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")


def ago(ts: Optional[int], now: Optional[int] = None) -> str:
    if not ts:
        return "-"
    ref = int(now if now is not None else dt.datetime.now().timestamp())
    diff = max(0, ref - int(ts))
    m = int(diff // 60)
    if m < 1:
        return "همین حالا"
    if m < 60:
        return f"{m} دقیقه پیش"
    h = m // 60
    if h < 24:
        return f"{h} ساعت پیش"
    return f"{h // 24} روز پیش"


def minutes_label(seconds: float) -> str:
    m = int(round(seconds / 60))
    if m < 60:
        return f"{m} دقیقه"
    return f"{m // 60} ساعت و {m % 60} دقیقه"


def status_label(status: str) -> str:
    return STATUS_LABEL.get(status, esc(status))


def priority_label(priority: str) -> str:
    return PRIORITY_LABEL.get(priority, esc(priority))


def role_label(role: str) -> str:
    return ROLE_LABEL.get(role, esc(role))


def ticket_card(t: Mapping[str, Any], *, tenant_name: str = "", overdue: bool = False,
                show_customer: bool = True) -> str:
    """Compact card used in lists and detail views."""
    lines = [f"<b>تیکت #{t['number']}</b> - {status_label(t.get('status', ''))}"]
    if show_customer:
        who = t.get("customer_name") or t.get("customer_username") or t.get("customer_id") or "?"
        lines.append(f"مشتری: {esc(who)}")
    if t.get("subject"):
        lines.append(f"موضوع: {bold(t['subject'])}")
    lines.append(f"اولویت: {priority_label(t.get('priority', ''))}")
    if t.get("assigned_to"):
        lines.append(f"اپراتور: {code(t['assigned_to'])}")
    if t.get("rating"):
        lines.append(f"امتیاز مشتری: {t['rating']}/5")
    if overdue:
        lines.append("<b>از SLA گذشته - فوری پاسخ دهيد</b>")
    if tenant_name:
        lines.append(f"کسب‌وکار: {esc(tenant_name)}")
    return "\n".join(lines)


def message_line(m: Mapping[str, Any], now: Optional[int] = None) -> str:
    sender = m.get("sender_type", "")
    marker = {"customer": "مشتری", "agent": "اپراتور", "system": "ربات"}.get(sender, "-")
    body = esc((m.get("body") or "").strip() or "")
    if m.get("file_type"):
        body = f"{body} [فایل:{esc(m['file_type'])}]".strip()
    internal = " <i>(یادداشت داخلی)</i>" if m.get("is_internal") else ""
    who = m.get("sender_id")
    who_s = code(who) if who else ""
    return f"{marker} {who_s} <i>{ago(m.get('created_at'), now)}</i>{internal}\n{body}"


def member_row(m: Mapping[str, Any], load: int = 0) -> str:
    who = mention(m.get("tg_id"), m.get("name"), m.get("username"))
    cap = m.get("capacity") or 0
    return f"{role_label(m.get('role', ''))} - {who} - بار کاری: {load}/{cap}"


def customer_row(c: Mapping[str, Any], ticket_count: int = 0) -> str:
    verified = "تایید شده" if c.get("verified_at") else "در انتظار"
    tag_s = f" #{esc(c['tag'])}" if c.get("tag") else ""
    who = mention(c.get("tg_id"), c.get("name"), c.get("username"))
    return f"[{verified}] {who}{tag_s} - {ticket_count} تیکت"


def tenant_row(t: Mapping[str, Any]) -> str:
    flag = "فعال" if t.get("status") == "active" else "غیرفعال"
    return f"[{flag}] <b>{esc(t.get('name'))}</b> {code(t.get('id'))} - {esc(t.get('slug') or '-')}"


def stats_block(s: Mapping[str, Any]) -> str:
    rating = s.get("rating") or 0
    return (
        f"<b>گزارش</b>\n"
        f"- کل تیکت‌ها: {s.get('total', 0)}\n"
        f"- باز: {s.get('open', 0)} | در انتظار: {s.get('pending', 0)} | بسته: {s.get('closed', 0)}\n"
        f"- میانگین اولین پاسخ: {s.get('first_reply_min', 0)} دقیقه\n"
        f"- میانگین رضایت: {rating or '-'}/5\n"
        f"- مشتریان: {s.get('customers', 0)} ({s.get('unverified', 0)} در انتظار وریفای)"
    )


def error_text(where: str, exc: BaseException) -> str:
    return f"خطا در {where}: {type(exc).__name__}: {str(exc)[:300]}"
