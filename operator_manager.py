"""Operator workload: capacity, auto-assignment, workload view.

Assignment policy (in order):
  1. never over a member's `capacity` of open tickets
  2. least-loaded active agent/admin first
  3. round-robin tie-break by member id so load spreads deterministically
  4. no candidate -> ticket stays unassigned and appears in the team queue
"""
from __future__ import annotations

import audit
import repositories as repo
from models import Role, STAFF_ROLES, Status

EFFECTIVE_ROLES = (Role.OWNER, Role.ADMIN, Role.AGENT)


def load_of(tenant_id: int, tg_id: int) -> int:
    return repo.count_tickets(tenant_id, Status.OPEN, assigned_to=tg_id)


def workload(tenant_id: int) -> dict[int, int]:
    members = repo.list_members(tenant_id, EFFECTIVE_ROLES)
    return {m["tg_id"]: load_of(tenant_id, m["tg_id"]) for m in members}


def pick_auto(tenant_id: int):
    """Least-loaded member under capacity, or None."""
    members = repo.list_members(tenant_id, EFFECTIVE_ROLES)
    best = None
    best_key = None
    for m in members:
        load = load_of(tenant_id, m["tg_id"])
        if load >= m["capacity"]:
            continue
        key = (load, m["id"])
        if best_key is None or key < best_key:
            best, best_key = m, key
    return best


def assign(ticket_id: int, tg_id: int | None, actor_tg_id: int) -> None:
    repo.set_assignee(ticket_id, tg_id)
    ticket = repo.get_ticket(ticket_id)
    audit.log(ticket["tenant_id"] if ticket else None, actor_tg_id,
              audit.Act.TICKET_ASSIGN, target=ticket_id, detail=str(tg_id or "auto"))


def auto_assign(ticket_id: int, actor_tg_id: int) -> int | None:
    ticket = repo.get_ticket(ticket_id)
    if ticket is None:
        return None
    member = pick_auto(ticket["tenant_id"])
    tg = member["tg_id"] if member else None
    assign(ticket_id, tg, actor_tg_id)
    return tg


def staff_rows(tenant_id: int) -> list[tuple[dict, int]]:
    """(member row, current load) for every active staff member."""
    members = repo.list_members(tenant_id, EFFECTIVE_ROLES)
    return [(m, load_of(tenant_id, m["tg_id"])) for m in members]


def notify_targets(tenant_id: int) -> list[int]:
    """Staff chat ids to alert on new customer activity: assignee first,
    then every admin/agent (deduplicated, capped)."""
    ticket_staff = repo.list_members(tenant_id, EFFECTIVE_ROLES)
    seen: list[int] = []
    for m in ticket_staff:
        if m["tg_id"] not in seen:
            seen.append(m["tg_id"])
    return seen[:30]
