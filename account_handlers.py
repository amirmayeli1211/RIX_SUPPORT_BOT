"""Customer panel (account layer): the shops a paying customer owns.

An account sits ABOVE shops: Reza sells a plan, the customer builds up to
`max_shops` shops from here, and each shop runs the full operator/ticket flow.
Nothing platform-level leaks into a shop's own panel.
"""
from __future__ import annotations

import audit
import bot
import callbacks as cb
import keyboards as kb
import menus
import repositories as repo
import tenant_manager
import validators
from formatters import esc


def _account(ctx):
    """The caller's active account, or None (denied by callers)."""
    return repo.account_by_tg(ctx["tg_id"])


def _deny(ctx, text: str = "دسترسی نداری.") -> None:
    bot.send(ctx["chat_id"], text, kb.cancel_button())


# ----------------------------------------------------------------- routing

def on_account_cb(ctx) -> None:
    """Callback namespace acc: <op>[:arg]."""
    if not ctx.get("is_account"):
        _deny(ctx, "پنل مشتری فعال ندارید.")
        return
    args = ctx.get("args") or []
    op = args[0] if args else ""
    if op == "shops":
        _shops(ctx)
    elif op == "new":
        _start_new_shop(ctx)
    elif op == "plan":
        _plan(ctx)
    elif op == "enter" and len(args) > 1 and args[1].isdigit():
        _enter_shop(ctx, int(args[1]))
    elif op == "createshop":
        _create_shop(ctx, (args[1] if len(args) > 1 else ""))
    else:
        _shops(ctx)


# ------------------------------------------------------------------ screens

def _send(ctx, text, keyboard) -> None:
    if ctx.get("message_id"):
        try:
            bot.edit(ctx["chat_id"], ctx["message_id"], text, keyboard)
            return
        except bot.TgError:
            pass
    bot.send(ctx["chat_id"], text, keyboard)


def _shops(ctx) -> None:
    account = _account(ctx)
    if not account:
        _deny(ctx)
        return
    text, keyboard = menus.screen_account_menu(account)
    _send(ctx, text, keyboard)


def _plan(ctx) -> None:
    account = _account(ctx)
    if not account:
        _deny(ctx)
        return
    text, keyboard = menus.screen_plan(account)
    _send(ctx, text, keyboard)


def _enter_shop(ctx, shop_id: int) -> None:
    account = _account(ctx)
    shop = repo.get_tenant(shop_id)
    if not account or not shop or shop.get("account_id") != account["id"]:
        _deny(ctx, "این فروشگاه مال شما نیست.")
        return
    if shop["status"] != "active":
        _deny(ctx, "این فروشگاه غیرفعال است.")
        return
    # Bind the caller into this shop so every downstream handler (settings,
    # operators, tickets) scopes to it. tenant_id is only ever set from an
    # ownership-checked account, never from user input.
    ctx["tenant_id"] = shop["id"]
    ctx["tenant_name"] = shop["name"]
    ctx["is_staff"] = True
    ctx["role"] = "owner"
    ctx["is_admin"] = True
    ctx["is_owner"] = True
    ctx["shop_entered"] = True
    text, keyboard = menus.screen_shop_entered(shop)
    _send(ctx, text, keyboard)


# --------------------------------------------------------------- create flow

def _start_new_shop(ctx) -> None:
    account = _account(ctx)
    if not account:
        _deny(ctx)
        return
    used = repo.account_shop_count(account["id"])
    cap = account.get("max_shops") or 1
    if used >= cap:
        bot.send(ctx["chat_id"],
                 f"به سقف پلن ({cap} فروشگاه) رسیدید. برای ارتقا با مالک تماس بگیرید.",
                 kb.markup([kb.btn("پلن من", cb.enc(cb.ACC, "plan"))]))
        return
    repo.set_state(ctx["tg_id"], "new_shop", None, str(account["id"]))
    bot.send(ctx["chat_id"],
             f"نام فروشگاه جدید را بفرستید ({used + 1} از {cap}):",
             kb.cancel_button())


def on_state_new_shop(ctx) -> None:
    """FSM: account holder typed a shop name."""
    account_id = ctx.get("state_data")
    repo.clear_state(ctx["tg_id"])
    name = validators.one_line(ctx.get("text", ""), 80)
    if name is None:
        bot.send(ctx["chat_id"], "نام نامعتبر است (۱ تا ۸۰ کاراکتر).")
        return
    if not account_id or not str(account_id).isdigit():
        bot.send(ctx["chat_id"], "خطا در شناسایی حساب شما.")
        return
    account = repo.get_account(int(account_id))
    if not account or account["status"] != "active":
        _deny(ctx, "حساب شما فعال نیست.")
        return
    used = repo.account_shop_count(account["id"])
    cap = account.get("max_shops") or 1
    if used >= cap:
        bot.send(ctx["chat_id"], f"به سقف پلن ({cap} فروشگاه) رسیدید.")
        return
    _create_shop_named(ctx, account, name)


def _create_shop(ctx, _arg: str) -> None:
    """Button path without FSM arg: fall back to asking for the name."""
    _start_new_shop(ctx)


def _create_shop_named(ctx, account, name: str) -> None:
    try:
        tenant_id = tenant_manager.create(
            name, account["tg_id"], account_id=account["id"])
    except tenant_manager.TenantError as exc:
        bot.send(ctx["chat_id"], f"❌ {esc(str(exc))}")
        return
    audit.log(tenant_id, ctx["tg_id"], "shop.create", target=name,
              detail=f"account={account['id']}")
    shop = repo.get_tenant(tenant_id)
    bot.send(ctx["chat_id"],
             f"فروشگاه «{esc(name)}» ساخته شد ✅\\n"
             "اکنون اپراتور اضافه کنید و لینک تیکت را بدهید.",
             kb.markup([kb.btn("ورود به فروشگاه", cb.enc(cb.ACC, "enter", tenant_id),
                               style="success"),
                        kb.btn("فروشگاه‌های من", cb.enc(cb.ACC, "shops"))]))
