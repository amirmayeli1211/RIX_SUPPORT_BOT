"""Keyboard builders - pure dict construction, no API calls, no I/O.

Colored buttons: Telegram Bot API 8.3+ honours `style` on inline buttons
("primary"=blue, "success"=green, "danger"=red). Older clients silently ignore
unknown fields, so a missing color is cosmetic only and never breaks a flow.
On top of the color we always keep a text prefix (e.g. an emoji-free label),
so the meaning survives on old clients too.
"""
from __future__ import annotations

import callbacks as cb
from models import ALL_PRIORITIES, PRIORITY_LABEL, Role


def btn(text: str, data: str | None = None, url: str | None = None,
        style: str | None = None, copy_text: str | None = None) -> dict:
    b: dict = {"text": text}
    if data is not None:
        b["callback_data"] = data
    if url:
        b["url"] = url
    if copy_text is not None:
        b["copy_text"] = {"text": copy_text}
    if style in ("primary", "success", "danger"):
        b["style"] = style
    return b


def markup(*rows) -> dict:
    cleaned = [list(r) for r in rows if r]
    return {"inline_keyboard": cleaned} if cleaned else None


def back(target: str = cb.MENU) -> dict:
    return btn("بازگشت", cb.enc(cb.NAV, target), style="primary")


# --------------------------------------------------------------- main menu

def main_menu(*, is_customer: bool, is_staff: bool, is_admin: bool,
              is_owner: bool, has_open_ticket: bool,
              is_super_owner: bool = False) -> dict | None:
    """Everything this user may do, all rows visible at once.

    Rows are appended per role and never hidden behind submenus: a customer
    sees only customer actions, an agent sees customer+agent, an admin adds
    the admin block, an owner adds the owner block. Nothing is culled by
    "not ready yet" - a button whose screen needs data explains that on tap.
    """
    rows: list[list[dict]] = []
    if is_customer:
        row = [btn("تیکت جدید", cb.enc(cb.NAV, "new_ticket"), style="success")]
        if has_open_ticket:
            row.append(btn("تیکت باز من", cb.enc(cb.NAV, "my_open")))
        rows.append(row)
        rows.append([btn("تیکت‌های من", cb.enc(cb.NAV, "my_tickets")),
                     btn("پروفایل من", cb.enc(cb.CU, "me", "view"))])
    if is_staff:
        rows.append([btn("تیکت‌های باز تیم", cb.enc(cb.NAV, "team_open"), style="primary"),
                     btn("تیکت‌های من", cb.enc(cb.NAV, "assigned"))])
        rows.append([btn("جست‌وجوی مشتری", cb.enc(cb.CU, "search", "start")),
                     btn("گزارش", cb.enc(cb.AD, "report"))])
    if is_admin:
        rows.append([btn("تنظیمات", cb.enc(cb.AD, "settings")),
                     btn("اپراتورها", cb.enc(cb.AD, "operators"))])
        rows.append([btn("مشتریان", cb.enc(cb.AD, "customers")),
                     btn("لینک دعوت مشتریان", cb.enc(cb.AD, "invite"), style="primary")])
    if is_owner or is_super_owner:
        rows.append([btn("خریدهای در انتظار", cb.enc(cb.OW, "orders"), style="success"),
                     btn("پلن‌ها و قیمت‌ها", cb.enc(cb.OW, "plans"), style="primary")])
        rows.append([btn("تنظیمات پرداخت", cb.enc(cb.OW, "payset")),
                     btn("مشتریان من", cb.enc(cb.OW, "accounts"))])
        rows.append([btn("فروش پلن (دستی)", cb.enc(cb.OW, "sell"))])
        rows.append([btn("کسب‌وکارها", cb.enc(cb.OW, "list")),
                     btn("گزارش سراسری", cb.enc(cb.OW, "report"))])
        rows.append([btn("لاگ اقدامات", cb.enc(cb.AD, "audit"))])
    if not (is_customer or is_staff or is_owner or is_super_owner):
        # Strangers are the buyers: put the shop right in front of them.
        rows.append([btn("خرید پلن", cb.enc(cb.BUY, "start"), style="success")])
    rows.append([btn("راهنما", cb.enc(cb.NAV, "help"))])
    return markup(*rows)


# -------------------------------------------------------------- tickets

