import discord
import re
import json
import csv
import urllib.request
import urllib.parse
import os
import asyncio
import time
import threading
import contextvars
import sys
from io import StringIO
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import pytz

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

TOKEN = os.getenv("DISCORD_TOKEN", "MTUxMDY3NzM0Njc4NzY1OTc3Nw.G_-vuz._ocUI4y-Nv7o9Kn0erGGra7cQfrHvFjKfBaeRc")
LICHTBOT_QUEUE_TOKEN = os.getenv("LICHTBOT_QUEUE_TOKEN", "")

TICKER_CHANNEL_ID = 1283706980103356448
PANEM_TICKER_CHANNEL_ID = 1482656882857349277
POST_CHANNEL_ID = 1281152286772695071
HORDENBUFF_CHANNEL_ID = 1510764309062615220
PANEM_HORDENBUFF_CHANNEL_ID = 1518153802983669810
LOG_ANALYSIS_CHANNEL_ID = 1279032487628242995

TICKER_CHANNEL_IDS = {
    TICKER_CHANNEL_ID,
    PANEM_TICKER_CHANNEL_ID
}

HORDENBUFF_CHANNEL_IDS = {
    HORDENBUFF_CHANNEL_ID,
    PANEM_HORDENBUFF_CHANNEL_ID
}

LOG_ANALYSIS_CHANNEL_IDS = {
    LOG_ANALYSIS_CHANNEL_ID,
    1509236359141785600,  # BWL Log Channel
    1509236588410834965,  # MC Log Channel
    1509235847109804082,  # Naxx Log Channel
    1509236271816511651   # AQ40 Log Channel
}
LOG_ANALYSIS_BOOTSTRAP_COUNT = int(os.getenv("LOG_ANALYSIS_BOOTSTRAP_COUNT", "10"))
LOG_ANALYSIS_HISTORY_LIMIT = int(os.getenv("LOG_ANALYSIS_HISTORY_LIMIT", "300"))

# LichtLoot / Prio-Check AQ40
AQ40_CHANNEL_ID = 1439219220528500806
# Message-IDs werden automatisch gesucht, weil jede neue RaidHelper-Anmeldung eine neue ID bekommt.
AQ40_RAID_HELPER_MESSAGE_ID = None
PRIO_REPORT_HOUR = 19
PRIO_REPORT_MINUTE = 0
PRIO_REPORT_FILE = "prio_report_state.json"

LICHTLOOT_RAILWAY_API_URL = os.getenv(
    "LICHTLOOT_RAILWAY_API_URL",
    "https://lichtloot-production.up.railway.app/api/apps-script"
)
LICHTLOOT_API_URL = os.getenv("LICHTLOOT_API_URL", LICHTLOOT_RAILWAY_API_URL)
LICHTLOOT_APPS_SCRIPT_URL = os.getenv(
    "LICHTLOOT_APPS_SCRIPT_URL",
    "https://script.google.com/macros/s/AKfycbzwRZ1908IawmEh3WdROu_TBwfu8Yr1YXJ1VicqEIf15eZ2zzRE3Yw9OaaeJ0ZADbye2g/exec"
)
WORLDBUFF_GUIDE_IMAGE_URL = os.getenv(
    "WORLDBUFF_GUIDE_IMAGE_URL",
    "https://lichtloot.de/images/worldbuff-anleitung.jpg"
)
HORDENBUFF_GUIDE_IMAGE_URL = os.getenv(
    "HORDENBUFF_GUIDE_IMAGE_URL",
    "https://lichtloot.de/images/Hordenbuff.jpg"
)
LICHTLOOT_GUILD_SLUG = os.getenv("LICHTLOOT_GUILD_SLUG", "lichtloot")
PANEM_GUILD_SLUG = os.getenv("PANEM_GUILD_SLUG", "panemloot")
WORLDBUFF_GUILD_SLUGS = [
    LICHTLOOT_GUILD_SLUG,
    PANEM_GUILD_SLUG
]

CHANNEL_GUILD_SLUGS = {
    PANEM_TICKER_CHANNEL_ID: PANEM_GUILD_SLUG,
    PANEM_HORDENBUFF_CHANNEL_ID: PANEM_GUILD_SLUG
}

# Direkter CSV-Export der internen Worldbuff-Uebersicht.
# Charakter/Gilde kommen aus diesem Sheet.
CSV_URL = "https://docs.google.com/spreadsheets/d/1eItzaMGhpJ28vv4sDA8wwmu0YhUxcbiz-2VLiCVyjv4/export?format=csv&gid=1498762908"
CSV_CACHE_CONTENT = ""
CSV_CACHE_TIME = None
CSV_CACHE_SECONDS = 300
WORLDBUFF_API_CACHE_ROWS = []
WORLDBUFF_API_CACHE_TIME = None
WORLDBUFF_API_CACHE_SECONDS = 60
HORDENBUFF_CSV_URL = "https://docs.google.com/spreadsheets/d/1eItzaMGhpJ28vv4sDA8wwmu0YhUxcbiz-2VLiCVyjv4/export?format=csv&gid=1246908857"
HORDENBUFF_CSV_CACHE_CONTENT = ""
HORDENBUFF_CSV_CACHE_TIME = None

# Das Worldbuffchannel-Sheet ist die Quelle fuer den tatsaechlichen Buff-Typ.
# Dadurch kann ein Lichtbringer-Termin nicht in der Uebersicht als Ony stehen,
# wenn im Worldbuffchannel fuer denselben Zeitpunkt Nef geplant ist.
WORLDBUFF_PLAN_CSV_URL = "https://docs.google.com/spreadsheets/d/1o7fzOAn9wC0iWcauC3bDo2RYR8kZ1xQMjkvSi1lJG8Q/gviz/tq?tqx=out:csv&gid=0"
WORLDBUFF_PLAN_CACHE_CONTENT = ""
WORLDBUFF_PLAN_CACHE_TIME = None
DATA_FILE = "worldbuffs.json"
DELETED_WORLDBUFF_FILE = "deleted_worldbuffs.json"
POST_FILE = "last_post.json"
HORDENBUFF_FILE = "hordenbuff.json"
HORDENBUFF_CLEANUP_FILE = "hordenbuff_cleanup.json"
RAID_ANNOUNCEMENT_FILE = "raid_announcements.json"
HORDENBUFF_CLEANUP_DELAY_MINUTES = 5
HORDENBUFF_CLEANUP_WINDOW_MINUTES = 45
HORDENBUFF_UPDATE_MIN_SECONDS = 30
DISCORD_RATE_LIMIT_FALLBACK_SECONDS = 300
RAID_ANNOUNCEMENT_CHECK_SECONDS = 60
LICHTLOOT_QUEUE_CHECK_SECONDS = 30
LICHTLOOT_URL = "https://lichtloot.de"
PUBLIC_API_CACHE_SECONDS = int(os.getenv("PUBLIC_API_CACHE_SECONDS", "45"))
PUBLIC_API_PORT = int(os.getenv("PORT") or os.getenv("PUBLIC_API_PORT", "8000"))

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

hordenbuff_update_lock = asyncio.Lock()
hordenbuff_last_update_at = 0
hordenbuff_rate_limited_until = 0
CURRENT_GUILD_SLUG = contextvars.ContextVar("CURRENT_GUILD_SLUG", default=LICHTLOOT_GUILD_SLUG)


def guild_slug_for_channel(channel_id):
    return CHANNEL_GUILD_SLUGS.get(int(channel_id), LICHTLOOT_GUILD_SLUG)


def current_guild_slug():
    return CURRENT_GUILD_SLUG.get()


def guild_scoped_file(filename):
    guild_slug = current_guild_slug()
    if guild_slug == LICHTLOOT_GUILD_SLUG:
        return filename
    return f"{guild_slug}_{filename}"


def hordenbuff_file():
    return guild_scoped_file(HORDENBUFF_FILE)


def hordenbuff_cleanup_file():
    return guild_scoped_file(HORDENBUFF_CLEANUP_FILE)


def worldbuff_file():
    return guild_scoped_file(DATA_FILE)


def deleted_worldbuff_file():
    return DELETED_WORLDBUFF_FILE


def worldbuff_post_file():
    return guild_scoped_file(POST_FILE)


def hordenbuff_channel_ids_for_current_guild():
    if current_guild_slug() == PANEM_GUILD_SLUG:
        return {PANEM_HORDENBUFF_CHANNEL_ID}
    return {HORDENBUFF_CHANNEL_ID}


def ticker_channel_ids_for_current_guild():
    if current_guild_slug() == PANEM_GUILD_SLUG:
        return {PANEM_TICKER_CHANNEL_ID}
    return {TICKER_CHANNEL_ID}


def can_post_worldbuff_overview():
    return current_guild_slug() == LICHTLOOT_GUILD_SLUG


def is_ticker_channel(channel_id):
    return int(channel_id) in TICKER_CHANNEL_IDS


def get_hordenbuff_message_id(data, channel_id):
    channel_key = str(channel_id)
    message_ids = data.get("message_ids_by_channel")

    if isinstance(message_ids, dict) and message_ids.get(channel_key):
        return message_ids.get(channel_key)

    if int(channel_id) == HORDENBUFF_CHANNEL_ID:
        return data.get("message_id")

    return None


def set_hordenbuff_message_id(data, channel_id, message_id):
    channel_key = str(channel_id)
    message_ids = data.setdefault("message_ids_by_channel", {})
    message_ids[channel_key] = message_id

    if int(channel_id) == HORDENBUFF_CHANNEL_ID:
        data["message_id"] = message_id


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


def is_open_worldbuff_status(status):
    clean = str(status or "").lower()
    clean = clean.replace("🟡", "").replace("🟢", "").replace("✅", "").strip()
    return clean in ["", "offen", "frei", "open"]


def get_open_worldbuff_signup_slots(limit=25):
    today = datetime.now(BERLIN_TZ).date()
    max_date = today + timedelta(days=92)
    slots = []
    seen = set()
    row_order = 0

    for row in iter_worldbuff_sheet_rows():
        buff = normalize_buff(row.get("buff", ""))
        if buff not in ["Nef", "Ony", "Hakkar"]:
            continue
        if row.get("charakter"):
            continue
        if not is_open_worldbuff_status(row.get("status")):
            continue
        if not is_lichtbringer(row.get("gilde", "")):
            continue

        try:
            slot_date = datetime.strptime(row.get("datum", ""), "%d.%m.%Y").date()
        except:
            continue

        if slot_date < today or slot_date > max_date:
            continue

        choice_buffs = [buff]
        if buff == "Ony":
            choice_buffs.append("Nef")
        elif buff == "Nef":
            choice_buffs.append("Ony")

        for choice_index, choice_buff in enumerate(choice_buffs):
            key = "|".join([choice_buff, row.get("datum", ""), row.get("uhrzeit", ""), row.get("gilde", "")])
            if key in seen:
                continue
            seen.add(key)

            slots.append({
                "buff": choice_buff,
                "original_buff": buff,
                "datum": row.get("datum", ""),
                "tag": row.get("tag", ""),
                "uhrzeit": row.get("uhrzeit", ""),
                "gilde": row.get("gilde", ""),
                "sort_date": slot_date,
                "row_order": row_order,
                "choice_order": choice_index
            })

        row_order += 1

    slots.sort(key=lambda row: (row["sort_date"], row.get("uhrzeit", ""), row.get("row_order", 0), row.get("choice_order", 0)))
    return slots[:limit]


def claim_worldbuff_slot_in_sheet(slot, charakter, discord_name):
    payload = {
        "action": "lichtbotClaimWorldbuffSlot",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "buff": slot.get("buff", ""),
        "datum": slot.get("datum", ""),
        "uhrzeit": slot.get("uhrzeit", ""),
        "gilde": slot.get("gilde", ""),
        "charakter": charakter,
        "discord": discord_name,
        "status": "bestätigt"
    }

    result = lichtloot_apps_script_post(payload)
    clear_worldbuff_csv_cache()
    return result


async def worldbuff_signup_core(slot, charakter, discord_name):
    charakter = str(charakter or "").strip()
    if not slot:
        return "⚠️ Dieser Worldbuff-Termin wurde nicht gefunden."
    if not charakter:
        return "Bitte trage einen Charakternamen ein."

    result = await asyncio.to_thread(claim_worldbuff_slot_in_sheet, slot, charakter, discord_name)

    if not result or not result.get("success"):
        reason = result.get("error") or result.get("message") if isinstance(result, dict) else "unbekannt"
        return f"⚠️ Worldbuff-Termin konnte nicht eingetragen werden. Grund: {reason}"

    await update_worldbuff_post()
    return (
        f"✅ **{charakter}** wurde für **{result.get('buff', slot.get('buff'))}** eingetragen: "
        f"{result.get('datum', slot.get('datum'))} um {result.get('uhrzeit', slot.get('uhrzeit'))}."
    )


def infer_worldbuff_char_from_discord_name(display_name):
    name = str(display_name or "").strip()
    if not name:
        return ""

    for separator in [" / ", "/", "|", " - "]:
        if separator in name:
            name = name.split(separator)[-1].strip()
            break

    name = re.sub(r"\([^)]*\)", "", name).strip()
    return name[:50]


class WorldbuffSignupModal(discord.ui.Modal):
    def __init__(self, slot, default_char=""):
        self.slot = slot
        title = f"{slot.get('buff', 'Worldbuff')} eintragen"
        super().__init__(title=title[:45])
        self.charakter = discord.ui.TextInput(
            label="Charaktername",
            placeholder="z. B. Juksi",
            default=str(default_char or "")[:50],
            required=True,
            max_length=50
        )
        self.add_item(self.charakter)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        result_text = await worldbuff_signup_core(
            self.slot,
            str(self.charakter.value or ""),
            interaction.user.display_name
        )
        await interaction.followup.send(result_text, ephemeral=True)


class WorldbuffSignupSelect(discord.ui.Select):
    def __init__(self, slots):
        self.slots = slots
        options = []
        for index, slot in enumerate(slots):
            label = f"{slot.get('buff')} · {slot.get('datum')} {slot.get('uhrzeit')}"
            description = str(slot.get("gilde") or "Lichtbringer")[:100]
            options.append(discord.SelectOption(
                label=label[:100],
                description=description,
                value=str(index),
                emoji=BUFF_EMOJIS.get(slot.get("buff"), "⚪")
            ))
        super().__init__(
            placeholder="Nef, Ony oder Hakkar-Termin auswählen",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction):
        index = int(self.values[0])
        slot = self.slots[index]
        charakter = infer_worldbuff_char_from_discord_name(interaction.user.display_name)
        await interaction.response.send_modal(WorldbuffSignupModal(slot, charakter))


class WorldbuffSignupView(discord.ui.View):
    def __init__(self, slots):
        super().__init__(timeout=180)
        if slots:
            self.add_item(WorldbuffSignupSelect(slots))


async def hordenbuff_signup_core(ally_char="", horde_char="", author_name=""):
    rend = await asyncio.to_thread(get_next_horden_rend_safe)

    if not rend:
        return "⚠️ Es wurde kein kommender Rend-Termin gefunden."

    ally_char = str(ally_char or "").strip()
    horde_char = str(horde_char or "").strip()

    if not ally_char and not horde_char:
        return "Bitte trage mindestens einen Namen ein: Ally-Char oder Horden-Char."

    data = await asyncio.to_thread(merge_hordenbuff_sheet_data, rend, load_hordenbuff_state(rend))
    data.setdefault("spieler", [])
    data.setdefault("uebernahmen", {})
    data.setdefault("helfer", [])

    if ally_char and ally_char not in data["spieler"]:
        data["spieler"].append(ally_char)

    if horde_char and horde_char not in data["helfer"]:
        data["helfer"].append(horde_char)

    if ally_char and horde_char:
        alte_helfer = [
            helper
            for helper, target
            in data["uebernahmen"].items()
            if target.lower() == ally_char.lower()
        ]

        for helper in alte_helfer:
            del data["uebernahmen"][helper]

        data["uebernahmen"][horde_char] = ally_char
        status = "zugeteilt"
        note = "Benötigt Buff für aktiven Termin; Helfer zugeteilt"
        sheet_char = ally_char
        result_text = f"✅ **{ally_char}** ist eingetragen. **{horde_char}** übernimmt."
    elif ally_char:
        status = "offen"
        note = "Benötigt Buff für aktiven Termin; Helfer offen"
        sheet_char = ally_char
        result_text = f"✅ **{ally_char}** ist für Rend angemeldet."
    else:
        ziel = get_next_unassigned_char(data)
        if ziel:
            data["uebernahmen"][horde_char] = ziel
            status = "zugeteilt"
            note = "Benötigt Buff für aktiven Termin; Helfer zugeteilt"
            sheet_char = ziel
            result_text = f"✅ **{horde_char}** hilft und übernimmt **{ziel}**."
        else:
            status = "offen"
            note = "Helfer bereit; noch kein Ally-Char offen"
            sheet_char = ""
            result_text = f"✅ **{horde_char}** ist als Horden-Helfer eingetragen."

    save_json(hordenbuff_file(), data)

    save_result = await asyncio.to_thread(
        hordenbuff_sheet_set,
        rend,
        sheet_char,
        horde_char,
        status,
        note
    )

    if not save_result or not save_result.get("success"):
        return (
            "⚠️ Anmeldung konnte nicht in Railway gespeichert werden. "
            f"Grund: {save_result.get('error', 'unbekannt') if isinstance(save_result, dict) else 'unbekannt'}"
        )

    await update_hordenbuff_post(force=True)
    return result_text


