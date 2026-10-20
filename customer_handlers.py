"""Customer-side flows and admin-side customer management.

Customer: new-ticket wizard (subject -> body), plain-text replies that land in
the open ticket, rating after close.
Admin: add-by-id (verification), search, tag, remove.
"""
from __future__ import annotations

import audit
import bot
import callbacks as cb
import config
import database as db
import keyboards as kb
import menus
import repositories as repo
import sla_manager
import ticket_manager
import validators
import verification
from formatters import esc
from models import Status

PAGE = 50


def _deny(ctx, text: str = "دسترسی نداری.") -> None:
    bot.send(ctx["chat_id"], text, kb.cancel_button())


# ============================================================ customer side

def on_customer_text(ctx) -> None:
    """Free text from a verified customer -> their open ticket."""
    customer = ctx["customer"]
    body = ctx.get("text") or ctx.get("caption") or ""
    file_id, file_type = _media(ctx)
    if not body and not file_id:
        bot.send(ctx["chat_id"], "متن یا فایلی نفرستید.")
        return
    if not body:
        body = "[فایل]"
    ticket_id = ticket_manager.customer_message(customer, body, file_id, file_type)
    ticket = repo.get_ticket(ticket_id)
    outside = "" if sla_manager.is_open_now(customer["tenant_id"]) else \
        "\n\n" + sla_manager.outside_hours_notice(customer["tenant_id"])
    bot.send(ctx["chat_id"],
             f"پیام شما در تیکت #{ticket['number']} ثبت شد.{outside}",
             kb.markup([kb.btn("مشاهده تیکت", cb.enc(cb.TK, ticket["id"], "view"),
                               style="primary")]))


def _media(ctx):
    if ctx.get("photo"):
        return ctx["photo"], "photo"
    if ctx.get("document"):
        return ctx["document"], "document"
    if ctx.get("voice"):
        return ctx["voice"], "voice"
    if ctx.get("video"):
        return ctx["video"], "video"
    return None, None


def on_state_subject(ctx) -> None:
    customer = ctx["customer"]
    subject = validators.one_line(ctx.get("text"), 120)
    if subject is None:
        bot.send(ctx["chat_id"], "موضوع باید ۱ تا ۱۲۰ کاراکتر باشد. دوباره:",
                 kb.cancel_button())
        return
    repo.set_state(ctx["tg_id"], "ticket_body", customer["tenant_id"], subject)
    bot.send(ctx["chat_id"], "توضیح مشکل را بنویسید (می‌توانید فایل هم بفرستید):",
             kb.cancel_button())


def on_state_body(ctx) -> None:
    customer = ctx["customer"]
    subject = ctx.get("state_data") or "تیکت"
    body = ctx.get("text") or ctx.get("caption") or ""
    file_id, file_type = _media(ctx)
    if not body and not file_id:
        bot.send(ctx["chat_id"], "متن یا فایلی نفرستید. توضیح:", kb.cancel_button())
        return
    if not body:
        body = "[فایل]"
    repo.clear_state(ctx["tg_id"])
    ticket_id = ticket_manager.open_ticket(customer["tenant_id"], customer, subject, body)
    _attach_file(ticket_id, file_id, file_type)
    ticket = repo.get_ticket(ticket_id)
    outside = "" if sla_manager.is_open_now(customer["tenant_id"]) else \
        "\n\n" + sla_manager.outside_hours_notice(customer["tenant_id"])
    bot.send(ctx["chat_id"],
             f"تیکت #{ticket['number']} ثبت شد. به‌زودی پاسخ می‌دهیم.{outside}",
             kb.markup([kb.btn("مشاهده تیکت", cb.enc(cb.TK, ticket["id"], "view"),
                               style="primary")]))


def _attach_file(ticket_id: int, file_id, file_type) -> None:
    if file_id:
        repo.add_message(ticket_id, "customer", None, "[فایل]", file_id, file_type)


