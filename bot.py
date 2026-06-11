import discord
import re
import json
import csv
import urllib.request
import urllib.parse
import os
import asyncio
from io import StringIO
from datetime import datetime, timedelta
import pytz

TOKEN = os.getenv("DISCORD_TOKEN")

TICKER_CHANNEL_ID = 1283706980103356448
POST_CHANNEL_ID = 1281152286772695071
HORDENBUFF_CHANNEL_ID = 1510764309062615220



# Direkter CSV-Export des Tabs "Worldbuff-Plan".
# Wichtig: Dieser Link zeigt auf das aktuelle Sheet/GID und nicht auf eine alte Web-Publish-Version.
CSV_URL = "https://docs.google.com/spreadsheets/d/1eItzaMGhpJ28vv4sDA8wwmu0YhUxcbiz-2VLiCVyjv4/export?format=csv&gid=1498762908"
CSV_CACHE_CONTENT = ""
CSV_CACHE_TIME = None
CSV_CACHE_SECONDS = 300
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycby7Rim3WtL0N2JV9bJng7AhT4j11PBPsofcYAT2sbMl_i3yHaeYeIc4UOjr0BA-x-kI/exec"

DATA_FILE = "worldbuffs.json"
POST_FILE = "last_post.json"
HORDENBUFF_FILE = "hordenbuff.json"
HORDENBUFF_CLEANUP_FILE = "hordenbuff_cleanup.json"
HORDENBUFF_CLEANUP_DELAY_MINUTES = 5
HORDENBUFF_CLEANUP_WINDOW_MINUTES = 45

BERLIN_TZ = pytz.timezone("Europe/Berlin")

LICHTBRINGER_GILDEN = ["Classic Lichtbringer", "Lichtbringer"]

BUFF_EMOJIS = {
    "Hakkar": "🟢",
    "ZG": "🟢",
    "Ony": "🔴",
    "Onyxia": "🔴",
    "Nef": "🔴",
    "Nefarian": "🔴",
    "Rend": "🟠"
}

TAG_LANG = {
    "Mo": "Montag",
    "Di": "Dienstag",
    "Mi": "Mittwoch",
    "Do": "Donnerstag",
    "Fr": "Freitag",
    "Sa": "Samstag",
    "So": "Sonntag"
}

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


async def delete_command_message(message):
    try:
        await message.delete()
    except:
        pass


async def send_temp(channel, text, seconds=10):
    try:
        await channel.send(text, delete_after=seconds)
    except:
        pass


def normalize_buff(buff):
    b = str(buff).strip().lower()
    b = b.replace("**", "")
    b = b.replace("🟢", "")
    b = b.replace("🔴", "")
    b = b.replace("🟠", "")
    b = b.replace("⚪", "")
    b = b.strip()

    if b in ["hakkar", "zg"] or "hakkar" in b or b == "zg":
        return "Hakkar"
    if b in ["ony", "onyxia"] or "ony" in b:
        return "Ony"
    if b in ["nef", "neff", "neffm", "nefarian"] or "nef" in b:
        return "Nef"
    if b == "rend" or "rend" in b:
        return "Rend"

    return str(buff).strip()


def is_lichtbringer(gilde):
    return any(name.lower() in gilde.lower() for name in LICHTBRINGER_GILDEN)


def make_buff_key(buff_data):
    datum = buff_data["datum"]
    zeit = buff_data["uhrzeit"]
    buff = normalize_buff(buff_data["buff"])
    gilde = buff_data["gilde"]

    if is_lichtbringer(gilde):
        return f"{datum}|{zeit}|{buff}|LICHTBRINGER"

    return f"{datum}|{zeit}|{buff}|{gilde}"


def make_hordenbuff_key(buff_data):
    return f"{buff_data['datum']}|{buff_data['uhrzeit']}|Rend|{buff_data['gilde']}"


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(filename, fallback):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return fallback


def clean_sheet_value(value):
    text = str(value or "").strip()
    if text.lower() in ["nan", "none", "null"]:
        return ""
    if text.endswith(";"):
        text = text[:-1].strip()
    return text


def make_tag_from_date(datum):
    try:
        dt = datetime.strptime(datum, "%d.%m.%Y")
        return ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][dt.weekday()]
    except:
        return ""



def normalize_sheet_header(value):
    text = clean_sheet_value(value).lower()
    text = text.replace(";", "")
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def find_column_index(header_map, *names):
    for name in names:
        key = normalize_sheet_header(name)
        if key in header_map:
            return header_map[key]
    return None


def get_cell(row, index):
    if index is None or index >= len(row):
        return ""
    return clean_sheet_value(row[index])


def normalize_sheet_date(value):
    text = clean_sheet_value(value)
    if not text:
        return ""

    for fmt in ["%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%m/%d/%Y"]:
        try:
            return datetime.strptime(text, fmt).strftime("%d.%m.%Y")
        except:
            pass

    return text


def normalize_sheet_time(value):
    text = clean_sheet_value(value)
    if not text:
        return ""

    text = text.replace(" Uhr", "").replace("Uhr", "").strip()

    # Google/CSV kann Uhrzeiten gelegentlich als 19:35:00 liefern.
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    return text


