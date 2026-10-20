"""Runtime configuration.

Every value comes from the environment — nothing secret is hard-coded, so the
repository can stay clean and Railway needs only env vars.

On Railway: attach a Volume mounted at /data. The SQLite database and backups
live there so they survive redeploys.
"""
from __future__ import annotations

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except ValueError:
        return default


# --- Telegram -----------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
BOT_USERNAME = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
# Super-owner: the telegram id that sees the platform view (all tenants).
OWNER_TG_ID = _int("OWNER_TG_ID", 0)

# --- Storage (Railway volume) ------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "rix.db")))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(DATA_DIR / "backups")))
BACKUP_KEEP = _int("BACKUP_KEEP", 7)

# --- HTTP ---------------------------------------------------------------
PORT = _int("PORT", 8080)

# --- Telegram API -------------------------------------------------------
TG_API_BASE = os.environ.get("TG_API_BASE", "https://api.telegram.org").rstrip("/")

# --- Behaviour ----------------------------------------------------------
DEFAULT_AGENT_CAPACITY = _int("DEFAULT_AGENT_CAPACITY", 10)  # max open tickets
SLA_TICK_SECONDS = _int("SLA_TICK_SECONDS", 60)              # background tick
MESSAGE_PAGE_SIZE = _int("MESSAGE_PAGE_SIZE", 10)
TICKET_PAGE_SIZE = _int("TICKET_PAGE_SIZE", 8)
# DEV=1 skips token validation so the offline self-test runs without a bot.
DEV = os.environ.get("DEV", "").strip() in {"1", "true", "yes"}


def api_url(method: str) -> str:
    return f"{TG_API_BASE}/bot{BOT_TOKEN}/{method}"


def ensure_dirs() -> None:
    for path in (DB_PATH.parent, BACKUP_DIR):
        path.mkdir(parents=True, exist_ok=True)


def validate() -> list[str]:
    """Problems that must stop the process at boot, returned as messages."""
    problems: list[str] = []
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        problems.append("BOT_TOKEN is missing or malformed (expected <id>:<secret>)")
    if not OWNER_TG_ID:
        problems.append("OWNER_TG_ID is not set - nobody can reach the owner panel")
    return problems
