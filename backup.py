"""SQLite online backup with rotation.

Uses sqlite3's backup API, so the copy is consistent even while the bot is
writing (a plain file copy of a WAL database can be torn).
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3

import config
import database as db


def make_backup() -> str:
    config.ensure_dirs()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_path = config.BACKUP_DIR / f"rix-{stamp}.sqlite3"
    source = db.connect()
    try:
        dest = sqlite3.connect(str(dest_path))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    _rotate()
    return str(dest_path)


def _rotate() -> None:
    files = sorted(p for p in config.BACKUP_DIR.glob("rix-*.sqlite3"))
    excess = len(files) - max(1, config.BACKUP_KEEP)
    for path in files[:max(0, excess)]:
        try:
            os.remove(path)
        except OSError:
            pass


def latest() -> str | None:
    files = sorted(config.BACKUP_DIR.glob("rix-*.sqlite3"))
    return str(files[-1]) if files else None


def restore(path: str) -> None:
    """Restore a backup over the live database. Bot must be stopped."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    # Keep the current db aside; a bad restore must be recoverable.
    if os.path.exists(config.DB_PATH):
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        os.replace(config.DB_PATH, config.BACKUP_DIR / f"rix-pre-restore-{stamp}.sqlite3")
    for suffix in ("-wal", "-shm"):
        side = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
        if side.exists():
            try:
                os.remove(side)
            except OSError:
                pass
    import shutil
    shutil.copy2(path, config.DB_PATH)
