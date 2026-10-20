"""Outbound notifications: bot -> chat, always best-effort.

Every send is wrapped: a user who blocked the bot, a deleted chat, or a rate
limit must never abort the operation that triggered the notification. Callers
inspect the boolean return only when the result changes their flow (e.g.
"customer unreachable, tell the agent").
"""
from __future__ import annotations

import bot
import callbacks as cb
import keyboards
import operator_manager
import repositories as repo
from formatters import esc, mention, ticket_card


def _try(chat_id: int | None, text: str, keyboard=None) -> bool:
    if not chat_id:
        return False
    try:
        bot.send(chat_id, text, keyboard)
        return True
    except bot.TgError:
        return False


def ticket_alert_keyboard(ticket) -> dict | None:
    """دیدم / مشاهده / پروفایل مشتری - act straight from the notification."""
    tid = ticket["id"]
    cid = ticket.get("customer_id") or 0
    rows = [
        [keyboards.btn("دیدم", cb.enc(cb.TK, tid, "seen"), style="primary"),
         keyboards.btn("مشاهده تیکت", cb.enc(cb.TK, tid, "view"), style="success")],
        [keyboards.btn("پروفایل مشتری", cb.enc(cb.CU, cid, "view") if cid
                       else cb.enc(cb.NAV, cb.MENU))],
    ]
    return keyboards.markup(*rows)


def new_ticket(ticket, assigned_tg_id: int | None) -> None:
    """Alert staff about a fresh customer ticket."""
    card = ticket_card(ticket)
    for tg in operator_manager.notify_targets(ticket["tenant_id"]):
        extra = ""
        if assigned_tg_id == tg:
            extra = "\n<b>این تیکت به شما اختصاص یافت.</b>"
        _try(tg, f"تیکت جدید:\n{card}{extra}", ticket_alert_keyboard(ticket))
    _try(ticket["customer_tg_id"],
         f"تیکت #{ticket['number']} ثبت شد. به‌زودی پاسخ می‌دهیم.")


def customer_replied(ticket) -> None:
    targets: list[int] = []
    if ticket["assigned_to"]:
        targets.append(ticket["assigned_to"])
    for tg in operator_manager.notify_targets(ticket["tenant_id"]):
        if tg not in targets:
            targets.append(tg)
    body = repo.last_customer_message_body(ticket["id"])
    excerpt = esc((body["body"] or "").strip()[:300]) if body else ""
    for tg in targets[:15]:
        _try(tg, f"پیام جدید مشتری در تیکت #{ticket['number']}:\n{excerpt}",
             ticket_alert_keyboard(ticket))


def agent_replied(ticket, body: str) -> bool:
    """Notify the customer; True when delivery succeeded."""
    ok = _try(ticket["customer_tg_id"],
              f"پاسخ تیکت #{ticket['number']}:\n{esc(body[:800])}")
    if ok:
        _try(ticket["customer_tg_id"], "پاسخ رضایت بخش بود؟",
             keyboards.rating_picker(ticket["id"]))
    return ok


def customer_unreachable(ticket) -> None:
    _try(ticket["assigned_to"],
         f"مشتری تیکت #{ticket['number']} به پیام دسترسی ندارد (ربات را بلاک کرده یا حذف شده).")


def request_rating(ticket) -> None:
    _try(ticket["customer_tg_id"],
         f"تیکت #{ticket['number']} بسته شد. از ۱ تا ۵ امتیاز دهید:",
         keyboards.rating_picker(ticket["id"]))


def rating_received(ticket) -> None:
    if ticket["assigned_to"]:
        _try(ticket["assigned_to"],
             f"مشتری به تیکت #{ticket['number']} امتیاز {ticket.get('rating') or '?'}/5 داد.")


def sla_warning(ticket, overdue_minutes: float) -> None:
    targets: list[int] = []
    if ticket["assigned_to"]:
        targets.append(ticket["assigned_to"])
    for tg in operator_manager.notify_targets(ticket["tenant_id"]):
        if tg not in targets:
            targets.append(tg)
    text = (f"هشدار SLA: تیکت #{ticket['number']} "
            f"{int(overdue_minutes)} دقیقه بدون پاسخ مانده است.")
    for tg in targets[:5]:
        _try(tg, text)


def owner_alert(text: str) -> None:
    import config
    if config.OWNER_TG_ID:
        _try(config.OWNER_TG_ID, text)
