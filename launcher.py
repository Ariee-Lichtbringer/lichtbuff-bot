import subprocess
import sys
import time


def start(name, script):
    print(f"Starte {name}: {script}", flush=True)
    return subprocess.Popen([sys.executable, "-u", script])


main_bot = start("Hauptbot", "bot.py")
po_bot = start("PO-Bot", "po_bot.py")

while True:
    main_code = main_bot.poll()
    if main_code is not None:
        print(f"Hauptbot wurde beendet (Code {main_code}). Container wird neu gestartet.", flush=True)
        if po_bot.poll() is None:
            po_bot.terminate()
        raise SystemExit(main_code or 1)

    po_code = po_bot.poll()
    if po_code is not None:
        print(f"PO-Bot wurde beendet (Code {po_code}). Neustart in 5 Sekunden.", flush=True)
        time.sleep(5)
        po_bot = start("PO-Bot", "po_bot.py")

    time.sleep(1)
