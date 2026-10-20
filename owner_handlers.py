"""Owner panel: create/manage businesses, platform report.

The super-owner (config.OWNER_TG_ID) sees every tenant; a tenant owner sees
only theirs.
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
import reports
import tenant_manager
import validators
from formatters import esc
from models import Role


def _owner(ctx) -> bool:
    if ctx.get("is_super_owner"):
        return True
    return bool(ctx.get("is_owner"))


def on_owner_cb(ctx) -> None:
    if not _owner(ctx):
        bot.send(ctx["chat_id"], "دسترسی نداری.", kb.cancel_button())
        return
    args = ctx.get("args") or []
    # Mixed encoding: "ow:<id>:<op>" (digit first) or "ow:<op>[:<arg>]".
    if args and args[0].isdigit():
        tid, op = int(args[0]), (args[1] if len(args) > 1 else "")
    else:
        tid, op = None, (args[0] if args else "")
    if op == "list":
        _list(ctx)
    elif op == "sell":
        _sell_start(ctx)
    elif op == "sellplan" and len(args) > 1 and args[1].isdigit():
        _sell_ask_id(ctx, int(args[1]))
    elif op == "accounts":
        _accounts(ctx)
    elif op == "orders":
        _orders(ctx)
    elif op == "plans":
        _plans(ctx)
    elif op == "planedit" and len(args) > 1 and args[1].isdigit():
        _plan_edit(ctx, int(args[1]))
    elif op == "planprice" and len(args) > 1 and args[1].isdigit():
        _plan_price_ask(ctx, int(args[1]))
    elif op == "plantoggle" and len(args) > 1 and args[1].isdigit():
        _plan_toggle(ctx, int(args[1]))
    elif op == "ok" and len(args) > 1 and args[1].isdigit():
        import buy_handlers
        buy_handlers.approve_order(ctx, int(args[1]), ctx["tg_id"])
    elif op == "no" and len(args) > 1 and args[1].isdigit():
        import buy_handlers
        buy_handlers.reject_order(ctx, int(args[1]), ctx["tg_id"])
    elif op == "card":
        _card_start(ctx)
    elif op == "holder":
        _holder_start(ctx)
    elif op == "payset":
        _pay_settings(ctx)
    elif op == "new":
        _start_new(ctx)
    elif op == "view" and tid:
        _view(ctx, tid)
    elif op == "enable" and tid:
        _set_status(ctx, tid, "active")
    elif op == "disable" and tid:
        _set_status(ctx, tid, "disabled")
    elif op == "report":
        bot.send(ctx["chat_id"], reports.platform_report())
    else:
        _list(ctx)


def _allowed(ctx, tenant_id: int) -> bool:
    if ctx.get("is_super_owner"):
        return True
    member = repo.member(tenant_id, ctx["tg_id"])
    return bool(member and member["role"] == Role.OWNER)


def _list(ctx) -> None:
    tenants = tenant_manager.tenants_of_owner(ctx["tg_id"])
    text, keyboard = menus.screen_tenants(tenants)
    bot.send(ctx["chat_id"], text, keyboard)


def _sell_start(ctx) -> None:
    """Owner sells a plan: first pick which plan the buyer gets."""
    import keyboards as kb2
    plans = repo.list_plans()
    if not plans:
        bot.send(ctx["chat_id"], "هیچ پلنی تعریف نشده است.")
        return
    bot.send(ctx["chat_id"],
             "پلن مشتری جدید را انتخاب کنید:",
             kb2.plan_picker(plans))


def _sell_ask_id(ctx, plan_id: int) -> None:
    plan = repo.get_plan(plan_id)
    if not plan:
        bot.send(ctx["chat_id"], "پلن پیدا نشد.")
        return
    repo.set_state(ctx["tg_id"], "sell_account", None, str(plan_id))
    bot.send(ctx["chat_id"],
             f"پلن <b>{esc(plan['name'])}</b> انتخاب شد.\n"
             "آیدی عددی مشتری را بفرستید (اول باید ربات را استارت کرده باشد):",
             kb.cancel_button())


def on_state_sell_account(ctx) -> None:
    import verification
    plan_id = ctx.get("state_data")
    tg_id = validators.tg_id(ctx.get("text", ""))
    if tg_id is None or not plan_id or not str(plan_id).isdigit():
        # Keep the state: a typo must not throw the owner out of the flow.
        bot.send(ctx["chat_id"],
                 "آیدی عددی نامعتبر است. دوباره بفرستید یا «انصراف» بزنید.")
        return
    repo.clear_state(ctx["tg_id"])
    try:
        status = verification.start_account(tg_id, int(plan_id))
    except verification.VerifyError as exc:
        bot.send(ctx["chat_id"], f"❌ {esc(str(exc))}")
        return
    bot.send(ctx["chat_id"], f"✅ {status}")


def _accounts(ctx) -> None:
    """Platform-level customer list (who bought a plan)."""
    accounts = repo.all_accounts()
    if not accounts:
        bot.send(ctx["chat_id"], "هنوز مشتری‌ای نخریده است.",
                 kb.markup([kb.btn("فروش پلن", cb.enc(cb.OW, "sell"), style="success")]))
        return
    lines = ["<b>مشتریان پلتفرم</b>"]
    for a in accounts:
        shops = repo.account_shop_count(a["id"])
        flag = {"active": "فعال", "pending": "در انتظار", "disabled": "غیرفعال"}.get(
            a["status"], a["status"])
        lines.append(
            f"- {esc(a.get('name') or a['tg_id'])} | {esc(a.get('plan_name') or '-')} | "
            f"{shops}/{a.get('max_shops') or 1} فروشگاه | {flag}")
    bot.send(ctx["chat_id"], "\n".join(lines),
             kb.markup([kb.btn("فروش پلن جدید", cb.enc(cb.OW, "sell"), style="success"),
                        kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))]))


def _orders(ctx) -> None:
    """Purchases waiting for approval."""
    rows = repo.pending_orders()
    if not rows:
        bot.send(ctx["chat_id"], "خرید در انتظار تأییدی نیست.",
                 kb.markup([kb.btn("پلن‌ها و قیمت‌ها", cb.enc(cb.OW, "plans")),
                            kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))]))
        return
    for o in rows[:10]:
        _send_order(ctx, o)


def _send_order(ctx, o) -> None:
    text = (
        f"<b>خرید #{o['id']}</b> در انتظار تأیید\n\n"
        f"پلن: {esc(o.get('plan_name') or '-')}\n"
        f"مبلغ: {int(o['amount']):,} تومان\n"
        f"خریدار: <code>{o['tg_id']}</code>"
    )
    keyboard = kb.order_review(o, o["tg_id"])
    file_id = o.get("receipt_file_id")
    if file_id:
        method = ("sendDocument" if o.get("receipt_type") == "document"
                  else "sendPhoto")
        key = "document" if method == "sendDocument" else "photo"
        try:
            bot.api(method, chat_id=ctx["chat_id"], **{key: file_id},
                    caption=text, reply_markup=keyboard)
            return
        except bot.TgError:
            pass
    bot.send(ctx["chat_id"], text, keyboard)


def _plans(ctx) -> None:
    plans = repo.list_plans(active_only=False)
    hints = []
    if not repo.card_number():
        hints.append("⚠️ شماره کارت تنظیم نشده — بدون آن خرید کار نمی‌کند.")
    if not any(int(p["price"] or 0) > 0 for p in plans):
        hints.append("⚠️ هیچ پلنی قیمت ندارد — خریدار چیزی برای انتخاب نمی‌بیند.")
    text = "<b>پلن‌ها و قیمت‌ها</b>\n\n"
    if hints:
        text += "\n".join(hints) + "\n\n"
    text += "روی هر پلن بزنید تا قیمت/وضعیتش را عوض کنید."
    bot.send(ctx["chat_id"], text, kb.plan_admin_list(plans))


def _plan_edit(ctx, plan_id: int) -> None:
    plan = repo.get_plan(plan_id)
    if not plan:
        bot.send(ctx["chat_id"], "پلن پیدا نشد.")
        return
    price = int(plan["price"] or 0)
    text = (
        f"<b>{esc(plan['name'])}</b>\n"
        f"سقف فروشگاه: {plan['max_shops']}\n"
        f"قیمت: {f'{price:,} تومان' if price else 'تعیین نشده'}\n"
        f"وضعیت: {'روشن' if plan['active'] else 'خاموش'}"
    )
    bot.send(ctx["chat_id"], text, kb.plan_admin_edit(plan))


def _plan_price_ask(ctx, plan_id: int) -> None:
    plan = repo.get_plan(plan_id)
    if not plan:
        bot.send(ctx["chat_id"], "پلن پیدا نشد.")
        return
    repo.set_state(ctx["tg_id"], "plan_price", None, str(plan_id))
    bot.send(ctx["chat_id"],
             f"قیمت جدید برای «{esc(plan['name'])}» را به تومان بفرستید:\n"
             "(۰ = غیرفعال کردن فروش این پلن)",
             kb.cancel_button())


def on_state_plan_price(ctx) -> None:
    plan_id = ctx.get("state_data")
    price = validators.price_toman(ctx.get("text", ""))
    if price is None or not plan_id or not str(plan_id).isdigit():
        bot.send(ctx["chat_id"], "عدد نامعتبر است. دوباره بفرستید یا لغو کنید:",
                 kb.cancel_button())
        return
    repo.set_plan_price(int(plan_id), price)
    audit.log(None, ctx["tg_id"], "plan.price", target=str(plan_id),
              detail=str(price))
    repo.clear_state(ctx["tg_id"])
    bot.send(ctx["chat_id"], "✅ قیمت ذخیره شد.",
             kb.markup([kb.btn("پلن‌ها", cb.enc(cb.OW, "plans"), style="primary")]))


def _plan_toggle(ctx, plan_id: int) -> None:
    active = repo.toggle_plan(plan_id)
    audit.log(None, ctx["tg_id"], "plan.toggle", target=str(plan_id),
              detail=str(active))
    bot.send(ctx["chat_id"], "✅ پلن روشن شد." if active else "پلن خاموش شد.",
             kb.markup([kb.btn("پلن‌ها", cb.enc(cb.OW, "plans"), style="primary")]))


def _pay_settings(ctx) -> None:
    """Card number + holder: the two things a bank transfer needs."""
    card = repo.card_number()
    holder = repo.card_holder()
    lines = [
        "<b>تنظیمات پرداخت</b>",
        "",
        f"شماره کارت: <code>{esc(card or '-')}</code>",
        f"به نام: {esc(holder or '-')}",
        "",
        "این اطلاعات به خریدار نشان داده می‌شود.",
    ]
    keyboard = kb.markup(
        [kb.btn("تغییر شماره کارت", cb.enc(cb.OW, "card"), style="primary"),
         kb.btn("تغییر نام صاحب کارت", cb.enc(cb.OW, "holder"))],
        [kb.btn("پلن‌ها و قیمت‌ها", cb.enc(cb.OW, "plans"))],
        [kb.btn("بازگشت", cb.enc(cb.NAV, cb.MENU))],
    )
    bot.send(ctx["chat_id"], "\n".join(lines), keyboard)


def _card_start(ctx) -> None:
    repo.set_state(ctx["tg_id"], "card_number", None)
    bot.send(ctx["chat_id"],
             "شماره کارت ۱۶ رقمی را بفرستید:\n(فقط عدد — بدون فاصله)",
             kb.cancel_button())


def on_state_card_number(ctx) -> None:
    card = validators.card_number(ctx.get("text", ""))
    if card is None:
        bot.send(ctx["chat_id"], "شماره کارت باید ۱۶ رقم باشد. دوباره بفرستید:",
                 kb.cancel_button())
        return
    repo.plat_set("card_number", card)
    audit.log(None, ctx["tg_id"], "platform.card", target="card_number")
    repo.clear_state(ctx["tg_id"])
    bot.send(ctx["chat_id"],
             f"✅ شماره کارت ذخیره شد:\n<code>{esc(card)}</code>",
             kb.markup([kb.btn("تنظیمات پرداخت", cb.enc(cb.OW, "payset"),
                               style="primary")]))


def _holder_start(ctx) -> None:
    repo.set_state(ctx["tg_id"], "card_holder", None)
    bot.send(ctx["chat_id"],
             "نام و نام خانوادگی صاحب کارت را بفرستید:",
             kb.cancel_button())


def on_state_card_holder(ctx) -> None:
    holder = validators.one_line(ctx.get("text", ""), 60)
    if not holder:
        bot.send(ctx["chat_id"], "نام نامعتبر است. دوباره بفرستید:",
                 kb.cancel_button())
        return
    repo.plat_set("card_holder", holder)
    repo.clear_state(ctx["tg_id"])
    bot.send(ctx["chat_id"], f"✅ نام صاحب کارت ذخیره شد: {esc(holder)}",
             kb.markup([kb.btn("تنظیمات پرداخت", cb.enc(cb.OW, "payset"),
                               style="primary")]))


def _start_new(ctx) -> None:
    repo.set_state(ctx["tg_id"], "new_tenant", None)
    bot.send(ctx["chat_id"],
             "نام کسب‌وکار را بفرستید (مثلا «فروشگاه الف»):",
             kb.cancel_button())


def on_state_new_tenant(ctx) -> None:
    name = validators.one_line(ctx.get("text", ""), 80)
    repo.clear_state(ctx["tg_id"])
    if name is None:
        bot.send(ctx["chat_id"], "نام نامعتبر است (۱ تا ۸۰ کاراکتر).")
        return
    try:
        tenant_id = tenant_manager.create(name, ctx["tg_id"])
    except tenant_manager.TenantError as exc:
        bot.send(ctx["chat_id"], f"❌ {esc(str(exc))}")
        return
    bot.send(ctx["chat_id"],
             f"✅ کسب‌وکار «{esc(name)}» ساخته شد.\n"
             "حالا اپراتور و مشتری اضافه کنید.",
             kb.markup([kb.btn("کسب‌وکارها", cb.enc(cb.OW, "list"), style="primary")]))


def _view(ctx, tenant_id: int) -> None:
    if not _allowed(ctx, tenant_id):
        bot.send(ctx["chat_id"], "دسترسی نداری.")
        return
    tenant = repo.get_tenant(tenant_id)
    if not tenant:
        bot.send(ctx["chat_id"], "کسب‌وکار پیدا نشد.")
        return
    stats = repo.tenant_stats(tenant_id)
    text = (
        f"<b>{esc(tenant['name'])}</b> ({'فعال' if tenant['status'] == 'active' else 'غیرفعال'})\n"
        f"مشتریان: {stats['customers']} | تیکت‌ها: {stats['total']} "
        f"(باز: {stats['open']})\n"
        f"اولین پاسخ: {stats['first_reply_min']} دقیقه | رضایت: {stats['rating'] or '-'}/5"
    )
    bot.send(ctx["chat_id"], text, kb.tenant_detail(tenant))


def _set_status(ctx, tenant_id: int, status: str) -> None:
    if not _allowed(ctx, tenant_id):
        bot.send(ctx["chat_id"], "دسترسی نداری.")
        return
    try:
        if status == "active":
            tenant_manager.enable(tenant_id, ctx["tg_id"])
        else:
            tenant_manager.disable(tenant_id, ctx["tg_id"])
    except tenant_manager.TenantError as exc:
        bot.send(ctx["chat_id"], f"❌ {esc(str(exc))}")
        return
    tenant = repo.get_tenant(tenant_id)
    _view(ctx, tenant_id)
    bot.send(ctx["chat_id"],
             f"وضعیت «{esc(tenant['name'])}»: "
             f"{'فعال' if status == 'active' else 'غیرفعال'}.")
