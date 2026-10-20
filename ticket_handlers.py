"""Staff-side ticket operations: view, reply, note, priority, transfer, close."""
from __future__ import annotations

import audit
import bot
import callbacks as cb
import database as db
import keyboards as kb
import menus
import notifications
import operator_manager
import repositories as repo
import ticket_manager
import validators
from formatters import esc
from models import Role, Status


def _staff(ctx) -> bool:
    return bool(ctx.get("is_staff"))


def _ticket_or_none(raw) -> int | None:
    return int(raw) if str(raw).isdigit() else None


def _owned_ticket(ctx, ticket_id: int):
    """Ticket of this tenant, or None (tenant boundary)."""
    ticket = repo.get_ticket(ticket_id)
    if not ticket or ticket["tenant_id"] != ctx.get("tenant_id"):
        return None
    return ticket


def _refresh(ctx, ticket_id: int) -> None:
    ticket = _owned_ticket(ctx, ticket_id)
    if not ticket:
        bot.send(ctx["chat_id"], "تیکت پیدا نشد.")
        return
    text, keyboard = menus.screen_ticket_detail(ticket, is_staff=_staff(ctx))
    if ctx.get("message_id"):
        try:
            bot.edit(ctx["chat_id"], ctx["message_id"], text, keyboard)
            return
        except bot.TgError:
            pass
    bot.send(ctx["chat_id"], text, keyboard)


def on_ticket_cb(ctx) -> None:
    if not _staff(ctx):
        _customer_view(ctx)
        return
    args = ctx.get("args") or []
    # Encoding is "<id>:<op>[:<arg>]" (see keyboards.ticket_detail).
    ticket_id = _ticket_or_none(args[0]) if args else None
    op = args[1] if len(args) > 1 else ""
    if op == "view" and ticket_id:
        _refresh(ctx, ticket_id)
    elif op == "reply" and ticket_id:
        _start_reply(ctx, ticket_id)
    elif op == "note" and ticket_id:
        _start_note(ctx, ticket_id)
    elif op == "prio" and ticket_id:
        bot.send(ctx["chat_id"], "اولویت را انتخاب کنید:", kb.priority_picker(ticket_id))
    elif op == "setprio" and ticket_id and len(args) > 2:
        _set_priority(ctx, ticket_id, args[2])
    elif op == "transfer" and ticket_id:
        members = repo.list_members(ctx["tenant_id"], (Role.OWNER, Role.ADMIN, Role.AGENT))
        bot.send(ctx["chat_id"], "انتقال به:", kb.transfer_picker(members, ticket_id))
    elif op == "setassign" and ticket_id and len(args) > 2:
        _set_assignee(ctx, ticket_id, args[2])
    elif op == "close" and ticket_id:
        bot.send(ctx["chat_id"], "تیکت بسته شود؟", kb.confirm_close(ticket_id))
    elif op == "yes" and ticket_id:
        _do_close(ctx, ticket_id)
    elif op == "reopen" and ticket_id:
        _do_reopen(ctx, ticket_id)
    elif op == "refresh" and ticket_id:
        _refresh(ctx, ticket_id)
    elif op == "seen" and ticket_id:
        _mark_seen(ctx, ticket_id)
    elif op == "delete" and ticket_id:
        _delete_ticket(ctx, ticket_id)
    else:
        bot.answer_cb(ctx["cb_id"], "نامعتبر")


def _customer_view(ctx) -> None:
    """A non-staff tapping a ticket button: only their own ticket."""
    args = ctx.get("args") or []
    ticket_id = _ticket_or_none(args[0]) if args else None
    if not ticket_id:
        return
    ticket = repo.get_ticket(ticket_id)
    customer = ctx.get("customer")
    if not ticket or not customer or ticket["customer_id"] != customer["id"]:
        bot.answer_cb(ctx["cb_id"], "این تیکت مال شما نیست.", alert=True)
        return
    text, keyboard = menus.screen_ticket_detail(ticket, is_staff=False)
    bot.edit(ctx["chat_id"], ctx["message_id"], text, keyboard)