class RendSignupModal(discord.ui.Modal, title="Rend anmelden"):
    ally_char = discord.ui.TextInput(
        label="Ally-Char",
        placeholder="z. B. Ariee",
        required=False,
        max_length=50
    )
    horde_char = discord.ui.TextInput(
        label="Horden-Char / Helfer",
        placeholder="z. B. Miimi",
        required=False,
        max_length=50
    )

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        result_text = await hordenbuff_signup_core(
            ally_char=str(self.ally_char.value or ""),
            horde_char=str(self.horde_char.value or ""),
            author_name=interaction.user.display_name
        )
        await interaction.followup.send(result_text, ephemeral=True)


class RendSignupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Rend-Anmeldung öffnen", style=discord.ButtonStyle.success)
    async def open_signup(self, interaction, button):
        await interaction.response.send_modal(RendSignupModal())


def get_discord_retry_after(error, fallback=DISCORD_RATE_LIMIT_FALLBACK_SECONDS):
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}

    for header in ("Retry-After", "X-RateLimit-Reset-After"):
        value = headers.get(header)
        if value:
            try:
                return max(float(value), 1)
            except (TypeError, ValueError):
                pass

    return fallback


def is_discord_rate_limit(error):
    return isinstance(error, discord.HTTPException) and getattr(error, "status", None) == 429


def block_discord_writes_after_rate_limit(error, context):
    global hordenbuff_rate_limited_until

    retry_after = get_discord_retry_after(error)
    hordenbuff_rate_limited_until = time.monotonic() + retry_after
    print(
        f"{context}: Discord Rate Limit. "
        f"Keine Hordenbuff-Updates fuer {int(retry_after)} Sekunden."
    )


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


def make_buff_slot_key(buff_data):
    datum = buff_data["datum"]
    zeit = buff_data["uhrzeit"]
    gilde = normalize_guild_for_overview(buff_data.get("gilde", ""))

    if gilde == "LICHTBRINGER":
        return f"{datum}|{zeit}|LICHTBRINGER"

    return f"{datum}|{zeit}|{gilde}"


def load_deleted_worldbuff_keys():
    data = load_json(deleted_worldbuff_file(), {})
    if isinstance(data, list):
        return {str(key): "" for key in data}
    if isinstance(data, dict):
        return {str(key): str(value or "") for key, value in data.items()}
    return {}


def save_deleted_worldbuff_keys(keys):
    save_json(deleted_worldbuff_file(), keys or {})


def is_deleted_worldbuff(buff_data):
    try:
        return make_buff_key(buff_data) in load_deleted_worldbuff_keys()
    except Exception:
        return False


def remember_deleted_worldbuff(term):
    if not term:
        return ""

    try:
        key = make_buff_key(term)
    except Exception:
        return ""

    keys = load_deleted_worldbuff_keys()
    keys[key] = datetime.now(BERLIN_TZ).isoformat()
    save_deleted_worldbuff_keys(keys)
    return key


def remove_deleted_worldbuff_from_all_caches(term):
    deleted_key = remember_deleted_worldbuff(term)
    if not deleted_key:
        return 0

    removed = 0
    for guild_slug in WORLDBUFF_GUILD_SLUGS:
        token = CURRENT_GUILD_SLUG.set(guild_slug)
        try:
            data = load_json(worldbuff_file(), [])
            kept = []
            for entry in data:
                try:
                    if make_buff_key(entry) == deleted_key:
                        removed += 1
                        continue
                except Exception:
                    pass
                kept.append(entry)
            if len(kept) != len(data):
                save_json(worldbuff_file(), kept)
                sync_worldbuff_ticker_cache_to_sheet(kept)
        finally:
            CURRENT_GUILD_SLUG.reset(token)

    return removed


def normalize_guild_for_overview(gilde):
    value = str(gilde or "").strip()
    lower = value.lower()

    if is_lichtbringer(value):
        return "LICHTBRINGER"
    if "horde" in lower:
        return "HORDE"

    return value


def make_overview_dedupe_key(buff_data):
    datum = buff_data.get("datum", "")
    zeit = buff_data.get("uhrzeit", "")
    buff = normalize_buff(buff_data.get("buff", ""))
    gilde = normalize_guild_for_overview(buff_data.get("gilde", ""))

    if buff == "Rend":
        return f"{datum}|{zeit}|{buff}"

    return f"{datum}|{zeit}|{buff}|{gilde}"


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


def get_worldbuff_plan_csv_content():
    global WORLDBUFF_PLAN_CACHE_CONTENT, WORLDBUFF_PLAN_CACHE_TIME

    now = datetime.now()

    if WORLDBUFF_PLAN_CACHE_CONTENT and WORLDBUFF_PLAN_CACHE_TIME:
        if (now - WORLDBUFF_PLAN_CACHE_TIME).total_seconds() < CSV_CACHE_SECONDS:
            return WORLDBUFF_PLAN_CACHE_CONTENT

    try:
        with urllib.request.urlopen(WORLDBUFF_PLAN_CSV_URL, timeout=5) as response:
            WORLDBUFF_PLAN_CACHE_CONTENT = response.read().decode("utf-8")
            WORLDBUFF_PLAN_CACHE_TIME = now
            return WORLDBUFF_PLAN_CACHE_CONTENT
    except Exception as e:
        print("Worldbuffchannel-CSV Fehler:", e)

        if WORLDBUFF_PLAN_CACHE_CONTENT:
            print("Nutze alten Worldbuffchannel CSV Cache")
            return WORLDBUFF_PLAN_CACHE_CONTENT

        return ""


def get_worldbuff_plan_overrides():
    content = get_worldbuff_plan_csv_content()
    overrides = {}

    if not content:
        return overrides

    try:
        reader = csv.reader(StringIO(content))

        for row in reader:
            if len(row) < 3:
                continue

            datum = normalize_sheet_date(row[0])
            buff = normalize_buff(row[1])
            uhrzeit = normalize_sheet_time(row[2])

            if not datum or not uhrzeit:
                continue

            if buff not in ["Hakkar", "Ony", "Nef", "Rend"]:
                continue

            overrides[f"{datum}|{uhrzeit}"] = buff
    except Exception as e:
        print("Fehler beim Lesen des Worldbuffchannel-Sheets:", e)

    return overrides


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
    plan_overrides = get_worldbuff_plan_overrides()

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

            if is_lichtbringer(gilde) and not charakter:
                buff = plan_overrides.get(f"{datum}|{uhrzeit}", buff)

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


def get_worldbuff_rows_from_apps_script(days=14):
    global WORLDBUFF_API_CACHE_ROWS, WORLDBUFF_API_CACHE_TIME

    now = datetime.now()
    if WORLDBUFF_API_CACHE_ROWS and WORLDBUFF_API_CACHE_TIME:
        if (now - WORLDBUFF_API_CACHE_TIME).total_seconds() < WORLDBUFF_API_CACHE_SECONDS:
            return list(WORLDBUFF_API_CACHE_ROWS)

    try:
        result = lichtloot_apps_script_get({
            "action": "getPublicWorldbuffs",
            "days": days,
            "t": int(time.time())
        })
        raw_rows = result.get("buffs") or result.get("entries") or []
        rows = []

        for row in raw_rows:
            if not isinstance(row, dict):
                continue

            datum = normalize_sheet_date(row.get("datum") or row.get("date") or "")
            uhrzeit = normalize_sheet_time(row.get("uhrzeit") or row.get("time") or "")
            buff = normalize_buff(row.get("buff") or row.get("name") or row.get("type") or "")
            gilde = clean_sheet_value(row.get("gilde") or row.get("guild") or row.get("fraktion") or "")

            if buff not in ["Hakkar", "Ony", "Nef", "Rend"]:
                continue
            if not datum or not uhrzeit or not gilde:
                continue

            rows.append({
                "buff": buff,
                "datum": datum,
                "tag": clean_sheet_value(row.get("tag") or "") or make_tag_from_date(datum),
                "uhrzeit": uhrzeit,
                "gilde": gilde,
                "charakter": clean_sheet_value(row.get("charakter") or row.get("caster") or row.get("werfer") or ""),
                "status": clean_sheet_value(row.get("status") or "")
            })

        WORLDBUFF_API_CACHE_ROWS = rows
        WORLDBUFF_API_CACHE_TIME = now
        print(f"Apps-Script-Worldbuffs: {len(rows)} Buff-Zeilen gelesen.")
        return list(rows)
    except Exception as e:
        print("Apps-Script-Worldbuffs Fehler:", e)
        return []


def get_active_horden_rend_from_state():
    data = load_json(hordenbuff_file(), {})
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

    buff_words = r"(Hakkar|hakkar|ZG|zg|Ony|ony|Onyxia|Nef|nef|Nefarian|Rend|rend)"
    date_words = r"(\d{1,2}\.\d{1,2}\.\d{4})"
    day_words = r"(?:Mo|Di|Mi|Do|Fr|Sa|So|Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)"
    time_words = r"(\d{1,2}:\d{2})"
    prefix = r"^(?:[🟢🔴🟠⚪🟡✅❌🔥🌿☠️💀•\-–—]\s*)?"
    suffix = r"\s+(.+)$"

    patterns = [
        re.compile(prefix + r"\**" + buff_words + r"\**\s+" + date_words + r"\s+(?:" + day_words + r")\s+" + time_words + suffix, re.IGNORECASE),
        re.compile(prefix + date_words + r"\s+(?:" + day_words + r")\s+" + time_words + r"\s+\**" + buff_words + r"\**" + suffix, re.IGNORECASE),
        re.compile(prefix + r"\**" + buff_words + r"\**\s+" + date_words + r"\s+" + time_words + suffix, re.IGNORECASE),
        re.compile(prefix + date_words + r"\s+" + time_words + r"\s+\**" + buff_words + r"\**" + suffix, re.IGNORECASE),
    ]

    for line in text.splitlines():
        line = line.strip()
        line = line.replace("**", "")

        match = None
        matched_pattern_index = -1
        for index, pattern in enumerate(patterns):
            match = pattern.match(line)
            if match:
                matched_pattern_index = index
                break

        if match:
            groups = match.groups()
            if matched_pattern_index in [0, 2]:
                buff, datum, uhrzeit, gilde = groups
            else:
                datum, uhrzeit, buff, gilde = groups
            buffs.append({
                "buff": normalize_buff(buff),
                "datum": datum,
                "tag": make_tag_from_date(datum),
                "uhrzeit": uhrzeit,
                "gilde": gilde.strip()
            })

    return buffs


def import_buffs_aus_sheet():
    rows = get_worldbuff_rows_from_apps_script(days=14)
    source = "Apps Script"

    if not rows:
        rows = iter_worldbuff_sheet_rows()
        source = "CSV"

    sheet_buffs = []

    for row in rows:
        sheet_buffs.append({
            "buff": row.get("buff", ""),
            "datum": row.get("datum", ""),
            "tag": row.get("tag", ""),
            "uhrzeit": row.get("uhrzeit", ""),
            "gilde": row.get("gilde", ""),
            "charakter": row.get("charakter", ""),
            "status": row.get("status", "")
        })

    if not sheet_buffs:
        print("Worldbuff-Sheet geladen, aber keine gueltigen Buff-Zeilen gefunden. Pruefe Apps Script, CSV_URL und Kopfzeile.")
    else:
        print(f"Worldbuff-Sheet via {source}: {len(sheet_buffs)} Buff-Zeilen gelesen.")

    return sheet_buffs


def import_werfer_aus_sheet():
    werfer = {}
    rows = get_worldbuff_rows_from_apps_script(days=14) or iter_worldbuff_sheet_rows()

    for row in rows:
        datum = row.get("datum", "")
        uhrzeit = row.get("uhrzeit", "")
        buff = normalize_buff(row.get("buff", ""))
        gilde = row.get("gilde", "")
        charakter = row.get("charakter", "")
        status = row.get("status", "")

        if not datum or not uhrzeit or not buff or not gilde or not charakter:
            continue

        key = make_buff_key({
            "datum": datum,
            "uhrzeit": uhrzeit,
            "buff": buff,
            "gilde": gilde
        })
        werfer[key] = {
            "charakter": charakter,
            "status": status
        }

    return werfer


def sende_wurf_ans_sheet(buff, charakter, discord_name):
    payload = {
        "action": "lichtbotSetWorldbuffCaster",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "buff": buff,
        "charakter": charakter,
        "discord": discord_name,
        "status": "bestätigt"
    }

    result = lichtloot_apps_script_post(payload)
    clear_worldbuff_csv_cache()
    return result


def sync_worldbuff_ticker_cache_to_sheet(data=None):
    if not LICHTBOT_QUEUE_TOKEN:
        print("Worldbuffticker-Sync uebersprungen: LICHTBOT_QUEUE_TOKEN fehlt.")
        return {"success": False, "error": "LICHTBOT_QUEUE_TOKEN fehlt."}

    raw_buffs = data if data is not None else load_json(worldbuff_file(), [])
    buffs = [buff for buff in raw_buffs if not is_deleted_worldbuff(buff)]
    payload = {
        "action": "lichtbotSyncWorldbuffTicker",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "buffs": json.dumps(buffs, ensure_ascii=False)
    }

    try:
        result = lichtloot_apps_script_post(payload)
        print(f"Worldbuffticker-Sync: {result}")
        return result
    except Exception as e:
        print(f"Worldbuffticker-Sync Fehler: {e}")
        return {"success": False, "error": str(e)}


def clear_worldbuff_csv_cache():
    global CSV_CACHE_CONTENT, CSV_CACHE_TIME, WORLDBUFF_PLAN_CACHE_CONTENT, WORLDBUFF_PLAN_CACHE_TIME

    CSV_CACHE_CONTENT = ""
    CSV_CACHE_TIME = None
    WORLDBUFF_PLAN_CACHE_CONTENT = ""
    WORLDBUFF_PLAN_CACHE_TIME = None


def clear_hordenbuff_csv_cache():
    global HORDENBUFF_CSV_CACHE_CONTENT, HORDENBUFF_CSV_CACHE_TIME

    HORDENBUFF_CSV_CACHE_CONTENT = ""
    HORDENBUFF_CSV_CACHE_TIME = None


def merge_buffs_into_data(data, new_buffs):
    existing_keys = {
        make_buff_key(b)
        for b in data
    }

    added = 0

    for buff in new_buffs:
        key = make_buff_key(buff)

        if key not in existing_keys:
            data.append(buff)
            existing_keys.add(key)
            added += 1

    return added


