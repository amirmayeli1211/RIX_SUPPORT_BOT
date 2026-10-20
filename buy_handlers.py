"""Self-service purchase: a stranger buys a plan without the owner lifting a finger.

Flow
----
    /start -> "خرید پلن" -> plan + price -> owner's card shown (copy button)
      -> "ارسال رسید" -> user sends a photo/file -> order goes to `pending`
      -> owner gets an alert with [تأیید و فعال‌سازی] / [رد کردن]
      -> on approve: account activated + customer panel unlocked + buyer told

The owner only prices the plans and sets a card number; everything else is
automatic. Amounts are always read from the plan row, never from the user's
message, so a buyer cannot name their own price.
"""
from __future__ import annotations

import audit
import bot
import callbacks as cb
import keyboards as kb
import menus
import repositories as repo
import validators
from formatters import esc


# ================================================================ helpers

def _plans_on_sale():
    return repo.buyable_plans()


def _reject(ctx, text: str) -> None:
    bot.send(ctx["chat_id"], text, kb.cancel_button())


def _send(ctx, text, keyboard) -> None:
    if ctx.get("message_id"):
        try:
            bot.edit(ctx["chat_id"], ctx["message_id"], text, keyboard)
            return
        except bot.TgError:
            pass
    bot.send(ctx["chat_id"], text, keyboard)


def _already_customer(tg_id: int) -> bool:
    return repo.account_by_tg(tg_id) is not None


# ================================================================ screens

def screen_buy(ctx) -> None:
    plans = _plans_on_sale()
    card = repo.card_number()
    if not plans:
        bot.send(ctx["chat_id"],
                 "در حال حاضر پلنی برای فروش فعال نیست.",
                 kb.markup([kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))]))
        return
    lines = ["<b>خرید پلن</b>", ""]
    if not card:
        lines.append("⚠️ شماره کارت هنوز تنظیم نشده؛ به‌زودی فعال می‌شود.")
        lines.append("")
    lines.append("پلن مورد نظر را انتخاب کنید:")
    _send(ctx, "\n".join(lines), kb.buy_menu(plans))


def screen_plan(ctx, plan_id: int) -> None:
    plan = repo.get_plan(plan_id)
    if not plan or not plan["active"]:
        _reject(ctx, "این پلن موجود نیست.")
        return
    if int(plan["price"] or 0) <= 0:
        _reject(ctx, "این پلن قیمت‌گذاری نشده است.")
        return
    if _already_customer(ctx["tg_id"]):
        bot.send(ctx["chat_id"],
                 "شما همین حالا مشتری فعال هستید ✅\n"
                 "برای خرید فروشگاه بیشتر با مالک تماس بگیرید.",
                 kb.markup([kb.btn("پنل من", cb.enc(cb.ACC, "shops"), style="primary")]))
        return
    card = repo.card_number()
    holder = repo.card_holder()
    pending = repo.latest_order(ctx["tg_id"])
    if pending and pending["status"] == "awaiting_receipt":
        repo.set_order_status(pending["id"], "cancelled")
    order_id = repo.create_order(ctx["tg_id"], plan_id, int(plan["price"]))
    order = repo.get_order(order_id)
    lines = [
        f"<b>پلن {esc(plan['name'])}</b>",
        f"مبلغ: <b>{int(plan['price']):,} تومان</b>",
        f"سقف فروشگاه: {plan['max_shops']}",
        "",
    ]
    if card:
        lines.append("مبلغ را به شماره کارت زیر واریز کنید:")
        if holder:
            lines.append(f"به نام <b>{esc(holder)}</b>")
        lines.append("")
        lines.append(f"<code>{esc(card)}</code>")
        lines.append("")
        lines.append("سپس دکمه «ارسال رسید» را بزنید و تصویر رسید را بفرستید.")
    else:
        lines.append("⚠️ شماره کارت تنظیم نشده است؛ با مالک تماس بگیرید.")
    bot.send(ctx["chat_id"], "\n".join(lines),
             kb.payment_screen(order, card, holder))


