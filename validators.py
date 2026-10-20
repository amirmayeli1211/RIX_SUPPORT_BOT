"""Input validation - every value that enters the database passes here first.

Contract: each function returns the cleaned value, or None when invalid.
Callers translate None into a Persian error message (see formatters.py).
"""
from __future__ import annotations

import re
import urllib.parse

from models import ALL_PRIORITIES, ALL_ROLES

_TG_ID = re.compile(r"^[1-9][0-9]{4,14}$")     # 5..15 digits, no leading zero
_CODE = re.compile(r"^[0-9]{6}$")
_HHMM = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
_TAG = re.compile(r"^[^\s]{1,32}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}$")


def tg_id(value) -> int | None:
    """Numeric telegram id, or None."""
    s = str(value or "").strip().split()[0] if str(value or "").strip() else ""
    if not _TG_ID.match(s):
        return None
    return int(s)


def is_bot_id(tg_id: int) -> bool:
    """Heuristic: bot ids are >= 10^9 and end in '000'. The authoritative
    check is api getChat (verification.is_human)."""
    s = str(tg_id)
    return tg_id >= 1_000_000_000 and s.endswith("000") and len(s) >= 10


def code(value) -> str | None:
    s = str(value or "").strip()
    return s if _CODE.match(s) else None


def one_line(value, max_len: int = 200) -> str | None:
    s = " ".join(str(value or "").split())
    if not s or len(s) > max_len:
        return None
    return s


def paragraph(value, max_len: int = 3500) -> str | None:
    s = str(value or "").strip()
    if not s or len(s) > max_len:
        return None
    return s


def role(value) -> str | None:
    s = str(value or "").strip().lower()
    return s if s in ALL_ROLES else None


def priority(value) -> str | None:
    s = str(value or "").strip().lower()
    return s if s in ALL_PRIORITIES else None


def status(value) -> str | None:
    s = str(value or "").strip().lower()
    return s if s in {"open", "pending", "closed"} else None


def sla_minutes(value) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 1440 else None


def capacity(value) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 100 else None


def business_hours(value) -> str | None:
    """'HH:MM-HH:MM' or '' (disabled). Overnight windows are allowed."""
    s = str(value or "").strip()
    if s.lower() in ("", "-", "off", "0"):
        return ""
    parts = s.split("-")
    if len(parts) != 2 or not _HHMM.match(parts[0].strip()) or not _HHMM.match(parts[1].strip()):
        return None
    return f"{parts[0].strip()}-{parts[1].strip()}"


def url(value) -> str | None:
    s = str(value or "").strip()
    if s.lower() in ("", "-", "off"):
        return ""
    try:
        parsed = urllib.parse.urlparse(s)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return s


_CARD = re.compile(r"^[0-9]{16}$")


def card_number(value) -> str | None:
    """16-digit card number; spaces and dashes are tolerated."""
    s = re.sub(r"[\s-]", "", str(value or ""))
    if not _CARD.match(s):
        return None
    return s


def price_toman(value) -> int | None:
    """Price in Toman: positive, at most 1,000,000,000; 0 disables selling."""
    s = re.sub(r"[,\s_]", "", str(value or ""))
    if not s.isdigit():
        return None
    n = int(s)
    if n < 0 or n > 1_000_000_000:
        return None
    return n


def tag(value) -> str | None:
    s = str(value or "").strip()
    return s if _TAG.match(s) else None


def slug(value) -> str | None:
    s = str(value or "").strip().lower().replace(" ", "-")
    s = "".join(ch for ch in s if ch.isalnum() or ch == "-")
    if not s:
        return None
    return s[:48] if _SLUG.match(s[:48]) else None


def rating(value) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 5 else None


def page(value, default: int = 1) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return n if n >= 1 else default
