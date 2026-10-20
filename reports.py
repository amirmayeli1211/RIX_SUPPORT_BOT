"""Reports: per-tenant and platform rollups, rendered as text."""
from __future__ import annotations

import database as db
import operator_manager
import repositories as repo
from formatters import esc, minutes_label, stats_block


def tenant_report(tenant_id: int) -> str:
    stats = repo.tenant_stats(tenant_id)
    lines = [stats_block(stats)]
    rows = operator_manager.staff_rows(tenant_id)
    if rows:
        lines.append("<b>بار کاری تیم</b>")
        for member, load in rows:
            who = member["name"] or member["tg_id"]
            lines.append(f"- {esc(who)} ({member['role']}): {load}/{member['capacity']}")
    top = db.q(
        "SELECT tk.number, tk.subject, c.name AS customer_name, tk.rating"
        " FROM tickets tk JOIN customers c ON c.id=tk.customer_id"
        " WHERE tk.tenant_id=? AND tk.rating IS NOT NULL"
        " ORDER BY tk.rating DESC, tk.id DESC LIMIT 5",
        (tenant_id,),
    )
    if top:
        lines.append("<b>آخرین امتیازها</b>")
        for r in top:
            lines.append(f"- #{r['number']} {r['rating']}/5 - {esc(r['customer_name'] or '')}")
    return "\n".join(lines)


def platform_report() -> str:
    stats = repo.platform_stats()
    return (
        "<b>گزارش سراسری</b>\n"
        f"- کسب‌وکارها: {stats['tenants']} (فعال: {stats['active_tenants']})\n"
        f"- مشتریان: {stats['customers']}\n"
        f"- تیکت‌ها: {stats['tickets']} (باز: {stats['open']})\n"
        f"- اعضای تیم: {stats['members']}"
    )


def tenant_summary_line(tenant_id: int) -> str:
    stats = repo.tenant_stats(tenant_id)
    return (f"باز: {stats['open']} | در انتظار: {stats['pending']} | "
            f"بسته: {stats['closed']} | اولین پاسخ: {minutes_label(stats['first_reply_min'] * 60)}")