def screen_mine(ctx) -> None:
    orders = repo.orders_of(ctx["tg_id"])
    if not orders:
        bot.send(ctx["chat_id"], "هنوز خریدی ثبت نکرده‌اید.",
                 kb.markup([kb.btn("خرید پلن", cb.enc(cb.BUY, "start"),
                                   style="success"),
                            kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))]))
        return
    flag = {"awaiting_receipt": "در انتظار رسید", "pending": "در حال بررسی",
            "approved": "تأیید شده ✅", "rejected": "رد شده ❌",
            "cancelled": "لغو شده"}
    lines = ["<b>خریدهای من</b>", ""]
    for o in orders:
        lines.append(
            f"#{o['id']} · {esc(o.get('plan_name') or '-')} · "
            f"{int(o['amount']):,} ت · {flag.get(o['status'], o['status'])}")
    bot.send(ctx["chat_id"], "\n".join(lines),
             kb.markup([kb.btn("خرید پلن", cb.enc(cb.BUY, "start"), style="success"),
                        kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))]))


# ============================================================== callbacks

def on_buy_cb(ctx) -> None:
    args = ctx.get("args") or []
    op = args[0] if args else ""
    if op in ("start", "") or op == "list":
        screen_buy(ctx)
    elif op == "plan" and len(args) > 1 and args[1].isdigit():
        screen_plan(ctx, int(args[1]))
    elif op == "mine":
        screen_mine(ctx)
    elif op == "receipt" and len(args) > 1 and args[1].isdigit():
        _ask_receipt(ctx, int(args[1]))
    elif op == "cancel" and len(args) > 1 and args[1].isdigit():
        _cancel(ctx, int(args[1]))
    else:
        screen_buy(ctx)


def _ask_receipt(ctx, order_id: int) -> None:
    order = repo.get_order(order_id)
    if not order or order["tg_id"] != ctx["tg_id"]:
        _reject(ctx, "این خرید مال شما نیست.")
        return
    if order["status"] not in ("awaiting_receipt", "rejected"):
        bot.send(ctx["chat_id"], "این خرید در حال بررسی است.")
        return
    repo.set_state(ctx["tg_id"], "buy_receipt", None, str(order_id))
    bot.send(ctx["chat_id"],
             "تصویر رسید پرداخت را بفرستید 📸\n"
             "(عکس یا فایل — پس از ارسال، مالک آن را بررسی می‌کند.)",
             kb.cancel_button())


def _cancel(ctx, order_id: int) -> None:
    order = repo.get_order(order_id)
    if not order or order["tg_id"] != ctx["tg_id"]:
        _reject(ctx, "این خرید مال شما نیست.")
        return
    if order["status"] in ("pending", "approved"):
        bot.send(ctx["chat_id"], "این خرید دیگر قابل لغو نیست.")
        return
    repo.set_order_status(order_id, "cancelled")
    bot.send(ctx["chat_id"], "خرید لغو شد.",
             kb.markup([kb.btn("خرید پلن", cb.enc(cb.BUY, "start"), style="success"),
                        kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))]))


# =================================================================== FSM

def on_state_buy_receipt(ctx) -> None:
    """The buyer sent the receipt (photo/document/anything with a file)."""
    order_id = ctx.get("state_data")
    if not order_id or not str(order_id).isdigit():
        repo.clear_state(ctx["tg_id"])
        bot.send(ctx["chat_id"], "خرید نامعتبر است.")
        return
    order = repo.get_order(int(order_id))
    if not order or order["tg_id"] != ctx["tg_id"]:
        repo.clear_state(ctx["tg_id"])
        _reject(ctx, "این خرید مال شما نیست.")
        return
    file_id, file_type = _receipt_media(ctx)
    if not file_id:
        bot.send(ctx["chat_id"],
                 "لطفاً تصویر یا فایل رسید را بفرستید (متن کافی نیست).",
                 kb.cancel_button())
        return
    repo.attach_receipt(order["id"], file_id, file_type or "photo")
    order = repo.get_order(order["id"])   # re-read: now carries the receipt
    repo.clear_state(ctx["tg_id"])
    audit.log(None, ctx["tg_id"], "order.receipt", target=str(order["id"]),
              detail=f"plan={order['plan_id']} amount={order['amount']}")
    bot.send(ctx["chat_id"],
             f"رسید شما ثبت شد ✅\nشماره خرید: #{order['id']}\n"
             "پس از تأیید مالک، پنل شما فعال می‌شود و همین‌جا خبر می‌دهیم.",
             kb.markup([kb.btn("خریدهای من", cb.enc(cb.BUY, "mine"))]))
    _notify_owner(order)