def _mark_seen(ctx, ticket_id: int) -> None:
    """'دیدم': claim the ticket and tell the customer they were heard."""
    ticket = _owned_ticket(ctx, ticket_id)
    if not ticket:
        bot.answer_cb(ctx["cb_id"], "تیکت پیدا نشد", alert=True)
        return
    if not ticket["assigned_to"]:
        operator_manager.assign(ticket_id, ctx["tg_id"], ctx["tg_id"])
    repo.add_message(ticket_id, "system", ctx["tg_id"], "پیام شما دیده شد.")
    bot.answer_cb(ctx["cb_id"], "دیده شد ✅")
    try:
        bot.send(ticket["customer_tg_id"],
                 f"پیام شما در تیکت #{ticket['number']} دیده شد. به‌زودی پاسخ می‌دهیم.")
    except bot.TgError:
        pass
    _refresh(ctx, ticket_id)


def _delete_ticket(ctx, ticket_id: int) -> None:
    ticket = _owned_ticket(ctx, ticket_id)
    if not ticket:
        bot.answer_cb(ctx["cb_id"], "تیکت پیدا نشد", alert=True)
        return
    if not ctx.get("is_admin"):
        bot.answer_cb(ctx["cb_id"], "فقط ادمین می‌تواند حذف کند", alert=True)
        return
    repo.delete_ticket(ticket_id)
    audit.log(ticket["tenant_id"], ctx["tg_id"], "ticket.delete", target=ticket_id)
    bot.send(ctx["chat_id"], f"تیکت #{ticket['number']} حذف شد.",
             kb.markup([kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU), style="primary")]))


# ---------------------------------------------------------------- reply/note

def _start_reply(ctx, ticket_id: int) -> None:
    ticket = _owned_ticket(ctx, ticket_id)
    if not ticket:
        bot.send(ctx["chat_id"], "تیکت پیدا نشد.")
        return
    repo.set_state(ctx["tg_id"], "agent_reply", ctx["tenant_id"], str(ticket_id))
    bot.send(ctx["chat_id"],
             f"پاسخ به تیکت #{ticket['number']} را بنویسید:",
             kb.cancel_button())


def on_state_reply(ctx) -> None:
    _finish_message(ctx, internal=False)


def _start_note(ctx, ticket_id: int) -> None:
    ticket = _owned_ticket(ctx, ticket_id)
    if not ticket:
        bot.send(ctx["chat_id"], "تیکت پیدا نشد.")
        return
    repo.set_state(ctx["tg_id"], "agent_note", ctx["tenant_id"], str(ticket_id))
    bot.send(ctx["chat_id"],
             f"یادداشت داخلی برای تیکت #{ticket['number']} (مشتری نمی‌بیند):",
             kb.cancel_button())


def on_state_note(ctx) -> None:
    _finish_message(ctx, internal=True)


def _finish_message(ctx, internal: bool) -> None:
    raw_id = ctx.get("state_data")
    ticket_id = _ticket_or_none(raw_id)
    body = validators.paragraph(ctx.get("text") or ctx.get("caption") or "", 3500)
    if ticket_id is None or body is None:
        repo.clear_state(ctx["tg_id"])
        bot.send(ctx["chat_id"], "پیام نامعتبر بود؛ لغو شد.")
        return
    ticket = _owned_ticket(ctx, ticket_id)
    if not ticket:
        repo.clear_state(ctx["tg_id"])
        bot.send(ctx["chat_id"], "تیکت پیدا نشد.")
        return
    try:
        ticket_manager.agent_reply(ticket_id, ctx["tg_id"], body, internal=internal)
    except ticket_manager.TicketError as exc:
        repo.clear_state(ctx["tg_id"])
        bot.send(ctx["chat_id"], f"❌ {esc(str(exc))}")
        return
    repo.clear_state(ctx["tg_id"])
    label = "یادداشت داخلی ثبت شد." if internal else "پاسخ ارسال شد."
    _refresh(ctx, ticket_id)
    bot.send(ctx["chat_id"], f"✅ {label}")
    if internal:
        audit.log(ticket["tenant_id"], ctx["tg_id"], audit.Act.TICKET_NOTE, target=ticket_id)