def iter_worldbuff_sheet_rows():
    """
    Liest das Worldbuff-Sheet robust ein.
    Die Spalten werden ueber die Kopfzeile gesucht, nicht mehr ueber feste Positionen.
    Dadurch funktionieren auch Hinweiszeilen oberhalb der Tabelle und kleinere Layout-Aenderungen.
    """
    content = get_csv_content()
    if not content:
        return []

    result = []

    try:
        reader = csv.reader(StringIO(content))
        rows = list(reader)
        header_map = None
        last_date = ""
        last_tag = ""

        for row in rows:
            if not row:
                continue

            normalized = [normalize_sheet_header(cell) for cell in row]

            # Kopfzeile finden: Tag | Datum | Uhrzeit | Icon | Buff | Gilde | Charakter | Status | Notiz
            if "tag" in normalized and "datum" in normalized and "uhrzeit" in normalized and "buff" in normalized:
                header_map = {key: idx for idx, key in enumerate(normalized) if key}
                continue

            if not header_map:
                continue

            tag_i = find_column_index(header_map, "Tag")
            datum_i = find_column_index(header_map, "Datum")
            uhrzeit_i = find_column_index(header_map, "Uhrzeit", "Zeit")
            buff_i = find_column_index(header_map, "Buff")
            gilde_i = find_column_index(header_map, "Gilde")
            charakter_i = find_column_index(header_map, "Charakter", "Char", "Werfer")
            status_i = find_column_index(header_map, "Status")

            tag = get_cell(row, tag_i)
            datum = normalize_sheet_date(get_cell(row, datum_i))
            uhrzeit = normalize_sheet_time(get_cell(row, uhrzeit_i))
            buff = normalize_buff(get_cell(row, buff_i))
            gilde = get_cell(row, gilde_i)
            charakter = get_cell(row, charakter_i)
            status = get_cell(row, status_i)

            if tag:
                last_tag = tag
            else:
                tag = last_tag

            if datum:
                last_date = datum
            else:
                datum = last_date

            if not tag and datum:
                tag = make_tag_from_date(datum)

            if buff not in ["Hakkar", "Ony", "Nef", "Rend"]:
                continue

            if not datum or not uhrzeit or not gilde:
                continue

            result.append({
                "buff": buff,
                "datum": datum,
                "tag": tag,
                "uhrzeit": uhrzeit,
                "gilde": gilde,
                "charakter": charakter,
                "status": status
            })

    except Exception as e:
        print("Fehler beim robusten Lesen des Worldbuff-Sheets:", e)

    return result


def get_active_horden_rend_from_state():
    data = load_json(HORDENBUFF_FILE, {})
    event_key = str(data.get("event_key", ""))

    if not event_key:
        return None

    parts = event_key.split("|")
    if len(parts) < 4:
        return None

    datum, uhrzeit, buff, gilde = parts[0], parts[1], parts[2], "|".join(parts[3:])

    if normalize_buff(buff) != "Rend":
        return None

    try:
        dt = datetime.strptime(f"{datum} {uhrzeit}", "%d.%m.%Y %H:%M")
        # Bestehenden Termin noch als Fallback akzeptieren, solange er nicht sehr alt ist.
        if dt < datetime.now(BERLIN_TZ).replace(tzinfo=None) - timedelta(hours=2):
            return None
    except:
        return None

    return {
        "buff": "Rend",
        "datum": datum,
        "tag": make_tag_from_date(datum),
        "uhrzeit": uhrzeit,
        "gilde": gilde
    }


def get_next_horden_rend_safe():
    rend = get_next_horden_rend()
    if rend:
        return rend

    fallback = get_active_horden_rend_from_state()
    if fallback:
        return fallback

    return None


def get_csv_content():
    global CSV_CACHE_CONTENT, CSV_CACHE_TIME

    now = datetime.now()

    if CSV_CACHE_CONTENT and CSV_CACHE_TIME:
        if (now - CSV_CACHE_TIME).total_seconds() < CSV_CACHE_SECONDS:
            return CSV_CACHE_CONTENT

    try:
        print("CSV Abruf gestartet")

        with urllib.request.urlopen(CSV_URL, timeout=5) as response:
            CSV_CACHE_CONTENT = response.read().decode("utf-8")
            CSV_CACHE_TIME = now
            print("CSV erfolgreich geladen")
            return CSV_CACHE_CONTENT

    except Exception as e:
        print("CSV Fehler:", e)

        if CSV_CACHE_CONTENT:
            print("Nutze alten CSV Cache")
            return CSV_CACHE_CONTENT

        return ""


def parse_ticker_message(text):
    buffs = []

    pattern = re.compile(
        r"^(?:[🟢🔴🟠⚪]\s*)?"
        r"\**(Hakkar|hakkar|ZG|zg|Ony|ony|Onyxia|Nef|nef|Nefarian|Rend|rend)\**\s+"
        r"(\d{2}\.\d{2}\.\d{4})\s+"
        r"([A-Za-zÄÖÜäöü]{2})\s+"
        r"(\d{2}:\d{2})\s+"
        r"(.+)$"
    )

    for line in text.splitlines():
        line = line.strip()
        line = line.replace("**", "")

        match = pattern.match(line)

        if match:
            buff, datum, tag, uhrzeit, gilde = match.groups()
            buffs.append({
                "buff": normalize_buff(buff),
                "datum": datum,
                "tag": tag,
                "uhrzeit": uhrzeit,
                "gilde": gilde.strip()
            })

    return buffs