def _receipt_media(ctx):
    if ctx.get("photo"):
        return ctx["photo"], "photo"
    if ctx.get("document"):
        return ctx["document"], "document"
    return None, None


def _notify_owner(order) -> None:
    """Alert the platform owner with approve/reject buttons + the receipt."""
    owner = _owner_tg_id()
    if not owner:
        return
    buyer = order["tg_id"]
    text = (
        "<b>خرید جدید در انتظار تأیید</b>\n\n"
        f"خرید #{order['id']} · پلن {esc(order.get('plan_name') or '-')}\n"
        f"مبلغ: {int(order['amount']):,} تومان\n"
        f"خریدار: <code>{buyer}</code>"
    )
    keyboard = kb.order_review(order, buyer)
    file_id = order.get("receipt_file_id")
    method = ("sendDocument" if order.get("receipt_type") == "document"
              else "sendPhoto")
    key = "document" if method == "sendDocument" else "photo"
    if file_id:
        try:
            bot.api(method, chat_id=owner, **{key: file_id},
                    caption=text, reply_markup=keyboard)
            return
        except bot.TgError:
            pass  # fall through to the text-only alert
    try:
        bot.send(owner, text, keyboard)
    except bot.TgError:
        pass


def _owner_tg_id():
    import config
    return config.OWNER_TG_ID or 0


# ================================================================ approve

def approve_order(ctx, order_id: int, by_tg_id: int) -> None:
    """Owner confirmed payment: activate the buyer's account immediately."""
    order = repo.get_order(order_id)
    if not order:
        _reject(ctx, "خرید پیدا نشد.")
        return
    if order["status"] == "approved":
        bot.send(ctx["chat_id"], "این خرید قبلاً تأیید شده است.")
        return
    plan = repo.get_plan(order["plan_id"])
    if not plan:
        _reject(ctx, "پلن این خرید حذف شده است.")
        return
    buyer = order["tg_id"]
    account = repo.account_by_tg(buyer)
    if account is None:
        account_id = repo.create_account(buyer, plan["id"], name=str(buyer))
        repo.mark_account_verified(account_id)
    else:
        account_id = account["id"]
        repo.set_account_plan(account_id, plan["id"])
    repo.set_order_status(order_id, "approved", reviewed_by=by_tg_id)
    import database as db
    db.ex("UPDATE orders SET account_id=? WHERE id=?", (account_id, order_id))
    audit.log(None, by_tg_id, "order.approve", target=str(order_id),
              detail=f"account={account_id} plan={plan['id']}")
    bot.send(ctx["chat_id"], f"✅ خرید #{order_id} تأیید شد و پنل خریدار فعال شد.")
    _welcome_buyer(buyer, plan)


def reject_order(ctx, order_id: int, by_tg_id: int, reason: str = "") -> None:
    order = repo.get_order(order_id)
    if not order:
        _reject(ctx, "خرید پیدا نشد.")
        return
    if order["status"] == "approved":
        bot.send(ctx["chat_id"], "این خرید تأیید شده و قابل رد نیست.")
        return
    repo.set_order_status(order_id, "rejected", reviewed_by=by_tg_id)
    audit.log(None, by_tg_id, "order.reject", target=str(order_id))
    bot.send(ctx["chat_id"], f"خرید #{order_id} رد شد.")
    try:
        bot.send(order["tg_id"],
                 f"متأسفانه خرید #{order_id} تأیید نشد ❌\n"
                 + (f"دلیل: {esc(reason)}\n" if reason else "")
                 + "اگر فکر می‌کنید اشتباهی رخ داده، به مالک پیام بدهید.",
                 kb.markup([kb.btn("خرید پلن", cb.enc(cb.BUY, "start"))]))
    except bot.TgError:
        pass


def _welcome_buyer(tg_id: int, plan) -> None:
    account = repo.account_by_tg(tg_id)
    if not account:
        return
    text, keyboard = menus.screen_account_menu(account)
    try:
        bot.send(tg_id,
                 f"🎉 پلن <b>{esc(plan['name'])}</b> برای شما فعال شد!\n"
                 "از همین حالا می‌توانید فروشگاه بسازید.\n\n" + text,
                 keyboard)
    except bot.TgError:
        pass
