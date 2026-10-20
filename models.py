"""Domain constants and light-weight dataclasses.

Constants (not enums) on purpose: they serialise to plain strings in SQLite
without adapters, and `Status.OPEN == "open"` stays true everywhere a row is
compared against a literal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


class Role:
    OWNER = "owner"
    ADMIN = "admin"
    AGENT = "agent"
    READONLY = "readonly"


ROLE_RANK = {Role.OWNER: 0, Role.ADMIN: 1, Role.AGENT: 2, Role.READONLY: 3}
ROLE_LABEL = {
    Role.OWNER: "مالک",
    Role.ADMIN: "ادمین",
    Role.AGENT: "اپراتور",
    Role.READONLY: "فقط‌خواندنی",
}
ALL_ROLES = (Role.OWNER, Role.ADMIN, Role.AGENT, Role.READONLY)
STAFF_ROLES = (Role.OWNER, Role.ADMIN, Role.AGENT)


class Status:
    OPEN = "open"
    PENDING = "pending"
    CLOSED = "closed"


STATUS_LABEL = {Status.OPEN: "باز", Status.PENDING: "در انتظار", Status.CLOSED: "بسته"}


class Priority:
    URGENT = "urgent"
    NORMAL = "normal"
    LOW = "low"


PRIORITY_LABEL = {Priority.URGENT: "فوری", Priority.NORMAL: "عادی", Priority.LOW: "کم"}
ALL_PRIORITIES = (Priority.URGENT, Priority.NORMAL, Priority.LOW)


class Sender:
    CUSTOMER = "customer"
    AGENT = "agent"
    SYSTEM = "system"


# FSM states (keyed by tg_id in fsm_states); St.IDLE means "no state".
class St:
    IDLE = ""
    ADD_CUSTOMER_ID = "add_customer_id"
    ADD_OPERATOR_ID = "add_operator_id"
    SET_VALUE = "set_value"          # data = setting key
    OP_CAPACITY = "op_capacity"      # data = member tg_id
    NEW_TENANT = "new_tenant"
    TICKET_SUBJECT = "ticket_subject"
    TICKET_BODY = "ticket_body"
    AGENT_REPLY = "agent_reply"      # data = ticket id
    AGENT_NOTE = "agent_note"        # data = ticket id
    TRANSFER_PICK = "transfer_pick"  # data = ticket id
    CONFIRM_CLOSE = "confirm_close"  # data = ticket id
    TAG_CUSTOMER = "tag_customer"    # data = customer id
    SEARCH_CUSTOMER = "search_customer"


@dataclass
class Tenant:
    id: int
    name: str
    slug: Optional[str] = None
    owner_tg_id: int = 0
    status: str = "active"
    created_at: int = 0

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Tenant":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()})


@dataclass
class Member:
    id: int
    tenant_id: int
    tg_id: int
    role: str = Role.AGENT
    name: Optional[str] = None
    username: Optional[str] = None
    capacity: int = 10
    active: int = 1
    created_at: int = 0

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Member":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()})


@dataclass
class Customer:
    id: int
    tenant_id: int
    tg_id: int
    name: Optional[str] = None
    username: Optional[str] = None
    tag: Optional[str] = None
    verified_at: Optional[int] = None
    created_at: int = 0

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Customer":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()})


@dataclass
class Ticket:
    id: int
    tenant_id: int
    customer_id: int
    number: int
    subject: Optional[str] = None
    priority: str = Priority.NORMAL
    status: str = Status.OPEN
    assigned_to: Optional[int] = None
    rating: Optional[int] = None
    sla_notified_at: Optional[int] = None
    created_at: int = 0
    first_reply_at: Optional[int] = None
    last_customer_msg_at: Optional[int] = None
    closed_at: Optional[int] = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Ticket":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row.keys()})


def has_at_least(role: str, minimum: str) -> bool:
    """role >= minimum in the owner > admin > agent > readonly order."""
    return ROLE_RANK.get(role, 99) <= ROLE_RANK.get(minimum, 99)
