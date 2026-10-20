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
    if ctx.get("is_account") and not ctx.get("is_super_owner"):
        from menus import screen_account_menu
        text, keyboard = screen_account_menu(ctx["account"])
        bot.send(ctx["chat_id"], text, keyboard)
        return
    if ctx.get("is_super_owner"):
        if repo.count_tenants() == 0:
            # Bootstrap: no business exists yet, so walk the owner straight
            # into creating the first one instead of an empty menu.
            repo.set_state(ctx["tg_id"], "new_tenant", None)
            bot.send(ctx["chat_id"],
                     "سلام مالک! 👑\nهنوز کسب‌وکاری ثبت نشده.\n"
                     "نام کسب‌وکار (مثلا «فروشگاه الف») را بفرستید تا ساخته شود:",
                     kb.cancel_button())
            return
        _send_menu(ctx)
        return
    # Unregistered visitor: welcome text plus the same menu everyone else
    # gets (currently just راهنا, but never a dead single button).
    text, keyboard = menus.screen_menu(ctx)
    bot.send(ctx["chat_id"],
             "سلام! 👋\nاین ربات پشتیبانی است.\nاگر مشتری هستید، ادمین شما را اضافه می‌کند "
             "و کد تأیید برایتان می‌آید.\n\n" + text,
             keyboard)


def on_menu(ctx) -> None:
    _send_menu(ctx, edit=bool(ctx.get("message_id")))


def on_panel(ctx) -> None:
    """Staff shortcut: straight to the team queue."""
    if not ctx.get("is_staff"):
        on_start(ctx)
        return
    on_nav(_nav_ctx(ctx, "team_open"))


def on_join_link(ctx, payload: str) -> None:
    """Deep link from an invite: become a customer of that tenant only."""
    import audit
    from formatters import esc
    parts = payload.split("_", 2)
    if len(parts) != 3 or not parts[1].isdigit():
        bot.send(ctx["chat_id"], "لینک دعوت نامعتبر است.")
        return
    tenant_id = int(parts[1])
    tenant = repo.get_tenant(tenant_id)
    code = repo.ensure_invite_code(tenant_id) if tenant else ""
    if not tenant or tenant["status"] != "active" or parts[2] != code:
        bot.send(ctx["chat_id"], "لینک دعوت معتبر نیست یا منقضی شده است.")
        return
    member = repo.member(tenant_id, ctx["tg_id"])
    if member:
        bot.send(ctx["chat_id"], "شما عضو این تیم هستید؛ نیازی به دعوت نیست.")
        return
    existing = repo.customer_by_tg(ctx["tg_id"], tenant_id)
    if existing and existing.get("blocked"):
        bot.send(ctx["chat_id"], "دسترسی شما نزد این کسب‌وکار مسدود است.")
        return
    if not existing:
        repo.add_customer(tenant_id, ctx["tg_id"], name=ctx.get("name"),
                          username=ctx.get("username"), verified_at=db.now())
        audit.log(tenant_id, ctx["tg_id"], audit.Act.CUSTOMER_VERIFY,
                  target=ctx["tg_id"], detail="invite-link")
    bot.send(ctx["chat_id"],
             f"به پشتیبانی «{esc(tenant['name'])}» خوش آمدید ✅\n"
             "از منوی زیر می‌توانید تیکت بزنید:",
             kb.main_menu(is_customer=True, is_staff=False, is_admin=False,
                          is_owner=False, has_open_ticket=False))