def build_overview():
    sheet_buffs = import_buffs_aus_sheet()
    data = list(sheet_buffs)

    werfer = import_werfer_aus_sheet()

    if not data:
        return "📢 **Worldbuff Übersicht**\n\nKeine Worldbuffs gefunden."

    heute = datetime.now(BERLIN_TZ).date()
    ende = heute + timedelta(days=7)

    gefiltert = []
    heutige_buffs = 0

    for b in data:
        try:
            buff_datum = datetime.strptime(b["datum"], "%d.%m.%Y").date()

            if heute <= buff_datum <= ende:
                gefiltert.append(b)
                if buff_datum == heute:
                    heutige_buffs += 1

        except:
            continue

    print(
        "Worldbuff-Uebersicht Zeitraum: "
        f"{heute.strftime('%d.%m.%Y')} bis {ende.strftime('%d.%m.%Y')} "
        f"- {len(gefiltert)} Termine, davon heute {heutige_buffs}."
    )

    data = gefiltert

    if not data:
        return "📢 **Worldbuff Übersicht**\n\nKeine kommenden Worldbuffs in den nächsten 7 Tagen gefunden."

    deduped = {}

    for b in data:
        key = make_overview_dedupe_key(b)
        current = deduped.get(key)
        info = werfer.get(make_buff_key(b))
        current_info = werfer.get(make_buff_key(current)) if current else None

        if not current:
            deduped[key] = b
            continue

        if info and info.get("charakter") and not (current_info and current_info.get("charakter")):
            deduped[key] = b
            continue

        if "worldbuff" in str(current.get("gilde", "")).lower() and "worldbuff" not in str(b.get("gilde", "")).lower():
            deduped[key] = b

    data = list(deduped.values())

    data.sort(
        key=lambda x: (
            datetime.strptime(x["datum"], "%d.%m.%Y"),
            x["uhrzeit"]
        )
    )

    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")

    text = "📢 **Worldbuffs**"
    text += f" · Stand {now}\n"
    text += "_Nächste 7 Tage · Eintragen per `!worldbuff`_\n"

    current_date = ""

    for b in data:
        datum = b["datum"]
        tag_kurz = b.get("tag") or make_tag_from_date(datum)
        tag_lang = TAG_LANG.get(tag_kurz, tag_kurz)
        zeit = b["uhrzeit"]
        buff = normalize_buff(b["buff"])
        gilde = b["gilde"]

        emoji = BUFF_EMOJIS.get(buff, "⚪")

        if datum != current_date:
            text += f"\n**{tag_lang}, {datum}**\n"
            current_date = datum

        werfer_text = ""

        key = make_buff_key(b)
        info = werfer.get(key)
        charakter = b.get("charakter") or (info and info.get("charakter")) or ""

        if charakter:
            if is_lichtbringer(gilde):
                werfer_text = f" - 🔵 {charakter}"
            else:
                werfer_text = f" - ⚔️ {charakter}"

        text += f"{emoji} **{buff}** {zeit} - {gilde}{werfer_text}\n"

    return text


def build_worldbuff_guide_embed():
    if not WORLDBUFF_GUIDE_IMAGE_URL:
        return None
    embed = discord.Embed(
        title="Worldbuff eintragen",
        description="Kurzanleitung für die Anmeldung per `!worldbuff`.",
        color=0x5865F2
    )
    embed.set_image(url=WORLDBUFF_GUIDE_IMAGE_URL)
    return embed


def build_hordenbuff_guide_embed():
    if not HORDENBUFF_GUIDE_IMAGE_URL:
        return None
    embed = discord.Embed(
        title="Hordenbuffs eintragen",
        description="Kurzanleitung für die Anmeldung per `!rend`.",
        color=0xED1C24
    )
    embed.set_image(url=HORDENBUFF_GUIDE_IMAGE_URL)
    return embed


async def delete_last_post(channel):
    post_data = load_json(worldbuff_post_file(), {})
    message_ids = post_data.get("message_ids")
    message_id = post_data.get("message_id")

    if not message_ids and message_id:
        message_ids = [message_id]

    if not message_ids:
        return

    for message_id in message_ids:
        try:
            old_message = await channel.fetch_message(message_id)
            await old_message.delete()
            await asyncio.sleep(0.4)
        except:
            pass


async def sync_recent_ticker_messages(limit=500):
    data = await asyncio.to_thread(load_json, worldbuff_file(), [])
    found_buffs = []

    for channel_id in ticker_channel_ids_for_current_guild():
        try:
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
        except Exception as e:
            print(f"Ticker-Channel {channel_id} konnte nicht geladen werden:", e)
            continue

        try:
            async for msg in channel.history(limit=limit):
                found_buffs.extend(parse_ticker_message(msg.content or ""))
        except Exception as e:
            print(f"Ticker-Historie {channel_id} konnte nicht gelesen werden:", e)
            continue

    found_buffs = [buff for buff in found_buffs if not is_deleted_worldbuff(buff)]

    if not found_buffs:
        return 0

    added = merge_buffs_into_data(data, found_buffs)

    if added:
        await asyncio.to_thread(save_json, worldbuff_file(), data)

    await asyncio.to_thread(sync_worldbuff_ticker_cache_to_sheet, data)

    print(f"Ticker-Historie geprüft: {len(found_buffs)} Buff-Zeilen gefunden, {added} neu gespeichert.")
    return added


async def update_worldbuff_post(sync_ticker=True):
    if not can_post_worldbuff_overview():
        print(f"Worldbuff-Uebersicht fuer {current_guild_slug()} uebersprungen: kein Zielchannel konfiguriert.")
        return

    channel = client.get_channel(POST_CHANNEL_ID)

    if channel is None:
        print("Ziel-Channel nicht gefunden.")
        return

    if sync_ticker:
        await sync_recent_ticker_messages()
    await delete_last_post(channel)

    text = await asyncio.to_thread(build_overview)
    guide_embed = build_worldbuff_guide_embed()

    if len(text) <= 1900:
        msg = await channel.send(text, embed=guide_embed)
        save_json(worldbuff_post_file(), {"message_id": msg.id, "message_ids": [msg.id]})
    else:
        chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
        last_msg = None
        message_ids = []

        for index, chunk in enumerate(chunks):
            last_msg = await channel.send(chunk, embed=guide_embed if index == 0 else None)
            message_ids.append(last_msg.id)

        if last_msg:
            save_json(worldbuff_post_file(), {"message_id": last_msg.id, "message_ids": message_ids})


async def sync_recent_ticker_messages_for_all_guilds(limit=500):
    total_added = 0

    for guild_slug in WORLDBUFF_GUILD_SLUGS:
        token = CURRENT_GUILD_SLUG.set(guild_slug)
        try:
            total_added += await sync_recent_ticker_messages(limit=limit)
        except Exception as e:
            print(f"Ticker-Sync fuer {guild_slug} fehlgeschlagen:", e)
        finally:
            CURRENT_GUILD_SLUG.reset(token)

    return total_added


async def update_worldbuff_overview_from_all_guilds():
    await sync_recent_ticker_messages_for_all_guilds()

    token = CURRENT_GUILD_SLUG.set(LICHTLOOT_GUILD_SLUG)
    try:
        await update_worldbuff_post(sync_ticker=False)
    finally:
        CURRENT_GUILD_SLUG.reset(token)


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
    cleanup_state = load_json(hordenbuff_cleanup_file(), {})
    event_key = make_hordenbuff_key(expired_rend)

    if cleanup_state.get("last_cleaned_event_key") == event_key:
        return

    for channel_id in hordenbuff_channel_ids_for_current_guild():
        try:
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
        except Exception as e:
            print(f"Hordenbuff-Channel {channel_id} konnte nicht bereinigt werden:", e)
            continue

        try:
            # Loescht die aktuellen Nachrichten im Hordenbuff-Channel.
            # Fuer sehr alte Nachrichten kann Discord bulk delete begrenzen; der Channel enthaelt aber normalerweise nur aktuelle Orga-Posts.
            await channel.purge(limit=500, check=lambda m: not m.pinned, bulk=True)
        except Exception as e:
            print(f"Fehler beim Bereinigen des Hordenbuff-Channels {channel_id}:", e)
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
                print(f"Fallback-Bereinigung {channel_id} fehlgeschlagen:", inner)

    cleanup_state["last_cleaned_event_key"] = event_key
    cleanup_state["last_cleaned_at"] = datetime.now(BERLIN_TZ).isoformat()
    save_json(hordenbuff_cleanup_file(), cleanup_state)

    # Alte Hordenbuff-Nachricht vergessen, damit fuer den naechsten Rend-Termin sicher ein frischer Post entsteht.
    save_json(hordenbuff_file(), {
        "event_key": "",
        "spieler": [],
        "uebernahmen": {},
        "helfer": [],
        "message_id": None,
        "message_ids_by_channel": {},
        "reminders_sent": []
    })

    await update_hordenbuff_post(force=True)


def load_hordenbuff_state(rend):
    fallback = {
        "event_key": "",
        "spieler": [],
        "uebernahmen": {},
        "helfer": [],
        "message_id": None,
        "reminders_sent": []
    }

    data = load_json(hordenbuff_file(), fallback)

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

        save_json(hordenbuff_file(), data)

    data.setdefault("spieler", [])
    data.setdefault("uebernahmen", {})
    data.setdefault("helfer", [])
    data.setdefault("reminders_sent", [])

    return data


def get_hordenbuff_csv_content():
    global HORDENBUFF_CSV_CACHE_CONTENT, HORDENBUFF_CSV_CACHE_TIME

    now = datetime.now()

    if HORDENBUFF_CSV_CACHE_CONTENT and HORDENBUFF_CSV_CACHE_TIME:
        if (now - HORDENBUFF_CSV_CACHE_TIME).total_seconds() < CSV_CACHE_SECONDS:
            return HORDENBUFF_CSV_CACHE_CONTENT

    try:
        with urllib.request.urlopen(HORDENBUFF_CSV_URL, timeout=5) as response:
            HORDENBUFF_CSV_CACHE_CONTENT = response.read().decode("utf-8")
            HORDENBUFF_CSV_CACHE_TIME = now
            return HORDENBUFF_CSV_CACHE_CONTENT
    except Exception as e:
        print("Hordenbuff-CSV Fehler:", e)

        if HORDENBUFF_CSV_CACHE_CONTENT:
            print("Nutze alten Hordenbuff CSV Cache")
            return HORDENBUFF_CSV_CACHE_CONTENT

        return ""


def iter_hordenbuff_sheet_rows():
    railway_rows = iter_hordenbuff_railway_rows()
    if railway_rows:
        return railway_rows

    content = get_hordenbuff_csv_content()
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

            if "tag" in normalized and "datum" in normalized and "uhrzeit" in normalized and "buff" in normalized:
                header_map = {key: idx for idx, key in enumerate(normalized) if key}
                continue

            if not header_map:
                continue

            tag_i = find_column_index(header_map, "Tag")
            datum_i = find_column_index(header_map, "Datum")
            uhrzeit_i = find_column_index(header_map, "Uhrzeit", "Zeit")
            buff_i = find_column_index(header_map, "Buff")
            gilde_i = find_column_index(header_map, "Gilde / Fraktion", "Gilde", "Fraktion")
            charakter_i = find_column_index(header_map, "Charakter", "Char", "Spieler")
            uebernehmer_i = find_column_index(header_map, "Übernehmer", "Uebernehmer", "Helfer", "Helper")
            status_i = find_column_index(header_map, "Status")
            notiz_i = find_column_index(header_map, "Notiz", "Note", "Hinweis")

            tag = get_cell(row, tag_i)
            datum = normalize_sheet_date(get_cell(row, datum_i))
            uhrzeit = normalize_sheet_time(get_cell(row, uhrzeit_i))
            buff = normalize_buff(get_cell(row, buff_i))
            gilde = get_cell(row, gilde_i)
            charakter = get_cell(row, charakter_i)
            uebernehmer = get_cell(row, uebernehmer_i)
            status = get_cell(row, status_i)
            notiz = get_cell(row, notiz_i)

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

            if normalize_sheet_header(str(tag)) in ["uebernahmenhelfer", "befehle", "quelle"]:
                break

            if buff != "Rend":
                continue

            if not datum or not uhrzeit:
                continue

            result.append({
                "buff": buff,
                "datum": datum,
                "tag": tag,
                "uhrzeit": uhrzeit,
                "gilde": gilde or "Horde",
                "charakter": charakter,
                "uebernehmer": uebernehmer,
                "status": status,
                "notiz": notiz
            })

    except Exception as e:
        print("Fehler beim Lesen des Hordenbuff-Sheets:", e)

    return result


def iter_hordenbuff_railway_rows():
    try:
        result = railway_get({
            "action": "getPublicHordenbuffs",
            "days": 60,
            "t": int(time.time())
        })
        if not result.get("success"):
            return []

        rows = []
        for entry in result.get("buffs", []):
            rows.append({
                "buff": normalize_buff(entry.get("buff", "Rend")),
                "datum": normalize_sheet_date(entry.get("datum", "")),
                "tag": entry.get("tag", "") or make_tag_from_date(entry.get("datum", "")),
                "uhrzeit": normalize_sheet_time(entry.get("uhrzeit", "")),
                "gilde": entry.get("gilde", "Horde") or "Horde",
                "charakter": entry.get("charakter", ""),
                "uebernehmer": entry.get("uebernehmer", ""),
                "status": entry.get("status", ""),
                "notiz": entry.get("note", "") or entry.get("notiz", "")
            })
        return rows
    except Exception as e:
        print("Railway-Hordenbuff Fehler:", e)
        return []


def merge_hordenbuff_sheet_data(rend, data):
    if not rend:
        return data

    rows = iter_hordenbuff_sheet_rows()
    target_date = rend.get("datum", "")
    target_time = rend.get("uhrzeit", "")

    synced = {
        "event_key": data.get("event_key", make_hordenbuff_key(rend)),
        "spieler": [],
        "uebernahmen": {},
        "helfer": [],
        "message_id": data.get("message_id"),
        "message_ids_by_channel": data.get("message_ids_by_channel", {}),
        "reminders_sent": data.get("reminders_sent", [])
    }

    for row in rows:
        if row.get("datum") != target_date or row.get("uhrzeit") != target_time:
            continue

        charakter = str(row.get("charakter") or "").strip()
        uebernehmer = str(row.get("uebernehmer") or "").strip()
        status = normalize_sheet_header(str(row.get("status") or ""))

        if status in {"erledigt", "done", "abgeschlossen", "fertig"}:
            continue

        if charakter and charakter != "-":
            if charakter not in synced["spieler"]:
                synced["spieler"].append(charakter)

        if uebernehmer and uebernehmer != "-":
            if uebernehmer not in synced["helfer"]:
                synced["helfer"].append(uebernehmer)
            if charakter and charakter != "-":
                synced["uebernahmen"][uebernehmer] = charakter

    return synced


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

    text += "✅ **Einfach anmelden:**\n"
    text += "`!rend`\n"
    text += "Dann Button klicken und im Formular eintragen:\n"
    text += "- Ally-Char = braucht Rend\n"
    text += "- Horden-Char = kann helfen\n"
    text += "- Beide Felder = Horden-Char übernimmt Ally-Char\n\n"

    text += "🗑️ **Eintrag löschen:**\n"
    text += "`!renddel Spielername`\n"
    text += "Beispiel: `!renddel Ariee`\n\n"

    text += "🔄 **Liste aktualisieren:**\n"
    text += "`!hordenbuff`\n"

    return text


async def update_hordenbuff_post(force=False):
    global hordenbuff_last_update_at

    now = time.monotonic()
    if now < hordenbuff_rate_limited_until:
        rest = int(hordenbuff_rate_limited_until - now)
        print(f"Hordenbuff-Update uebersprungen: Discord Rate Limit noch {rest} Sekunden aktiv.")
        return

    async with hordenbuff_update_lock:
        now = time.monotonic()
        if now < hordenbuff_rate_limited_until:
            rest = int(hordenbuff_rate_limited_until - now)
            print(f"Hordenbuff-Update uebersprungen: Discord Rate Limit noch {rest} Sekunden aktiv.")
            return

        if not force and now - hordenbuff_last_update_at < HORDENBUFF_UPDATE_MIN_SECONDS:
            print("Hordenbuff-Update uebersprungen: Aktualisierung wurde gerade erst ausgefuehrt.")
            return

        hordenbuff_last_update_at = now

        rend = await asyncio.to_thread(get_next_horden_rend_safe)

        for channel_id in hordenbuff_channel_ids_for_current_guild():
            channel = client.get_channel(channel_id)

            if channel is None:
                try:
                    channel = await client.fetch_channel(channel_id)
                except Exception as e:
                    print(f"Hordenbuff-Channel {channel_id} nicht gefunden:", e)
                    continue

            if not rend:
                try:
                    await channel.send(
                        "⚠️ Es wurde kein kommender Rend-Termin im Sheet gefunden.",
                        delete_after=15
                    )
                except discord.HTTPException as e:
                    if is_discord_rate_limit(e):
                        block_discord_writes_after_rate_limit(e, "Hordenbuff ohne Rend")
                    else:
                        print(f"Hordenbuff ohne Rend konnte nicht gesendet werden: {e}")
                continue

            data = await asyncio.to_thread(merge_hordenbuff_sheet_data, rend, load_hordenbuff_state(rend))
            text = build_hordenbuff_text(rend, data)
            guide_embed = build_hordenbuff_guide_embed()
            message_id = get_hordenbuff_message_id(data, channel_id)

            try:
                if message_id:
                    try:
                        msg = await channel.fetch_message(message_id)
                    except discord.NotFound:
                        msg = await channel.send(text, embed=guide_embed)
                        set_hordenbuff_message_id(data, channel_id, msg.id)
                        save_json(hordenbuff_file(), data)
                        continue

                    await msg.edit(content=text, embed=guide_embed)
                    save_json(hordenbuff_file(), data)
                else:
                    msg = await channel.send(text, embed=guide_embed)
                    set_hordenbuff_message_id(data, channel_id, msg.id)
                    save_json(hordenbuff_file(), data)

            except discord.HTTPException as e:
                if is_discord_rate_limit(e):
                    block_discord_writes_after_rate_limit(e, "Hordenbuff-Update")
                    return

                print(f"Hordenbuff-Update Discord-Fehler in {channel_id}: {e}")

            except Exception as e:
                print(f"Hordenbuff-Update Fehler in {channel_id}: {e}")