def on_rate_cb(ctx) -> None:
    args = ctx.get("args") or []
    try:
        ticket_id, stars = int(args[0]), int(args[1])
    except (IndexError, ValueError):
        bot.answer_cb(ctx["cb_id"], "نامعتبر")
        return
    try:
        ticket_manager.rate(ticket_id, stars, ctx["tg_id"])
    except ticket_manager.TicketError as exc:
        bot.answer_cb(ctx["cb_id"], str(exc), alert=True)
        return
    ticket = repo.get_ticket(ticket_id)
    import notifications
    notifications.rating_received(ticket)
    bot.answer_cb(ctx["cb_id"], f"امتیاز {stars}/5 ثبت شد. ممنون!")
    if ctx.get("message_id"):
        try:
            bot.edit(ctx["chat_id"], ctx["message_id"], f"امتیاز شما: {stars}/5 ثبت شد. ممنون!")
        except bot.TgError:
            pass


# ============================================================= admin side

def on_customer_cb(ctx) -> None:
    if not ctx.get("is_admin") and not ctx.get("is_super_owner"):
        _deny(ctx)
        return
    args = ctx.get("args") or []
    op = args[0] if args else ""
    if op == "new":
        _start_add(ctx)
    elif op == "search":
        _start_search(ctx)
    elif op == "view" and len(args) > 1:
        _view(ctx, args[1])
    elif op == "tickets" and len(args) > 1:
        _tickets(ctx, args[1])
    elif op == "tag" and len(args) > 1:
        _start_tag(ctx, args[1])
    elif op == "close" and len(args) > 1:
        _remove(ctx, args[1])
    elif op == "list":
        _list(ctx, int(args[1]) if len(args) > 1 and args[1].isdigit() else 1)
    else:
        _list(ctx, 1)


def _start_add(ctx) -> None:
    tenant_id = _tenant(ctx)
    if not tenant_id:
        return
    repo.set_state(ctx["tg_id"], "add_customer_id", tenant_id)
    bot.send(ctx["chat_id"],
             "آیدی عددی مشتری را بفرستید.\n"
             "(تلگرام: تنظیمات > پروفایل > شناسه عددی)",
             kb.cancel_button())


def on_state_add_customer_id(ctx) -> None:
    tenant_id = ctx.get("tenant_id") or ctx.get("state_data")
    try:
        status = verification.start(tenant_id, ctx["tg_id"], ctx.get("text", ""))
    except verification.VerifyError as exc:
        bot.send(ctx["chat_id"], f"❌ {esc(str(exc))}", kb.cancel_button())
        return
    except Exception as exc:  # network etc
        bot.send(ctx["chat_id"], f"❌ خطا: {esc(str(exc)[:200])}", kb.cancel_button())
        return
    repo.clear_state(ctx["tg_id"])
    bot.send(ctx["chat_id"], f"✅ {status}",
             kb.markup([kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU), style="primary")]))


def _start_search(ctx) -> None:
    tenant_id = _tenant(ctx)
    if not tenant_id:
        return
    repo.set_state(ctx["tg_id"], "search_customer", tenant_id)
    bot.send(ctx["chat_id"], "نام، آیدی عددی یا تگ مشتری را بفرستید:", kb.cancel_button())


def on_state_search(ctx) -> None:
    tenant_id = ctx.get("tenant_id") or ctx.get("state_data")
    needle = (ctx.get("text") or "").strip()
    repo.clear_state(ctx["tg_id"])
    if not needle:
        bot.send(ctx["chat_id"], "چیزی ننوشتید.")
        return
    results = repo.find_customers(tenant_id, needle)
    if not results:
        bot.send(ctx["chat_id"], "مشتری‌ای پیدا نشد.",
                 kb.markup([kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))]))
        return
    text = "<b>نتایج جستجو</b>\n\n" + "\n".join(
        f"- {esc(c['name'] or c['username'] or c['tg_id'])} ({c['tg_id']})"
        for c in results[:20])
    bot.send(ctx["chat_id"], text, kb.customer_list(results[:20]))


