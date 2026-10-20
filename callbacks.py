"""Callback-data encoding.

Telegram caps callback_data at 64 bytes, so the scheme is short and
positional: "<prefix>:<part>:<part>". decode() is the single parser - no
handler ever splits the raw string itself, so a format change is one edit.
"""
from __future__ import annotations

MAX_LEN = 64

# Namespaces
NAV = "nav"      # navigation: nav:<screen>
TK = "tk"        # ticket ops:  tk:<ticket_id>:<op>
CU = "cu"        # customer:   cu:<customer_id>:<op>
AD = "ad"        # admin:      ad:<op>:<arg>
OW = "ow"        # owner:      ow:<op>:<arg>
RATE = "rate"    # rating:     rate:<ticket_id>:<1-5>
OP = "op"        # operator:   op:<op>:<tg_id>

# Common operations
MENU = "menu"
BACK = "back"
REFRESH = "refresh"
CLOSE = "close"
CONFIRM = "confirm"
CANCEL = "cancel"
YES = "yes"
NO = "no"


def enc(prefix: str, *parts) -> str:
    out = ":".join([str(prefix), *(str(p) for p in parts if p not in (None, ""))])
    if len(out.encode("utf-8")) > MAX_LEN:
        raise ValueError(f"callback_data too long: {out!r}")
    return out


def decode(data: str) -> tuple[str, list[str]]:
    parts = str(data or "").split(":")
    return (parts[0] if parts else "", parts[1:] if len(parts) > 1 else [])


def is_cb(data: str, prefix: str, op: str | None = None) -> bool:
    """True when data matches prefix and (optionally) a specific op."""
    p, parts = decode(data)
    if p != prefix:
        return False
    return op is None or (parts and parts[0] == op)