def ticket_list(tickets, prefix: str = cb.TK, op: str = "view",
                next_cb: str | None = None, prev_cb: str | None = None,
                empty_label: str = "موردی نیست") -> dict | None:
    if not tickets:
        return markup([btn(empty_label, cb.enc(cb.NAV, cb.MENU))])
    rows = []
    for t in tickets:
        label = f"#{t['number']} | {t.get('customer_name') or t.get('customer_id')}"
        if t.get("status") == "open":
            label = f"* {label}"
        rows.append([btn(label, cb.enc(prefix, t["id"], op))])
    nav_row = []
    if prev_cb:
        nav_row.append(btn("قبلی", prev_cb, style="primary"))
    if next_cb:
        nav_row.append(btn("بعدی", next_cb, style="primary"))
    if nav_row:
        rows.append(nav_row)
    rows.append([btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))])
    return markup(*rows)


def ticket_detail(ticket, *, is_staff: bool) -> dict | None:
    tid = ticket["id"]
    cid = ticket.get("customer_id") or 0
    rows: list[list[dict]] = []
    if is_staff:
        rows.append([btn("پاسخ", cb.enc(cb.TK, tid, "reply"), style="success"),
                     btn("دیدم", cb.enc(cb.TK, tid, "seen"), style="primary")])
        rows.append([btn("یادداشت داخلی", cb.enc(cb.TK, tid, "note")),
                     btn("اولویت", cb.enc(cb.TK, tid, "prio")),
                     btn("انتقال", cb.enc(cb.TK, tid, "transfer"))])
        rows.append([btn("پروفایل مشتری", cb.enc(cb.CU, cid, "view") if cid else cb.enc(cb.NAV, cb.MENU))])
        if ticket["status"] != "closed":
            rows.append([btn("بستن تیکت", cb.enc(cb.TK, tid, cb.CLOSE), style="danger")])
        else:
            rows.append([btn("بازگشایی", cb.enc(cb.TK, tid, "reopen"), style="primary")])
        rows.append([btn("حذف تیکت", cb.enc(cb.TK, tid, "delete"), style="danger")])
    rows.append([btn("بروزرسانی", cb.enc(cb.TK, tid, cb.REFRESH))])
    rows.append([btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))])
    return markup(*rows)


def priority_picker(ticket_id: int) -> dict | None:
    rows = [[btn(PRIORITY_LABEL[p], cb.enc(cb.TK, ticket_id, "setprio", p), style="primary")]
            for p in ALL_PRIORITIES]
    rows.append([btn("بازگشت", cb.enc(cb.TK, ticket_id, "view"))])
    return markup(*rows)


def transfer_picker(members, ticket_id: int) -> dict | None:
    rows = [[btn(f"{m['name'] or m['tg_id']}", cb.enc(cb.TK, ticket_id, "setassign", m["tg_id"]),
                 style="primary")] for m in members]
    rows.append([btn("خودکار (کمترین بار)", cb.enc(cb.TK, ticket_id, "setassign", "auto"))])
    rows.append([btn("بازگشت", cb.enc(cb.TK, ticket_id, "view"))])
    return markup(*rows)


def confirm_close(ticket_id: int) -> dict | None:
    return markup(
        [btn("بله، ببند", cb.enc(cb.TK, ticket_id, cb.YES), style="danger"),
         btn("انصراف", cb.enc(cb.TK, ticket_id, "view"))]
    )


def rating_picker(ticket_id: int) -> dict | None:
    rows = [[btn(str(n), cb.enc(cb.RATE, ticket_id, n), style="success") for n in range(1, 6)]]
    return markup(*rows)


# -------------------------------------------------------------- customers

def customer_list(customers, next_cb: str | None = None, prev_cb: str | None = None) -> dict | None:
    if not customers:
        return markup([btn("مشتری‌ای نیست", cb.enc(cb.NAV, cb.MENU))])
    rows = []
    for c in customers:
        who = c.get("name") or c.get("username") or c["tg_id"]
        mark = "+" if c.get("verified_at") else "?"
        rows.append([btn(f"{mark} {who}", cb.enc(cb.CU, c["id"], "view"))])
    nav = []
    if prev_cb:
        nav.append(btn("قبلی", prev_cb, style="primary"))
    if next_cb:
        nav.append(btn("بعدی", next_cb, style="primary"))
    if nav:
        rows.append(nav)
    rows.append([btn("افزودن مشتری", cb.enc(cb.CU, "new", "start"), style="success")])
    rows.append([btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))])
    return markup(*rows)


