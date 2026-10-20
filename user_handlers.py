"""User-facing entry points: /start, /menu, /panel, /help, nav callbacks."""
from __future__ import annotations

import callbacks as cb
import bot
import database as db
import keyboards as kb
import menus
import repositories as repo
from models import Role, Status


def _send_menu(ctx, edit: bool = False) -> None:
    text, keyboard = menus.screen_menu(ctx)
    if edit and ctx.get("message_id"):
        try:
            bot.edit(ctx["chat_id"], ctx["message_id"], text, keyboard)
            return
        except bot.TgError:
            pass
    bot.send(ctx["chat_id"], text, keyboard)


def on_start(ctx) -> None:
    if ctx.get("is_staff"):
        _send_menu(ctx)
        return
    if ctx.get("is_customer"):
        _send_menu(ctx)
        return
    tenant_name = ctx.get("tenant_name") or ""
    bot.send(ctx["chat_id"],
             "سلام! 👋\nاین ربات پشتیبانی است.\nاگر مشتری هستید، ادمین شما را اضافه می‌کند "
             "و کد تأیید برایتان می‌آید.",
             kb.markup([kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU), style="primary")]))


def on_menu(ctx) -> None:
    _send_menu(ctx, edit=bool(ctx.get("message_id")))


def on_panel(ctx) -> None:
    """Staff shortcut: straight to the team queue."""
    if not ctx.get("is_staff"):
        on_start(ctx)
        return
    on_nav(_nav_ctx(ctx, "team_open"))


def on_help(ctx) -> None:
    text, keyboard = menus.screen_help()
    bot.send(ctx["chat_id"], text, keyboard)


def on_unknown(ctx) -> None:
    text, keyboard = menus.screen_menu(ctx)
    bot.send(ctx["chat_id"],
             "متوجه نشدم. از منوی زیر انتخاب کن:",
             keyboard or kb.markup([kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))]))


def _nav_ctx(ctx, screen: str) -> dict:
    out = dict(ctx)
    out["cb_data"] = cb.enc(cb.NAV, screen)
    out["args"] = [screen]
    return out


# ---------------------------------------------------------------- nav

def on_nav(ctx) -> None:
    screen = (ctx.get("args") or ["menu"])[0]
    if screen == cb.MENU:
        _send_menu(ctx, edit=bool(ctx.get("message_id")))
    elif screen == "my_open":
        _my_open(ctx)
    elif screen == "my_tickets":
        _my_tickets(ctx)
    elif screen == "team_open":
        page = 1
        try:
            page = int((ctx.get("args") or ["1"])[1])
        except (IndexError, ValueError):
            page = 1
        _team_queue(ctx, Status.OPEN, "team_open", max(1, page))
    elif screen == "assigned":
        _assigned(ctx)
    elif screen == "new_ticket":
        _new_ticket(ctx)
    elif screen == "cancel":
        repo.clear_state(ctx["tg_id"])
        bot.send(ctx["chat_id"], "لغو شد.")
        _send_menu(ctx)
    elif screen == "help":
        on_help(ctx)
    else:
        _send_menu(ctx, edit=bool(ctx.get("message_id")))


def _my_open(ctx) -> None:
    customer = ctx.get("customer")
    if not customer:
        bot.send(ctx["chat_id"], "شما مشتری ثبت‌شده‌ای نیستید.")
        return
    ticket = repo.open_ticket_for(customer["id"])
    if not ticket:
        bot.send(ctx["chat_id"], "تیکت بازی ندارید.",
                 kb.markup([kb.btn("تیکت جدید", cb.enc(cb.NAV, "new_ticket"), style="success")]))
        return
    full = repo.get_ticket(ticket["id"])
    text, keyboard = menus.screen_ticket_detail(full, is_staff=False)
    bot.send(ctx["chat_id"], text, keyboard)


def _my_tickets(ctx) -> None:
    customer = ctx.get("customer")
    if not customer:
        bot.send(ctx["chat_id"], "شما مشتری ثبت‌شده‌ای نیستید.")
        return
    tickets = repo.customer_tickets(customer["id"], limit=10)
    if not tickets:
        bot.send(ctx["chat_id"], "هنوز تیکتی ندارید.",
                 kb.markup([kb.btn("تیکت جدید", cb.enc(cb.NAV, "new_ticket"), style="success")]))
        return
    text, keyboard = menus.screen_ticket_list("تیکت‌های من", tickets)
    bot.send(ctx["chat_id"], text, keyboard)


def _team_queue(ctx, status: str, screen: str, page: int = 1) -> None:
    import config
    if not ctx.get("is_staff"):
        bot.send(ctx["chat_id"], "فقط اعضای تیم.")
        return
    tenant_id = ctx["tenant_id"]
    size = config.TICKET_PAGE_SIZE
    tickets = repo.list_tickets(tenant_id, status=status, limit=size, offset=(page - 1) * size)
    title = "تیکت‌های باز تیم" if status == Status.OPEN else "تیکت‌های من"
    next_cb = cb.enc(cb.NAV, screen, page + 1) if len(tickets) == size else None
    prev_cb = cb.enc(cb.NAV, screen, page - 1) if page > 1 else None
    text, keyboard = menus.screen_ticket_list(title, tickets, next_cb=next_cb, prev_cb=prev_cb)
    _send_or_edit(ctx, text, keyboard)


def on_team_page(ctx) -> None:
    page = 1
    try:
        page = int((ctx.get("args") or ["1"])[1])
    except (IndexError, ValueError):
        page = 1
    _team_queue(ctx, Status.OPEN, "team_open", max(1, page))


def _assigned(ctx) -> None:
    import config
    if not ctx.get("is_staff"):
        bot.send(ctx["chat_id"], "فقط اعضای تیم.")
        return
    tenant_id = ctx["tenant_id"]
    tickets = repo.list_tickets(tenant_id, assigned_to=ctx["tg_id"], limit=config.TICKET_PAGE_SIZE)
    open_ones = [t for t in tickets if t["status"] != Status.CLOSED]
    text, keyboard = menus.screen_ticket_list("تیکت‌های من", open_ones or tickets)
    _send_or_edit(ctx, text, keyboard)


def _new_ticket(ctx) -> None:
    if not ctx.get("is_customer"):
        bot.send(ctx["chat_id"], "فقط مشتریان می‌توانند تیکت بسازند.",
                 kb.cancel_button())
        return
    import sla_manager
    tenant_id = ctx["customer_tenant_id"]
    db_clear = repo.set_state(ctx["tg_id"], "ticket_subject", tenant_id)
    if not sla_manager.is_open_now(tenant_id):
        text, keyboard = menus.screen_outside_hours(tenant_id, ctx.get("has_open_ticket", False), ctx)
        bot.send(ctx["chat_id"], text, keyboard)
    else:
        bot.send(ctx["chat_id"], "موضوع تیکت را در یک جمله بنویس:",
                 kb.cancel_button())


def _send_or_edit(ctx, text, keyboard) -> None:
    if ctx.get("message_id"):
        try:
            bot.edit(ctx["chat_id"], ctx["message_id"], text, keyboard)
            return
        except bot.TgError:
            pass
    bot.send(ctx["chat_id"], text, keyboard)
