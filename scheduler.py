"""Background scheduler: SLA alerts, daily backup, housekeeping.

One daemon thread, one loop, fixed cadence with a stop event. Every task is
wrapped so an exception logs and the loop continues - a broken task must never
silently kill the scheduler (that is how SLA alerts quietly stop firing).
"""
from __future__ import annotations

import threading
import time

import backup
import config
import database as db
import repositories as repo
import sla_manager

DAY = 86400


class Scheduler:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_backup_day = ""
        self._last_sla = 0.0
        self._last_cleanup = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()
        print("[scheduler] started", flush=True)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.wait(config.SLA_TICK_SECONDS):
            self.tick()

    def tick(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._sla(now)
        self._daily_backup(now)
        self._cleanup(now)

    def _sla(self, now: float) -> None:
        if now - self._last_sla < config.SLA_TICK_SECONDS:
            return
        self._last_sla = now
        try:
            fired = sla_manager.check_and_alert()
            if fired:
                print(f"[scheduler] sla alerts sent: {fired}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[scheduler] sla task failed: {type(exc).__name__}: {exc}", flush=True)

    def _daily_backup(self, now: float) -> None:
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if day == self._last_backup_day:
            return
        # Only after 03:00 local, so a midnight deploy does not race it.
        if time.localtime(now).tm_hour < 3:
            return
        self._last_backup_day = day
        try:
            path = backup.make_backup()
            print(f"[scheduler] backup: {path}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[scheduler] backup failed: {type(exc).__name__}: {exc}", flush=True)

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup < 3600:
            return
        self._last_cleanup = now
        try:
            repo.purge_expired_codes(int(now) - DAY)
            repo.purge_stale_states(int(now) - 7 * DAY)
        except Exception as exc:  # noqa: BLE001
            print(f"[scheduler] cleanup failed: {type(exc).__name__}: {exc}", flush=True)


# Module-level singleton so bot.py and tests share one instance.
scheduler = Scheduler()
