"""Central dispatcher: one entry per update, routes to the right handler.

Routing order (deliberate):
  1. callback queries -> namespace prefix (nav/tk/cu/ad/ow/op/rate)
  2. FSM state       -> the module that owns that state (waiting for a reply)
  3. commands        -> /start /menu /panel /help
  4. plain text      -> customer message flow, or verification code confirm
Anything unmatched gets a friendly nudge with the menu, never a silence.
"""
from __future__ import annotations

import callbacks as cb
import database as db
import error_handler
import keyboards as kb
import menus
import permissions
import repositories as repo
import verification
from models import Role, Status, St

# --------------------------------------------------------------- ctx build

def build_ctx(update: dict) -> dict | None:
    """Extract a uniform context dict from an update, or None if unusable."""
    if "callback_query" in update:
        q = update["callback_query"]
        from_user = q.get("from") or {}
        data = q.get("data") or ""
        chat_id = (q.get("message") or {}).get("chat", {}).get("id") or from_user.get("id")
        return {
            "kind": "cb", "tg_id": from_user.get("id", 0), "chat_id": chat_id,
            "cb_id": q.get("id"), "cb_data": data,
            "message_id": (q.get("message") or {}).get("message_id"),
            "name": from_user.get("first_name"), "username": from_user.get("username"),
        }
    msg = update.get("message")
    if not msg:
        return None
    from_user = msg.get("from") or {}
    if from_user.get("is_bot"):
        return None  # never let another bot drive this one
    chat = msg.get("chat") or {}
    return {
        "kind": "msg", "tg_id": from_user.get("id", 0),
        "chat_id": chat.get("id") or from_user.get("id", 0),
        "text": (msg.get("text") or "").strip(),
        "message_id": msg.get("message_id"),
        "name": from_user.get("first_name"), "username": from_user.get("username"),
        "photo": _largest_photo(msg), "document": (msg.get("document") or {}).get("file_id"),
        "voice": (msg.get("voice") or {}).get("file_id"),
        "video": (msg.get("video") or {}).get("file_id"),
        "caption": (msg.get("caption") or "").strip(),
    }


def _largest_photo(msg: dict) -> str | None:
    photos = msg.get("photo") or []
    if not photos:
        return None
    return max(photos, key=lambda p: p.get("file_size") or 0).get("file_id")


def enrich(ctx: dict) -> dict:
    """Attach roles: staff membership, customer record, open-ticket flag."""
    tg = ctx["tg_id"]
    member = permissions.resolve(tg)
    if member:
        tenant = repo.get_tenant(member["tenant_id"])
        role = member["role"]
        ctx.update({
            "tenant_id": member["tenant_id"], "member": member, "role": role,
            "is_staff": True,
            "is_admin": role in (Role.OWNER, Role.ADMIN),
            "is_owner": role == Role.OWNER,
            "tenant_name": tenant["name"] if tenant else "",
            "tenant_status": tenant["status"] if tenant else "",
        })
    customer = repo.customer_by_tg(tg)
    if customer:
        ctx.update({
            "is_customer": True,
            "customer": customer,
            "customer_tenant_id": customer["tenant_id"],
            "has_open_ticket": repo.open_ticket_for(customer["id"]) is not None,
        })
    if not member and not customer and config_owner_is(tg):
        # Super-owner (OWNER_TG_ID) with no membership yet: give them the
        # owner menu anyway, otherwise they can never create the first tenant
        # (the panel that creates tenants is itself behind the owner menu).
        ctx["is_super_owner"] = True
        ctx["is_owner"] = True
    return ctx


def config_owner_is(tg_id: int) -> bool:
    import config
    return bool(config.OWNER_TG_ID and tg_id == config.OWNER_TG_ID)


# ------------------------------------------------------------- dispatch

@error_handler.guard
def handle(update: dict) -> None:
    ctx = build_ctx(update)
    if not ctx:
        return
    ctx = enrich(ctx)
    if ctx["kind"] == "cb":
        _route_cb(ctx)
        return
    _route_msg(ctx)