def customer_detail(customer) -> dict | None:
    cid = customer["id"]
    rows = [
        [btn("تیکت‌ها", cb.enc(cb.CU, cid, "tickets")),
         btn("تگ", cb.enc(cb.CU, cid, "tag"))],
    ]
    if customer.get("blocked"):
        rows.append([btn("آزادسازی مشتری", cb.enc(cb.CU, cid, "unblock"), style="success")])
    else:
        rows.append([btn("مسدودسازی", cb.enc(cb.CU, cid, "block"), style="danger")])
    rows.append([btn("حذف مشتری", cb.enc(cb.CU, cid, cb.CLOSE), style="danger")])
    rows.append([btn("بازگشت", cb.enc(cb.AD, "customers"))])
    return markup(*rows)


def admin_customers_menu() -> dict | None:
    return markup(
        [btn("جستجو", cb.enc(cb.CU, "search", "start"), style="primary"),
         btn("افزودن مشتری", cb.enc(cb.CU, "new", "start"), style="success")],
        [btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))],
    )


# -------------------------------------------------------------- operators

def operator_list(members, loads: dict[int, int]) -> dict | None:
    rows = []
    for m in members:
        load = loads.get(m["tg_id"], 0)
        label = f"{m['name'] or m['tg_id']} | {load}/{m['capacity']} | {m['role']}"
        rows.append([btn(label, cb.enc(cb.OP, "view", m["tg_id"]))])
    rows.append([btn("افزودن اپراتور", cb.enc(cb.AD, "op_add", "start"), style="success")])
    rows.append([btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))])
    return markup(*rows)


def operator_detail(member_row, load: int) -> dict | None:
    tg = member_row["tg_id"]
    rows = [
        [btn("ارتقا به ادمین", cb.enc(cb.OP, "role", tg, Role.ADMIN), style="primary"),
         btn("تنزل به اپراتور", cb.enc(cb.OP, "role", tg, Role.AGENT))],
        [btn("تغییر سقف", cb.enc(cb.OP, "cap", tg))],
        [btn("غیرفعال", cb.enc(cb.OP, "off", tg), style="danger"),
         btn("حذف", cb.enc(cb.OP, "del", tg), style="danger")],
        [btn("بازگشت", cb.enc(cb.AD, "operators"))],
    ]
    return markup(*rows)


# --------------------------------------------------------------- settings

SETTING_LABELS = {
    "welcome_text": "متن خوش‌آمد",
    "business_hours": "ساعت کاری (HH:MM-HH:MM)",
    "outside_hours_text": "متن خارج از ساعت",
    "sla_minutes": "SLA (دقیقه)",
    "support_url": "لینک پشتیبانی",
}


def settings_menu(settings: dict) -> dict | None:
    rows = []
    for key, label in SETTING_LABELS.items():
        value = (settings.get(key) or "-")[:25]
        rows.append([btn(f"{label}: {value}", cb.enc(cb.AD, "set", key))])
    rows.append([btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))])
    return markup(*rows)


def tenant_list(tenants) -> dict | None:
    rows = []
    for t in tenants:
        mark = "فعال" if t["status"] == "active" else "غیرفعال"
        rows.append([btn(f"{mark} | {t['name']}", cb.enc(cb.OW, "view", t["id"]))])
    rows.append([btn("افزودن کسب‌وکار", cb.enc(cb.OW, "new", "start"), style="success")])
    rows.append([btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))])
    return markup(*rows)


def tenant_detail(tenant) -> dict | None:
    tid = tenant["id"]
    if tenant["status"] == "active":
        status_btn = btn("غیرفعال کردن", cb.enc(cb.OW, tid, "disable"), style="danger")
    else:
        status_btn = btn("فعال کردن", cb.enc(cb.OW, tid, "enable"), style="success")
    return markup(
        [status_btn],
        [btn("بازگشت", cb.enc(cb.OW, "list"))],
    )


# ------------------------------------------------------------ buy a plan

