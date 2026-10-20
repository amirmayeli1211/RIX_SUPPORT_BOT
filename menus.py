"""Menu screens: text + keyboard pairs, one function per screen.

Handlers call screen_*() and send/edit the result - no handler assembles a
menu inline, so a screen looks identical whether it is reached from /start,
a back button, or a callback.
"""
from __future__ import annotations

import callbacks as cb
import config
import keyboards as kb
import repositories as repo
import sla_manager
from formatters import (ago, esc, human_dt, mention, priority_label, status_label,
                        ticket_card)
from models import Status


def _menu_row(ctx) -> dict | None:
    return kb.main_menu(
        is_customer=ctx.get("is_customer", False),
        is_staff=ctx.get("is_staff", False),
        is_admin=ctx.get("is_admin", False),
        is_owner=ctx.get("is_owner", False),
        has_open_ticket=ctx.get("has_open_ticket", False),
        is_super_owner=ctx.get("is_super_owner", False),
    )


def screen_menu(ctx) -> tuple[str, dict | None]:
    lines = ["<b>منوی اصلی</b>"]
    tenant_name = ctx.get("tenant_name")
    if tenant_name:
        lines.append(f"کسب‌وکار: {esc(tenant_name)}")
    if ctx.get("is_customer"):
        lines.append("برای دریافت پشتیبانی، تیکت جدید بسازید.")
    if ctx.get("is_staff"):
        lines.append("تیکت‌های منتظر پاسخ را از فهرست تیم ببینید.")
    return "\n".join(lines), _menu_row(ctx)


def screen_outside_hours(tenant_id: int, has_open_ticket: bool, ctx) -> tuple[str, dict | None]:
    notice = sla_manager.outside_hours_notice(tenant_id)
    return notice, _menu_row(ctx)


def screen_ticket_list(title: str, tickets, *, next_cb: str | None = None,
                       prev_cb: str | None = None) -> tuple[str, dict | None]:
    if not tickets:
        return f"{title}\n\nموردی وجود ندارد.", kb.ticket_list([])
    body = "\n".join(
        f"#{t['number']} | {esc(t.get('customer_name') or t.get('customer_id'))} | "
        f"{status_label(t['status'])} | {ago(t['last_customer_msg_at'] or t['created_at'])}"
        for t in tickets
    )
    return f"<b>{title}</b>\n\n{body}", kb.ticket_list(
        tickets, next_cb=next_cb, prev_cb=prev_cb)


def screen_ticket_detail(ticket, *, is_staff: bool) -> tuple[str, dict | None]:
    import ticket_manager
    overdue = sla_manager.is_overdue(ticket)
    text = ticket_manager.summary(ticket, is_staff=is_staff)
    if overdue:
        text += "\n\n<b>این تیکت از SLA گذشته است.</b>"
    if not is_staff:
        text += f"\n\nاولویت: {priority_label(ticket['priority'])} | وضعیت: {status_label(ticket['status'])}"
    return text, kb.ticket_detail(ticket, is_staff=is_staff)


def screen_customer_detail(customer) -> tuple[str, dict | None]:
    tickets = repo.customer_tickets(customer["id"], limit=10)
    lines = [
        f"<b>مشتری</b> {mention(customer['tg_id'], customer['name'], customer['username'])}",
        f"شناسه: <code>{customer['tg_id']}</code>",
        f"وضعیت: {'تایید شده' if customer['verified_at'] else 'در انتظار وریفای'}",
        f"تگ: {esc(customer['tag'] or '-')}",
        f"تیکت‌ها: {len(tickets)}",
        f"عضویت: {human_dt(customer['created_at'])}",
    ]
    if tickets:
        lines.append("")
        lines.append("<b>آخرین تیکت‌ها</b>")
        for t in tickets[:5]:
            lines.append(f"- #{t['number']} {esc(t['subject'] or '')} [{status_label(t['status'])}]")
    return "\n".join(lines), kb.customer_detail(customer)


def screen_operator_detail(member_row, load: int) -> tuple[str, dict | None]:
    text = (
        f"<b>اپراتور</b> {mention(member_row['tg_id'], member_row['name'], member_row['username'])}\n"
        f"شناسه: <code>{member_row['tg_id']}</code>\n"
        f"نقش: {member_row['role']}\n"
        f"بار کاری: {load}/{member_row['capacity']}\n"
        f"وضعیت: {'فعال' if member_row['active'] else 'غیرفعال'}"
    )
    return text, kb.operator_detail(member_row, load)