async def add_rend_spieler(message, charakter):
    rend = await asyncio.to_thread(get_next_horden_rend_safe)

    if not rend:
        await send_temp(
            message.channel,
            "⚠️ Es wurde kein kommender Rend-Termin im Sheet gefunden."
        )
        await delete_command_message(message)
        return

    data = await asyncio.to_thread(merge_hordenbuff_sheet_data, rend, load_hordenbuff_state(rend))

    if charakter not in data["spieler"]:
        data["spieler"].append(charakter)

    save_json(hordenbuff_file(), data)

    await asyncio.to_thread(
        hordenbuff_sheet_set,
        rend,
        charakter,
        "",
        "offen",
        "Benötigt Buff für aktiven Termin; Helfer offen"
    )

    await update_hordenbuff_post(force=True)
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

    data = await asyncio.to_thread(merge_hordenbuff_sheet_data, rend, load_hordenbuff_state(rend))
    data.setdefault("helfer", [])
    data.setdefault("uebernahmen", {})

    if helfer_name not in data["helfer"]:
        data["helfer"].append(helfer_name)

    if helfer_name in data.get("uebernahmen", {}):
        ziel = data["uebernahmen"][helfer_name]

        save_json(hordenbuff_file(), data)
        await send_temp(
            message.channel,
            f"ℹ️ {helfer_name} ist bereits für **{ziel}** eingeteilt."
        )

        await update_hordenbuff_post(force=True)
        await delete_command_message(message)
        return

    ziel = get_next_unassigned_char(data)

    if not ziel:
        save_json(hordenbuff_file(), data)
        await asyncio.to_thread(
            hordenbuff_sheet_set,
            rend,
            "",
            helfer_name,
            "offen",
            "Helfer bereit; noch kein Ally-Char offen"
        )
        await send_temp(
            message.channel,
            f"✅ {helfer_name} wurde als Helfer eingetragen. Aktuell ist noch kein freier Ally-Char offen."
        )

        await update_hordenbuff_post(force=True)
        await delete_command_message(message)
        return

    data["uebernahmen"][helfer_name] = ziel

    save_json(hordenbuff_file(), data)

    await asyncio.to_thread(
        hordenbuff_sheet_set,
        rend,
        ziel,
        helfer_name,
        "zugeteilt",
        "Benötigt Buff für aktiven Termin; Helfer zugeteilt"
    )

    await update_hordenbuff_post(force=True)
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

    data = await asyncio.to_thread(merge_hordenbuff_sheet_data, rend, load_hordenbuff_state(rend))

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

    save_json(hordenbuff_file(), data)

    await asyncio.to_thread(
        hordenbuff_sheet_set,
        rend,
        ziel,
        helfer_name,
        "zugeteilt",
        "Benötigt Buff für aktiven Termin; Helfer zugeteilt"
    )

    await update_hordenbuff_post(force=True)
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

    data = await asyncio.to_thread(merge_hordenbuff_sheet_data, rend, load_hordenbuff_state(rend))
    helfer_name = message.author.display_name

    data.setdefault("uebernahmen", {})
    data.setdefault("helfer", [])

    if helfer_name not in data["helfer"]:
        data["helfer"].append(helfer_name)

    data["uebernahmen"][helfer_name] = charakter

    save_json(hordenbuff_file(), data)

    await asyncio.to_thread(
        hordenbuff_sheet_set,
        rend,
        charakter,
        helfer_name,
        "zugeteilt",
        "Benötigt Buff für aktiven Termin; Helfer zugeteilt"
    )

    await update_hordenbuff_post(force=True)
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

    data = await asyncio.to_thread(merge_hordenbuff_sheet_data, rend, load_hordenbuff_state(rend))

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

    save_json(hordenbuff_file(), data)

    await asyncio.to_thread(hordenbuff_sheet_delete, rend, charakter)

    await update_hordenbuff_post(force=True)
    await delete_command_message(message)


async def process_hordenbuff_reminders_for_current_guild():
    # Nach Ablauf eines Rendbuffs wird der Hordenbuff-Channel automatisch bereinigt.
    # Beispiel: Rend 19:35 -> um 19:40 wird geloescht und der naechste Post erstellt.
    expired_rend = await asyncio.to_thread(get_recent_expired_horden_rend)
    if expired_rend:
        await clear_hordenbuff_channel_and_post_next(expired_rend)

    rend = await asyncio.to_thread(get_next_horden_rend_safe)

    if not rend:
        return

    channels = []

    for channel_id in hordenbuff_channel_ids_for_current_guild():
        channel = client.get_channel(channel_id)

        if channel is None:
            try:
                channel = await client.fetch_channel(channel_id)
            except Exception as e:
                print(f"Hordenbuff-Reminder-Channel {channel_id} nicht gefunden:", e)
                continue

        channels.append(channel)

    if not channels:
        return

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
            for channel in channels:
                await channel.send(reminder_text)

            data.setdefault("reminders_sent", [])
            data["reminders_sent"].append(str(minute))

            save_json(hordenbuff_file(), data)

            await update_hordenbuff_post(force=True)


async def hordenbuff_reminder_loop():
    await client.wait_until_ready()

    while not client.is_closed():
        for guild_slug in [LICHTLOOT_GUILD_SLUG, PANEM_GUILD_SLUG]:
            token = CURRENT_GUILD_SLUG.set(guild_slug)
            try:
                await process_hordenbuff_reminders_for_current_guild()
            except Exception as e:
                print(f"Fehler im Hordenbuff-Reminder fuer {guild_slug}:", e)
            finally:
                CURRENT_GUILD_SLUG.reset(token)

        await asyncio.sleep(60)



# =========================================================
# LICHTLOOT PRIO-CHECK / DISCORD-ABGLEICH ALLE RAIDS
# =========================================================

# Alle RaidHelper-Quellen für den Discord-Abgleich.
# ZG und AQ20 haben jeweils zwei RaidHelper-Posts.
DISCORD_RAIDHELPER_SOURCES = {
    # Keine festen Message-IDs: Der Bot sucht immer den neuesten passenden RaidHelper-Anmelder im jeweiligen Channel.
    "AQ40": [
        {"channel_id": AQ40_CHANNEL_ID}
    ],
    "MC": [
        {"channel_id": 1469393982688722979}
    ],
    "BWL": [
        {"channel_id": 1372324345459773595}
    ],
    "NAXX": [
        {"channel_id": 1349654882952417302}
    ],
    "ZG": [
        {"channel_id": 1510311947973951528},
        {"channel_id": 1512935197060890744}
    ],
    "AQ20": [
        {"channel_id": 1512935248931983450},
        {"channel_id": 1509919374360838154}
    ],
    "ONY": [
        {"channel_id": 1429084566634627215}
    ]
}

PRIO_CHECK_UPDATE_TASKS = {}
PRIO_SYNC_INTERVAL_SECONDS = 300


def get_primary_raid_channel_id(raid):
    raid = normalize_raid_name(raid)
    sources = DISCORD_RAIDHELPER_SOURCES.get(raid, [])
    if not sources:
        return None
    return sources[0].get("channel_id")


def normalize_raid_name(value):
    raid = str(value or "").strip().upper()
    aliases = {
        "ONYXIA": "ONY",
        "ONIXIA": "ONY",
        "NAXXRAMAS": "NAXX",
        "AQ": "AQ40"
    }
    return aliases.get(raid, raid)

def format_log_analysis_post_date(value):
    raw = str(value or "").strip()
    if not raw:
        return "-"
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d.%m.%Y")
        except Exception:
            pass
    return raw

def build_log_analysis_post_text(payload):
    analysis_type = str(payload.get("analysisType") or payload.get("type") or "log").upper()
    raid = normalize_raid_name(payload.get("raid") or "")
    raid_label = raid or "Raid"
    raid_date = format_log_analysis_post_date(payload.get("raidDate") or "")
    sheet_url = str(payload.get("sheetUrl") or "").strip()
    report_url = str(payload.get("reportUrl") or "").strip()
    report_code = str(payload.get("reportCode") or "").strip()

    lines = [
        f"📊 **{analysis_type}-Loganalyse fertig**",
        "",
        f"**Raid:** {raid_label}",
        f"**Datum:** {raid_date}"
    ]
    if report_code:
        lines.append(f"**Report:** `{report_code}`")
    lines.append("")
    lines.append(f"🔗 **{analysis_type} öffnen:** {sheet_url}")
    if report_url:
        lines.append(f"🧾 **Warcraft Logs:** {report_url}")
    return "\n".join(lines)

def build_log_analysis_post_embed(payload):
    analysis_type = str(payload.get("analysisType") or payload.get("type") or "log").upper()
    raid = normalize_raid_name(payload.get("raid") or "")
    raid_label = raid or "Raid"
    raid_date = format_log_analysis_post_date(payload.get("raidDate") or "")
    report_code = str(payload.get("reportCode") or "").strip()
    report_url = str(payload.get("reportUrl") or "").strip()

    color = 0x3B82F6 if analysis_type == "CLA" else 0x22C55E
    embed = discord.Embed(
        title=f"{analysis_type}-Loganalyse fertig",
        description="Die Auswertung ist bereit und kann über die Buttons geöffnet werden.",
        color=color
    )
    embed.add_field(name="Raid", value=raid_label, inline=True)
    embed.add_field(name="Datum", value=raid_date, inline=True)
    if report_code:
        embed.add_field(name="Report", value=f"`{report_code}`", inline=True)
    if report_url:
        embed.url = report_url
    embed.set_footer(text="LichtLoot · Warcraft Logs Auswertung")
    return embed

def build_log_analysis_post_view(payload):
    analysis_type = str(payload.get("analysisType") or payload.get("type") or "log").upper()
    sheet_url = str(payload.get("sheetUrl") or "").strip()
    report_url = str(payload.get("reportUrl") or "").strip()
    view = discord.ui.View(timeout=None)
    if sheet_url.startswith("http"):
        view.add_item(discord.ui.Button(label=f"{analysis_type} öffnen", style=discord.ButtonStyle.link, url=sheet_url))
    if report_url.startswith("http"):
        view.add_item(discord.ui.Button(label="Warcraft Logs", style=discord.ButtonStyle.link, url=report_url))
    return view

async def post_log_analysis_from_queue(payload):
    channel_id = str(payload.get("channelId") or "").strip()
    if not channel_id:
        print("Loganalyse-Post ohne ChannelId uebersprungen.")
        return

    raid = normalize_raid_name(payload.get("raid") or "")
    if raid not in {"MC", "BWL", "NAXX", "AQ40"}:
        print(f"Loganalyse-Post fuer {raid or 'unbekannt'} uebersprungen.")
        return

    sheet_url = str(payload.get("sheetUrl") or "").strip()
    if not sheet_url:
        print("Loganalyse-Post ohne Sheet-Link uebersprungen.")
        return

    channel = client.get_channel(int(channel_id))
    if channel is None:
        channel = await client.fetch_channel(int(channel_id))
    await channel.send(
        embed=build_log_analysis_post_embed(payload),
        view=build_log_analysis_post_view(payload)
    )
    print(f"Loganalyse gepostet: {payload.get('analysisType')} {raid} in {channel_id}")


def format_raid_announcement_date(value):
    raw = str(value or "").strip()
    if not raw:
        return "noch offen"

    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d.%m.%Y")
        except ValueError:
            pass

    return raw


def format_raid_announcement_time(value):
    raw = str(value or "").strip()
    if not raw:
        return "noch offen"
    match = re.search(r"(\d{1,2}):(\d{2})", raw)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)} Uhr"
    return raw


def build_raid_announcement_text(raid):
    raid_short = normalize_raid_name(raid.get("raid") or raid.get("raidName") or "")
    raid_name = str(raid.get("raidName") or raid_short or "Raid").strip()
    raid_date = format_raid_announcement_date(raid.get("raidDate"))
    raid_time = format_raid_announcement_time(raid.get("raidTime"))
    player_pin = str(raid.get("playerPin") or "").strip()
    created_by = str(
        raid.get("createdBy") or
        raid.get("erstelltVon") or
        raid.get("created_by") or
        "Unbekannt"
    ).strip()

    text = (
        f"📣 **Neuer Raid erstellt: {raid_name}**\n"
        f"🗓️ **Datum:** {raid_date}\n"
        f"⏰ **Start:** {raid_time}\n"
        f"👤 **Erstellt von:** {created_by}\n\n"
        f"🔑 **Prio-PIN:** `{player_pin}`\n"
        f"➡️ **Prios eintragen:** {LICHTLOOT_URL}\n\n"
        "Bitte tragt eure Prios rechtzeitig ein."
    )

    return text[:1900]


def get_raid_names_for_channel(channel_id):
    result = []
    for raid, sources in DISCORD_RAIDHELPER_SOURCES.items():
        for source in sources:
            if int(source["channel_id"]) == int(channel_id):
                result.append(raid)
                break
    return result


def normalize_prio_name(value):
    text = str(value or "").strip()
    text = re.sub(r"<@!?\d+>", "", text)
    text = re.sub(r"<@&\d+>", "", text)
    text = re.sub(r"[`*_~>•\-]+", " ", text)
    text = re.sub(r"[✅❌⚠️📝👥🍀🔍📋🟢🔴🟠⚪⭐🌟🔥💚⚔️🛡️]+", " ", text)
    text = text.strip()

    if not text:
        return ""

    # Discordnamen wie "Karuzy/Nick" oder "Reike/Rydøn | Jonas" -> erster Char zählt.
    text = re.split(r"[/|,;()]", text, maxsplit=1)[0].strip()
    text = re.sub(r"\s+", " ", text)

    # Nur realistische Char-Namen übernehmen.
    match = re.search(r"[A-Za-zÄÖÜäöüßÀ-ÿ][A-Za-zÄÖÜäöüßÀ-ÿ'´`\-]{1,20}", text)
    if not match:
        return ""

    return match.group(0).strip()


def prio_key(value):
    value = str(value or "").strip().lower()
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    value = re.sub(r"[^a-z0-9]", "", value)
    return value


def split_prio_aliases(value):
    """
    Zerlegt PO-Discordnamen in Aliasnamen.
    Wird NICHT für Raid-Helper-Anmeldungen genutzt, damit die Anmeldezahl stabil bleibt.
    """
    raw = str(value or "").strip()
    if not raw:
        return []

    raw = re.sub(r"<@!?\d+>", " ", raw)
    raw = re.sub(r"<@&\d+>", " ", raw)
    raw = re.sub(r"<:[^:]+:\d+>", " ", raw)
    raw = re.sub(r"\[[^\]]+\]", " ", raw)
    raw = re.sub(r"[`*_~>•]+", " ", raw)
    raw = re.sub(r"\bRole icon\b", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\bGildenmeister\b", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s+", " ", raw).strip()

    parts = re.split(r"[/|,;()]+", raw)
    result = []
    seen = set()

    for part in parts:
        candidate = normalize_prio_name(part)
        key = prio_key(candidate)

        if not candidate or not key:
            continue
        if len(candidate) < 2 or len(candidate) > 20:
            continue
        if key in seen:
            continue

        seen.add(key)
        result.append(candidate)

    return result


def add_alias_names(target, value):
    aliases = split_prio_aliases(value)

    for alias in aliases:
        key = prio_key(alias)
        if alias and key:
            target[key] = alias


def add_name(target, value):
    name = normalize_prio_name(value)
    key = prio_key(name)
    if name and key:
        target[key] = name


def collect_message_text(message):
    parts = []

    if getattr(message, "content", None):
        parts.append(message.content)

    for embed in getattr(message, "embeds", []) or []:
        if getattr(embed, "url", None):
            parts.append(str(embed.url))
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        if getattr(embed, "author", None):
            if getattr(embed.author, "name", None):
                parts.append(str(embed.author.name))
            if getattr(embed.author, "url", None):
                parts.append(str(embed.author.url))
        for field in embed.fields:
            if field.name:
                parts.append(str(field.name))
            if field.value:
                parts.append(str(field.value))
                parts.append("<<FIELD_BREAK>>")
        if embed.footer and embed.footer.text:
            parts.append(embed.footer.text)
        if getattr(embed, "thumbnail", None) and getattr(embed.thumbnail, "url", None):
            parts.append(str(embed.thumbnail.url))
        if getattr(embed, "image", None) and getattr(embed.image, "url", None):
            parts.append(str(embed.image.url))

    for row in getattr(message, "components", []) or []:
        for child in getattr(row, "children", []) or []:
            if getattr(child, "url", None):
                parts.append(str(child.url))
            if getattr(child, "label", None):
                parts.append(str(child.label))

    return "\n".join(parts)