def buy_menu(plans) -> dict | None:
    """Prices on the buttons - the user never has to ask what it costs."""
    rows = []
    for pl in plans:
        rows.append([btn(f"{pl['name']} — {int(pl['price']):,} تومان"
                         f" · {pl['max_shops']} فروشگاه",
                         cb.enc(cb.BUY, "plan", pl["id"]), style="primary")])
    rows.append([btn("خریدهای من", cb.enc(cb.BUY, "mine"))])
    rows.append([btn("منوی اصلی", cb.enc(cb.NAV, cb.MENU))])
    return markup(*rows)


def payment_screen(order, card: str, holder: str) -> dict | None:
    rows = []
    if card:
        rows.append([btn("کپی شماره کارت", copy_text=card, style="success")])
    rows.append([btn("ارسال رسید", cb.enc(cb.BUY, "receipt", order["id"]),
                     style="primary")])
    rows.append([btn("انصراف از خرید", cb.enc(cb.BUY, "cancel", order["id"]),
                     style="danger")])
    return markup(*rows)


def order_review(order, tg_id: int) -> dict | None:
    return markup(
        [btn("تأیید و فعال‌سازی", cb.enc(cb.OW, "ok", order["id"]), style="success"),
         btn("رد کردن", cb.enc(cb.OW, "no", order["id"]), style="danger")],
        [btn("پیام به خریدار", url=f"tg://user?id={tg_id}")],
    )


def plan_admin_list(plans) -> dict | None:
    """Owner-side price/active editor for every plan."""
    rows = []
    for pl in plans:
        price = int(pl["price"] or 0)
        price_txt = f"{price:,} ت" if price else "قیمت ندارد"
        flag = "" if pl["active"] else " (خاموش)"
        rows.append([btn(f"{pl['name']} · {price_txt}{flag}",
                         cb.enc(cb.OW, "planedit", pl["id"]), style="primary")])
    rows.append([btn("بازگشت", cb.enc(cb.NAV, cb.MENU))])
    return markup(*rows)


def plan_admin_edit(plan) -> dict | None:
    return markup(
        [btn("تغییر قیمت", cb.enc(cb.OW, "planprice", plan["id"]), style="primary")],
        [btn("خاموش کردن" if plan["active"] else "روشن کردن",
             cb.enc(cb.OW, "plantoggle", plan["id"]))],
        [btn("بازگشت", cb.enc(cb.OW, "plans"))],
    )


# ------------------------------------------- customer panel (account)

def account_menu(account) -> dict | None:
    """The panel a paying customer lands on: their shops + how to grow."""
    rows = [[btn("فروشگاه‌های من", cb.enc(cb.ACC, "shops"), style="primary"),
             btn("ساخت فروشگاه", cb.enc(cb.ACC, "new"), style="success")]]
    rows.append([btn("پلن من", cb.enc(cb.ACC, "plan")),
                 btn("راهنما", cb.enc(cb.NAV, "help"))])
    return markup(*rows)


def shop_list(shops, account_id: int) -> dict | None:
    rows = []
    for sh in shops:
        rows.append([btn(f"{sh['name']}", cb.enc(cb.ACC, "enter", sh["id"]),
                         style="primary")])
    rows.append([btn("ساخت فروشگاه", cb.enc(cb.ACC, "new"), style="success")])
    rows.append([btn("بازگشت", cb.enc(cb.NAV, cb.MENU))])
    return markup(*rows)


def plan_picker(plans) -> dict | None:
    """Owner picks a plan when selling to a new customer."""
    rows = [[btn(f"{pl['name']} — تا {pl['max_shops']} فروشگاه",
                 cb.enc(cb.OW, "sellplan", pl["id"]), style="primary")]
            for pl in plans]
    rows.append([btn("انصراف", cb.enc(cb.NAV, cb.MENU), style="danger")])
    return markup(*rows)


def plan_display(account) -> dict | None:
    return markup(
        [btn("ارتقای پلن (با مالک)", cb.enc(cb.NAV, cb.MENU), style="primary")],
        [btn("بازگشت", cb.enc(cb.NAV, cb.MENU))],
    )


# ------------------------------------------------------- verification code

def code_keyboard(code_text: str) -> dict | None:
    """Copy-text button: one tap puts the code in the input box. Supported on
    Bot API 7.11+; the code is also shown as text for older clients."""
    return markup([btn("کپی کد", copy_text=code_text, style="primary")])


def cancel_button() -> dict | None:
    return markup([btn("انصراف", cb.enc(cb.NAV, cb.MENU), style="danger")])