def screen_settings(settings: dict) -> tuple[str, dict | None]:
    lines = ["<b>تنظیمات کسب‌وکار</b>", "", "برای تغییر، روی مورد مربوطه بزنید."]
    return "\n".join(lines), kb.settings_menu(settings)


def screen_setting_edit(key: str, current: str) -> tuple[str, dict | None]:
    label = kb.SETTING_LABELS.get(key, key)
    return (f"<b>{esc(label)}</b>\n\nمقدار فعلی: <code>{esc(current or '-')}</code>\n\n"
            "مقدار جدید را بفرستید:",
            kb.cancel_button())


def screen_tenants(tenants) -> tuple[str, dict | None]:
    if not tenants:
        return "هنوز کسب‌وکاری ثبت نشده.", kb.tenant_list([])
    body = "\n".join(
        f"- {esc(t['name'])} ({'فعال' if t['status'] == 'active' else 'غیرفعال'})"
        for t in tenants
    )
    return f"<b>کسب‌وکارها</b>\n\n{body}", kb.tenant_list(tenants)


def screen_account_menu(account) -> tuple[str, dict | None]:
    """Customer panel home: shops owned + plan info."""
    import keyboards as kb2
    import repositories as repo2
    aid = account["id"]
    shops = repo2.account_shops(aid)
    used = len(shops)
    cap = account.get("max_shops") or 1
    plan_name = account.get("plan_name") or "-"
    lines = [
        f"<b>پنل مشتری</b> {esc(account.get('name') or account['tg_id'])}",
        f"پلن: <b>{esc(plan_name)}</b> — {used}/{cap} فروشگاه",
    ]
    if shops:
        lines.append("")
        lines.append("<b>فروشگاه‌های شما:</b>")
        for sh in shops:
            flag = "فعال" if sh["status"] == "active" else "غیرفعال"
            lines.append(f"- {esc(sh['name'])} ({flag})")
    else:
        lines.append("")
        lines.append("هنوز فروشگاهی ندارید. اولین فروشگاه خود را بسازید.")
    if used >= cap:
        lines.append("")
        lines.append("<i>به سقف پلن رسیدید؛ برای ارتقا با مالک تماس بگیرید.</i>")
    return "\n".join(lines), kb2.account_menu(account)


def screen_shop_entered(shop) -> tuple[str, dict | None]:
    """After a customer opens one of their shops: the shop's own menu."""
    import keyboards as kb2
    lines = [
        f"<b>فروشگاه: {esc(shop['name'])}</b>",
        "از اینجا همه‌چیز همین فروشگاه است: اپراتورها، مشتریان، لینک‌ها و تیکت‌ها.",
    ]
    keyboard = kb2.markup(
        [kb2.btn("تیکت‌های باز تیم", cb.enc(cb.NAV, "team_open"), style="primary"),
         kb2.btn("گزارش", cb.enc(cb.AD, "report"))],
        [kb2.btn("تنظیمات", cb.enc(cb.AD, "settings")),
         kb2.btn("اپراتورها", cb.enc(cb.AD, "operators"))],
        [kb2.btn("مشتریان", cb.enc(cb.AD, "customers")),
         kb2.btn("لینک دعوت", cb.enc(cb.AD, "invite"), style="success")],
        [kb2.btn("فروشگاه‌های من", cb.enc(cb.ACC, "shops"), style="primary")],
    )
    return "\n".join(lines), keyboard


def screen_plan(account) -> tuple[str, dict | None]:
    import keyboards as kb2
    text = (
        f"<b>پلن فعلی:</b> {esc(account.get('plan_name') or '-')}\n"
        f"سقف فروشگاه: {account.get('max_shops') or 1}\n\n"
        "برای ارتقا یا تغییر پلن با مالک پلتفرم در تماس باشید."
    )
    return text, kb2.plan_display(account)


def screen_help() -> tuple[str, dict | None]:
    text = (
        "<b>راهنما</b>\n\n"
        "مشتری: تیکت جدید بسازید، موضوع و توضیح را بفرستید، تا پاسخ پیگیری کنید.\n"
        "اپراتور: از فهرست تیم، تیکت را باز کنید و پاسخ دهید.\n"
        "ادمین: تنظیمات، اپراتورها، مشتریان و گزارش از منوی اصلی.\n"
        "مالک: کسب‌وکارها را مدیریت کنید و لاگ اقدامات را ببینید."
    )
    return text, kb.markup([kb.btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU), style="primary")])
