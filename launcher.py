"""Start only the bots configured for this Railway service."""
import os
import subprocess
import sys
import time


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
        # Each configured worker owns its own health/readiness endpoint.
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
