"""Error containment.

Rules:
  * A handler crash must never kill the polling loop.
  * The user gets a short apology, never a traceback.
  * The owner gets the traceback (truncated) so bugs are actually fixed.
  * The incident lands in the audit trail with the actor and the payload.
"""
from __future__ import annotations

import functools
import traceback

MAX_TRACE = 1500


def describe(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-MAX_TRACE:]


def guard(fn):
    """Wrap a handler(ctx): log, notify, swallow."""
    @functools.wraps(fn)
    def wrapper(ctx):
        try:
            return fn(ctx)
        except Exception as exc:  # noqa: BLE001 - containment is the point
            handle(ctx, fn.__name__, exc)
            return None
    return wrapper


def handle(ctx, where: str, exc: BaseException) -> None:
    try:
        import audit
        audit.log(ctx.get("tenant_id"), ctx.get("tg_id"), audit.Act.ERROR,
                  target=where, detail=f"{type(exc).__name__}: {exc}")
    except Exception:
        pass
    try:
        import bot
        bot.send(ctx["chat_id"], "متأسفم، خطایی پیش اومد. دوباره تلاش کن.")
        import config
        if config.OWNER_TG_ID:
            bot.send(config.OWNER_TG_ID,
                     f"خطا در {where}:\n<code>{_esc(describe(exc))}</code>")
    except Exception:
        pass
    print(f"[error] {where}: {type(exc).__name__}: {exc}\n{describe(exc)}", flush=True)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
