"""Customer onboarding verification.

Flow (owner/admin adds a customer by numeric id):
  1. admin enters a numeric telegram id            -> validators.tg_id
  2. bot checks the target is a reachable human    -> is_human() via getChat
  3. bot sends the target a 6-digit code           -> issue + code_keyboard
  4. target sends the code back to the bot         -> confirm()
  5. customer row is created+verified, panel opens for them

`is_human` is authoritative here: validators.is_bot_id is only a heuristic,
and getChat tells us the truth (type, and whether the user ever started the
bot - a user who never pressed Start cannot be messaged at all).
"""
from __future__ import annotations

import audit
import bot
import keyboards
import repositories as repo
import validators
from formatters import esc


class VerifyError(Exception):
    """Business-level refusal with a Persian message for the admin."""


def is_human(tg_id: int) -> tuple[bool, str]:
    """Ask Telegram who this id is. Returns (ok, reason)."""
    try:
        chat = bot.api("getChat", chat_id=tg_id)
    except bot.TgError as exc:
        message = str(exc)
        if "user not found" in message.lower() or "chat not found" in message.lower():
            return False, "چنین کاربری پیدا نشد."
        if "bot can't initiate conversation" in message.lower() or "403" in message:
            return False, "این کاربر هنوز ربات را استارت نکرده است؛ ابتدا /start بزند."
        return False, f"تلگرام جواب نداد: {message[:120]}"
    ctype = (chat or {}).get("type", "")
    if ctype == "channel":
        return False, "این آیدی مربوط به کانال است، نه کاربر."
    if ctype not in ("private", "group", "supergroup"):
        return False, f"نوع چت پشتیبانی نمی‌شود: {ctype}"
    return True, ""


def start(tenant_id: int, admin_tg_id: int, raw_id: str) -> str:
    """Admin submitted an id. Sends the code; returns a status line."""
    tg_id = validators.tg_id(raw_id)
    if tg_id is None:
        raise VerifyError("آیدی عددی نامعتبر است. نمونه: 123456789")
    if validators.is_bot_id(tg_id):
        raise VerifyError("این آیدی شبیه آیدی یک ربات است؛ مشتری باید انسان باشد.")
    ok, reason = is_human(tg_id)
    if not ok:
        raise VerifyError(reason)

    existing = repo.member(tenant_id, tg_id)
    if existing:
        raise VerifyError("این کاربر عضو تیم است؛ مشتری نمی‌شود.")

    code = repo.issue_code(tenant_id, tg_id, "customer_verify")
    try:
        bot.send(
            tg_id,
            f"کد تأیید پشتیبانی:\n<code>{esc(code)}</code>\n\n"
            "آن را برای ربات بفرستید تا پنل شما فعال شود.",
            keyboards.code_keyboard(code),
        )
    except bot.TgError as exc:
        raise VerifyError(
            "امکان ارسال پیام به این کاربر نیست؛ باید اول ربات را استارت کند."
        ) from exc

    audit.log(tenant_id, admin_tg_id, audit.Act.CUSTOMER_ADD, target=tg_id)
    return f"کد تأیید برای <code>{tg_id}</code> ارسال شد. تا ۱۵ دقیقه فرصت دارد."


def confirm(tg_id: int, text: str) -> bool:
    """User sent a code. Returns True when it was a valid verify code."""
    code = validators.code(text)
    if code is None:
        return False
    tenant_id = repo.consume_code(tg_id, code, "customer_verify")
    if tenant_id is None:
        return False
    tenant = repo.get_tenant(tenant_id)
    if tenant is None or tenant["status"] != "active":
        return False
    repo.add_customer(tenant_id, tg_id, verified_at=_now())
    repo.mark_customer_verified(tenant_id, tg_id)
    audit.log(tenant_id, tg_id, audit.Act.CUSTOMER_VERIFY, target=tg_id)
    welcome = repo.get_setting(tenant_id, "welcome_text",
                               "به پشتیبانی خوش آمدی. از منوی زیر انتخاب کن:")
    bot.send(tenant_id_chat_of(tg_id), f"تأیید شد. {esc(welcome)}",
             keyboards.main_menu(is_customer=True, is_staff=False, is_admin=False,
                                 is_owner=False, has_open_ticket=False))
    return True


def tenant_id_chat_of(tg_id: int) -> int:
    return tg_id


def _now() -> int:
    import time
    return int(time.time())
