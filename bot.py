"""Telegram Bot API client - stdlib only, no dependencies.

Why raw HTTP: this project must run on Railway with a bare image and also in
a sandbox with no pip. `urllib` costs nothing and removes a deploy failure
class entirely.

`style` on buttons needs Bot API 8.3+ (Feb 2026). Older clients ignore the
unknown field, so colors degrade gracefully.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import config


class TgError(Exception):
    pass


def api(method: str, timeout: int = 30, **params):
    if not config.BOT_TOKEN and not config.DEV:
        raise TgError("BOT_TOKEN is not configured")
    data = json.dumps(params).encode()
    req = urllib.request.Request(
        config.api_url(method), data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode())
        except Exception:
            raise TgError(f"{method}: HTTP {exc.code}") from exc
    except Exception as exc:  # network
        raise TgError(f"{method}: {exc}") from exc
    if not payload.get("ok"):
        raise TgError(f"{method}: {payload.get('description')}")
    return payload.get("result")


def send(chat_id, text, keyboard=None, reply_to=None):
    params = {"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML",
              "link_preview_options": {"is_disabled": True}}
    if keyboard:
        params["reply_markup"] = keyboard
    if reply_to:
        params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    return api("sendMessage", **params)


def edit(chat_id, message_id, text, keyboard=None):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text[:4096],
              "parse_mode": "HTML",
              "link_preview_options": {"is_disabled": True}}
    if keyboard:
        params["reply_markup"] = keyboard
    try:
        return api("editMessageText", **params)
    except TgError as exc:
        if "not modified" in str(exc).lower():
            return None
        raise


def answer_cb(cb_id, text=None, alert=False):
    params = {"callback_query_id": cb_id}
    if text:
        params.update(text=text[:200], show_alert=alert)
    try:
        return api("answerCallbackQuery", **params)
    except TgError:
        return None


def copy_msg(chat_id, from_chat_id, message_id, keyboard=None):
    params = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    if keyboard:
        params["reply_markup"] = keyboard
    return api("copyMessage", **params)


def get_updates(offset=0, timeout=30):
    return api("getUpdates", timeout=timeout + 10, offset=offset,
               allowed_updates=["message", "callback_query"])


def set_commands(scope=None):
    commands = [
        {"command": "start", "description": "شروع / Start"},
        {"command": "menu", "description": "منوی اصلی / Main menu"},
        {"command": "panel", "description": "پنل / Panel"},
        {"command": "help", "description": "راهنما / Help"},
    ]
    params = {"commands": commands}
    if scope:
        params["scope"] = scope
    return api("setMyCommands", **params)


def me():
    return api("getMe")


def poll_loop(handler, stop=None):
    """Long polling in the calling thread. handler(update) never raises."""
    offset = 0
    backoff = 1.0
    while not (stop and stop.is_set()):
        try:
            updates = get_updates(offset, timeout=30)
            backoff = 1.0
        except TgError as exc:
            # 409 = a second poller is alive; back off instead of hammering.
            print(f"[tg] poll error: {exc}", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue
        for update in updates or []:
            offset = max(offset, update["update_id"] + 1)
            try:
                handler(update)
            except Exception as exc:  # one bad update must not kill the bot
                print(f"[tg] handler error: {type(exc).__name__}: {exc}", flush=True)


# ------------------------------------------------------------------ main

def main() -> int:
    """Process entry: validate config, migrate, start servers, poll."""
    import database
    import healthcheck
    import handlers
    import scheduler as scheduler_mod

    problems = config.validate()
    if problems and not config.DEV:
        for problem in problems:
            print(f"[boot] FATAL: {problem}", flush=True)
        return 2

    applied = database.init()
    print(f"[boot] database ready (migrations applied: {applied or 'none'})", flush=True)

    healthcheck.start()
    scheduler_mod.scheduler.start()

    try:
        identity = me()
        print(f"[boot] authenticated as @{identity.get('username')} "
              f"(id {identity.get('id')})", flush=True)
    except TgError as exc:
        print(f"[boot] getMe failed: {exc}", flush=True)
        if not config.DEV:
            return 3

    try:
        set_commands()
    except TgError as exc:
        print(f"[boot] setMyCommands failed: {exc}", flush=True)

    print("[boot] polling started", flush=True)
    try:
        poll_loop(handlers.handle)
    except KeyboardInterrupt:
        print("[boot] interrupted, shutting down", flush=True)
    finally:
        scheduler_mod.scheduler.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
