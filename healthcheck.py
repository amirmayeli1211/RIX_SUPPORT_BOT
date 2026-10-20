"""HTTP healthcheck server - lets Railway probe liveness.

One tiny stdlib HTTP server on $PORT:
  GET /health  -> 200 {"status":"ok","db":true,"tickets":N} or 503 when the
                  database is unreachable.
Nothing else is served here; the bot is a worker, not a web app.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import database as db
import repositories as repo


class _Handler(BaseHTTPRequestHandler):
    server_version = "RIX"

    def do_GET(self):  # noqa: N802 - stdlib naming
        if self.path.split("?")[0] not in ("/health", "/healthz", "/"):
            self._reply(404, {"status": "not found"})
            return
        db_ok = db.healthy()
        payload = {"status": "ok" if db_ok else "degraded", "db": db_ok}
        if db_ok:
            try:
                payload["tickets_open"] = db.scalar(
                    "SELECT COUNT(*) FROM tickets WHERE status='open'")
            except Exception:
                payload["tickets_open"] = None
        self._reply(200 if db_ok else 503, payload)

    def log_message(self, fmt, *args):  # silence default stderr access log
        print(f"[health] {fmt % args}", flush=True)

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start(port: int | None = None) -> ThreadingHTTPServer:
    port = port or config.PORT
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, name="health", daemon=True)
    thread.start()
    print(f"[health] listening on :{port}", flush=True)
    return server