def extract_signup_names_from_text(text):
    """
    Liest Spieler aus RaidHelper-Anmeldern.

    Unterstützte Formate:
    - altes Embedformat: `5` **Karuzy/Nick**
    - neues Textformat: :Fury: 39 Karuzy/Nick
    - Custom-Emoji: <:Fury:123456789> 39 Karuzy/Nick

    Bench und Absence werden ignoriert.
    Es zählt immer der erste Charakter vor / oder |.
    """
    names = {}

    valid_signup_roles = {
        "tank", "protection",
        "warrior", "fury", "arms",
        "druid", "feral", "balance", "restoration",
        "paladin", "holy1", "holy", "retribution",
        "rogue", "combat", "assassination", "subtlety",
        "hunter", "marksmanship", "beastmastery", "survival",
        "priest", "discipline", "shadow",
        "mage", "fire", "frost", "arcane",
        "warlock", "destruction", "affliction", "demonology",
        "shaman", "elemental", "enhancement"
    }

    ignored_words = [
        "bench", "absence", "absent",
        "leaderx", "datex", "signupsx", "timex", "countdownx",
        "loot prio", "raidsheet", "invite", "consumables", "raidregeln",
        "worte des tauens", "buffeinteilung", "standard consumables",
        "tanks:", "ranged:", "healers:"
    ]

    def clean_line(value):
        return str(value or "").replace("\u200e", "").replace("\u2800", "").strip()

    def add_signup_candidate(raw_name):
        raw_name = clean_line(raw_name)
        if not raw_name:
            return

        raw_name = re.split(r"\s+:[A-Za-z0-9_]+:\s*`?\d+`?\s+", raw_name, maxsplit=1)[0].strip()
        raw_name = re.split(r"\s+<:[^:>]+:\d+>\s*`?\d+`?\s+", raw_name, maxsplit=1)[0].strip()

        raw_name = raw_name.replace("**", "").replace("`", "").strip()
        candidate = normalize_prio_name(raw_name)
        key = prio_key(candidate)

        if candidate and key:
            names[key] = candidate

    for raw_field in str(text or "").split("\n<<FIELD_BREAK>>\n"):
        field = clean_line(raw_field)
        if not field:
            continue

        for raw_line in field.splitlines():
            line = clean_line(raw_line)
            if not line:
                continue

            lower_line = line.lower()

            if any(word in lower_line for word in ignored_words):
                continue

            if re.match(r"^:([A-Za-z0-9_]+):\s*[A-Za-zÄÖÜäöüß ]+\s*\(\d+(?:/\d+)?\)", line):
                continue
            if re.match(r"^<:([A-Za-z0-9_]+):\d+>\s*[A-Za-zÄÖÜäöüß ]+\s*\(\d+(?:/\d+)?\)", line):
                continue

            old_match = re.search(r"`\d+`\s*\*\*([^*]+)\*\*", line)
            if old_match:
                add_signup_candidate(old_match.group(1))
                continue

            new_match = re.search(r"^:([A-Za-z0-9_]+):\s*(?:\*\*)?`?\d+`?(?:\*\*)?\s+(.+)$", line)
            if new_match:
                role = prio_key(new_match.group(1))
                if role in valid_signup_roles:
                    add_signup_candidate(new_match.group(2))
                continue

            custom_match = re.search(r"^<:([A-Za-z0-9_]+):\d+>\s*(?:\*\*)?`?\d+`?(?:\*\*)?\s+(.+)$", line)
            if custom_match:
                role = prio_key(custom_match.group(1))
                if role in valid_signup_roles:
                    add_signup_candidate(custom_match.group(2))
                continue

    return names


def raid_search_terms(raid):
    raid = normalize_raid_name(raid)
    terms = {raid.lower()}

    aliases = {
        "ONY": ["ony", "onyxia", "onixia"],
        "NAXX": ["naxx", "naxxramas"],
        "MC": ["mc", "molten core"],
        "BWL": ["bwl", "blackwing lair"],
        "AQ40": ["aq40", "ahn'qiraj", "ahn qiraj", "tempel von ahn", "temple of ahn"],
        "AQ20": ["aq20", "ruins of ahn", "ruinen von ahn"],
        "ZG": ["zg", "zul'gurub", "zulgurub"],
    }

    for term in aliases.get(raid, []):
        terms.add(term.lower())

    return terms


def text_mentions_raid(raid, text):
    lower = str(text or "").lower()
    return any(term and term in lower for term in raid_search_terms(raid))


def extract_raid_datetime_object_from_text(text):
    date_text, time_text = extract_raid_datetime_from_text(text)

    if not date_text or not time_text:
        return None

    try:
        return BERLIN_TZ.localize(
            datetime.strptime(f"{date_text} {time_text}", "%d.%m.%Y %H:%M")
        )
    except Exception:
        return None


async def find_latest_raidhelper_message(raid, channel, limit=500):
    """
    Sucht im Raid-Channel den neuesten passenden RaidHelper-Anmelder.

    Wichtig:
    - Keine feste Message-ID.
    - Content UND Embeds werden geprüft.
    - Der neueste Post mit echten Anmeldungen wird verwendet.
    """
    signup_candidates = []
    dated_candidates = []
    fallback_candidates = []

    async for msg in channel.history(limit=limit):
        text = collect_message_text(msg)
        if not text.strip():
            continue

        signups = extract_signup_names_from_text(text)
        event_dt = extract_raid_datetime_object_from_text(text)
        mentions_raid = text_mentions_raid(raid, text)

        item = {
            "message": msg,
            "signup_count": len(signups),
            "event_dt": event_dt,
            "mentions_raid": mentions_raid,
        }

        if len(signups) > 0 and mentions_raid:
            signup_candidates.append(item)
        elif len(signups) > 0:
            signup_candidates.append(item)
        elif event_dt and mentions_raid:
            dated_candidates.append(item)
        elif event_dt:
            dated_candidates.append(item)
        else:
            fallback_candidates.append(item)

    def newest_message_key(item):
        return item["message"].created_at.timestamp()

    if signup_candidates:
        signup_candidates.sort(key=newest_message_key, reverse=True)
        return signup_candidates[0]["message"]

    if dated_candidates:
        dated_candidates.sort(key=newest_message_key, reverse=True)
        return dated_candidates[0]["message"]

    if fallback_candidates:
        fallback_candidates.sort(key=newest_message_key, reverse=True)
        return fallback_candidates[0]["message"]

    return None

async def get_raid_helper_message(raid, source):
    channel = client.get_channel(int(source["channel_id"])) or await client.fetch_channel(int(source["channel_id"]))

    # Alte Kompatibilität: Falls irgendwo doch noch eine message_id hinterlegt ist, darf sie genutzt werden.
    # Standard ist aber automatische Suche.
    message_id = source.get("message_id")
    if message_id:
        try:
            return await channel.fetch_message(int(message_id))
        except Exception as e:
            print(f"Feste RaidHelper-Message-ID nicht gefunden, suche automatisch weiter: {e}")

    msg = await find_latest_raidhelper_message(raid, channel)
    if not msg:
        raise RuntimeError(f"Keine passende RaidHelper-Nachricht im Channel {source['channel_id']} für {raid} gefunden.")

    source["resolved_message_id"] = str(msg.id)
    return msg


async def get_raid_signup_names_from_source(raid, source):
    raid_message = await get_raid_helper_message(raid, source)
    text = collect_message_text(raid_message)
    return extract_signup_names_from_text(text)


def extract_raid_datetime_from_text(text):
    """
    Liest Datum/Uhrzeit aus RaidHelper.
    Unterstützt:
    - Discord-Unix-Timestamp <t:...>
    - 16.06.2026 18:45
    - 10. Juni 2026 + :TimeX: 19:45
    """
    raw = str(text or "")

    timestamp_match = re.search(r"<t:(\d+):[dDfFtTR]>", raw)
    if timestamp_match:
        unix_ts = int(timestamp_match.group(1))
        dt = datetime.fromtimestamp(unix_ts, BERLIN_TZ)
        return dt.strftime("%d.%m.%Y"), dt.strftime("%H:%M")

    date_text = ""
    time_text = ""

    numeric_date_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", raw)
    if numeric_date_match:
        day, month, year = numeric_date_match.groups()
        date_text = f"{int(day):02d}.{int(month):02d}.{year}"
    else:
        month_names = {
            "januar": 1, "jan": 1,
            "februar": 2, "feb": 2,
            "maerz": 3, "märz": 3, "mrz": 3,
            "april": 4, "apr": 4,
            "mai": 5,
            "juni": 6, "jun": 6,
            "juli": 7, "jul": 7,
            "august": 8, "aug": 8,
            "september": 9, "sep": 9,
            "oktober": 10, "okt": 10,
            "november": 11, "nov": 11,
            "dezember": 12, "dez": 12,
        }

        german_date_match = re.search(
            r"(\d{1,2})\.??\s+([A-Za-zÄÖÜäöüß]+)\s+(\d{4})",
            raw,
            re.IGNORECASE
        )
        if german_date_match:
            day, month_name, year = german_date_match.groups()
            month = month_names.get(month_name.lower())
            if month:
                date_text = f"{int(day):02d}.{month:02d}.{year}"

    time_line_match = re.search(
        r"(?:TimeX|Uhrzeit|Zeit)\s*:?\s*(\d{1,2}:\d{2})",
        raw,
        re.IGNORECASE
    )
    if time_line_match:
        time_text = time_line_match.group(1)
    else:
        time_match = re.search(r"(\d{1,2}:\d{2})", raw)
        if time_match:
            time_text = time_match.group(1)

    if date_text and time_text:
        hour, minute = time_text.split(":")
        return date_text, f"{int(hour):02d}:{minute}"

    return "", ""


async def get_raid_event_info_from_source(raid, source):
    raid_message = await get_raid_helper_message(raid, source)
    text = collect_message_text(raid_message)
    raid_date, raid_time = extract_raid_datetime_from_text(text)

    return {
        "raid": raid,
        "raidDate": raid_date,
        "raidTime": raid_time,
        "discordChannelId": str(source["channel_id"]),
        "raidHelperMessageId": str(source.get("resolved_message_id") or source.get("message_id") or "")
    }


# Kompatibilität für alte Debug-Befehle/Funktionsnamen
async def get_aq40_raid_helper_message():
    return await get_raid_helper_message("AQ40", DISCORD_RAIDHELPER_SOURCES["AQ40"][0])


async def get_aq40_signup_names():
    return await get_raid_signup_names_from_source("AQ40", DISCORD_RAIDHELPER_SOURCES["AQ40"][0])


async def get_aq40_event_info():
    return await get_raid_event_info_from_source("AQ40", DISCORD_RAIDHELPER_SOURCES["AQ40"][0])


async def get_naxx_raid_helper_message():
    return await get_raid_helper_message("NAXX", DISCORD_RAIDHELPER_SOURCES["NAXX"][0])


async def get_naxx_signup_names():
    return await get_raid_signup_names_from_source("NAXX", DISCORD_RAIDHELPER_SOURCES["NAXX"][0])


async def get_naxx_event_info():
    return await get_raid_event_info_from_source("NAXX", DISCORD_RAIDHELPER_SOURCES["NAXX"][0])


