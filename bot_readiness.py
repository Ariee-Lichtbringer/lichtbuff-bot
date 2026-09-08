"""HTTP readiness for the actual PO worker, independent from launcher liveness."""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def readiness(bot):
    checks = {
        "discord": bot.is_ready() and not bot.is_closed(),
        "queue_running": bot._queue_task is not None and not bot._queue_task.done(),
        "refresh_running": bot._refresh_task is not None and not bot._refresh_task.done(),
        "queue_recent": bot._queue_last_success > 0 and time.monotonic() - bot._queue_last_success < 180,
    }
    return all(checks.values()), checks


def start_readiness_server(bot):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlsplit(self.path).path in {"/", "/live"}:
                ready, result = True, {"alive": True}
            else:
                ready, checks = readiness(bot)
                result = {"ready": ready, "checks": checks, "worker": "p0-v2"}
            self.send_response(200 if ready else 503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def log_message(self, *_args):
            pass

    # In a combined container the main bot owns PORT; expose PO readiness locally.
    port = int(os.environ.get("PO_HEALTH_PORT") or ("8081" if os.environ.get("DISCORD_TOKEN", "").strip() else os.environ.get("PORT", "8080")))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"P0-Bot V2 Bereitschaftsprüfung auf Port {port}.", flush=True)
    return server
