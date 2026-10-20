"""Permission resolution and the @require decorator.

Single source of truth for "who may do what": every privileged handler is
wrapped, and the role is resolved from the database on each call - a demotion
takes effect immediately, with no restart.
"""
from __future__ import annotations

import functools

import database as db
import repositories as repo
from models import Role, has_at_least


def resolve(tg_id: int):
    """Best active membership row for this user, or None."""
    return repo.best_membership(tg_id)


def tenant_of(tg_id: int) -> int | None:
    m = resolve(tg_id)
    return m["tenant_id"] if m else None


def is_customer(tg_id: int, tenant_id: int | None = None) -> bool:
    row = repo.customer_by_tg(tg_id, tenant_id)
    return row is not None


def require(minimum: str, *, allow_customer: bool = False):
    """Decorator for handlers taking (ctx).

    Replies with a denial and returns None unless the caller's role is at
    least `minimum`. `allow_customer=True` also lets a verified customer
    through (used by the shared customer flows).
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(ctx):
            if allow_customer and ctx.get("is_customer"):
                return fn(ctx)
            member = resolve(ctx["tg_id"])
            if member is None or not has_at_least(member["role"], minimum):
                import keyboards
                import bot
                bot.send(ctx["chat_id"], "دسترسی نداری.",
                         keyboards.markup([keyboards.btn("منوی اصلی", "nav:menu")]))
                db_audit_denied(ctx, minimum)
                return None
            ctx["member"] = member
            ctx["tenant_id"] = member["tenant_id"]
            ctx["role"] = member["role"]
            return fn(ctx)
        return wrapper
    return deco


def db_audit_denied(ctx, minimum: str) -> None:
    import audit
    audit.log(None, ctx.get("tg_id"), "access.denied", target=ctx.get("cb_data") or "text",
              detail=f"required>={minimum}")
