"""Start only the bots configured for this Railway service."""
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


def configured_bots(environ):
    jobs = []
    if environ.get("DISCORD_TOKEN", "").strip():
        jobs.append(("Hauptbot", "bot.py"))
    if environ.get("PO_BOT_TOKEN", "").strip():
        jobs.append(("PO-Bot", "po_bot.py"))
    return jobs


def main():
    jobs = configured_bots(os.environ)
    if not jobs:
        raise SystemExit("Kein Bot konfiguriert: DISCORD_TOKEN oder PO_BOT_TOKEN fehlt.")
    children = []
    try:
        for name, script in jobs:
            print(f"Starte {name}: {script}", flush=True)
            children.append((name, subprocess.Popen([sys.executable, "-u", script])))
        # The main bot supplies its own HTTP server. A PO-only service needs one.
        if not os.environ.get("DISCORD_TOKEN", "").strip():
            class HealthHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    healthy = all(child.poll() is None for _, child in children)
                    self.send_response(200 if healthy else 503)
                    self.end_headers()
                    self.wfile.write(b"ok" if healthy else b"bot stopped")

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), HealthHandler)
            Thread(target=server.serve_forever, daemon=True).start()
        while True:
            for name, child in children:
                code = child.poll()
                if code is not None:
                    print(f"{name} wurde beendet (Code {code}). Container wird neu gestartet.", flush=True)
                    raise SystemExit(code or 1)
            time.sleep(1)
    finally:
        for _, child in children:
            if child.poll() is None:
                child.terminate()


if __name__ == "__main__":
    main()