def _list(ctx, page: int = 1) -> None:
    tenant_id = _tenant(ctx)
    if not tenant_id:
        return
    customers = repo.list_customers(tenant_id, limit=PAGE, offset=(page - 1) * PAGE)
    if not customers and page == 1:
        bot.send(ctx["chat_id"], "مشتری‌ای نیست.", kb.admin_customers_menu())
        return
    text = f"<b>مشتریان</b> (صفحه {page})"
    next_cb = cb.enc(cb.CU, "list", page + 1) if len(customers) == PAGE else None
    prev_cb = cb.enc(cb.CU, "list", page - 1) if page > 1 else None
    keyboard = kb.customer_list(customers, next_cb=next_cb, prev_cb=prev_cb)
    bot.send(ctx["chat_id"], text, keyboard)


def _view(ctx, raw_id: str) -> None:
    if not raw_id.isdigit():
        return
    customer = repo.get_customer(int(raw_id))
    if not customer or customer["tenant_id"] != _tenant(ctx):
        bot.send(ctx["chat_id"], "مشتری پیدا نشد.")
        return
    text, keyboard = menus.screen_customer_detail(customer)
    bot.send(ctx["chat_id"], text, keyboard)


def _tickets(ctx, raw_id: str) -> None:
    if not raw_id.isdigit():
        return
    customer = repo.get_customer(int(raw_id))
    if not customer or customer["tenant_id"] != _tenant(ctx):
        bot.send(ctx["chat_id"], "مشتری پیدا نشد.")
        return
    tickets = repo.customer_tickets(customer["id"], limit=10)
    text, keyboard = menus.screen_ticket_list(
        f"تیکت‌های {esc(customer['name'] or customer['tg_id'])}", tickets)
    bot.send(ctx["chat_id"], text, keyboard)


def _start_tag(ctx, raw_id: str) -> None:
    if not raw_id.isdigit():
        return
    customer = repo.get_customer(int(raw_id))
    if not customer or customer["tenant_id"] != _tenant(ctx):
        bot.send(ctx["chat_id"], "مشتری پیدا نشد.")
        return
    repo.set_state(ctx["tg_id"], "tag_customer", customer["tenant_id"], raw_id)
    bot.send(ctx["chat_id"],
             f"تگ مشتری {esc(customer['name'] or customer['tg_id'])} را بفرستید "
             "(خالی = حذف تگ):", kb.cancel_button())


def on_state_tag(ctx) -> None:
    raw_id = ctx.get("state_data")
    tenant_id = ctx.get("tenant_id") or ctx.get("state_data")
    repo.clear_state(ctx["tg_id"])
    if not raw_id or not str(raw_id).isdigit():
        bot.send(ctx["chat_id"], "مشتری پیدا نشد.")
        return
    customer = repo.get_customer(int(raw_id))
    if not customer or customer["tenant_id"] != tenant_id:
        bot.send(ctx["chat_id"], "مشتری پیدا نشد.")
        return
    text = (ctx.get("text") or "").strip()
    tag = validators.tag(text) if text else None
    if text and tag is None:
        bot.send(ctx["chat_id"], "تگ نامعتبر است (بدون فاصله، حداکثر ۳۲ کاراکتر).")
        return
    repo.set_customer_tag(customer["id"], tag)
    audit.log(tenant_id, ctx["tg_id"], audit.Act.CUSTOMER_TAG, target=customer["tg_id"],
              detail=tag or "removed")
    bot.send(ctx["chat_id"], "تگ ذخیره شد." if tag else "تگ حذف شد.")


def _remove(ctx, raw_id: str) -> None:
    if not raw_id.isdigit():
        return
    customer = repo.get_customer(int(raw_id))
    if not customer or customer["tenant_id"] != _tenant(ctx):
        bot.send(ctx["chat_id"], "مشتری پیدا نشد.")
        return
    repo.delete_customer(customer["id"])
    audit.log(_tenant(ctx), ctx["tg_id"], audit.Act.CUSTOMER_DELETE, target=customer["tg_id"])
    bot.send(ctx["chat_id"], "مشتری حذف شد. تیکت‌هایش نیز پاک شدند.",
             kb.markup([kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU), style="primary")]))


def _tenant(ctx) -> int | None:
    tid = ctx.get("tenant_id") or ctx.get("state_data")
    if not tid:
        _deny(ctx, "ابتدا /start بزنید.")
    return tid
