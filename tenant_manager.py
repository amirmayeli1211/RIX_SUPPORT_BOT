"""Tenant lifecycle - create, enable/disable, switch.

A tenant is born complete: seed settings, an owner membership for whoever
created it, and the welcome text. Nothing else has to happen for a new
business to start taking tickets.
"""
from __future__ import annotations

import audit
import repositories as repo
from models import Role, Status


class TenantError(Exception):
    pass


def create(name: str, creator_tg_id: int, slug: str | None = None,
           account_id: int | None = None) -> int:
    if not name or not name.strip():
        raise TenantError("نام کسب‌وکار خالی است.")
    tenant_id = repo.create_tenant(name.strip(), creator_tg_id, slug,
                                   account_id=account_id)
    repo.seed_settings(tenant_id)
    if creator_tg_id:
        repo.add_member(tenant_id, creator_tg_id, Role.OWNER)
    audit.log(tenant_id, creator_tg_id, audit.Act.TENANT_CREATE, target=name,
              detail=f"account={account_id}" if account_id else "")
    return tenant_id


def set_status(tenant_id: int, status: str, actor_tg_id: int) -> None:
    if status not in (Status.OPEN, Status.CLOSED, "active", "disabled"):
        raise TenantError("وضعیت نامعتبر.")
    normalized = "active" if status in (Status.OPEN, "active") else "disabled"
    repo.set_tenant_status(tenant_id, normalized)
    audit.log(tenant_id, actor_tg_id, audit.Act.TENANT_STATUS, target=normalized)


def enable(tenant_id: int, actor_tg_id: int) -> None:
    set_status(tenant_id, "active", actor_tg_id)


def disable(tenant_id: int, actor_tg_id: int) -> None:
    set_status(tenant_id, "disabled", actor_tg_id)


def get_or_raise(tenant_id: int):
    tenant = repo.get_tenant(tenant_id)
    if tenant is None:
        raise TenantError("کسب‌وکار پیدا نشد.")
    return tenant


def invite_link(tenant_id: int) -> str:
    """Deep link that registers the tapper as a customer of this tenant only."""
    import config
    code = repo.ensure_invite_code(tenant_id)
    username = config.BOT_USERNAME
    if not username:
        import bot as _bot
        try:
            username = _bot.me().get("username", "")
        except _bot.TgError:
            username = ""
    return f"https://t.me/{username}?start=join_{tenant_id}_{code}"


def staff_invite_link(tenant_id: int) -> str:
    """Deep link that adds the tapper as an OPERATOR of this tenant."""
    import config
    code = repo.ensure_staff_code(tenant_id)
    username = config.BOT_USERNAME
    if not username:
        import bot as _bot
        try:
            username = _bot.me().get("username", "")
        except _bot.TgError:
            username = ""
    return f"https://t.me/{username}?start=staff_{tenant_id}_{code}"


def tenants_of_owner(tg_id: int):
    """Tenants this user owns (or all, for the super-owner)."""
    import config
    if config.OWNER_TG_ID and tg_id == config.OWNER_TG_ID:
        return repo.list_tenants()
    return [t for t in repo.list_tenants()
            if repo.member(t["id"], tg_id) and repo.member(t["id"], tg_id)["role"] == Role.OWNER]
