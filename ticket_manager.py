"""Ticket lifecycle: create, message, close, transfer, rating.

All state transitions that matter live here - handlers stay thin and never
touch SQL directly, so the rules (SLA stamps, first-reply stamps, audit rows)
cannot be skipped by a forgotten UPDATE.
"""
from __future__ import annotations

import audit
import bot
import notifications
import operator_manager
import repositories as repo
from formatters import esc, mention, ticket_card
from models import Priority, Status


class TicketError(Exception):
    pass


def open_ticket(tenant_id: int, customer, subject: str, body: str,
                actor_tg_id: int | None = None) -> int:
    """Create a ticket with its first customer message; auto-assign."""
    ticket_id = repo.create_ticket(tenant_id, customer["id"], subject, Priority.NORMAL)
    repo.add_message(ticket_id, "customer", customer["tg_id"], body)
    assigned = operator_manager.auto_assign(ticket_id, actor_tg_id or customer["tg_id"])
    audit.log(tenant_id, actor_tg_id or customer["tg_id"], audit.Act.TICKET_CREATE,
              target=ticket_id, detail=subject[:80])
    ticket = repo.get_ticket(ticket_id)
    if ticket:
        notifications.new_ticket(ticket, assigned)
    return ticket_id


def customer_message(customer, body: str, file_id: str | None = None,
                     file_type: str | None = None) -> int:
    """Append a message to the customer's open ticket (creating one if they
    have none open). Returns the ticket id."""
    if customer.get("blocked"):
        # Handlers already refuse blocked customers; enforce here too so no
        # other entry point (future webhook, import, ...) can slip past.
        raise TicketError("دسترسی شما نزد این کسب‌وکار مسدود است.")
    tenant_id = customer["tenant_id"]
    ticket = repo.open_ticket_for(customer["id"])
    if ticket is None:
        subject = (body or "تیکت جدید").strip().splitlines()[0][:60]
        ticket_id = repo.create_ticket(tenant_id, customer["id"], subject)
        repo.add_message(ticket_id, "customer", customer["tg_id"], body, file_id, file_type)
        operator_manager.auto_assign(ticket_id, customer["tg_id"])
        ticket = repo.get_ticket(ticket_id)
        audit.log(tenant_id, customer["tg_id"], audit.Act.TICKET_CREATE, target=ticket_id)
        if ticket:
            notifications.new_ticket(ticket, ticket["assigned_to"])
        return ticket_id
    ticket_id = ticket["id"]
    repo.add_message(ticket_id, "customer", customer["tg_id"], body, file_id, file_type)
    repo.touch_customer_msg(ticket_id)
    repo.set_ticket_status(ticket_id, Status.OPEN)
    audit.log(tenant_id, customer["tg_id"], audit.Act.TICKET_REPLY, target=ticket_id)
    fresh = repo.get_ticket(ticket_id)
    if fresh:
        notifications.customer_replied(fresh)
    return ticket_id


def agent_reply(ticket_id: int, agent_tg_id: int, body: str,
                internal: bool = False) -> None:
    ticket = repo.get_ticket(ticket_id)
    if ticket is None:
        raise TicketError("تیکت پیدا نشد.")
    if ticket["status"] == Status.CLOSED and not internal:
        raise TicketError("تیکت بسته است؛ اول بازگشایی کن.")
    repo.add_message(ticket_id, "agent", agent_tg_id, body, internal=internal)
    if not internal:
        repo.mark_first_reply(ticket_id)
        repo.set_ticket_status(ticket_id, Status.PENDING)
        audit.log(ticket["tenant_id"], agent_tg_id, audit.Act.TICKET_REPLY, target=ticket_id)
        notified = notifications.agent_replied(ticket, body)
        if not notified:
            notifications.customer_unreachable(ticket)
    else:
        audit.log(ticket["tenant_id"], agent_tg_id, audit.Act.TICKET_NOTE, target=ticket_id)


def close(ticket_id: int, actor_tg_id: int, ask_rating: bool = True) -> None:
    ticket = repo.get_ticket(ticket_id)
    if ticket is None:
        raise TicketError("تیکت پیدا نشد.")
    repo.set_ticket_status(ticket_id, Status.CLOSED)
    audit.log(ticket["tenant_id"], actor_tg_id, audit.Act.TICKET_CLOSE, target=ticket_id)
    if ask_rating:
        notifications.request_rating(ticket)


def reopen(ticket_id: int, actor_tg_id: int) -> None:
    ticket = repo.get_ticket(ticket_id)
    if ticket is None:
        raise TicketError("تیکت پیدا نشد.")
    repo.set_ticket_status(ticket_id, Status.OPEN)
    audit.log(ticket["tenant_id"], actor_tg_id, audit.Act.TICKET_STATUS, target=ticket_id,
              detail="reopen")


def transfer(ticket_id: int, to_tg_id: int | None, actor_tg_id: int) -> None:
    """to_tg_id=None means auto (least loaded)."""
    if to_tg_id is None:
        operator_manager.auto_assign(ticket_id, actor_tg_id)
    else:
        operator_manager.assign(ticket_id, to_tg_id, actor_tg_id)
    ticket = repo.get_ticket(ticket_id)
    if ticket and ticket["assigned_to"]:
        try:
            bot.send(ticket["assigned_to"],
                     f"تیکت #{ticket['number']} به شما منتقل شد.\n"
                     f"موضوع: {esc(ticket['subject'] or '-')}")
        except bot.TgError:
            pass


def set_priority(ticket_id: int, priority: str, actor_tg_id: int) -> None:
    if priority not in (Priority.URGENT, Priority.NORMAL, Priority.LOW):
        raise TicketError("اولویت نامعتبر.")
    repo.set_priority(ticket_id, priority)
    ticket = repo.get_ticket(ticket_id)
    audit.log(ticket["tenant_id"] if ticket else None, actor_tg_id,
              audit.Act.TICKET_PRIORITY, target=ticket_id, detail=priority)


def rate(ticket_id: int, rating: int, customer_tg_id: int) -> None:
    ticket = repo.get_ticket(ticket_id)
    if ticket is None:
        raise TicketError("تیکت پیدا نشد.")
    if ticket["customer_tg_id"] != customer_tg_id:
        raise TicketError("این تیکت مال شما نیست.")
    repo.set_rating(ticket_id, rating)
    audit.log(ticket["tenant_id"], customer_tg_id, audit.Act.TICKET_RATE, target=ticket_id,
              detail=str(rating))


def summary(ticket, *, is_staff: bool = True) -> str:
    """Card + the last few messages, rendered for Telegram HTML."""
    if ticket is None:
        return "تیکت پیدا نشد."
    lines = [ticket_card(ticket, show_customer=is_staff)]
    msgs = repo.list_messages(ticket["id"], include_internal=is_staff)
    for m in msgs[-8:]:
        who = mention(m["sender_id"]) if m["sender_id"] else ""
        tag = {"customer": "مشتری", "agent": "اپراتور", "system": "ربات"}.get(
            m["sender_type"], "")
        prefix = f"<i>(داخلی)</i> " if m["is_internal"] else ""
        body = esc((m["body"] or "").strip()) or "<i>[فایل]</i>"
        lines.append(f"{prefix}<b>{tag}</b> {who}:\n{body}")
    if is_staff:
        lines.append(mention(ticket["customer_tg_id"], ticket.get("customer_name")))
    return "\n\n".join(lines)
