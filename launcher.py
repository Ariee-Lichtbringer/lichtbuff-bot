import os
import sys


entrypoint = os.getenv("BOT_ENTRYPOINT", "bot.py").strip() or "bot.py"
allowed = {"bot.py", "po_bot.py"}

if entrypoint not in allowed:
    raise SystemExit(f"BOT_ENTRYPOINT ist ungueltig: {entrypoint}")

print(f"Starte {entrypoint}", flush=True)
os.execvp(sys.executable, [sys.executable, "-u", entrypoint])
