"""Admin panel: settings, operators, reports, audit - all via buttons."""
from __future__ import annotations

import audit
import bot
import callbacks as cb
import config
import database as db
import keyboards as kb
import menus
import operator_manager
import repositories as repo
import reports
import validators
from formatters import esc, mention
from models import ALL_ROLES, Role

SETTING_VALIDATORS = {
    "sla_minutes": validators.sla_minutes,
    "business_hours": validators.business_hours,
    "support_url": validators.url,
    "welcome_text": lambda v: validators.paragraph(v, 1000),
    "outside_hours_text": lambda v: validators.paragraph(v, 500),
}


def _admin(ctx) -> bool:
    return bool(ctx.get("is_admin") or ctx.get("is_super_owner"))


def _deny(ctx) -> None:
    bot.send(ctx["chat_id"], "دسترسی نداری.", kb.cancel_button())


# ================================================================ callbacks

def on_admin_cb(ctx) -> None:
    if not _admin(ctx):
        _deny(ctx)
        return
    args = ctx.get("args") or []
    op = args[0] if args else ""
    if op == "settings":
        _settings(ctx)
    elif op == "set" and len(args) > 1:
        _edit_setting(ctx, args[1])
    elif op == "operators":
        _operators(ctx)
    elif op == "op_add":
        _start_add_operator(ctx)
    elif op == "customers":
        _customers(ctx)
    elif op == "report":
        _report(ctx)
    elif op == "audit":
        _audit(ctx)
    else:
        _settings(ctx)


def _settings(ctx) -> None:
    tenant_id = ctx["tenant_id"]
    text, keyboard = menus.screen_settings(repo.all_settings(tenant_id))
    _send_or_edit(ctx, text, keyboard)


def _edit_setting(ctx, key: str) -> None:
    if key not in SETTING_VALIDATORS:
        bot.answer_cb(ctx["cb_id"], "نامعتبر")
        return
    tenant_id = ctx["tenant_id"]
    current = repo.get_setting(tenant_id, key, "")
    repo.set_state(ctx["tg_id"], "set_value", tenant_id, key)
    text, keyboard = menus.screen_setting_edit(key, current)
    bot.send(ctx["chat_id"], text, keyboard)


def on_state_set_value(ctx) -> None:
    key = ctx.get("state_data")
    tenant_id = ctx.get("tenant_id") or ctx.get("state_data")
    validator = SETTING_VALIDATORS.get(key or "")
    if validator is None:
        repo.clear_state(ctx["tg_id"])
        bot.send(ctx["chat_id"], "تنظیم نامعتبر بود.")
        return
    raw = (ctx.get("text") or "").strip()
    value = validator(raw)
    if value is None:
        bot.send(ctx["chat_id"], "مقدار نامعتبر است. دوباره بفرستید یا لغو کنید:",
                 kb.cancel_button())
        return
    repo.set_setting(tenant_id, key, value)
    audit.log(tenant_id, ctx["tg_id"], audit.Act.SETTING_SET, target=key)
    repo.clear_state(ctx["tg_id"])
    bot.send(ctx["chat_id"], "✅ ذخیره شد.",
             kb.markup([kb.btn("تنظیمات", cb.enc(cb.AD, "settings"), style="primary")]))


def _operators(ctx) -> None:
    tenant_id = ctx["tenant_id"]
    rows = operator_manager.staff_rows(tenant_id)
    members = [m for m, _ in rows]
    loads = {m["tg_id"]: load for m, load in rows}
    text = "<b>اپراتورها</b>\n\nبار کاری هر نفر = تیکت‌های باز او."
    bot.send(ctx["chat_id"], text, kb.operator_list(members, loads))


def _start_add_operator(ctx) -> None:
    repo.set_state(ctx["tg_id"], "add_operator_id", ctx["tenant_id"])
    bot.send(ctx["chat_id"],
             "آیدی عددی اپراتور جدید را بفرستید (اول باید ربات را استارت کرده باشد):",
             kb.cancel_button())