def lichtloot_get(params):
    query = urllib.parse.urlencode(dict({"guild": current_guild_slug()}, **params))
    url = LICHTLOOT_API_URL + "?" + query

    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def lichtloot_post(payload):
    data = json.dumps(dict({"guild": current_guild_slug()}, **payload)).encode("utf-8")

    request = urllib.request.Request(
        LICHTLOOT_API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def lichtloot_apps_script_post(payload):
    data = json.dumps(dict({"guild": current_guild_slug()}, **payload)).encode("utf-8")

    request = urllib.request.Request(
        LICHTLOOT_APPS_SCRIPT_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def lichtloot_apps_script_get(params):
    query = urllib.parse.urlencode(dict({"guild": current_guild_slug()}, **params))
    url = LICHTLOOT_APPS_SCRIPT_URL + "?" + query

    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def railway_get(params):
    query = urllib.parse.urlencode(dict({"guild": current_guild_slug()}, **params))
    url = LICHTLOOT_RAILWAY_API_URL + "?" + query

    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def railway_post(payload):
    data = json.dumps(dict({"guild": current_guild_slug()}, **payload)).encode("utf-8")

    request = urllib.request.Request(
        LICHTLOOT_RAILWAY_API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_warcraft_log_urls(text):
    urls = []
    seen = set()
    pattern = re.compile(r"https?://(?:[a-z]+\.)?warcraftlogs\.com/reports/[A-Za-z0-9]+[^\s<>)\]]*", re.IGNORECASE)

    for match in pattern.finditer(str(text or "")):
        url = match.group(0).rstrip(".,;:!")
        code_match = re.search(r"/reports/([A-Za-z0-9]+)", url, re.IGNORECASE)
        if not code_match:
            continue
        report_code = code_match.group(1)
        key = report_code.lower()
        if key in seen:
            continue
        seen.add(key)
        urls.append({
            "url": url,
            "reportCode": report_code
        })

    return urls


def is_logsync_command(text):
    value = str(text or "").strip().lower()
    return bool(re.match(r"^!+\s*(?:lllogsync|logsync)\b", value))


async def handle_log_analysis_message(message, announce=True):
    if int(message.channel.id) not in LOG_ANALYSIS_CHANNEL_IDS:
        return []

    text = collect_message_text(message)
    logs = extract_warcraft_log_urls(text)
    if not logs:
        return []

    if not LICHTBOT_QUEUE_TOKEN:
        print("Loganalyse uebersprungen: LICHTBOT_QUEUE_TOKEN fehlt.")
        return []

    saved = []

    for log in logs:
        payload = {
            "action": "lichtbotSaveLogAnalysis",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "reportUrl": log["url"],
            "reportCode": log["reportCode"],
            "status": "pending",
            "title": "Discord Log",
            "discordChannelId": str(message.channel.id),
            "discordMessageId": str(message.id),
            "discordAuthor": getattr(message.author, "display_name", "") or str(message.author),
            "postedAt": message.created_at.isoformat(),
            "summary": json.dumps({
                "note": "Automatisch aus Discord erkannt. Detailanalyse wird im LichtLoot-Dashboard vorbereitet."
            }, ensure_ascii=False)
        }

        try:
            result = await asyncio.to_thread(railway_post, payload)
            if result.get("success"):
                saved.append(log["reportCode"])
            else:
                print("Loganalyse konnte nicht gespeichert werden:", result)
        except Exception as e:
            print("Loganalyse-Speicherung fehlgeschlagen:", e)

    if announce and saved:
        try:
            await message.channel.send(
                "✅ Loganalyse in LichtLoot aufgenommen: "
                + ", ".join(f"`{code}`" for code in saved),
                delete_after=30
            )
        except:
            pass

    return saved


async def sync_recent_log_analyses_from_channel(channel_id, target_count=LOG_ANALYSIS_BOOTSTRAP_COUNT, history_limit=LOG_ANALYSIS_HISTORY_LIMIT):
    if not LICHTBOT_QUEUE_TOKEN:
        print("Loganalyse-History-Sync uebersprungen: LICHTBOT_QUEUE_TOKEN fehlt.")
        return []

    try:
        channel = client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    except Exception as e:
        print(f"Loganalyse-Channel {channel_id} konnte nicht geladen werden:", e)
        return []

    saved_codes = []
    saved_code_keys = set()
    seen_codes = set()

    try:
        async for msg in channel.history(limit=history_limit, oldest_first=False):
            if msg.author == client.user:
                continue

            logs = extract_warcraft_log_urls(collect_message_text(msg))
            new_logs = [
                log for log in logs
                if log["reportCode"].lower() not in seen_codes
            ]
            if not new_logs:
                continue

            for log in new_logs:
                seen_codes.add(log["reportCode"].lower())

            saved = await handle_log_analysis_message(msg, announce=False)
            for code in saved:
                key = code.lower()
                if key not in saved_code_keys:
                    saved_codes.append(code)
                    saved_code_keys.add(key)

            if len(saved_codes) >= target_count:
                break
    except Exception as e:
        print("Loganalyse-History-Sync fehlgeschlagen:", e)

    print(f"Loganalyse-History-Sync: {len(saved_codes)} Report(s) an LichtLoot gesendet.")
    return saved_codes[:target_count]


async def sync_recent_log_analyses():
    all_saved = []
    for channel_id in LOG_ANALYSIS_CHANNEL_IDS:
        saved = await sync_recent_log_analyses_from_channel(channel_id)
        all_saved.extend(saved)
    return all_saved


PUBLIC_API_CACHE = {}
PUBLIC_API_CACHE_LOCK = threading.Lock()


def public_api_cache_config(path):
    if path == "/api/dashboard":
        return "dashboard", {"action": "getActiveRaids"}
    if path == "/api/worldbuffs":
        return "worldbuffs", {"action": "getPublicWorldbuffs", "days": 14}
    if path == "/api/hordenbuffs":
        return "hordenbuffs", {"action": "getPublicHordenbuffs", "days": 30}
    return None, None


def get_public_api_cache(key):
    with PUBLIC_API_CACHE_LOCK:
        entry = PUBLIC_API_CACHE.get(key)
        if not entry:
            return None
        return dict(entry)


def set_public_api_cache(key, data, error=None):
    payload = {
        "cachedAt": datetime.utcnow().isoformat() + "Z",
        "timestamp": time.time(),
        "data": data,
        "error": error
    }
    with PUBLIC_API_CACHE_LOCK:
        PUBLIC_API_CACHE[key] = payload
    return payload


def refresh_public_api_cache(key, params):
    try:
        data = lichtloot_get(params)
        return set_public_api_cache(key, data, None)
    except Exception as error:
        cached = get_public_api_cache(key)
        if cached:
            cached["stale"] = True
            cached["error"] = str(error)
            return cached
        return set_public_api_cache(key, {"success": False, "error": str(error)}, str(error))


def get_public_api_payload(path):
    key, params = public_api_cache_config(path)
    if not key:
        return 404, {"success": False, "error": "Endpoint nicht gefunden."}

    cached = get_public_api_cache(key)
    if cached and time.time() - cached.get("timestamp", 0) < PUBLIC_API_CACHE_SECONDS:
        data = cached.get("data") or {}
        if isinstance(data, dict):
            data = dict(data)
            data["_cache"] = {
                "source": "railway",
                "cachedAt": cached.get("cachedAt"),
                "stale": bool(cached.get("stale"))
            }
        return 200, data

    refreshed = refresh_public_api_cache(key, params)
    data = refreshed.get("data") or {}
    if isinstance(data, dict):
        data = dict(data)
        data["_cache"] = {
            "source": "railway",
            "cachedAt": refreshed.get("cachedAt"),
            "stale": bool(refreshed.get("stale"))
        }
    return 200, data


class PublicApiHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json(200, {"success": True, "status": "ok"})
            return

        status, payload = get_public_api_payload(path)
        self.send_json(status, payload)

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "public, max-age=20")

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)


def public_api_refresh_loop():
    endpoints = [
        public_api_cache_config("/api/dashboard"),
        public_api_cache_config("/api/worldbuffs"),
        public_api_cache_config("/api/hordenbuffs")
    ]
    while True:
        for key, params in endpoints:
            if key and params:
                refresh_public_api_cache(key, params)
        time.sleep(PUBLIC_API_CACHE_SECONDS)


def start_public_api_server():
    try:
        server = ThreadingHTTPServer(("0.0.0.0", PUBLIC_API_PORT), PublicApiHandler)
    except Exception as error:
        print(f"Public API konnte nicht gestartet werden: {error}")
        return

    threading.Thread(target=public_api_refresh_loop, daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Public API laeuft auf Port {PUBLIC_API_PORT}.")


def hordenbuff_sheet_set(rend, charakter="", uebernehmer="", status="", note=""):
    if not LICHTBOT_QUEUE_TOKEN:
        print("Hordenbuff-Railway-Sync uebersprungen: LICHTBOT_QUEUE_TOKEN fehlt.")
        return {"success": False, "error": "LICHTBOT_QUEUE_TOKEN fehlt."}

    payload = {
        "action": "lichtbotSetHordenbuffEntry",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "datum": rend.get("datum", ""),
        "uhrzeit": rend.get("uhrzeit", ""),
        "charakter": charakter,
        "uebernehmer": uebernehmer,
        "status": status,
        "note": note
    }

    try:
        result = railway_post(payload)
        clear_hordenbuff_csv_cache()
        return result
    except Exception as e:
        print(f"Hordenbuff-Railway-Sync Fehler: {e}")
        return {"success": False, "error": str(e)}


def hordenbuff_sheet_delete(rend, name):
    if not LICHTBOT_QUEUE_TOKEN:
        print("Hordenbuff-Railway-Sync uebersprungen: LICHTBOT_QUEUE_TOKEN fehlt.")
        return {"success": False, "error": "LICHTBOT_QUEUE_TOKEN fehlt."}

    try:
        result = railway_post({
            "action": "lichtbotDeleteHordenbuffEntry",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "datum": rend.get("datum", ""),
            "uhrzeit": rend.get("uhrzeit", ""),
            "name": name
        })

        clear_hordenbuff_csv_cache()
        return result
    except Exception as e:
        print(f"Hordenbuff-Railway-Loeschung Fehler: {e}")
        return {"success": False, "error": str(e)}


async def handle_lichtloot_queue_item(item, resolve_old_queue=True):
    update_type = str(item.get("type") or "").strip()
    row_number = item.get("rowNumber")
    payload = {}

    try:
        raw_payload = item.get("payload") or {}
        payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload or "{}")
    except Exception:
        payload = {}

    if update_type == "worldbuff_update" and payload.get("deleted"):
        removed = await asyncio.to_thread(remove_deleted_worldbuff_from_all_caches, payload)
        print(f"Worldbuff-Loeschung aus Queue verarbeitet, {removed} Cache-Eintraege entfernt.")

    if update_type == "raid_announcement":
        await post_raid_announcement_by_id(payload.get("raidId") or payload.get("id"))
    elif update_type == "log_analysis_post":
        await post_log_analysis_from_queue(payload)
    elif update_type == "worldbuff_update":
        await update_worldbuff_overview_from_all_guilds()
    elif update_type == "hordenbuff_update":
        await update_hordenbuff_post(force=True)
    else:
        await update_worldbuff_overview_from_all_guilds()
        await update_hordenbuff_post(force=True)

    if resolve_old_queue and row_number:
        await asyncio.to_thread(lichtloot_post, {
            "action": "lichtbotResolveQueue",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "rowNumber": row_number
        })


async def lichtloot_queue_loop():
    await client.wait_until_ready()

    if not LICHTBOT_QUEUE_TOKEN:
        print("LichtLoot-Queue deaktiviert: LICHTBOT_QUEUE_TOKEN fehlt.")
        return

    print(f"LichtLoot-Queue aktiv: pruefe alle {LICHTLOOT_QUEUE_CHECK_SECONDS} Sekunden auf Updates.")

    while not client.is_closed():
        try:
            result = await asyncio.to_thread(lichtloot_get, {
                "action": "lichtbotGetQueue",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                "t": int(time.time())
            })

            if result.get("success"):
                items = result.get("items", [])
                if items:
                    update_types = ", ".join(str(item.get("type") or "?") for item in items)
                    print(f"LichtLoot-Queue: {len(items)} Update(s) gefunden: {update_types}")

                for item in items:
                    try:
                        await handle_lichtloot_queue_item(item)
                    except Exception as item_error:
                        print("Fehler beim Verarbeiten eines LichtLoot-Queue-Eintrags:", item_error)
            else:
                print("LichtLoot-Queue Antwort:", result)

            railway_result = await asyncio.to_thread(railway_get, {
                "action": "lichtbotGetQueue",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                "t": int(time.time())
            })

            if railway_result.get("success"):
                railway_items = railway_result.get("items", [])
                if railway_items:
                    update_types = ", ".join(str(item.get("type") or "?") for item in railway_items)
                    print(f"Railway-Queue: {len(railway_items)} Update(s) gefunden: {update_types}")

                for item in railway_items:
                    try:
                        await handle_lichtloot_queue_item(item, resolve_old_queue=False)
                        row_number = item.get("rowNumber")
                        if row_number:
                            await asyncio.to_thread(railway_post, {
                                "action": "lichtbotResolveQueue",
                                "queueToken": LICHTBOT_QUEUE_TOKEN,
                                "rowNumber": row_number
                            })
                    except Exception as item_error:
                        print("Fehler beim Verarbeiten eines Railway-Queue-Eintrags:", item_error)
            else:
                print("Railway-Queue Antwort:", railway_result)

        except Exception as e:
            print("Fehler im LichtLoot-Queue-Loop:", e)

        await asyncio.sleep(LICHTLOOT_QUEUE_CHECK_SECONDS)


async def get_prio_names_for_event(raid, event_info):
    """
    Ermittelt die richtige LichtLoot-RaidID über Raid + Datum + Uhrzeit des neuesten RaidHelper-Anmelders.

    Wenn das Apps Script mehrere passende Raids findet, verwendet es die dort ausgewählte neueste RaidID
    (selectedBy / matchedCount werden in den Metadaten mitgeführt).
    """
    raid = normalize_raid_name(raid)

    if not event_info.get("raidDate") or not event_info.get("raidTime"):
        raise RuntimeError(f"Raid-Helper Datum/Uhrzeit konnten nicht gelesen werden für {raid}.")

    raid_result = await asyncio.to_thread(lichtloot_get, {
        "action": "getRaidByDateTime",
        "raid": raid,
        "date": event_info["raidDate"],
        "time": event_info["raidTime"]
    })

    if not raid_result.get("success") or not raid_result.get("raidId"):
        raise RuntimeError(
            "Kein passender LichtLoot-Raid gefunden für "
            + raid + " "
            + event_info.get("raidDate", "") + " " + event_info.get("raidTime", "")
            + ": " + str(raid_result)
        )

    selected_raid_id = raid_result["raidId"]

    prio_result = await asyncio.to_thread(lichtloot_get, {
        "action": "getPriosByRaidId",
        "raidId": selected_raid_id
    })

    names = {}
    for entry in prio_result.get("prios", []):
        add_name(names, entry.get("Spieler") or entry.get("player"))

    meta = {
        "event": event_info,
        "raid": raid_result,
        "prioResult": prio_result,
        "raidId": selected_raid_id,
        "raidDate": raid_result.get("raidDate") or event_info.get("raidDate"),
        "raidTime": raid_result.get("raidTime") or event_info.get("raidTime"),
        "matchedCount": raid_result.get("matchedCount", 1),
        "selectedBy": raid_result.get("selectedBy", ""),
        "playerPin": raid_result.get("playerPin", ""),
        "leadPin": raid_result.get("leadPin", ""),
        "status": raid_result.get("status", "")
    }

    return names, meta


async def get_aq40_prio_names():
    event_info = await get_aq40_event_info()
    return await get_prio_names_for_event("AQ40", event_info)


async def get_naxx_prio_names():
    event_info = await get_naxx_event_info()
    return await get_prio_names_for_event("NAXX", event_info)



def build_discord_signup_rows(raid, event_info, signups, source_name="Discord"):
    rows = []
    now = datetime.now(BERLIN_TZ).isoformat()

    for char_name in sorted(signups.values(), key=lambda x: x.lower()):
        rows.append({
            "char": char_name,
            "spieler": char_name,
            "klasse": "",
            "status": "angemeldet",
            "discordName": char_name,
            "quelle": source_name,
            "zeitstempel": now
        })

    return rows


async def sync_discord_signup_rows_for_source(raid, source):
    raid = normalize_raid_name(raid)

    raid_message = await get_raid_helper_message(raid, source)
    text_msg = collect_message_text(raid_message)
    raid_date, raid_time = extract_raid_datetime_from_text(text_msg)
    signups = extract_signup_names_from_text(text_msg)

    if not raid_date or not raid_time:
        raise RuntimeError(f"Datum/Uhrzeit konnten für {raid} nicht aus Discord gelesen werden.")

    rows = build_discord_signup_rows(
        raid,
        {
            "raidDate": raid_date,
            "raidTime": raid_time,
            "raidHelperMessageId": str(raid_message.id),
            "discordChannelId": str(source["channel_id"])
        },
        signups,
        source_name=f"Discord:{source['channel_id']}:{raid_message.id}"
    )

    payload = {
        "action": "saveDiscordSignupRows",
        "raid": raid,
        "raidDate": raid_date,
        "raidTime": raid_time,
        "discordChannelId": str(source["channel_id"]),
        "raidHelperMessageId": str(raid_message.id),
        "rows": rows
    }

    result = await asyncio.to_thread(lichtloot_post, payload)

    return {
        "raid": raid,
        "raidDate": raid_date,
        "raidTime": raid_time,
        "messageId": str(raid_message.id),
        "channelId": str(source["channel_id"]),
        "signups": signups,
        "rows": rows,
        "apiResult": result
    }


async def sync_discord_signup_rows(raid):
    raid = normalize_raid_name(raid)
    sources = DISCORD_RAIDHELPER_SOURCES.get(raid, [])

    if not sources:
        raise RuntimeError(f"Keine Discord-RaidHelper-Quelle für {raid} hinterlegt.")

    results = []
    for source in sources:
        results.append(await sync_discord_signup_rows_for_source(raid, source))

    return results



def extract_po_from_line(line):
    raw = str(line or "").strip()
    if not raw:
        return None

    # Erkennt: "PO Item", "P0 Item", "Prio: PO Item".
    match = re.search(r"\b(P0|PO)\b\s*[:\-–—]?\s*(.+)$", raw, re.IGNORECASE)
    if not match:
        return None

    item = match.group(2).strip()
    item = re.sub(r"<[^>]+>", "", item).strip()
    item = item[:120]

    if not item or len(item) < 3:
        return None

    return item


async def get_po_entries_from_channel(channel_id, limit=800):
    channel = client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    entries = []
    names = {}

    async for msg in channel.history(limit=limit):
        if msg.author == client.user:
            continue

        message_text = collect_message_text(msg)
        item = None

        for line in message_text.splitlines():
            item = extract_po_from_line(line)
            if item:
                break

        if not item:
            continue

        display_name = getattr(msg.author, "display_name", "") or str(msg.author)
        aliases = split_prio_aliases(display_name)

        if not aliases:
            fallback_line = message_text.splitlines()[0] if message_text.splitlines() else ""
            aliases = split_prio_aliases(fallback_line)

        if not aliases:
            continue

        main_player = aliases[0]

        for alias in aliases:
            key = prio_key(alias)
            if key:
                names[key] = alias

        entries.append({
            "player": main_player,
            "aliases": aliases,
            "item": item,
            "messageId": str(msg.id),
            "createdAt": msg.created_at.isoformat()
        })

    return names, entries


async def get_po_entries_for_source(source, limit=800):
    return await get_po_entries_from_channel(source["channel_id"], limit=limit)


async def get_aq40_po_entries(limit=800):
    return await get_po_entries_for_source(DISCORD_RAIDHELPER_SOURCES["AQ40"][0], limit=limit)


def sorted_names(name_map, keys):
    return sorted([name_map[k] for k in keys if k in name_map], key=lambda x: x.lower())


def build_prio_check_result(raid, signups, prios, po_names, po_entries, prio_meta=None):
    signup_keys = set(signups.keys())
    prio_keys = set(prios.keys())
    po_keys = set(po_names.keys())

    angemeldet_ohne_prio = signup_keys - prio_keys
    prio_ohne_anmeldung = prio_keys - signup_keys
    po_ohne_prio = po_keys - prio_keys
    po_ohne_anmeldung = po_keys - signup_keys
    vollstaendig = signup_keys & prio_keys

    return {
        "raid": raid,
        "raidId": (prio_meta or {}).get("raidId", ""),
        "raidDate": (prio_meta or {}).get("raidDate", ""),
        "raidTime": (prio_meta or {}).get("raidTime", ""),
        "createdAt": datetime.now(BERLIN_TZ).isoformat(),
        "counts": {
            "signups": len(signup_keys),
            "prios": len(prio_keys),
            "po": len(po_keys),
            "complete": len(vollstaendig)
        },
        "raidInfo": prio_meta or {},
        "signups": sorted_names(signups, signup_keys),
        "prios": sorted_names(prios, prio_keys),
        "poPlayers": sorted_names(po_names, po_keys),
        "poEntries": po_entries,
        "missingPrio": sorted_names(signups, angemeldet_ohne_prio),
        "prioWithoutSignup": sorted_names(prios, prio_ohne_anmeldung),
        "poWithoutPrio": sorted_names(po_names, po_ohne_prio),
        "poWithoutSignup": sorted_names(po_names, po_ohne_anmeldung),
        "complete": sorted_names(signups, vollstaendig)
    }


def build_prio_check_text(result, report_title=None):
    raid = result.get("raid", "")
    if not report_title:
        report_title = f"{raid} Prio-Check"

    today = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")
    counts = result.get("counts", {})

    text = f"📋 **{report_title}**\n"
    text += f"🕒 Stand: {today}\n\n"
    text += f"👥 Angemeldet: **{counts.get('signups', 0)}**\n"
    text += f"📝 Prios gesetzt: **{counts.get('prios', 0)}**\n"
    text += f"🍀 PO-Meldungen: **{counts.get('po', 0)}**\n"
    text += f"✅ Vollständig: **{counts.get('complete', 0)}**\n\n"

    sections = [
        ("⚠️ Angemeldet ohne Prio", result.get("missingPrio", [])),
        ("⚠️ PO gesetzt, aber keine Prio", result.get("poWithoutPrio", [])),
    ]

    for title, values in sections:
        text += f"**{title} ({len(values)})**\n"
        if values:
            for name in values[:40]:
                text += f"- {name}\n"
            if len(values) > 40:
                text += f"- … und {len(values) - 40} weitere\n"
        else:
            text += "- keine\n"
        text += "\n"

    if result.get("missingPrio"):
        text += "Bitte tragt eure LichtLoot-Prios noch ein.\n"

    return text[:1900]


async def refresh_prio_check_for_source(raid, source, post_to_discord=False, report_title=None):
    raid = normalize_raid_name(raid)

    signups = await get_raid_signup_names_from_source(raid, source)
    event_info = await get_raid_event_info_from_source(raid, source)
    prios, prio_meta = await get_prio_names_for_event(raid, event_info)
    po_names, po_entries = await get_po_entries_for_source(source)

    result = build_prio_check_result(raid, signups, prios, po_names, po_entries, prio_meta)

    await asyncio.to_thread(lichtloot_post, {
        "action": "savePrioCheck",
        "raid": raid,
        "raidId": result.get("raidId", ""),
        "payload": result
    })

    if post_to_discord:
        channel = client.get_channel(int(source["channel_id"])) or await client.fetch_channel(int(source["channel_id"]))
        await channel.send(build_prio_check_text(result, report_title))

    return result


async def refresh_prio_check(raid, post_to_discord=False, report_title=None):
    raid = normalize_raid_name(raid)
    sources = DISCORD_RAIDHELPER_SOURCES.get(raid, [])

    if not sources:
        raise RuntimeError(f"Keine Discord-RaidHelper-Quelle für {raid} hinterlegt.")

    results = []
    for source in sources:
        try:
            result = await refresh_prio_check_for_source(
                raid,
                source,
                post_to_discord=post_to_discord,
                report_title=report_title or f"{raid} Prio-Check"
            )
            if result:
                results.append(result)
        except Exception as e:
            print(f"Fehler beim {raid} Prio-Check für Quelle {source}:", e)
            if post_to_discord:
                try:
                    channel = client.get_channel(int(source["channel_id"])) or await client.fetch_channel(int(source["channel_id"]))
                    await channel.send(f"⚠️ Der {raid} Prio-Check konnte nicht erstellt werden. Bitte Bot-Konsole prüfen.")
                except:
                    pass

    return results


async def refresh_aq40_prio_check(post_to_discord=False, report_title="AQ40 Prio-Check"):
    results = await refresh_prio_check("AQ40", post_to_discord=post_to_discord, report_title=report_title)
    return results[0] if results else None


async def refresh_all_prio_checks():
    all_results = {}
    for raid in DISCORD_RAIDHELPER_SOURCES.keys():
        results = await refresh_prio_check(raid, post_to_discord=False)
        all_results[raid] = results
    return all_results


def schedule_prio_check_update(raid="AQ40", reason=""):
    raid = normalize_raid_name(raid)
    old_task = PRIO_CHECK_UPDATE_TASKS.get(raid)

    if old_task and not old_task.done():
        old_task.cancel()

    async def delayed_update():
        try:
            await asyncio.sleep(20)
            await refresh_prio_check(raid, post_to_discord=False)
            print(f"{raid} Prio-Check aktualisiert: {reason}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Fehler beim verzögerten {raid} Prio-Check:", e)

    PRIO_CHECK_UPDATE_TASKS[raid] = client.loop.create_task(delayed_update())


async def prio_report_loop():
    await client.wait_until_ready()

    while not client.is_closed():
        try:
            now = datetime.now(BERLIN_TZ)
            state = load_json(PRIO_REPORT_FILE, {})
            today_key = now.strftime("%Y-%m-%d")

            if (
                now.hour == PRIO_REPORT_HOUR
                and now.minute >= PRIO_REPORT_MINUTE
                and state.get("last_aq40_report") != today_key
            ):
                await refresh_aq40_prio_check(
                    post_to_discord=True,
                    report_title="AQ40 Prio-Report"
                )
                state["last_aq40_report"] = today_key
                save_json(PRIO_REPORT_FILE, state)

        except Exception as e:
            print("Fehler im Prio-Report-Loop:", e)

        await asyncio.sleep(60)


async def raid_announcement_loop():
    await client.wait_until_ready()

    while not client.is_closed():
        try:
            state = load_json(RAID_ANNOUNCEMENT_FILE, {})
            posted_ids = set(str(x) for x in state.get("posted_raid_ids", []))
            initialized = bool(state.get("initialized"))

            result = await asyncio.to_thread(lichtloot_get, {
                "action": "getActiveRaids",
                "t": int(time.time())
            })

            raids = result.get("allRaids") or result.get("raids") or []
            active_ids = set()
            new_posts = []

            for raid in raids:
                raid_id = str(raid.get("raidId") or "").strip()
                raid_name = normalize_raid_name(raid.get("raid") or raid.get("raidName") or "")
                player_pin = str(raid.get("playerPin") or "").strip()

                if not raid_id or not raid_name or not player_pin:
                    continue

                active_ids.add(raid_id)

                if raid_id not in posted_ids:
                    if initialized:
                        new_posts.append(raid)
                    posted_ids.add(raid_id)

            for raid in new_posts:
                raid_name = normalize_raid_name(raid.get("raid") or raid.get("raidName") or "")
                channel_id = get_primary_raid_channel_id(raid_name)

                if not channel_id:
                    print(f"Kein Raid-Channel fuer {raid_name} hinterlegt.")
                    continue

                channel = client.get_channel(int(channel_id))
                if channel is None:
                    channel = await client.fetch_channel(int(channel_id))

                try:
                    await channel.send(build_raid_announcement_text(raid))
                    print(f"Raid-Ankuendigung gepostet: {raid.get('raidId')} in {channel_id}")
                    await asyncio.sleep(2)
                except discord.HTTPException as e:
                    if is_discord_rate_limit(e):
                        block_discord_writes_after_rate_limit(e, "Raid-Ankuendigung")
                        break
                    print(f"Raid-Ankuendigung fehlgeschlagen fuer {raid.get('raidId')}: {e}")

            state["posted_raid_ids"] = sorted(posted_ids)
            state["known_active_raid_ids"] = sorted(active_ids)
            state["initialized"] = True
            state["updated_at"] = datetime.now(BERLIN_TZ).isoformat()
            save_json(RAID_ANNOUNCEMENT_FILE, state)

        except Exception as e:
            print("Fehler im Raid-Ankuendigungs-Loop:", e)

        await asyncio.sleep(RAID_ANNOUNCEMENT_CHECK_SECONDS)


async def post_raid_announcement_by_id(raid_id):
    raid_id = str(raid_id or "").strip()
    if not raid_id:
        return False

    result = await asyncio.to_thread(lichtloot_get, {
        "action": "getActiveRaids",
        "t": int(time.time())
    })
    raids = result.get("allRaids") or result.get("raids") or []
    raid = next(
        (
            item for item in raids
            if str(item.get("raidId") or item.get("id") or "").strip() == raid_id
            or str(item.get("playerPin") or "").strip() == raid_id
        ),
        None
    )

    if not raid:
        print(f"Raid-Ankuendigung manuell: Raid {raid_id} nicht gefunden.")
        return False

    raid_name = normalize_raid_name(raid.get("raid") or raid.get("raidName") or "")
    channel_id = get_primary_raid_channel_id(raid_name)
    if not channel_id:
        print(f"Raid-Ankuendigung manuell: Kein Channel fuer {raid_name} hinterlegt.")
        return False

    channel = client.get_channel(int(channel_id))
    if channel is None:
        channel = await client.fetch_channel(int(channel_id))

    await channel.send(build_raid_announcement_text(raid))
    print(f"Raid-Ankuendigung manuell gepostet: {raid_id} in {channel_id}")
    await asyncio.sleep(2)
    return True


async def prio_sync_loop():
    await client.wait_until_ready()

    while not client.is_closed():
        try:
            await refresh_all_prio_checks()
            print("Discord-Abgleich für alle Raids aktualisiert.")
        except Exception as e:
            print("Fehler im raidübergreifenden Discord-Abgleich:", e)

        await asyncio.sleep(PRIO_SYNC_INTERVAL_SECONDS)

async def handle_ticker_update(message):
    if not is_ticker_channel(message.channel.id):
        return

    new_buffs = [buff for buff in parse_ticker_message(message.content) if not is_deleted_worldbuff(buff)]

    if not new_buffs:
        return

    old_data = load_json(worldbuff_file(), [])

    merge_buffs_into_data(old_data, new_buffs)

    save_json(worldbuff_file(), old_data)
    await asyncio.to_thread(sync_worldbuff_ticker_cache_to_sheet, old_data)

    print(f"{len(new_buffs)} Worldbuffs aus Ticker übernommen oder geprüft.")

    await update_worldbuff_overview_from_all_guilds()

    if any(normalize_buff(b["buff"]) == "Rend" for b in new_buffs):
        await update_hordenbuff_post(force=True)


@client.event
async def on_ready():
    print(f"Bot online als {client.user}")
    print(f"Überwache Ticker-Channels: {sorted(TICKER_CHANNEL_IDS)}")
    print(f"Postet Übersicht in Channel: {POST_CHANNEL_ID}")
    print(f"Hordenbuff-Channels: {sorted(HORDENBUFF_CHANNEL_IDS)}")
    print(f"Loganalyse-Channels: {sorted(LOG_ANALYSIS_CHANNEL_IDS)}")
    print("Version 4.9 gestartet: Raid-Ankuendigungen und DC-Abgleich aktiv.")

    if not hasattr(client, "hordenbuff_task_started"):
        client.hordenbuff_task_started = True
        client.loop.create_task(hordenbuff_reminder_loop())

    if not hasattr(client, "raid_announcement_task_started"):
        client.raid_announcement_task_started = True
        client.loop.create_task(raid_announcement_loop())

    if not hasattr(client, "lichtloot_queue_task_started"):
        client.lichtloot_queue_task_started = True
        client.loop.create_task(lichtloot_queue_loop())

    if not hasattr(client, "worldbuff_startup_task_started"):
        client.worldbuff_startup_task_started = True
        client.loop.create_task(update_worldbuff_overview_from_all_guilds())

    if not hasattr(client, "log_analysis_history_sync_started"):
        client.log_analysis_history_sync_started = True
        client.loop.create_task(sync_recent_log_analyses())

    # Automatischer AQ40-Prio-Report deaktiviert.
    # if not hasattr(client, "prio_report_task_started"):
    #     client.prio_report_task_started = True
    #     client.loop.create_task(prio_report_loop())

    # Raidübergreifender DC-Hintergrundsync deaktiviert.
    # if not hasattr(client, "prio_sync_task_started"):
    #     client.prio_sync_task_started = True
    #     client.loop.create_task(prio_sync_loop())


@client.event
async def on_message_edit(before, after):
    if after.author == client.user:
        return

    CURRENT_GUILD_SLUG.set(guild_slug_for_channel(after.channel.id))

    #for raid in get_raid_names_for_channel(after.channel.id):
    #  schedule_prio_check_update(raid, f"Nachricht im {raid}-Channel bearbeitet")

    await handle_log_analysis_message(after)
    await handle_ticker_update(after)


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    CURRENT_GUILD_SLUG.set(guild_slug_for_channel(message.channel.id))

    await handle_log_analysis_message(message)

    content = message.content.strip()
    lower = content.lower()

    if is_logsync_command(content):
        if int(message.channel.id) not in LOG_ANALYSIS_CHANNEL_IDS:
            await message.channel.send("⚠️ Dieser Befehl funktioniert nur im Loganalyse-Channel.", delete_after=20)
            return
        saved = await sync_recent_log_analyses_from_channel(message.channel.id)
        await message.channel.send(
            f"✅ {len(saved)} Warcraft-Logs aus der Channel-History an LichtLoot gesendet.",
            delete_after=30
        )
        return

    if lower.startswith("!lldebug"):
        parts = lower.replace(".", "").split()
        raid = normalize_raid_name(parts[1] if len(parts) > 1 else "AQ40")
        sources = DISCORD_RAIDHELPER_SOURCES.get(raid, [])

        if not sources:
            await message.channel.send(f"⚠️ Kein RaidHelper-Eintrag für **{raid}** gefunden.")
            return

        lines = [f"🧪 **LLDEBUG {raid} – nur Anmeldungen**"]

        for idx, source in enumerate(sources, start=1):
            try:
                raid_message = await get_raid_helper_message(raid, source)
                text_msg = collect_message_text(raid_message)
                raid_date, raid_time = extract_raid_datetime_from_text(text_msg)
                signups = extract_signup_names_from_text(text_msg)

                lines.append(
                    f"Quelle {idx}: Message `{raid_message.id}`\n"
                    f"Discord: **{raid_date or '-'}** um **{raid_time or '-'}**\n"
                    f"Anmeldungen erkannt: **{len(signups)}**"
                )

                payload_rows = build_discord_signup_rows(
                    raid,
                    {
                        "raidDate": raid_date,
                        "raidTime": raid_time,
                        "raidHelperMessageId": str(raid_message.id),
                        "discordChannelId": str(source["channel_id"])
                    },
                    signups,
                    source_name=f"Discord:{source['channel_id']}:{raid_message.id}"
                )

                lines.append(f"Sheet-Zeilen vorbereitet: **{len(payload_rows)}**")
                lines.append("Noch nicht gespeichert. Zum Speichern: `!" + raid.lower() + "check`")

            except Exception as e:
                lines.append(f"Quelle {idx}: ⚠️ Fehler: {e}")

        await message.channel.send("\n".join(lines)[:1900])
        try:
            await delete_command_message(message)
        except:
            pass
        return

    if lower.startswith("!priocheck") or lower.endswith("check"):
        parts = lower.split()
        command = parts[0] if parts else lower

        command_map = {
            "!aq40check": "AQ40",
            "!naxxcheck": "NAXX",
            "!mccheck": "MC",
            "!bwlcheck": "BWL",
            "!zgcheck": "ZG",
            "!aq20check": "AQ20",
            "!onycheck": "ONY",
            "!onyxiacheck": "ONY",
            "!onixiacheck": "ONY"
        }

        if lower.startswith("!priocheck") and len(parts) > 1:
            raid = normalize_raid_name(parts[1])
        elif command in command_map:
            raid = command_map[command]
        else:
            channel_raids = get_raid_names_for_channel(message.channel.id)
            raid = channel_raids[0] if channel_raids else "AQ40"

        await message.channel.send(f"🔄 **{raid} DC-Anmeldungen werden ins Sheet geschrieben...**")

        try:
            results = await asyncio.wait_for(sync_discord_signup_rows(raid), timeout=90)

            total = sum(len(r.get("rows", [])) for r in results)
            details = []
            for r in results:
                api = r.get("apiResult", {})
                details.append(
                    f"Quelle `{r.get('messageId')}`: **{len(r.get('rows', []))}** Zeilen | "
                    f"RaidID `{api.get('raidId', '-')}` | gespeichert `{api.get('written', '-')}`"
                )

            await message.channel.send(
                f"✅ **{raid} DC-Anmeldungen gespeichert.**\n"
                f"Gesamt: **{total}**\n" +
                "\n".join(details)
            )

            await delete_command_message(message)

        except asyncio.TimeoutError:
            await message.channel.send(f"⏱️ **{raid} Timeout** – Speichern der Anmeldungen dauerte länger als 90 Sekunden.")
        except Exception as e:
            err = str(e)
            if len(err) > 1500:
                err = err[:1500] + " …"
            await message.channel.send(f"⚠️ **{raid} Fehler beim Speichern der DC-Anmeldungen:**\n```{err}```")
        return

    if lower.startswith("!lldebug"):
        parts = lower.replace(".", "").split()
        raid = normalize_raid_name(parts[1] if len(parts) > 1 else "AQ40")
        sources = DISCORD_RAIDHELPER_SOURCES.get(raid, [])

        if not sources:
            await message.channel.send(f"⚠️ Kein RaidHelper-Eintrag für **{raid}** gefunden.")
            return

        await message.channel.send(f"🧪 **LLDEBUG {raid} gestartet**")

        lines = [f"🧪 **LLDEBUG {raid}**"]

        for idx, source in enumerate(sources, start=1):
            try:
                raid_message = await get_raid_helper_message(raid, source)
                text_msg = collect_message_text(raid_message)
                raid_date, raid_time = extract_raid_datetime_from_text(text_msg)
                signups = extract_signup_names_from_text(text_msg)

                lines.append(
                    f"Quelle {idx}: Message `{raid_message.id}`\n"
                    f"Discord: **{raid_date or '-'}** um **{raid_time or '-'}**\n"
                    f"Anmeldungen: **{len(signups)}**"
                )

                if not raid_date or not raid_time:
                    lines.append("⚠️ Datum/Uhrzeit fehlen, API wird nicht aufgerufen.")
                    continue

                raid_result = await asyncio.wait_for(
                    asyncio.to_thread(lichtloot_get, {
                        "action": "getRaidByDateTime",
                        "raid": raid,
                        "date": raid_date,
                        "time": raid_time
                    }),
                    timeout=25
                )

                lines.append(
                    f"RaidID: `{raid_result.get('raidId', '-')}`\n"
                    f"success: `{raid_result.get('success')}` | "
                    f"matchedCount: `{raid_result.get('matchedCount', 0)}` | "
                    f"selectedBy: `{raid_result.get('selectedBy', '-')}`"
                )

                if raid_result.get("raidId"):
                    prio_result = await asyncio.wait_for(
                        asyncio.to_thread(lichtloot_get, {
                            "action": "getPriosByRaidId",
                            "raidId": raid_result["raidId"]
                        }),
                        timeout=25
                    )
                    lines.append(f"Prios geladen: **{len(prio_result.get('prios', []))}**")

            except asyncio.TimeoutError:
                lines.append(f"Quelle {idx}: ⏱️ Timeout bei LichtLoot-API.")
            except Exception as e:
                lines.append(f"Quelle {idx}: ⚠️ Fehler: {e}")

        await message.channel.send("\n".join(lines)[:1900])
        try:
            await delete_command_message(message)
        except:
            pass
        return

    if lower.startswith("!debuglichtloot"):
        parts = lower.replace(".", "").split()
        raid = normalize_raid_name(parts[1] if len(parts) > 1 else "AQ40")
        sources = DISCORD_RAIDHELPER_SOURCES.get(raid, [])

        if not sources:
            await message.channel.send(f"⚠️ Kein RaidHelper-Eintrag für **{raid}** gefunden.")
            return

        await message.channel.send(f"🔎 **LichtLoot API Debug {raid} startet...**")

        lines = [f"🔎 **LichtLoot API Debug {raid}**"]

        for idx, source in enumerate(sources, start=1):
            try:
                raid_message = await get_raid_helper_message(raid, source)
                text_msg = collect_message_text(raid_message)
                raid_date, raid_time = extract_raid_datetime_from_text(text_msg)
                signups = extract_signup_names_from_text(text_msg)

                lines.append(
                    f"Quelle {idx}: Message `{raid_message.id}`\n"
                    f"Discord: **{raid_date or '-'}** um **{raid_time or '-'}**\n"
                    f"Anmeldungen: **{len(signups)}**"
                )

                if not raid_date or not raid_time:
                    lines.append("⚠️ Datum/Uhrzeit konnten nicht gelesen werden.")
                    continue

                raid_result = await asyncio.wait_for(
                    asyncio.to_thread(lichtloot_get, {
                        "action": "getRaidByDateTime",
                        "raid": raid,
                        "date": raid_date,
                        "time": raid_time
                    }),
                    timeout=30
                )

                lines.append(
                    f"LichtLoot Antwort: success=`{raid_result.get('success')}` | "
                    f"RaidID=`{raid_result.get('raidId', '-')}` | "
                    f"matchedCount=`{raid_result.get('matchedCount', 0)}` | "
                    f"selectedBy=`{raid_result.get('selectedBy', '-')}`"
                )

                if raid_result.get("raidId"):
                    prio_result = await asyncio.wait_for(
                        asyncio.to_thread(lichtloot_get, {
                            "action": "getPriosByRaidId",
                            "raidId": raid_result["raidId"]
                        }),
                        timeout=30
                    )
                    lines.append(f"Prios geladen: **{len(prio_result.get('prios', []))}**")

            except asyncio.TimeoutError:
                lines.append(f"Quelle {idx}: ⏱️ Timeout bei LichtLoot-API.")
            except Exception as e:
                lines.append(f"Quelle {idx}: ⚠️ Fehler: {e}")

        await message.channel.send("\n".join(lines)[:1900])
        try:
            await delete_command_message(message)
        except:
            pass
        return

    #for raid in get_raid_names_for_channel(message.channel.id):
    #    schedule_prio_check_update(raid, f"Nachricht im {raid}-Channel")


    if lower.startswith("!debugraid"):
        parts = lower.split()
        raid = normalize_raid_name(parts[1] if len(parts) > 1 else "AQ40")
        sources = DISCORD_RAIDHELPER_SOURCES.get(raid, [])

        if not sources:
            await message.channel.send(f"⚠️ Kein RaidHelper-Eintrag für **{raid}** gefunden.")
            return

        for source in sources:
            raid_message = await get_raid_helper_message(raid, source)

            print(f"\n========== RAID HELPER DEBUG {raid} ==========")
            print(f"CHANNEL: {source['channel_id']} MESSAGE: {source.get('resolved_message_id') or source.get('message_id') or 'AUTO'}")
            print("MESSAGE:")
            print(raid_message.content)

            for embed in raid_message.embeds:
                print("\n========== EMBED ==========\n")
                print(embed.to_dict())

        await message.channel.send(
            f"✅ Raid-Helper Daten für **{raid}** wurden in die Konsole geschrieben."
        )
        return

    if lower.startswith("!debugsource"):
        parts = lower.split()
        raid = normalize_raid_name(parts[1] if len(parts) > 1 else "AQ40")
        sources = DISCORD_RAIDHELPER_SOURCES.get(raid, [])

        if not sources:
            await message.channel.send(f"⚠️ Kein RaidHelper-Channel für **{raid}** gefunden.")
            await delete_command_message(message)
            return

        lines = [f"🔎 **{raid} verwendete RaidHelper-Quelle**"]
        for idx, source in enumerate(sources, start=1):
            try:
                raid_message = await get_raid_helper_message(raid, source)
                text = collect_message_text(raid_message)
                raid_date, raid_time = extract_raid_datetime_from_text(text)
                signups = extract_signup_names_from_text(text)
                lines.append(
                    f"Quelle {idx}: Channel `{source['channel_id']}` | Message `{raid_message.id}` | "
                    f"Datum **{raid_date or '-'}** um **{raid_time or '-'}** | Anmeldungen **{len(signups)}**"
                )
            except Exception as e:
                lines.append(f"Quelle {idx}: ⚠️ Fehler: {e}")

        await message.channel.send("\n".join(lines)[:1900])
        await delete_command_message(message)
        return

    if lower.startswith("!debugevent"):
        parts = lower.split()
        raid = normalize_raid_name(parts[1] if len(parts) > 1 else "AQ40")
        sources = DISCORD_RAIDHELPER_SOURCES.get(raid, [])

        if not sources:
            await message.channel.send(f"⚠️ Kein RaidHelper-Eintrag für **{raid}** gefunden.")
            await delete_command_message(message)
            return

        lines = [f"🕒 **{raid} Event Debug**"]
        for idx, source in enumerate(sources, start=1):
            info = await get_raid_event_info_from_source(raid, source)
            lines.append(
                f"Quelle {idx}: **{info.get('raidDate') or '-'}** um **{info.get('raidTime') or '-'}**"
            )

        await message.channel.send("\n".join(lines))
        await delete_command_message(message)
        return

    if lower.startswith("!debugsignup"):
        parts = lower.split()
        raid = normalize_raid_name(parts[1] if len(parts) > 1 else "AQ40")
        sources = DISCORD_RAIDHELPER_SOURCES.get(raid, [])

        if not sources:
            await message.channel.send(f"⚠️ Kein RaidHelper-Eintrag für **{raid}** gefunden.")
            await delete_command_message(message)
            return

        text_parts = [f"🔎 **{raid} Signup Debug**"]
        for idx, source in enumerate(sources, start=1):
            signups = await get_raid_signup_names_from_source(raid, source)
            values = sorted(signups.values(), key=lambda x: x.lower())
            preview = "\n".join("- " + name for name in values[:80]) or "- keine"
            text_parts.append(f"\n**Quelle {idx}: {len(values)} gefunden**\n{preview}")

        await message.channel.send("\n".join(text_parts)[:1900])
        await delete_command_message(message)
        return

    if not lower.startswith("!debug") and not lower.startswith("!lldebug") and (lower.startswith("!priocheck") or lower.endswith("check")):
        parts = lower.split()
        command = parts[0] if parts else lower

        command_map = {
            "!aq40check": "AQ40",
            "!naxxcheck": "NAXX",
            "!mccheck": "MC",
            "!bwlcheck": "BWL",
            "!zgcheck": "ZG",
            "!aq20check": "AQ20",
            "!onycheck": "ONY",
            "!onyxiacheck": "ONY",
            "!onixiacheck": "ONY"
        }

        if lower.startswith("!priocheck") and len(parts) > 1:
            raid = normalize_raid_name(parts[1])
        elif command in command_map:
            raid = command_map[command]
        else:
            channel_raids = get_raid_names_for_channel(message.channel.id)
            raid = channel_raids[0] if channel_raids else "AQ40"

        await message.channel.send(f"🔄 **{raid} DC-Abgleich wird geprüft...**")

        try:
            results = await asyncio.wait_for(
                refresh_prio_check(raid, post_to_discord=True),
                timeout=90
            )

            if results:
                first = results[0]
                counts = first.get("counts", {})
                info = first.get("raidInfo", {})
                raid_meta = info.get("raid", {}) if isinstance(info, dict) else {}

                await message.channel.send(
                    f"✅ **{raid} DC-Abgleich gespeichert.**\n"
                    f"RaidID: `{first.get('raidId', '-')}`\n"
                    f"Discord-Datum: **{first.get('raidDate', '-') or '-'}** | "
                    f"Anmeldungen: **{counts.get('signups', 0)}** | "
                    f"Prios: **{counts.get('prios', 0)}** | "
                    f"PO: **{counts.get('po', 0)}**\n"
                    f"Treffer im Sheet: **{raid_meta.get('matchedCount', 1)}** | "
                    f"Auswahl: **{raid_meta.get('selectedBy', 'direkt')}**"
                )
                await delete_command_message(message)
            else:
                await message.channel.send(f"⚠️ Für **{raid}** wurde kein Ergebnis erstellt. Bitte Bot-Konsole prüfen.")

        except asyncio.TimeoutError:
            await message.channel.send(f"⏱️ **{raid} Check Timeout** – der Abgleich hängt länger als 90 Sekunden. Bitte danach `!lldebug {raid.lower()}` testen.")
        except Exception as e:
            err = str(e)
            if len(err) > 1500:
                err = err[:1500] + " …"
            await message.channel.send(f"⚠️ **{raid} Check Fehler:**\n```{err}```")
        return

    if lower == "!wb":
        await update_worldbuff_post()
        await update_hordenbuff_post(force=True)
        await delete_command_message(message)
        return

    if lower in ["!worldbuff", "!worldbuffs"]:
        slots = await asyncio.to_thread(get_open_worldbuff_signup_slots)

        if not slots:
            await send_temp(
                message.channel,
                "⚠️ Es wurde kein freier Nef-, Ony- oder Hakkar-Termin gefunden."
            )
            await delete_command_message(message)
            return

        await message.channel.send(
            "✅ **Worldbuff eintragen**\n"
            "Wähle Nef, Ony oder Hakkar mit passendem freien Termin aus. "
            "Danach öffnet sich ein Fenster für den Charakternamen.",
            view=WorldbuffSignupView(slots),
            delete_after=180
        )
        await delete_command_message(message)
        return

    if lower in ["!hordenbuff", "!hordebuff", "!horde"]:
        await update_hordenbuff_post(force=True)
        await delete_command_message(message)
        return

    if lower.startswith("!rendhelfer "):
        helfer_name = content.split(maxsplit=1)[1].strip()

        if not helfer_name:
            await send_temp(
                message.channel,
                "Bitte nutze den Befehl so: `!rendhelfer Name`, z. B. `!rendhelfer Miimi`."
            )
            await delete_command_message(message)
            return

        await auto_assign_hordenbuff_helper(message, helfer_name)
        return

    if lower == "!rendhelfer":
        await send_temp(
            message.channel,
            "Bitte nutze den Befehl so: `!rendhelfer Name`, z. B. `!rendhelfer Miimi`."
        )
        await delete_command_message(message)
        return

    if lower.startswith("!rendbei "):
        parts = content.split(maxsplit=2)

        if len(parts) < 3:
            await send_temp(
                message.channel,
                "Bitte nutze den Befehl so: `!rendbei Allyname Helfername`, z. B. `!rendbei Ariee Miimi`."
            )
            await delete_command_message(message)
            return

        ziel = parts[1].strip()
        helfer_name = parts[2].strip()

        await set_specific_hordenbuff_helper(message, ziel, helfer_name)
        return

    if lower == "!rendbei":
        await send_temp(
            message.channel,
            "Bitte nutze den Befehl so: `!rendbei Allyname Helfername`, z. B. `!rendbei Ariee Miimi`."
        )
        await delete_command_message(message)
        return

    if lower.startswith("!rendchar "):
        charakter = content.split(maxsplit=1)[1].strip()

        if not charakter:
            await send_temp(
                message.channel,
                "Bitte nutze den Befehl so: `!rendchar Spielername`."
            )
            await delete_command_message(message)
            return

        await set_hordenbuff_char(message, charakter)
        return

    if lower.startswith("!renddel "):
        charakter = content.split(maxsplit=1)[1].strip()

        if not charakter:
            await send_temp(
                message.channel,
                "Bitte nutze den Befehl so: `!renddel Spielername`."
            )
            await delete_command_message(message)
            return

        await delete_rend_entry(message, charakter)
        return

    if lower.startswith("!rend "):
        charakter = content.split(maxsplit=1)[1].strip()

        if not charakter:
            await message.channel.send(
                "✅ **Rend-Anmeldung**\n"
                "Klick auf den Button und trage ein, was passt:\n"
                "Ally-Char = braucht Rend, Horden-Char = kann helfen.",
                view=RendSignupView(),
                delete_after=180
            )
            await delete_command_message(message)
            return

        await add_rend_spieler(message, charakter)
        return

    if lower == "!rend":
        await message.channel.send(
            "✅ **Rend-Anmeldung**\n"
            "Klick auf den Button und trage ein, was passt:\n"
            "Ally-Char = braucht Rend, Horden-Char = kann helfen.",
            view=RendSignupView(),
            delete_after=180
        )
        await delete_command_message(message)
        return

    if lower == "!rendchar":
        await send_temp(
            message.channel,
            "Bitte nutze den Befehl so: `!rendchar Spielername`, z. B. `!rendchar Ariee`."
        )
        await delete_command_message(message)
        return

    if lower == "!renddel":
        await send_temp(
            message.channel,
            "Bitte nutze den Befehl so: `!renddel Spielername`, z. B. `!renddel Ariee`."
        )
        await delete_command_message(message)
        return

    if lower.startswith("!wurf "):
        parts = content.split(maxsplit=2)

        if len(parts) < 3:
            await message.channel.send(
                "Bitte nutze den Befehl so: `!wurf hakkar Charaktername`."
            )
            return

        buff = normalize_buff(parts[1])
        charakter = parts[2].strip()

        if buff not in ["Hakkar", "Ony", "Nef", "Rend"]:
            await message.channel.send(
                "Diesen Buff kenne ich nicht. Nutze: `hakkar`, `ony`, `nef` oder `rend`."
            )
            return

        try:
            result = await asyncio.to_thread(
                sende_wurf_ans_sheet,
                buff,
                charakter,
                str(message.author)
            )

            if result.get("success"):
                await message.channel.send(
                    f"✅ **{charakter}** wurde für **{result.get('buff')}** eingetragen: "
                    f"{result.get('datum')} um {result.get('uhrzeit')}."
                )

                await update_worldbuff_post()

                if buff == "Rend":
                    await update_hordenbuff_post(force=True)

            else:
                await message.channel.send(
                    f"⚠️ Apps-Script-Antwort:\n```{result}```"
                )

        except Exception as e:
            print(f"Fehler bei !wurf: {e}")
            await message.channel.send(
                "⚠️ Beim Eintragen ist ein Fehler passiert. Bitte prüfe Apps Script und Sheet."
            )

        return

    await handle_ticker_update(message)


start_public_api_server()
client.run(TOKEN)
