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