def on_state_add_operator(ctx) -> None:
    import verification
    tenant_id = ctx.get("tenant_id") or ctx.get("state_data")
    tg_id = validators.tg_id(ctx.get("text", ""))
    if tg_id is None:
        bot.send(ctx["chat_id"], "آیدی عددی نامعتبر است. دوباره:", kb.cancel_button())
        return
    ok, reason = verification.is_human(tg_id)
    if not ok:
        bot.send(ctx["chat_id"], f"❌ {esc(reason)}", kb.cancel_button())
        return
    if repo.customer_by_tg(tg_id, tenant_id):
        bot.send(ctx["chat_id"],
                 "این کاربر مشتری است؛ ابتدا از فهرست مشتریان حذفش کنید.",
                 kb.cancel_button())
        return
    repo.add_member(tenant_id, tg_id, Role.AGENT,
                    capacity=config.DEFAULT_AGENT_CAPACITY)
    audit.log(tenant_id, ctx["tg_id"], audit.Act.MEMBER_ADD, target=tg_id, detail="agent")
    repo.clear_state(ctx["tg_id"])
    try:
        bot.send(tg_id, "شما به عنوان اپراتور اضافه شدید. /start بزنید.")
    except bot.TgError:
        pass
    bot.send(ctx["chat_id"], "✅ اپراتور اضافه شد.",
             kb.markup([kb.btn("اپراتورها", cb.enc(cb.AD, "operators"), style="primary")]))


def _customers(ctx) -> None:
    tenant_id = ctx["tenant_id"]
    total = repo.count_customers(tenant_id)
    pending = repo.count_unverified(tenant_id)
    text = (f"<b>مشتریان</b>\nکل: {total} | در انتظار وریفای: {pending}\n\n"
            "برای افزودن، آیدی عددی مشتری را بدهید تا کد تأیید برود.")
    bot.send(ctx["chat_id"], text, kb.admin_customers_menu())


def _report(ctx) -> None:
    tenant_id = ctx["tenant_id"]
    bot.send(ctx["chat_id"], reports.tenant_report(tenant_id))


def _audit(ctx) -> None:
    tenant_id = ctx.get("tenant_id")
    rows = audit.recent(tenant_id, limit=20)
    bot.send(ctx["chat_id"], audit.render(rows))


# ============================================================== operators

def on_operator_cb(ctx) -> None:
    if not _admin(ctx):
        _deny(ctx)
        return
    args = ctx.get("args") or []
    op = args[0] if args else ""
    if op == "view" and len(args) > 1 and args[1].isdigit():
        _view_operator(ctx, int(args[1]))
    elif op == "role" and len(args) > 2:
        _set_role(ctx, args[1], args[2])
    elif op == "cap" and len(args) > 1 and args[1].isdigit():
        _ask_capacity(ctx, int(args[1]))
    elif op == "off" and len(args) > 1 and args[1].isdigit():
        _deactivate(ctx, int(args[1]))
    elif op == "del" and len(args) > 1 and args[1].isdigit():
        _remove(ctx, int(args[1]))
    else:
        bot.answer_cb(ctx["cb_id"], "نامعتبر")


def _member_of_tenant(ctx, tg_id: int):
    member = repo.member(ctx["tenant_id"], tg_id)
    return member


def _view_operator(ctx, tg_id: int) -> None:
    member = _member_of_tenant(ctx, tg_id)
    if not member:
        bot.send(ctx["chat_id"], "اپراتور پیدا نشد.")
        return
    load = operator_manager.load_of(ctx["tenant_id"], tg_id)
    text, keyboard = menus.screen_operator_detail(member, load)
    bot.send(ctx["chat_id"], text, keyboard)