def import_buffs_aus_sheet():
    rows = iter_worldbuff_sheet_rows()
    sheet_buffs = []

    for row in rows:
        sheet_buffs.append({
            "buff": row.get("buff", ""),
            "datum": row.get("datum", ""),
            "tag": row.get("tag", ""),
            "uhrzeit": row.get("uhrzeit", ""),
            "gilde": row.get("gilde", "")
        })

    if not sheet_buffs:
        print("Worldbuff-Sheet geladen, aber keine gueltigen Buff-Zeilen gefunden. Pruefe CSV_URL und Kopfzeile.")
    else:
        print(f"Worldbuff-Sheet: {len(sheet_buffs)} Buff-Zeilen gelesen.")

    return sheet_buffs


def import_werfer_aus_sheet():
    werfer = {}
    rows = iter_worldbuff_sheet_rows()

    for row in rows:
        datum = row.get("datum", "")
        uhrzeit = row.get("uhrzeit", "")
        buff = normalize_buff(row.get("buff", ""))
        charakter = row.get("charakter", "")
        status = row.get("status", "")

        if not datum or not uhrzeit or not buff or not charakter:
            continue

        key = f"{datum}|{uhrzeit}|{buff}"
        werfer[key] = {
            "charakter": charakter,
            "status": status
        }

    return werfer