def _route_cb(ctx) -> None:
    import admin_handlers
    import customer_handlers
    import owner_handlers
    import ticket_handlers
    import user_handlers
    prefix, parts = cb.decode(ctx["cb_data"])
    ctx["args"] = parts
    bot_answer = _cb_preview(ctx)
    if bot_answer:
        import bot
        bot.answer_cb(ctx["cb_id"], bot_answer)
    if prefix == cb.NAV:
        user_handlers.on_nav(ctx)
    elif prefix == cb.TK:
        ticket_handlers.on_ticket_cb(ctx)
    elif prefix == cb.CU:
        customer_handlers.on_customer_cb(ctx)
    elif prefix == cb.AD:
        admin_handlers.on_admin_cb(ctx)
    elif prefix == cb.OW:
        owner_handlers.on_owner_cb(ctx)
    elif prefix == cb.OP:
        admin_handlers.on_operator_cb(ctx)
    elif prefix == cb.RATE:
        customer_handlers.on_rate_cb(ctx)
    else:
        user_handlers.on_nav(ctx)  # unknown -> back to menu


def _cb_preview(ctx) -> str | None:
    """Short toast for taps that only navigate; ops that reply keep silent."""
    prefix, parts = cb.decode(ctx["cb_data"])
    if prefix == cb.NAV:
        return None
    return None


def _route_msg(ctx) -> None:
    import admin_handlers
    import customer_handlers
    import owner_handlers
    import ticket_handlers
    import user_handlers

    text = ctx.get("text", "")
    state_row = repo.get_state(ctx["tg_id"])
    state = state_row["state"] if state_row else None

    if state:
        ctx["state"] = state
        ctx["state_data"] = state_row["data"] if state_row else None
        handled = _route_state(ctx, state)
        if handled:
            return

    if text.startswith("/"):
        _route_command(ctx, text.split()[0].split("@")[0])
        return

    # A live verification code from a user we just invited?
    if verification.confirm(ctx["tg_id"], text):
        return

    # Otherwise: customer message flow (creates/appends a ticket).
    if ctx.get("is_customer"):
        customer_handlers.on_customer_text(ctx)
        return

    user_handlers.on_unknown(ctx)


def _route_state(ctx, state: str) -> bool:
    import admin_handlers
    import customer_handlers
    import owner_handlers
    import ticket_handlers
    table = {
        St.ADD_CUSTOMER_ID: customer_handlers.on_state_add_customer_id,
        St.TAG_CUSTOMER: customer_handlers.on_state_tag,
        St.SEARCH_CUSTOMER: customer_handlers.on_state_search,
        St.ADD_OPERATOR_ID: admin_handlers.on_state_add_operator,
        St.OP_CAPACITY: admin_handlers.on_state_capacity,
        St.SET_VALUE: admin_handlers.on_state_set_value,
        St.NEW_TENANT: owner_handlers.on_state_new_tenant,
        St.TICKET_SUBJECT: customer_handlers.on_state_subject,
        St.TICKET_BODY: customer_handlers.on_state_body,
        St.AGENT_REPLY: ticket_handlers.on_state_reply,
        St.AGENT_NOTE: ticket_handlers.on_state_note,
        St.TRANSFER_PICK: ticket_handlers.on_state_transfer,
    }
    handler = table.get(state)
    if handler is None:
        repo.clear_state(ctx["tg_id"])
        return False
    handler(ctx)
    return True


def _route_command(ctx, command: str) -> None:
    import user_handlers
    mapping = {
        "/start": user_handlers.on_start,
        "/menu": user_handlers.on_menu,
        "/panel": user_handlers.on_panel,
        "/help": user_handlers.on_help,
    }
    handler = mapping.get(command)
    if handler:
        handler(ctx)
    else:
        user_handlers.on_unknown(ctx)


# Contexts passed into handlers use the keys documented in build_ctx/enrich.
__all__ = ["handle", "build_ctx", "enrich"]