def _set_role(ctx, raw_id: str, role_value: str) -> None:
    if not raw_id.isdigit() or role_value not in ALL_ROLES:
        bot.answer_cb(ctx["cb_id"], "نامعتبر")
        return
    tg_id = int(raw_id)
    member = _member_of_tenant(ctx, tg_id)
    if not member:
        bot.send(ctx["chat_id"], "اپراتور پیدا نشد.")
        return
    if member["role"] == Role.OWNER:
        bot.answer_cb(ctx["cb_id"], "نقش مالک قابل تغییر نیست", alert=True)
        return
    if ctx.get("is_super_owner") or ctx.get("role") == Role.OWNER or \
            (ctx.get("role") == Role.ADMIN and role_value != Role.OWNER):
        repo.set_member_role(ctx["tenant_id"], tg_id, role_value)
        audit.log(ctx["tenant_id"], ctx["tg_id"], audit.Act.MEMBER_ROLE, target=tg_id,
                  detail=role_value)
        bot.answer_cb(ctx["cb_id"], "نقش تغییر کرد")
    else:
        bot.answer_cb(ctx["cb_id"], "اجازه نداری", alert=True)


def _ask_capacity(ctx, tg_id: int) -> None:
    member = _member_of_tenant(ctx, tg_id)
    if not member:
        bot.send(ctx["chat_id"], "اپراتور پیدا نشد.")
        return
    repo.set_state(ctx["tg_id"], "op_capacity", ctx["tenant_id"], str(tg_id))
    bot.send(ctx["chat_id"],
             f"سقف تیکت‌های همزمان برای {esc(member['name'] or str(tg_id))} "
             f"(الان {member['capacity']}) را بفرستید (۱ تا ۱۰۰):",
             kb.cancel_button())


def on_state_capacity(ctx) -> None:
    raw_id = ctx.get("state_data")
    tenant_id = ctx.get("tenant_id") or ctx.get("state_data")
    value = validators.capacity(ctx.get("text", ""))
    repo.clear_state(ctx["tg_id"])
    if not raw_id or not str(raw_id).isdigit() or value is None:
        bot.send(ctx["chat_id"], "مقدار نامعتبر بود.")
        return
    repo.set_member_capacity(tenant_id, int(raw_id), value)
    audit.log(tenant_id, ctx["tg_id"], audit.Act.MEMBER_ROLE, target=raw_id,
              detail=f"capacity={value}")
    bot.send(ctx["chat_id"], "✅ سقف به‌روزرسانی شد.")


def _deactivate(ctx, tg_id: int) -> None:
    member = _member_of_tenant(ctx, tg_id)
    if not member:
        bot.send(ctx["chat_id"], "اپراتور پیدا نشد.")
        return
    if member["role"] == Role.OWNER:
        bot.answer_cb(ctx["cb_id"], "مالک را نمی‌توان غیرفعال کرد", alert=True)
        return
    repo.set_member_active(ctx["tenant_id"], tg_id, 0)
    audit.log(ctx["tenant_id"], ctx["tg_id"], audit.Act.MEMBER_REMOVE, target=tg_id,
              detail="deactivated")
    bot.answer_cb(ctx["cb_id"], "غیرفعال شد")


def _remove(ctx, tg_id: int) -> None:
    member = _member_of_tenant(ctx, tg_id)
    if not member:
        bot.send(ctx["chat_id"], "اپراتور پیدا نشد.")
        return
    if member["role"] == Role.OWNER:
        bot.answer_cb(ctx["cb_id"], "مالک را نمی‌توان حذف کرد", alert=True)
        return
    repo.set_member_active(ctx["tenant_id"], tg_id, 0)
    audit.log(ctx["tenant_id"], ctx["tg_id"], audit.Act.MEMBER_REMOVE, target=tg_id,
              detail="removed")
    bot.answer_cb(ctx["cb_id"], "حذف شد")


# ------------------------------------------------------------------ utils

def _send_or_edit(ctx, text, keyboard) -> None:
    if ctx.get("message_id"):
        try:
            bot.edit(ctx["chat_id"], ctx["message_id"], text, keyboard)
            return
        except bot.TgError:
            pass
    bot.send(ctx["chat_id"], text, keyboard)