def sende_wurf_ans_sheet(buff, charakter, discord_name):
    payload = {
        "buff": buff,
        "charakter": charakter,
        "discord": discord_name
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        APPS_SCRIPT_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        result = response.read().decode("utf-8")
        return json.loads(result)


def build_overview():
    data = load_json(DATA_FILE, [])
    sheet_buffs = import_buffs_aus_sheet()

    existing_keys = {
        make_buff_key(b)
        for b in data
    }

    for buff in sheet_buffs:
        key = make_buff_key(buff)

        if key not in existing_keys:
            data.append(buff)
            existing_keys.add(key)

    werfer = import_werfer_aus_sheet()

    if not data:
        return "📢 **Worldbuff Übersicht**\n\nKeine Worldbuffs gefunden."

    heute = datetime.now(BERLIN_TZ).date()
    ende = heute + timedelta(days=7)

    gefiltert = []

    for b in data:
        try:
            buff_datum = datetime.strptime(b["datum"], "%d.%m.%Y").date()

            if heute <= buff_datum <= ende:
                gefiltert.append(b)

        except:
            continue

    data = gefiltert

    if not data:
        return "📢 **Worldbuff Übersicht**\n\nKeine kommenden Worldbuffs in den nächsten 7 Tagen gefunden."

    data.sort(
        key=lambda x: (
            datetime.strptime(x["datum"], "%d.%m.%Y"),
            x["uhrzeit"]
        )
    )

    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")

    text = "📢 **Worldbuff Übersicht**\n"
    text += f"🕒 Letzte Aktualisierung: {now}\n"
    text = "📢 **Worldbuff Übersicht**\n"
    text += f"🕒 Letzte Aktualisierung: {now}\n"
    text += "_Automatisch aus dem Worldbuff-Ticker und dem Sheet erstellt._\n"
    text += "_Angezeigt werden nur Termine der nächsten 7 Tage._\n\n"

    text += "━━━━━━━━━━━━━━━\n"
    text += "📋 **Worldbuff-Anleitung**\n\n"

    text += "🔵 **Lichtbringer-Werfer eintragen**\n"
    text += "`!wurf Buff Charaktername`\n\n"

    text += "**Beispiele:**\n"
    text += "`!wurf hakkar Ariee`\n"
    text += "`!wurf ony Protekta`\n"
    text += "`!wurf nef Paladrium`\n"
    text += "`!wurf rend Miimi`\n\n"

    text += "Der Bot trägt euch automatisch beim nächsten passenden Termin im Sheet ein "
    text += "und aktualisiert anschließend die Übersicht.\n\n"

    text += "🪓 **Horde-Rend Koordination**\n"
    text += "Die Anmeldung für Rend erfolgt im Hordenbuff-Channel über:\n"
    text += "`!rend Spielername`\n\n"

    text += "━━━━━━━━━━━━━━━\n\n"

    current_date = ""

    for b in data:
        datum = b["datum"]
        tag_kurz = b["tag"]
        tag_lang = TAG_LANG.get(tag_kurz, tag_kurz)
        zeit = b["uhrzeit"]
        buff = normalize_buff(b["buff"])
        gilde = b["gilde"]

        emoji = BUFF_EMOJIS.get(buff, "⚪")

        if datum != current_date:
            text += f"\n**{tag_lang}, {datum}**\n"
            current_date = datum

        werfer_text = ""

        key = f"{datum}|{zeit}|{buff}"
        info = werfer.get(key)

        if info and info.get("charakter"):
            if is_lichtbringer(gilde):
                werfer_text = f" - 🔵 {info['charakter']}"
            else:
                werfer_text = f" - ⚔️ {info['charakter']}"

        text += f"{emoji} **{buff}** {zeit} - {gilde}{werfer_text}\n"

    return text


async def delete_last_post(channel):
    post_data = load_json(POST_FILE, {})
    message_id = post_data.get("message_id")

    if not message_id:
        return

    try:
        old_message = await channel.fetch_message(message_id)
        await old_message.delete()
    except:
        pass


async def update_worldbuff_post():
    channel = client.get_channel(POST_CHANNEL_ID)

    if channel is None:
        print("Ziel-Channel nicht gefunden.")
        return

    await delete_last_post(channel)

    text = await asyncio.to_thread(build_overview)

    if len(text) <= 1900:
        msg = await channel.send(text)
        save_json(POST_FILE, {"message_id": msg.id})
    else:
        chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
        last_msg = None

        for chunk in chunks:
            last_msg = await channel.send(chunk)

        if last_msg:
            save_json(POST_FILE, {"message_id": last_msg.id})


def get_next_horden_rend():
    buffs = import_buffs_aus_sheet()
    now = datetime.now(BERLIN_TZ).replace(tzinfo=None)

    rend_termine = []

    for b in buffs:
        if normalize_buff(b["buff"]) != "Rend":
            continue

        try:
            dt = datetime.strptime(
                f"{b['datum']} {b['uhrzeit']}",
                "%d.%m.%Y %H:%M"
            )

            if dt >= now:
                rend_termine.append((dt, b))

        except:
            continue

    rend_termine.sort(key=lambda x: x[0])

    if not rend_termine:
        return None

    return rend_termine[0][1]


def get_upcoming_horden_rends(limit=5):
    buffs = import_buffs_aus_sheet()
    now = datetime.now(BERLIN_TZ).replace(tzinfo=None)

    rend_termine = []

    for b in buffs:
        if normalize_buff(b["buff"]) != "Rend":
            continue

        try:
            dt = datetime.strptime(
                f"{b['datum']} {b['uhrzeit']}",
                "%d.%m.%Y %H:%M"
            )

            if dt >= now:
                rend_termine.append((dt, b))

        except:
            continue

    rend_termine.sort(key=lambda x: x[0])

    return [
        buff
        for _, buff in rend_termine[:limit]
    ]



def get_recent_expired_horden_rend():
    """
    Findet den gerade abgelaufenen Rend-Termin.
    Beispiel: Rend 19:35 -> ab 19:40 wird einmalig aufgeraeumt.
    Das Zeitfenster verhindert, dass der Bot beim Neustart alte Termine von gestern bereinigt.
    """
    buffs = import_buffs_aus_sheet()
    now = datetime.now(BERLIN_TZ).replace(tzinfo=None)
    expired = []

    for b in buffs:
        if normalize_buff(b.get("buff")) != "Rend":
            continue

        try:
            dt = datetime.strptime(
                f"{b['datum']} {b['uhrzeit']}",
                "%d.%m.%Y %H:%M"
            )
        except:
            continue

        cleanup_at = dt + timedelta(minutes=HORDENBUFF_CLEANUP_DELAY_MINUTES)
        cleanup_until = dt + timedelta(minutes=HORDENBUFF_CLEANUP_WINDOW_MINUTES)

        if cleanup_at <= now <= cleanup_until:
            expired.append((dt, b))

    expired.sort(key=lambda x: x[0], reverse=True)
    return expired[0][1] if expired else None


async def clear_hordenbuff_channel_and_post_next(expired_rend):
    channel = client.get_channel(HORDENBUFF_CHANNEL_ID) or await client.fetch_channel(HORDENBUFF_CHANNEL_ID)
    cleanup_state = load_json(HORDENBUFF_CLEANUP_FILE, {})
    event_key = make_hordenbuff_key(expired_rend)

    if cleanup_state.get("last_cleaned_event_key") == event_key:
        return

    try:
        # Loescht die aktuellen Nachrichten im Hordenbuff-Channel.
        # Fuer sehr alte Nachrichten kann Discord bulk delete begrenzen; der Channel enthaelt aber normalerweise nur aktuelle Orga-Posts.
        await channel.purge(limit=500, check=lambda m: not m.pinned, bulk=True)
    except Exception as e:
        print("Fehler beim Bereinigen des Hordenbuff-Channels:", e)
        # Fallback: zumindest die letzten Nachrichten einzeln versuchen.
        try:
            async for msg in channel.history(limit=100):
                if msg.pinned:
                    continue
                try:
                    await msg.delete()
                    await asyncio.sleep(0.2)
                except:
                    pass
        except Exception as inner:
            print("Fallback-Bereinigung fehlgeschlagen:", inner)

    cleanup_state["last_cleaned_event_key"] = event_key
    cleanup_state["last_cleaned_at"] = datetime.now(BERLIN_TZ).isoformat()
    save_json(HORDENBUFF_CLEANUP_FILE, cleanup_state)

    # Alte Hordenbuff-Nachricht vergessen, damit fuer den naechsten Rend-Termin sicher ein frischer Post entsteht.
    save_json(HORDENBUFF_FILE, {
        "event_key": "",
        "spieler": [],
        "uebernahmen": {},
        "helfer": [],
        "message_id": None,
        "reminders_sent": []
    })

    await update_hordenbuff_post()


def load_hordenbuff_state(rend):
    fallback = {
        "event_key": "",
        "spieler": [],
        "uebernahmen": {},
        "helfer": [],
        "message_id": None,
        "reminders_sent": []
    }

    data = load_json(HORDENBUFF_FILE, fallback)

    if not rend:
        return fallback

    event_key = make_hordenbuff_key(rend)

    if data.get("event_key") != event_key:
        data = {
            "event_key": event_key,
            "spieler": [],
            "uebernahmen": {},
            "helfer": [],
            "message_id": None,
            "reminders_sent": []
        }

        save_json(HORDENBUFF_FILE, data)

    data.setdefault("spieler", [])
    data.setdefault("uebernahmen", {})
    data.setdefault("helfer", [])
    data.setdefault("reminders_sent", [])

    return data


def get_assigned_targets(data):
    return {
        target.lower()
        for target in data.get("uebernahmen", {}).values()
    }


def get_next_unassigned_char(data):
    assigned = get_assigned_targets(data)

    for charakter in data.get("spieler", []):
        if charakter.lower() not in assigned:
            return charakter

    return None


def build_hordenbuff_text(rend, data):
    tag_kurz = rend.get("tag", "")
    tag_lang = TAG_LANG.get(tag_kurz, tag_kurz)

    text = "🪓 **Horde-Rend Koordination**\n\n"
    text += f"📌 **Aktiv verwalteter Termin:** {tag_lang}, {rend['datum']} um {rend['uhrzeit']}\n\n"

    upcoming = get_upcoming_horden_rends(limit=5)

    text += "📅 **Kommende Rend-Termine laut Lichtbuff:**\n"

    if upcoming:
        for item in upcoming:
            item_tag = TAG_LANG.get(item.get("tag", ""), item.get("tag", ""))
            text += f"🟠 {item_tag}, {item['datum']} um {item['uhrzeit']}\n"
    else:
        text += "-\n"

    text += "\n✅ **Benötigen den Buff für den aktiven Termin:**\n"

    if data.get("spieler"):
        assigned = get_assigned_targets(data)

        for name in data["spieler"]:
            if name.lower() in assigned:
                text += f"✅ {name} _(zugeteilt)_\n"
            else:
                text += f"✅ {name}\n"
    else:
        text += "-\n"

    text += "\n🛡️ **Übernahmen / Helfer:**\n"

    uebernahmen = data.get("uebernahmen", {})
    helfer_liste = data.get("helfer", [])
    zugeteilte_helfer = {name.lower() for name in uebernahmen.keys()}
    freie_helfer = [name for name in helfer_liste if name.lower() not in zugeteilte_helfer]

    if uebernahmen:
        for helfer, ziel in uebernahmen.items():
            text += f"🛡️ {helfer} → übernimmt **{ziel}**\n"

    if freie_helfer:
        for helfer in freie_helfer:
            text += f"🛡️ {helfer} _(bereit, noch nicht zugeteilt)_\n"

    if not uebernahmen and not freie_helfer:
        text += "-\n"

    text += "\n━━━━━━━━━━━━━━━\n"
    text += "📋 **Befehle**\n\n"

    text += "✅ **Ally-Char anmelden:**\n"
    text += "`!rend Spielername`\n"
    text += "Beispiel: `!rend Ariee`\n\n"

    text += "🛡️ **Ich kann übernehmen / automatisch zuteilen:**\n"
    text += "`!rendhelfer Name`\n"
    text += "Beispiel: `!rendhelfer Miimi`\n"
    text += "_Der Bot teilt diesen Helfer automatisch dem nächsten freien Ally-Char zu._\n\n"

    text += "🎯 **Gezielt festlegen, wer wen übernimmt:**\n"
    text += "`!rendbei Allyname Helfername`\n"
    text += "Beispiel: `!rendbei Ariee Miimi`\n\n"

    text += "🗑️ **Eintrag löschen:**\n"
    text += "`!renddel Spielername`\n"
    text += "Beispiel: `!renddel Ariee`\n\n"

    text += "🔄 **Liste aktualisieren:**\n"
    text += "`!hordenbuff`\n"

    return text


async def update_hordenbuff_post():
    channel = client.get_channel(HORDENBUFF_CHANNEL_ID)

    if channel is None:
        print("Hordenbuff-Channel nicht gefunden.")
        return

    rend = await asyncio.to_thread(get_next_horden_rend_safe)

    if not rend:
        await channel.send(
            "⚠️ Es wurde kein kommender Rend-Termin im Sheet gefunden.",
            delete_after=15
        )
        return

    data = load_hordenbuff_state(rend)
    text = build_hordenbuff_text(rend, data)

    try:
        if data.get("message_id"):
            msg = await channel.fetch_message(data["message_id"])
            await msg.edit(content=text)
        else:
            msg = await channel.send(text)
            data["message_id"] = msg.id
            save_json(HORDENBUFF_FILE, data)

    except:
        msg = await channel.send(text)
        data["message_id"] = msg.id
        save_json(HORDENBUFF_FILE, data)


async def add_rend_spieler(message, charakter):
    rend = await asyncio.to_thread(get_next_horden_rend_safe)

    if not rend:
        await send_temp(
            message.channel,
            "⚠️ Es wurde kein kommender Rend-Termin im Sheet gefunden."
        )
        await delete_command_message(message)
        return

    data = load_hordenbuff_state(rend)

    if charakter not in data["spieler"]:
        data["spieler"].append(charakter)

    save_json(HORDENBUFF_FILE, data)

    await update_hordenbuff_post()
    await delete_command_message(message)


async def auto_assign_hordenbuff_helper(message, helfer_name):
    rend = await asyncio.to_thread(get_next_horden_rend_safe)

    if not rend:
        await send_temp(
            message.channel,
            "⚠️ Es wurde kein kommender Rend-Termin im Sheet gefunden."
        )
        await delete_command_message(message)
        return

    data = load_hordenbuff_state(rend)
    data.setdefault("helfer", [])
    data.setdefault("uebernahmen", {})

    if helfer_name not in data["helfer"]:
        data["helfer"].append(helfer_name)

    if helfer_name in data.get("uebernahmen", {}):
        ziel = data["uebernahmen"][helfer_name]

        save_json(HORDENBUFF_FILE, data)
        await send_temp(
            message.channel,
            f"ℹ️ {helfer_name} ist bereits für **{ziel}** eingeteilt."
        )

        await update_hordenbuff_post()
        await delete_command_message(message)
        return

    ziel = get_next_unassigned_char(data)

    if not ziel:
        save_json(HORDENBUFF_FILE, data)
        await send_temp(
            message.channel,
            f"✅ {helfer_name} wurde als Helfer eingetragen. Aktuell ist noch kein freier Ally-Char offen."
        )

        await update_hordenbuff_post()
        await delete_command_message(message)
        return

    data["uebernahmen"][helfer_name] = ziel

    save_json(HORDENBUFF_FILE, data)

    await update_hordenbuff_post()
    await delete_command_message(message)

    
async def set_specific_hordenbuff_helper(
    message,
    ziel,
    helfer_name
):
    rend = await asyncio.to_thread(get_next_horden_rend_safe)

    if not rend:
        await send_temp(
            message.channel,
            "⚠️ Es wurde kein kommender Rend-Termin im Sheet gefunden."
        )
        await delete_command_message(message)
        return

    data = load_hordenbuff_state(rend)

    if ziel not in data.get("spieler", []):
        data.setdefault("spieler", [])
        data["spieler"].append(ziel)

    data.setdefault("uebernahmen", {})
    data.setdefault("helfer", [])

    if helfer_name not in data["helfer"]:
        data["helfer"].append(helfer_name)

    alte_helfer = [
        helper
        for helper, target
        in data["uebernahmen"].items()
        if target.lower() == ziel.lower()
    ]

    for helper in alte_helfer:
        del data["uebernahmen"][helper]

    data["uebernahmen"][helfer_name] = ziel

    save_json(HORDENBUFF_FILE, data)

    await update_hordenbuff_post()
    await delete_command_message(message)


async def set_hordenbuff_char(message, charakter):
    rend = await asyncio.to_thread(get_next_horden_rend_safe)

    if not rend:
        await send_temp(
            message.channel,
            "⚠️ Es wurde kein kommender Rend-Termin im Sheet gefunden."
        )
        await delete_command_message(message)
        return

    data = load_hordenbuff_state(rend)
    helfer_name = message.author.display_name

    data.setdefault("uebernahmen", {})
    data.setdefault("helfer", [])

    if helfer_name not in data["helfer"]:
        data["helfer"].append(helfer_name)

    data["uebernahmen"][helfer_name] = charakter

    save_json(HORDENBUFF_FILE, data)

    await update_hordenbuff_post()
    await delete_command_message(message)


async def delete_rend_entry(message, charakter):
    rend = await asyncio.to_thread(get_next_horden_rend_safe)

    if not rend:
        await send_temp(
            message.channel,
            "⚠️ Es wurde kein kommender Rend-Termin im Sheet gefunden."
        )
        await delete_command_message(message)
        return

    data = load_hordenbuff_state(rend)

    data["spieler"] = [
        name for name in data.get("spieler", [])
        if name.lower() != charakter.lower()
    ]

    remove_helpers = []

    for helper, ziel in data.get("uebernahmen", {}).items():
        if ziel.lower() == charakter.lower() or helper.lower() == charakter.lower():
            remove_helpers.append(helper)

    for helper in remove_helpers:
        del data["uebernahmen"][helper]

    data["helfer"] = [
        name for name in data.get("helfer", [])
        if name.lower() != charakter.lower()
    ]

    save_json(HORDENBUFF_FILE, data)

    await update_hordenbuff_post()
    await delete_command_message(message)


async def hordenbuff_reminder_loop():
    await client.wait_until_ready()

    while not client.is_closed():
        try:
            # Nach Ablauf eines Rendbuffs wird der Hordenbuff-Channel automatisch bereinigt.
            # Beispiel: Rend 19:35 -> um 19:40 wird geloescht und der naechste Post erstellt.
            expired_rend = await asyncio.to_thread(get_recent_expired_horden_rend)
            if expired_rend:
                await clear_hordenbuff_channel_and_post_next(expired_rend)

            rend = await asyncio.to_thread(get_next_horden_rend_safe)

            if rend:
                channel = client.get_channel(HORDENBUFF_CHANNEL_ID)

                if channel:
                    data = load_hordenbuff_state(rend)

                    rend_dt = datetime.strptime(
                        f"{rend['datum']} {rend['uhrzeit']}",
                        "%d.%m.%Y %H:%M"
                    )

                    now = datetime.now(BERLIN_TZ).replace(tzinfo=None)
                    minutes_left = int((rend_dt - now).total_seconds() / 60)

                    reminders = {
                        30: "⏰ **Rend in 30 Minuten!** Bitte rechtzeitig vorbereiten.",
                        15: "⏰ **Rend in 15 Minuten!** Ally-Char/duellfähigen Char bereithalten.",
                        5: "🚨 **Rend in 5 Minuten!** Jetzt einloggen und bereitmachen."
                    }

                    for minute, reminder_text in reminders.items():
                        already_sent = str(minute) in data.get("reminders_sent", [])

                        if minute - 1 <= minutes_left <= minute and not already_sent:
                            await channel.send(reminder_text)

                            data.setdefault("reminders_sent", [])
                            data["reminders_sent"].append(str(minute))

                            save_json(HORDENBUFF_FILE, data)

                            await update_hordenbuff_post()

        except Exception as e:
            print("Fehler im Hordenbuff-Reminder:", e)

        await asyncio.sleep(60)




async def handle_ticker_update(message):
    if message.channel.id != TICKER_CHANNEL_ID:
        return

    new_buffs = parse_ticker_message(message.content)

    if not new_buffs:
        return

    old_data = load_json(DATA_FILE, [])

    existing_keys = {
        make_buff_key(b)
        for b in old_data
    }

    for buff in new_buffs:
        key = make_buff_key(buff)

        if key not in existing_keys:
            old_data.append(buff)
            existing_keys.add(key)

    save_json(DATA_FILE, old_data)

    print(f"{len(new_buffs)} Worldbuffs aus Ticker übernommen oder geprüft.")

    await update_worldbuff_post()

    if any(normalize_buff(b["buff"]) == "Rend" for b in new_buffs):
        await update_hordenbuff_post()


async def scan_recent_ticker_messages(limit=250):
    """
    Liest beim Bot-Start rückwirkend die letzten Ticker-Nachrichten ein.
    Wichtig für Railway/Cloud-Hosting, weil lokale JSON-Dateien nach Deploys leer sein können.
    """
    try:
        channel = client.get_channel(TICKER_CHANNEL_ID) or await client.fetch_channel(TICKER_CHANNEL_ID)
    except Exception as e:
        print("Ticker-Channel konnte nicht geladen werden:", e)
        return

    old_data = load_json(DATA_FILE, [])
    existing_keys = {
        make_buff_key(b)
        for b in old_data
    }

    added = 0
    checked_messages = 0

    try:
        async for msg in channel.history(limit=limit):
            if msg.author == client.user:
                continue

            checked_messages += 1
            message_text = collect_message_text(msg)
            buffs = parse_ticker_message(message_text)

            for buff in buffs:
                key = make_buff_key(buff)

                if key not in existing_keys:
                    old_data.append(buff)
                    existing_keys.add(key)
                    added += 1

    except Exception as e:
        print("Fehler beim rückwirkenden Ticker-Scan:", e)
        return

    if added:
        save_json(DATA_FILE, old_data)
        print(f"Ticker-Rückscan: {added} neue Worldbuffs aus {checked_messages} Nachrichten übernommen.")
        await update_worldbuff_post()

        if any(normalize_buff(b.get("buff")) == "Rend" for b in old_data):
            await update_hordenbuff_post()
    else:
        print(f"Ticker-Rückscan: keine neuen Worldbuffs gefunden ({checked_messages} Nachrichten geprüft).")


async def initial_startup_sync():
    await client.wait_until_ready()

    if getattr(client, "initial_startup_sync_done", False):
        return

    client.initial_startup_sync_done = True

    await scan_recent_ticker_messages(limit=250)
    await update_worldbuff_post()
    await update_hordenbuff_post()




@client.event
async def on_ready():
    print(f"Bot online als {client.user}")
    print(f"Überwache Ticker-Channel: {TICKER_CHANNEL_ID}")
    print(f"Postet Übersicht in Channel: {POST_CHANNEL_ID}")
    print(f"Hordenbuff-Channel: {HORDENBUFF_CHANNEL_ID}")
    print("Lichtbuff-Version gestartet: Worldbuff + Hordenbuff aktiv.")

    if not hasattr(client, "startup_sync_task_started"):
        client.startup_sync_task_started = True
        client.loop.create_task(initial_startup_sync())

    if not hasattr(client, "hordenbuff_task_started"):
        client.hordenbuff_task_started = True
        client.loop.create_task(hordenbuff_reminder_loop())


@client.event
async def on_message_edit(before, after):
    if after.author == client.user:
        return

    await handle_ticker_update(after)


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    content = message.content.strip()
    lower = content.lower()

    if lower == "!wb":
        await update_worldbuff_post()
        await update_hordenbuff_post()
        await delete_command_message(message)
        return

    if lower in ["!hordenbuff", "!hordebuff", "!horde"]:
        await update_hordenbuff_post()
        await delete_command_message(message)
        return

    if lower.startswith("!rendhelfer "):
        helfer_name = content.split(maxsplit=1)[1].strip()
        if not helfer_name:
            await send_temp(message.channel, "Bitte nutze den Befehl so: `!rendhelfer Name`, z. B. `!rendhelfer Miimi`.")
            await delete_command_message(message)
            return
        await auto_assign_hordenbuff_helper(message, helfer_name)
        return

    if lower == "!rendhelfer":
        await send_temp(message.channel, "Bitte nutze den Befehl so: `!rendhelfer Name`, z. B. `!rendhelfer Miimi`.")
        await delete_command_message(message)
        return

    if lower.startswith("!rendbei "):
        parts = content.split(maxsplit=2)
        if len(parts) < 3:
            await send_temp(message.channel, "Bitte nutze den Befehl so: `!rendbei Allyname Helfername`, z. B. `!rendbei Ariee Miimi`.")
            await delete_command_message(message)
            return
        ziel = parts[1].strip()
        helfer_name = parts[2].strip()
        await set_specific_hordenbuff_helper(message, ziel, helfer_name)
        return

    if lower == "!rendbei":
        await send_temp(message.channel, "Bitte nutze den Befehl so: `!rendbei Allyname Helfername`, z. B. `!rendbei Ariee Miimi`.")
        await delete_command_message(message)
        return

    if lower.startswith("!rendchar "):
        charakter = content.split(maxsplit=1)[1].strip()
        if not charakter:
            await send_temp(message.channel, "Bitte nutze den Befehl so: `!rendchar Spielername`.")
            await delete_command_message(message)
            return
        await set_hordenbuff_char(message, charakter)
        return

    if lower.startswith("!renddel "):
        charakter = content.split(maxsplit=1)[1].strip()
        if not charakter:
            await send_temp(message.channel, "Bitte nutze den Befehl so: `!renddel Spielername`.")
            await delete_command_message(message)
            return
        await delete_rend_entry(message, charakter)
        return

    if lower.startswith("!rend "):
        charakter = content.split(maxsplit=1)[1].strip()
        if not charakter:
            await send_temp(message.channel, "Bitte nutze den Befehl so: `!rend Spielername`.")
            await delete_command_message(message)
            return
        await add_rend_spieler(message, charakter)
        return

    if lower == "!rend":
        await send_temp(message.channel, "Bitte nutze den Befehl so: `!rend Spielername`, z. B. `!rend Ariee`.")
        await delete_command_message(message)
        return

    if lower == "!rendchar":
        await send_temp(message.channel, "Bitte nutze den Befehl so: `!rendchar Spielername`, z. B. `!rendchar Ariee`.")
        await delete_command_message(message)
        return

    if lower == "!renddel":
        await send_temp(message.channel, "Bitte nutze den Befehl so: `!renddel Spielername`, z. B. `!renddel Ariee`.")
        await delete_command_message(message)
        return

    if lower.startswith("!wurf "):
        parts = content.split(maxsplit=2)
        if len(parts) < 3:
            await message.channel.send("Bitte nutze den Befehl so: `!wurf hakkar Charaktername`.")
            return

        buff = normalize_buff(parts[1])
        charakter = parts[2].strip()

        if buff not in ["Hakkar", "Ony", "Nef", "Rend"]:
            await message.channel.send("Diesen Buff kenne ich nicht. Nutze: `hakkar`, `ony`, `nef` oder `rend`.")
            return

        try:
            result = await asyncio.to_thread(sende_wurf_ans_sheet, buff, charakter, str(message.author))
            if result.get("success"):
                await message.channel.send(
                    f"✅ **{charakter}** wurde für **{result.get('buff')}** eingetragen: "
                    f"{result.get('datum')} um {result.get('uhrzeit')}."
                )
                await update_worldbuff_post()
                if buff == "Rend":
                    await update_hordenbuff_post()
            else:
                await message.channel.send(f"⚠️ Apps-Script-Antwort:\n```{result}```")
        except Exception as e:
            print(f"Fehler bei !wurf: {e}")
            await message.channel.send("⚠️ Beim Eintragen ist ein Fehler passiert. Bitte prüfe Apps Script und Sheet.")
        return

    await handle_ticker_update(message)


if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN ist nicht gesetzt. Bitte in Railway unter Variables eintragen.")

client.run(TOKEN)