def on_staff_link(ctx, payload: str) -> None:
    """Deep link: the tapper becomes an OPERATOR of that tenant."""
    import audit
    from formatters import esc
    parts = payload.split("_", 2)
    if len(parts) != 3 or not parts[1].isdigit():
        bot.send(ctx["chat_id"], "لینک دعوت نامعتبر است.")
        return
    tenant_id = int(parts[1])
    tenant = repo.get_tenant(tenant_id)
    code = repo.ensure_staff_code(tenant_id) if tenant else ""
    if not tenant or tenant["status"] != "active" or parts[2] != code:
        bot.send(ctx["chat_id"], "لینک دعوت معتبر نیست یا منقضی شده است.")
        return
    existing = repo.member(tenant_id, ctx["tg_id"])
    if existing:
        bot.send(ctx["chat_id"],
                 f"شما همین حالا عضو تیم «{esc(tenant['name'])}» هستید.",
                 kb.main_menu(is_customer=False, is_staff=True,
                              is_admin=existing["role"] in ("owner", "admin"),
                              is_owner=existing["role"] == "owner",
                              has_open_ticket=False))
        return
    customer = repo.customer_by_tg(ctx["tg_id"], tenant_id)
    if customer:
        bot.send(ctx["chat_id"],
                 "شما مشتری این کسب‌وکار هستید؛ برای عضویت در تیم، "
                 "ادمین باید شما را اضافه کند.")
        return
    repo.add_member(tenant_id, ctx["tg_id"], Role.AGENT, name=ctx.get("name"),
                    username=ctx.get("username"))
    audit.log(tenant_id, ctx["tg_id"], audit.Act.MEMBER_ADD, detail="staff-invite-link")
    bot.send(ctx["chat_id"],
             f"به تیم «{esc(tenant['name'])}» پیوستید 🎧\n"
             "از این پس تیکت‌های مشتریان این کسب‌وکار به شما نمایش داده می‌شود.",
             kb.main_menu(is_customer=False, is_staff=True, is_admin=False,
                          is_owner=False, has_open_ticket=False))


def on_group_command(ctx) -> None:
    """/bind and /unbind inside a Telegram group."""
    import audit
    from formatters import esc
    text = (ctx.get("text") or "").split()
    cmd = text[0].split("@")[0].lower() if text else ""
    member = repo.best_membership(ctx["tg_id"])
    import config
    is_super = bool(config.OWNER_TG_ID and ctx["tg_id"] == config.OWNER_TG_ID)
    if cmd == "/bind":
        if not is_super and (not member or member["role"] not in ("owner", "admin")):
            bot.send(ctx["chat_id"], "فقط مالک/ادمین کسب‌وکار می‌تواند گروه را متصل کند.")
            return
        # tenant: super-owner picks via /bind <id>; others use their own
        if is_super and len(text) > 1 and text[1].isdigit():
            tenant_id = int(text[1])
        elif member:
            tenant_id = member["tenant_id"]
        else:
            bot.send(ctx["chat_id"], "شناسه کسب‌وکار را هم بدهید: /bind <شناسه>")
            return
        tenant = repo.get_tenant(tenant_id)
        if not tenant:
            bot.send(ctx["chat_id"], "کسب‌وکار پیدا نشد.")
            return
        repo.bind_group(tenant_id, ctx["chat_id"])
        audit.log(tenant_id, ctx["tg_id"], "group.bind", target=ctx["chat_id"])
        bot.send(ctx["chat_id"],
                 f"این گروه به «{esc(tenant['name'])}» متصل شد ✅\n"
                 "هر پیام مشتریان اینجا تیکت می‌شود و اپراتورها اعلان می‌گیرند.")
    elif cmd == "/unbind":
        if not member and not is_super:
            bot.send(ctx["chat_id"], "دسترسی ندارید.")
            return
        tenant = repo.tenant_by_group(ctx["chat_id"])
        if not tenant:
            bot.send(ctx["chat_id"], "این گروه به چیزی متصل نیست.")
            return
        repo.unbind_group(tenant["id"], ctx["chat_id"])
        audit.log(tenant["id"], ctx["tg_id"], "group.unbind", target=ctx["chat_id"])
        bot.send(ctx["chat_id"], "اتصال گروه قطع شد.")
    else:
        bot.send(ctx["chat_id"], "دستورات گروهی: /bind  |  /unbind")


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