# ---------------------------------------------------------------- priority

def _set_priority(ctx, ticket_id: int, priority: str) -> None:
    try:
        ticket_manager.set_priority(ticket_id, priority, ctx["tg_id"])
    except ticket_manager.TicketError as exc:
        bot.send(ctx["chat_id"], f"❌ {esc(str(exc))}")
        return
    _refresh(ctx, ticket_id)


# ---------------------------------------------------------------- transfer

def _set_assignee(ctx, ticket_id: int, target: str) -> None:
    if target == "auto":
        ticket_manager.transfer(ticket_id, None, ctx["tg_id"])
        bot.answer_cb(ctx["cb_id"], "به کمترین بار منتقل شد")
    else:
        if not target.isdigit():
            bot.answer_cb(ctx["cb_id"], "نامعتبر")
            return
        member = repo.member(ctx["tenant_id"], int(target))
        if not member:
            bot.answer_cb(ctx["cb_id"], "اپراتور یافت نشد", alert=True)
            return
        ticket_manager.transfer(ticket_id, member["tg_id"], ctx["tg_id"])
        bot.answer_cb(ctx["cb_id"], "منتقل شد")
    _refresh(ctx, ticket_id)


def on_state_transfer(ctx) -> None:
    """Transfer by typed id, or 'auto'."""
    raw = (ctx.get("text") or "").strip()
    raw_id = ctx.get("state_data")
    ticket_id = _ticket_or_none(raw_id)
    repo.clear_state(ctx["tg_id"])
    if ticket_id is None:
        bot.send(ctx["chat_id"], "تیکت پیدا نشد.")
        return
    if raw.lower() in ("auto", "خودکار"):
        ticket_manager.transfer(ticket_id, None, ctx["tg_id"])
        bot.send(ctx["chat_id"], "به کمترین بار منتقل شد.")
        return
    if not validators.tg_id(raw):
        bot.send(ctx["chat_id"], "آیدی عددی نامعتبر است.")
        return
    member = repo.member(ctx["tenant_id"], validators.tg_id(raw))
    if not member:
        bot.send(ctx["chat_id"], "این کاربر عضو تیم نیست.")
        return
    ticket_manager.transfer(ticket_id, member["tg_id"], ctx["tg_id"])
    bot.send(ctx["chat_id"], "منتقل شد.")


# ---------------------------------------------------------------- close

def _do_close(ctx, ticket_id: int) -> None:
    try:
        ticket_manager.close(ticket_id, ctx["tg_id"])
    except ticket_manager.TicketError as exc:
        bot.send(ctx["chat_id"], f"❌ {esc(str(exc))}")
        return
    ticket = repo.get_ticket(ticket_id)
    text, keyboard = menus.screen_ticket_detail(ticket, is_staff=_staff(ctx))
    if ctx.get("message_id"):
        try:
            bot.edit(ctx["chat_id"], ctx["message_id"], text, keyboard)
        except bot.TgError:
            pass
    bot.send(ctx["chat_id"], "✅ تیکت بسته شد. نظرسنجی رضایت برای مشتری ارسال شد.")


def _do_reopen(ctx, ticket_id: int) -> None:
    try:
        ticket_manager.reopen(ticket_id, ctx["tg_id"])
    except ticket_manager.TicketError as exc:
        bot.send(ctx["chat_id"], f"❌ {esc(str(exc))}")
        return
    _refresh(ctx, ticket_id)
    bot.send(ctx["chat_id"], "تیکت بازگشایی شد.")
