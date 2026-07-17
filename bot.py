import discord
import re
import json
import csv
import hashlib
import urllib.request
import urllib.parse
import urllib.error
import os
import asyncio
import time
import threading
import contextvars
import sys
from io import StringIO, BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import pytz

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

DISCORD_SILENT_CHANNEL_POSTS = os.getenv("DISCORD_SILENT_CHANNEL_POSTS", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


async def send_silent(channel, *args, **kwargs):
    added_silent = False
    if DISCORD_SILENT_CHANNEL_POSTS and "silent" not in kwargs:
        kwargs["silent"] = True
        added_silent = True

    try:
        return await channel.send(*args, **kwargs)
    except TypeError:
        if added_silent:
            kwargs.pop("silent", None)
            return await channel.send(*args, **kwargs)
        raise

TOKEN = os.getenv("DISCORD_TOKEN", "MTUxMDY3NzM0Njc4NzY1OTc3Nw.G_-vuz._ocUI4y-Nv7o9Kn0erGGra7cQfrHvFjKfBaeRc")
LICHTBOT_QUEUE_TOKEN = os.getenv("LICHTBOT_QUEUE_TOKEN", "")

TICKER_CHANNEL_ID = 1283706980103356448
PANEM_TICKER_CHANNEL_ID = 1482656882857349277
POST_CHANNEL_ID = 1281152286772695071
HORDENBUFF_CHANNEL_ID = 1510764309062615220
PANEM_HORDENBUFF_CHANNEL_ID = 1518153802983669810
LOG_ANALYSIS_CHANNEL_ID = 1279032487628242995
WORLDBUFF_POSTER_MESSAGE_IDS = {
    value.strip()
    for value in os.getenv("WORLDBUFF_POSTER_MESSAGE_IDS", "1526256966027055114").split(",")
    if value.strip()
}

TICKER_CHANNEL_IDS = {
    TICKER_CHANNEL_ID,
    POST_CHANNEL_ID,
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
RAID_BANNER_DIR = Path(__file__).resolve().parent / "raid-banners"
PO_GUIDE_IMAGE_PATH = Path(__file__).resolve().parent / "po-anleitung.jpeg"
RAID_SIGNUP_DM_CACHE = {}

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
def normalize_lichtloot_api_url(value):
    url = str(value or "").strip() or LICHTLOOT_RAILWAY_API_URL
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host in {"lichtloot.de", "www.lichtloot.de"}:
        return LICHTLOOT_RAILWAY_API_URL
    return url


LICHTLOOT_API_URL = normalize_lichtloot_api_url(os.getenv("LICHTLOOT_API_URL", LICHTLOOT_RAILWAY_API_URL))
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
CLASS_EMOJI_FALLBACKS = {
    "warrior": "⚔️",
    "druid": "🌿",
    "paladin": "✨",
    "rogue": "🗡️",
    "hunter": "🏹",
    "priest": "💠",
    "mage": "🔥",
    "warlock": "💀",
    "shaman": "⚡",
}
CLASS_EMOJI_ENV = {
    "warrior": ("CLASS_EMOJI_WARRIOR", "classicon_warrior"),
    "druid": ("CLASS_EMOJI_DRUID", "classicon_druid"),
    "paladin": ("CLASS_EMOJI_PALADIN", "classicon_paladin"),
    "rogue": ("CLASS_EMOJI_ROGUE", "classicon_rogue"),
    "hunter": ("CLASS_EMOJI_HUNTER", "classicon_hunter"),
    "priest": ("CLASS_EMOJI_PRIEST", "classicon_priest"),
    "mage": ("CLASS_EMOJI_MAGE", "classicon_mage"),
    "warlock": ("CLASS_EMOJI_WARLOCK", "classicon_warlock"),
    "shaman": ("CLASS_EMOJI_SHAMAN", "classicon_shaman"),
}
CLASS_EMOJI_NAME_ALIASES = {
    "warrior": ["krieger", "warrior", "classicon_warrior"],
    "druid": ["druide", "druid", "classicon_druid"],
    "paladin": ["pala", "paladin", "classicon_paladin"],
    "rogue": ["schurke", "rogue", "classicon_rogue"],
    "hunter": ["jäger", "jaeger", "jager", "hunter", "classicon_hunter"],
    "priest": ["priester", "priest", "classicon_priest"],
    "mage": ["magier", "mage", "classicon_mage"],
    "warlock": ["hexenmeister", "hexer", "warlock", "classicon_warlock"],
    "shaman": ["schamane", "shaman", "classicon_shaman"],
}
PO_ITEM_EMOJI_ALIASES = {
    "amulett von veknilash": ["amulett_von_veknilash"],
    "auge von c'thun": ["auge_von_cthun_"],
    "auge des todes": ["auge_des_todes"],
    "armreifen der königlichen erlösung": ["armreifen_der_kniglichen_erlsung"],
    "band der unerhörten gebete": ["_band_der_unerhrten_gebete", "band_der_unerhrten_gebete"],
    "band der unnatürlichen kräfte": ["band_der_unnatrlichen_krfte_", "band_der_unnatuerlichen_kraefte"],
    "die gebundene essenz saphirons": ["die_gebundene_essenz_saphirons"],
    "gebundene essenz von saphiron": ["die_gebundene_essenz_saphirons"],
    "die zehrende kälte": ["die_zehrende_klte", "die_zehrende_kaelte"],
    "fetisch des sandhäschers": ["fetisch_des_sandhschers", "fetisch_des_sandhaeschers"],
    "formel: brust - große werte": ["formel_brust__groe_werte_"],
    "gressil, vorbote des untergangs": ["gressil_vorbote_des_untergangs"],
    "hammer des wirbelnden nethers": ["hammer_des_wirbelnden_nethers_"],
    "ring des märtyrers": ["ring_des_mrtyrers"],
    "saphirons linkes auge": ["saphirons_linkes_auge"],
    "schild der geißelung": ["_schild_der_geielung", "schild_der_geisselung"],
    "szepter des falschen propheten": ["szepter_des_falschen_propheten"],
    "stulpen der vernichtung": ["stulpen_der_vernichtung"],
    "stulpen der dunklen stürme": ["stulpen_der_dunklen_strme"],
    "umhang des geballten hasses": ["umhang_des_geballten_hasses"],
    "wappen des schlächters": ["wappen_des_schlchters_", "wappen_des_schlaechters"],
}
SPEC_EMOJI_FALLBACKS = {
    "tank": "🛡️",
    "heal": "➕",
    "holy": "➕",
    "paladin_holy": "✨",
    "priest_holy": "➕",
    "discipline": "💠",
    "shadow": "🌑",
    "arms": "⚔️",
    "fury": "⚔️",
    "retri": "✨",
    "fire": "🔥",
    "frost": "❄️",
    "arcane": "✦",
    "assassination": "🗡️",
    "subtlety": "🗡️",
    "combat": "🗡️",
    "affliction": "💀",
    "demonology": "💀",
    "destruction": "🔥",
    "feral": "⚔️",
    "balance": "🌑",
    "survival": "🏹",
    "marksman": "🏹",
    "beastmaster": "🏹",
    "elemental": "⚡",
    "enhancement": "⚡",
}
SPEC_EMOJI_NAME_ALIASES = {
    "tank": ["tank", "prot", "schutz"],
    "heal": ["heilung", "heal", "heiler", "resto", "restoration"],
    "holy": ["holy", "heilig"],
    "paladin_holy": ["holy_pala", "paladin_holy", "pala_holy", "palaholy", "holy_paladin", "heilig_paladin"],
    "priest_holy": ["holy_priester", "priest_holy", "priester_holy", "holy_priest", "heilig_priester"],
    "discipline": ["disziplin", "discipline", "disc"],
    "shadow": ["schatten", "shadow"],
    "arms": ["arms", "waffen"],
    "fury": ["fury"],
    "retri": ["retri", "ret", "vergeltung"],
    "fire": ["feuer", "fire"],
    "frost": ["frost", "eis"],
    "arcane": ["arkan", "arcane"],
    "assassination": ["assassination", "assa"],
    "subtlety": ["subtlety", "sub"],
    "combat": ["combat", "kampf"],
    "affliction": ["affliction", "affli", "gebrechen"],
    "demonology": ["demonology", "demo"],
    "destruction": ["destruction", "destro", "zerstoerung"],
    "feral": ["feraldd", "feral"],
    "balance": ["eule", "balance", "moonkin"],
    "survival": ["survival"],
    "marksman": ["marksman", "marksmanship"],
    "beastmaster": ["beastmaster", "beastmastery", "bm"],
    "elemental": ["elemental", "ele"],
    "enhancement": ["enhancement", "enh"],
}
RAID_SIGNUP_SPECS = {
    "Warrior": [("Arms", "arms"), ("Fury", "fury"), ("Tank", "tank")],
    "Druid": [("Heilung", "heal"), ("Tank", "tank"), ("FeralDD", "feral"), ("Eule", "balance")],
    "Paladin": [("Holy", "paladin_holy"), ("Retri", "retri"), ("Tank", "tank")],
    "Rogue": [("Assassination", "assassination"), ("Combat", "combat"), ("Subtlety", "subtlety")],
    "Hunter": [("Survival", "survival"), ("Marksman", "marksman"), ("Beastmaster", "beastmaster")],
    "Priest": [("Disziplin", "discipline"), ("Holy", "priest_holy"), ("Schatten", "shadow")],
    "Mage": [("Fire", "fire"), ("Frost", "frost"), ("Arcane", "arcane")],
    "Warlock": [("Affliction", "affliction"), ("Demonology", "demonology"), ("Destruction", "destruction")],
    "Shaman": [("Heilung", "heal"), ("Elemental", "elemental"), ("Enhancement", "enhancement")],
}
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
P0_RELEASE_CSV_URL = os.getenv(
    "P0_RELEASE_CSV_URL",
    "https://docs.google.com/spreadsheets/d/1ejape-5N42TDUIsglYZV1uPupQxYMiUK6JE1QiPJKbE/export?format=csv&gid=0"
)
P0_RELEASE_CACHE = {}
P0_RELEASE_CACHE_TIME = None
P0_RELEASE_CACHE_SECONDS = 300
P0_RELEASE_REFRESHING = False

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
P0_POST_FILE = "p0_posts.json"
P0_POST_UPDATE_LOCKS = {}
PO_POST_FILE = "po_posts.json"
PO_POST_LOCKS = {}
LICHTLOOT_QUEUE_IN_PROGRESS = set()
LICHTLOOT_QUEUE_RECENTLY_DONE = {}
P0_REVIEW_TEST_NAMES = {"ariee", "juksi"}
P0_REVIEW_LIVE_NAMES = {"kaese", "käse", "blondi", "blondie"}
P0_REVIEW_TEST_MODE = os.getenv("P0_REVIEW_TEST_MODE", "true").lower() != "false"
RAID_ANNOUNCEMENT_FILE = "raid_announcements.json"
HORDENBUFF_CLEANUP_DELAY_MINUTES = 5
HORDENBUFF_CLEANUP_WINDOW_MINUTES = 45
HORDENBUFF_UPDATE_MIN_SECONDS = 30
DISCORD_RATE_LIMIT_FALLBACK_SECONDS = 300
RAID_ANNOUNCEMENT_CHECK_SECONDS = 60
LICHTLOOT_QUEUE_CHECK_SECONDS = 30
LICHTLOOT_URL = "https://lichtloot.de"
DEFAULT_RAID_HELPER_CHANNEL_ID = "1508478036398571601"
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
class_emoji_cache = {}
spec_emoji_cache = {}
item_emoji_cache = {}


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


def p0_post_file():
    return guild_scoped_file(P0_POST_FILE)


def po_post_file():
    return guild_scoped_file(PO_POST_FILE)


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
    return {TICKER_CHANNEL_ID, POST_CHANNEL_ID}


def can_post_worldbuff_overview():
    return current_guild_slug() == LICHTLOOT_GUILD_SLUG


def is_ticker_channel(channel_id):
    return int(channel_id) in TICKER_CHANNEL_IDS


def is_worldbuff_poster_source_message(message):
    return str(getattr(message, "id", "") or "") in WORLDBUFF_POSTER_MESSAGE_IDS


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


async def delete_message_later(message, seconds=15):
    if not message:
        return
    try:
        await asyncio.sleep(seconds)
        await message.delete()
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


def clean_hordenbuff_name(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def hordenbuff_name_key(value):
    return clean_hordenbuff_name(value).casefold()


def add_unique_hordenbuff_name(names, name):
    clean_name = clean_hordenbuff_name(name)
    if not clean_name:
        return
    key = hordenbuff_name_key(clean_name)
    if not any(hordenbuff_name_key(existing) == key for existing in names):
        names.append(clean_name)


def remove_hordenbuff_name(names, name):
    key = hordenbuff_name_key(name)
    return [existing for existing in names if hordenbuff_name_key(existing) != key]


def find_hordenbuff_takeover_key(takeovers, helper_name):
    helper_key = hordenbuff_name_key(helper_name)
    for existing_helper in list(takeovers.keys()):
        if hordenbuff_name_key(existing_helper) == helper_key:
            return existing_helper
    return None


def set_hordenbuff_takeover(data, helper_name, target_name):
    helper_name = clean_hordenbuff_name(helper_name)
    target_name = clean_hordenbuff_name(target_name)
    data.setdefault("uebernahmen", {})
    data.setdefault("helfer", [])
    add_unique_hordenbuff_name(data["helfer"], helper_name)

    existing_helper = find_hordenbuff_takeover_key(data["uebernahmen"], helper_name)
    if existing_helper and existing_helper != helper_name:
        del data["uebernahmen"][existing_helper]

    target_key = hordenbuff_name_key(target_name)
    for helper, target in list(data["uebernahmen"].items()):
        if hordenbuff_name_key(target) == target_key and hordenbuff_name_key(helper) != hordenbuff_name_key(helper_name):
            del data["uebernahmen"][helper]

    data["uebernahmen"][helper_name] = target_name


def dedupe_hordenbuff_state(data):
    data.setdefault("spieler", [])
    data.setdefault("helfer", [])
    data.setdefault("uebernahmen", {})

    deduped_players = []
    for name in data.get("spieler", []):
        add_unique_hordenbuff_name(deduped_players, name)
    data["spieler"] = deduped_players

    deduped_helpers = []
    for name in data.get("helfer", []):
        add_unique_hordenbuff_name(deduped_helpers, name)
    data["helfer"] = deduped_helpers

    deduped_takeovers = {}
    for helper, target in data.get("uebernahmen", {}).items():
        helper_name = clean_hordenbuff_name(helper)
        target_name = clean_hordenbuff_name(target)
        if not helper_name or not target_name:
            continue
        existing_helper = find_hordenbuff_takeover_key(deduped_takeovers, helper_name)
        if existing_helper:
            del deduped_takeovers[existing_helper]
        target_key = hordenbuff_name_key(target_name)
        for old_helper, old_target in list(deduped_takeovers.items()):
            if hordenbuff_name_key(old_target) == target_key:
                del deduped_takeovers[old_helper]
        deduped_takeovers[helper_name] = target_name
        add_unique_hordenbuff_name(data["helfer"], helper_name)
    data["uebernahmen"] = deduped_takeovers
    return data


async def hordenbuff_signup_core(ally_char="", horde_char="", author_name=""):
    rend = await asyncio.to_thread(get_next_horden_rend_safe)

    if not rend:
        return "⚠️ Es wurde kein kommender Rend-Termin gefunden."

    ally_char = clean_hordenbuff_name(ally_char)
    horde_char = clean_hordenbuff_name(horde_char)

    if not ally_char and not horde_char:
        return "Bitte trage mindestens einen Namen ein: Ally-Char oder Horden-Char."

    data = await asyncio.to_thread(merge_hordenbuff_sheet_data, rend, load_hordenbuff_state(rend))
    data.setdefault("spieler", [])
    data.setdefault("uebernahmen", {})
    data.setdefault("helfer", [])

    add_unique_hordenbuff_name(data["spieler"], ally_char)

    add_unique_hordenbuff_name(data["helfer"], horde_char)

    if ally_char and horde_char:
        alte_helfer = [
            helper
            for helper, target
            in data["uebernahmen"].items()
            if hordenbuff_name_key(target) == hordenbuff_name_key(ally_char)
        ]

        for helper in alte_helfer:
            del data["uebernahmen"][helper]

        set_hordenbuff_takeover(data, horde_char, ally_char)
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
            set_hordenbuff_takeover(data, horde_char, ziel)
            status = "zugeteilt"
            note = "Benötigt Buff für aktiven Termin; Helfer zugeteilt"
            sheet_char = ziel
            result_text = f"✅ **{horde_char}** hilft und übernimmt **{ziel}**."
        else:
            status = "offen"
            note = "Helfer bereit; noch kein Ally-Char offen"
            sheet_char = ""
            result_text = f"✅ **{horde_char}** ist als Horden-Helfer eingetragen."

    save_json(hordenbuff_file(), dedupe_hordenbuff_state(data))

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
    table_patterns = [
        re.compile(r"^" + buff_words + r"\s+" + date_words + r"\s+" + day_words + r"\s+" + time_words + suffix, re.IGNORECASE),
        re.compile(r"^" + buff_words + r"\s+" + date_words + r"\s+" + time_words + suffix, re.IGNORECASE),
    ]

    for line in text.splitlines():
        line = line.strip()
        line = line.replace("**", "").replace("`", "")
        line = line.strip("| ")
        line = re.sub(r"\s*\|\s*", " ", line)
        line = re.sub(r"\s+", " ", line)
        if not line or re.match(r"^[\\/|_\-= ]+$", line):
            continue
        if re.search(r"\bbuff\b.*\bdatum\b.*\buhrzeit\b.*\bgilde\b", line, re.IGNORECASE):
            continue

        match = None
        matched_pattern_index = -1
        for index, pattern in enumerate(patterns):
            match = pattern.match(line)
            if match:
                matched_pattern_index = index
                break
        if not match:
            for pattern in table_patterns:
                match = pattern.match(line)
                if match:
                    matched_pattern_index = 0
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
                "gilde": re.sub(r"^(?:Mo|Di|Mi|Do|Fr|Sa|So|Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\s+", "", gilde.strip(), flags=re.IGNORECASE)
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
    existing_identity = {
        make_overview_dedupe_key(b): index
        for index, b in enumerate(data)
    }

    added = 0

    for buff in new_buffs:
        key = make_buff_key(buff)
        identity_key = make_overview_dedupe_key(buff)

        if key not in existing_keys:
            old_index = existing_identity.get(identity_key)
            if old_index is not None:
                old_key = make_buff_key(data[old_index])
                data[old_index] = buff
                existing_keys.discard(old_key)
                existing_keys.add(key)
                continue
            data.append(buff)
            existing_keys.add(key)
            existing_identity[identity_key] = len(data) - 1
            added += 1

    return added


def discord_message_search_text(message):
    parts = [message.content or ""]

    for embed in getattr(message, "embeds", []) or []:
        for value in [
            getattr(embed, "title", ""),
            getattr(embed, "description", "")
        ]:
            if value:
                parts.append(str(value))

        for field in getattr(embed, "fields", []) or []:
            if getattr(field, "name", ""):
                parts.append(str(field.name))
            if getattr(field, "value", ""):
                parts.append(str(field.value))

        footer = getattr(embed, "footer", None)
        if footer and getattr(footer, "text", ""):
            parts.append(str(footer.text))

    return "\n".join(part for part in parts if part)


def build_overview():
    sheet_buffs = import_buffs_aus_sheet()
    data = list(sheet_buffs)
    local_ticker_buffs = [
        buff for buff in load_json(worldbuff_file(), [])
        if isinstance(buff, dict) and not is_deleted_worldbuff(buff)
    ]
    if local_ticker_buffs:
        merge_buffs_into_data(data, local_ticker_buffs)

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


def current_worldbuff_announcement_block(max_lines=8):
    sheet_buffs = import_buffs_aus_sheet()
    data = list(sheet_buffs)
    local_ticker_buffs = [
        buff for buff in load_json(worldbuff_file(), [])
        if isinstance(buff, dict) and not is_deleted_worldbuff(buff)
    ]
    if local_ticker_buffs:
        merge_buffs_into_data(data, local_ticker_buffs)

    if not data:
        return ""

    werfer = import_werfer_aus_sheet()
    today = datetime.now(BERLIN_TZ).date()
    max_date = today + timedelta(days=7)
    rows = []
    seen = set()

    for buff in data:
        try:
            buff_date = datetime.strptime(buff.get("datum", ""), "%d.%m.%Y").date()
        except Exception:
            continue
        if not (today <= buff_date <= max_date):
            continue
        key = make_overview_dedupe_key(buff)
        if key in seen:
            continue
        seen.add(key)
        rows.append(buff)

    rows.sort(key=lambda item: (datetime.strptime(item["datum"], "%d.%m.%Y"), item.get("uhrzeit", "")))
    if not rows:
        return ""

    lines = [
        "**VEM zuletzt** (falls mal ein anderer Käfer gewünscht wird, gerne für nächste Woche aufzeigen)",
        "",
        "Wir spielen wie immer mit WB's! Jeder kennt die Regeln! Sollten dennoch einige Spieler meinen ihre WB's nicht zu nutzen, ohne dies vorher abzusprechen, behalten wir uns weiter Maßnahmen vor!",
        ""
    ]
    current_date = ""
    added = 0

    for buff in rows:
        if added >= max_lines:
            remaining = len(rows) - added
            if remaining > 0:
                lines.append(f"... und {remaining} weitere Worldbuff-Termine im Worldbuff-Post.")
            break

        datum = buff.get("datum", "")
        tag_kurz = buff.get("tag") or make_tag_from_date(datum)
        tag_lang = TAG_LANG.get(tag_kurz, tag_kurz)
        if datum != current_date:
            lines.append(f"**{tag_lang}, {datum}**")
            current_date = datum

        buff_name = normalize_buff(buff.get("buff", ""))
        gilde = buff.get("gilde", "")
        key = make_buff_key(buff)
        info = werfer.get(key)
        charakter = buff.get("charakter") or (info and info.get("charakter")) or ""
        werfer_text = f" - {'🔵' if is_lichtbringer(gilde) else '⚔️'} {charakter}" if charakter else ""
        emoji = BUFF_EMOJIS.get(buff_name, "⚪")
        lines.append(f"{emoji} **{buff_name}** {buff.get('uhrzeit', '')} - {gilde}{werfer_text}")
        added += 1

    return "\n".join(lines).strip()


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


async def fetch_worldbuff_post_messages(channel):
    post_data = load_json(worldbuff_post_file(), {})
    message_ids = post_data.get("message_ids")
    message_id = post_data.get("message_id")

    if not message_ids and message_id:
        message_ids = [message_id]
    if not isinstance(message_ids, list):
        message_ids = []

    messages = []
    for message_id in message_ids:
        try:
            messages.append(await channel.fetch_message(int(message_id)))
        except:
            pass
    return messages


def is_own_discord_message(message):
    return bool(client.user and message.author and message.author.id == client.user.id)


def is_worldbuff_overview_message(message):
    content = message.content or ""
    if content.startswith("📢 **Worldbuffs**") or content.startswith("📢 **Worldbuff Übersicht**"):
        return True

    return any(
        embed.title == "Worldbuff eintragen"
        for embed in getattr(message, "embeds", []) or []
    )


def is_hordenbuff_overview_message(message):
    content = message.content or ""
    if content.startswith("🪓 **Horde-Rend Koordination**"):
        return True

    return any(
        embed.title == "Hordenbuffs eintragen"
        for embed in getattr(message, "embeds", []) or []
    )


async def find_recent_own_messages(channel, matches, limit=100):
    found = []

    try:
        async for message in channel.history(limit=limit):
            if is_own_discord_message(message) and matches(message):
                found.append(message)
    except Exception as e:
        print(f"Discord-Historie konnte in Channel {getattr(channel, 'id', '?')} nicht gelesen werden:", e)

    return found


async def delete_extra_messages(messages):
    for message in messages[1:]:
        try:
            await message.delete()
            await asyncio.sleep(0.4)
        except Exception:
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
            for message_id in WORLDBUFF_POSTER_MESSAGE_IDS:
                try:
                    source_msg = await channel.fetch_message(int(message_id))
                    found_buffs.extend(parse_ticker_message(discord_message_search_text(source_msg)))
                except discord.NotFound:
                    pass
                except Exception as e:
                    print(f"Worldbuff-Poster-Message {message_id} in Channel {channel_id} konnte nicht gelesen werden:", e)

            async for msg in channel.history(limit=limit):
                found_buffs.extend(parse_ticker_message(discord_message_search_text(msg)))
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
        return 0

    channel = client.get_channel(POST_CHANNEL_ID)

    if channel is None:
        print("Ziel-Channel nicht gefunden.")
        return 0

    if sync_ticker:
        await sync_recent_ticker_messages()
    text = await asyncio.to_thread(build_overview)
    guide_embed = build_worldbuff_guide_embed()
    existing_messages = await fetch_worldbuff_post_messages(channel)
    known_message_ids = {message.id for message in existing_messages}
    recent_messages = await find_recent_own_messages(channel, is_worldbuff_overview_message, limit=100)

    if recent_messages:
        if not existing_messages:
            print(f"Worldbuff-Uebersicht im Channel wiedergefunden: {len(recent_messages)} Nachricht(en).")
        existing_messages.extend(message for message in recent_messages if message.id not in known_message_ids)

    if len(text) <= 1900:
        if existing_messages:
            msg = existing_messages[0]
            await msg.edit(content=text, embed=guide_embed)
            await delete_extra_messages(existing_messages)
        else:
            msg = await send_silent(channel, text, embed=guide_embed)
        save_json(worldbuff_post_file(), {"message_id": msg.id, "message_ids": [msg.id]})
        return 1
    else:
        chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
        last_msg = None
        message_ids = []

        for index, chunk in enumerate(chunks):
            if index < len(existing_messages):
                last_msg = existing_messages[index]
                await last_msg.edit(content=chunk, embed=guide_embed if index == 0 else None)
            else:
                last_msg = await send_silent(channel, chunk, embed=guide_embed if index == 0 else None)
            message_ids.append(last_msg.id)

        for old_msg in existing_messages[len(chunks):]:
            try:
                await old_msg.delete()
            except:
                pass

        if last_msg:
            save_json(worldbuff_post_file(), {"message_id": last_msg.id, "message_ids": message_ids})
        return len(message_ids)


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


def get_upcoming_horden_rend_entries(limit=None):
    rows = iter_hordenbuff_railway_rows()
    now = datetime.now(BERLIN_TZ).replace(tzinfo=None)
    rend_termine = []
    seen_events = set()

    for row in rows:
        if normalize_buff(row.get("buff", "Rend")) != "Rend":
            continue

        try:
            dt = datetime.strptime(
                f"{row['datum']} {row['uhrzeit']}",
                "%d.%m.%Y %H:%M"
            )

            if dt >= now:
                event_key = f"{row.get('datum', '')}|{row.get('uhrzeit', '')}"
                if event_key in seen_events:
                    continue
                seen_events.add(event_key)
                rend_termine.append((dt, {
                    "buff": "Rend",
                    "datum": row.get("datum", ""),
                    "tag": row.get("tag", "") or make_tag_from_date(row.get("datum", "")),
                    "uhrzeit": row.get("uhrzeit", ""),
                    "gilde": row.get("gilde", "") or "Horde",
                    "charakter": row.get("charakter", ""),
                    "uebernehmer": row.get("uebernehmer", ""),
                    "status": row.get("status", ""),
                    "notiz": row.get("notiz", "")
                }))

        except:
            continue

    rend_termine.sort(key=lambda x: x[0])
    entries = [buff for _, buff in rend_termine]

    if limit is None:
        return entries

    return entries[:limit]


def get_next_horden_rend():
    upcoming = get_upcoming_horden_rend_entries(limit=1)
    return upcoming[0] if upcoming else None


def get_upcoming_horden_rends(limit=4):
    return get_upcoming_horden_rend_entries(limit=limit)



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
            add_unique_hordenbuff_name(synced["spieler"], charakter)

        if uebernehmer and uebernehmer != "-":
            add_unique_hordenbuff_name(synced["helfer"], uebernehmer)
            if charakter and charakter != "-":
                set_hordenbuff_takeover(synced, uebernehmer, charakter)

    return dedupe_hordenbuff_state(synced)


def get_assigned_targets(data):
    return {
        hordenbuff_name_key(target)
        for target in data.get("uebernahmen", {}).values()
    }


def get_next_unassigned_char(data):
    assigned = get_assigned_targets(data)

    for charakter in data.get("spieler", []):
        if hordenbuff_name_key(charakter) not in assigned:
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
            if hordenbuff_name_key(name) in assigned:
                text += f"✅ {name} _(zugeteilt)_\n"
            else:
                text += f"✅ {name}\n"
    else:
        text += "-\n"

    text += "\n🛡️ **Übernahmen / Helfer:**\n"

    uebernahmen = data.get("uebernahmen", {})
    helfer_liste = data.get("helfer", [])
    zugeteilte_helfer = {hordenbuff_name_key(name) for name in uebernahmen.keys()}
    freie_helfer = [name for name in helfer_liste if hordenbuff_name_key(name) not in zugeteilte_helfer]

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
        return 0

    async with hordenbuff_update_lock:
        now = time.monotonic()
        if now < hordenbuff_rate_limited_until:
            rest = int(hordenbuff_rate_limited_until - now)
            print(f"Hordenbuff-Update uebersprungen: Discord Rate Limit noch {rest} Sekunden aktiv.")
            return 0

        if not force and now - hordenbuff_last_update_at < HORDENBUFF_UPDATE_MIN_SECONDS:
            print("Hordenbuff-Update uebersprungen: Aktualisierung wurde gerade erst ausgefuehrt.")
            return 0

        hordenbuff_last_update_at = now

        rend = await asyncio.to_thread(get_next_horden_rend_safe)
        updated_count = 0

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
                    await send_silent(
                        channel,
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
            found_messages = await find_recent_own_messages(channel, is_hordenbuff_overview_message, limit=100)

            try:
                msg = None
                if message_id:
                    try:
                        msg = await channel.fetch_message(message_id)
                    except discord.NotFound:
                        msg = None
                    except Exception as e:
                        print(f"Gespeicherter Hordenbuff-Post {message_id} konnte nicht geladen werden:", e)

                if not msg:
                    msg = found_messages[0] if found_messages else None

                if not msg:
                    msg = await send_silent(channel, text, embed=guide_embed)
                else:
                    await msg.edit(content=text, embed=guide_embed)

                duplicates = [message for message in found_messages if message.id != msg.id]
                await delete_extra_messages([msg] + duplicates)
                set_hordenbuff_message_id(data, channel_id, msg.id)
                save_json(hordenbuff_file(), data)
                updated_count += 1

            except discord.HTTPException as e:
                if is_discord_rate_limit(e):
                    block_discord_writes_after_rate_limit(e, "Hordenbuff-Update")
                    return updated_count

                print(f"Hordenbuff-Update Discord-Fehler in {channel_id}: {e}")

            except Exception as e:
                print(f"Hordenbuff-Update Fehler in {channel_id}: {e}")
        return updated_count


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

    add_unique_hordenbuff_name(data["spieler"], charakter)

    save_json(hordenbuff_file(), dedupe_hordenbuff_state(data))

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

    helfer_name = clean_hordenbuff_name(helfer_name)
    add_unique_hordenbuff_name(data["helfer"], helfer_name)

    existing_helper = find_hordenbuff_takeover_key(data.get("uebernahmen", {}), helfer_name)
    if existing_helper:
        ziel = data["uebernahmen"][existing_helper]

        save_json(hordenbuff_file(), dedupe_hordenbuff_state(data))
        await send_temp(
            message.channel,
            f"ℹ️ {helfer_name} ist bereits für **{ziel}** eingeteilt."
        )

        await update_hordenbuff_post(force=True)
        await delete_command_message(message)
        return

    ziel = get_next_unassigned_char(data)

    if not ziel:
        save_json(hordenbuff_file(), dedupe_hordenbuff_state(data))
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

    set_hordenbuff_takeover(data, helfer_name, ziel)

    save_json(hordenbuff_file(), dedupe_hordenbuff_state(data))

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

    ziel = clean_hordenbuff_name(ziel)
    helfer_name = clean_hordenbuff_name(helfer_name)
    data.setdefault("spieler", [])
    add_unique_hordenbuff_name(data["spieler"], ziel)

    data.setdefault("uebernahmen", {})
    data.setdefault("helfer", [])

    add_unique_hordenbuff_name(data["helfer"], helfer_name)

    alte_helfer = [
        helper
        for helper, target
        in data["uebernahmen"].items()
        if hordenbuff_name_key(target) == hordenbuff_name_key(ziel)
    ]

    for helper in alte_helfer:
        del data["uebernahmen"][helper]

    set_hordenbuff_takeover(data, helfer_name, ziel)

    save_json(hordenbuff_file(), dedupe_hordenbuff_state(data))

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
    helfer_name = clean_hordenbuff_name(message.author.display_name)
    charakter = clean_hordenbuff_name(charakter)

    data.setdefault("uebernahmen", {})
    data.setdefault("helfer", [])

    add_unique_hordenbuff_name(data["helfer"], helfer_name)

    set_hordenbuff_takeover(data, helfer_name, charakter)

    save_json(hordenbuff_file(), dedupe_hordenbuff_state(data))

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
    charakter_key = hordenbuff_name_key(charakter)

    data["spieler"] = [
        name for name in data.get("spieler", [])
        if hordenbuff_name_key(name) != charakter_key
    ]

    remove_helpers = []

    for helper, ziel in data.get("uebernahmen", {}).items():
        if hordenbuff_name_key(ziel) == charakter_key or hordenbuff_name_key(helper) == charakter_key:
            remove_helpers.append(helper)

    for helper in remove_helpers:
        del data["uebernahmen"][helper]

    data["helfer"] = [
        name for name in data.get("helfer", [])
        if hordenbuff_name_key(name) != charakter_key
    ]

    save_json(hordenbuff_file(), dedupe_hordenbuff_state(data))

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
                await send_silent(channel, reminder_text)

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
DISCORD_CHANNEL_SYNC_INTERVAL_SECONDS = 900


def get_primary_raid_channel_id(raid):
    raid = normalize_raid_name(raid)
    sources = DISCORD_RAIDHELPER_SOURCES.get(raid, [])
    if not sources:
        return None
    return sources[0].get("channel_id")


async def sync_accessible_discord_channels():
    if not LICHTBOT_QUEUE_TOKEN:
        print("Discord-Channel-Sync uebersprungen: LICHTBOT_QUEUE_TOKEN fehlt.")
        return {"success": False, "error": "LICHTBOT_QUEUE_TOKEN fehlt."}

    channels = []
    for guild in client.guilds:
        member = guild.me or guild.get_member(client.user.id)
        if member is None:
            continue

        for channel in getattr(guild, "text_channels", []):
            permissions = channel.permissions_for(member)
            if not permissions.view_channel or not permissions.send_messages:
                continue
            channels.append({
                "id": str(channel.id),
                "name": channel.name,
                "type": "text",
                "category": channel.category.name if channel.category else "",
                "position": int(getattr(channel, "position", 0) or 0),
                "canSend": True,
                "discordGuildId": str(guild.id),
                "discordGuildName": guild.name,
            })

    result = await asyncio.to_thread(lichtloot_post, {
        "action": "lichtbotSaveDiscordChannels",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "channels": channels
    })
    print(f"Discord-Channel-Sync gespeichert: {result.get('saved', 0)} Channels.")
    return result


async def discord_channel_sync_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            await sync_accessible_discord_channels()
        except Exception as e:
            print("Discord-Channel-Sync Fehler:", e)
        await asyncio.sleep(DISCORD_CHANNEL_SYNC_INTERVAL_SECONDS)


def normalize_raid_name(value):
    raid = str(value or "").strip().upper()
    compact = re.sub(r"[^A-Z0-9]+", "", raid)
    aliases = {
        "ONYXIA": "ONY",
        "ONIXIA": "ONY",
        "NAXXRAMAS": "NAXX",
        "AQ": "AQ40"
    }
    if "AQ40" in compact or "AHNQIRAJ40" in compact:
        return "AQ40"
    if "AQ20" in compact:
        return "AQ20"
    if "ZULGURUB" in compact or compact.startswith("ZG"):
        return "ZG"
    if "NAXX" in compact:
        return "NAXX"
    if "BLACKWING" in compact or compact.startswith("BWL"):
        return "BWL"
    if "MOLTENCORE" in compact or compact.startswith("MC"):
        return "MC"
    if "ONY" in compact:
        return "ONY"
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
    await send_silent(
        channel,
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
    description = str(raid.get("description") or "").strip()
    max_players = str(raid.get("maxPlayers") or "").strip()
    tank_slots = str(raid.get("tankSlots") or "").strip()
    heal_slots = str(raid.get("healSlots") or "").strip()
    dd_slots = str(raid.get("ddSlots") or "").strip()
    signup_deadline = format_raid_announcement_time(raid.get("signupDeadline") or raid.get("signup_deadline") or "")
    created_by = str(
        raid.get("createdBy") or
        raid.get("erstelltVon") or
        raid.get("created_by") or
        "Unbekannt"
    ).strip()

    lines = [
        f"**{raid_name.upper()}**",
        "",
    ]
    if description:
        lines.extend([description, ""])

    lines.extend([
        f"📣 **Raidlead:** {created_by}",
        f"🗓️ **Datum:** {raid_date}",
        f"⏰ **Start:** {raid_time}",
    ])

    if max_players or tank_slots or heal_slots or dd_slots:
        slot_parts = []
        if max_players:
            slot_parts.append(f"Gesamt {max_players}")
        if tank_slots:
            slot_parts.append(f"Tanks {tank_slots}")
        if heal_slots:
            slot_parts.append(f"Heals {heal_slots}")
        if dd_slots:
            slot_parts.append(f"DD {dd_slots}")
        lines.append("👥 **Slots:** " + " · ".join(slot_parts))

    lines.extend([
        "",
        f"🔑 **Prio-PIN:** `{player_pin}`",
        f"🌐 **Webansicht:** {LICHTLOOT_URL}",
        "",
        "Bitte meldet euch im Discord an und tragt eure Prios rechtzeitig ein."
    ])

    worldbuff_block = current_worldbuff_announcement_block()
    if worldbuff_block:
        lines.extend(["", "", worldbuff_block])

    text = "\n".join(lines)

    return text[:1900]


def build_raid_announcement_embed(raid):
    raid_short = normalize_raid_name(raid.get("raid") or raid.get("raidName") or "")
    raid_name = str(raid.get("raidName") or raid_short or "Raid").strip()
    raid_date = format_raid_announcement_date(raid.get("raidDate"))
    raid_time = format_raid_announcement_time(raid.get("raidTime"))
    player_pin = str(raid.get("playerPin") or "").strip() or "-"
    description = str(raid.get("description") or "").strip()
    max_players = str(raid.get("maxPlayers") or "").strip()
    tank_slots = str(raid.get("tankSlots") or "").strip()
    heal_slots = str(raid.get("healSlots") or "").strip()
    dd_slots = str(raid.get("ddSlots") or "").strip()
    signup_deadline = format_raid_announcement_time(raid.get("signupDeadline") or raid.get("signup_deadline") or "")
    created_by = str(
        raid.get("createdBy") or
        raid.get("erstelltVon") or
        raid.get("created_by") or
        "Gildenleitung"
    ).strip()
    description_text = (description or "Raidanmeldung ist geöffnet.").strip()

    embed = discord.Embed(
        title=raid_name.upper(),
        description=description_text[:3900],
        color=0x7c3aed
    )
    embed.add_field(name="Raidlead", value=created_by, inline=True)
    embed.add_field(name="Datum", value=raid_date, inline=True)
    embed.add_field(name="Start", value=raid_time, inline=True)
    if signup_deadline != "noch offen":
        embed.add_field(name="Anmeldeschluss", value=signup_deadline, inline=False)

    slot_parts = []
    if max_players:
        slot_parts.append(f"Gesamt {max_players}")
    if tank_slots:
        slot_parts.append(f"Tanks {tank_slots}")
    if heal_slots:
        slot_parts.append(f"Heals {heal_slots}")
    if dd_slots:
        slot_parts.append(f"DD {dd_slots}")
    if slot_parts:
        embed.add_field(name="Slots", value=" · ".join(slot_parts), inline=False)

    embed.add_field(name="Prio-PIN", value=f"`{player_pin}`", inline=True)
    embed.add_field(name="Webansicht", value=LICHTLOOT_URL, inline=True)
    worldbuff_block = current_worldbuff_announcement_block()
    if worldbuff_block:
        embed.add_field(name="Aktuelle Worldbuffs", value=worldbuff_block[:1024], inline=False)
    image_url = raid_image_url(raid)
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text="Bitte meldet euch im Discord an und tragt eure Prios rechtzeitig ein.")
    return embed


def raid_key_for_image(raid):
    return normalize_raid_name(raid.get("raid") or raid.get("raidName") or "").lower()


def raid_banner_attachment_name(raid):
    return ""


def raid_banner_file(raid):
    return None


def raid_image_url(raid):
    explicit = str(raid.get("raidImageUrl") or raid.get("imageUrl") or "").strip()
    if explicit.startswith("http://") or explicit.startswith("https://"):
        replaced = re.sub(
            r"https://(?:www\.)?lichtloot\.de/images/(?:raid-banners/)?(zg|aq20|aq40|bwl|mc|naxx|ony)\.jpg(?:[?#].*)?$",
            r"https://lichtloot-production.up.railway.app/images/raid-banners/\1.jpg",
            explicit,
            flags=re.IGNORECASE
        )
        replaced = re.sub(
            r"/images/(zg|aq20|aq40|bwl|mc|naxx|ony)\.jpg(?:[?#].*)?$",
            r"/images/raid-banners/\1.jpg",
            replaced,
            flags=re.IGNORECASE
        )
        return replaced
    raid_key = normalize_raid_name(raid.get("raid") or raid.get("raidName") or "").lower()
    image_map = {
        "zg": "zg.jpg",
        "aq20": "aq20.jpg",
        "aq40": "aq40.jpg",
        "bwl": "bwl.jpg",
        "mc": "mc.jpg",
        "naxx": "naxx.jpg",
        "ony": "ony.jpg",
    }
    filename = image_map.get(raid_key)
    return f"https://lichtloot-production.up.railway.app/images/raid-banners/{filename}" if filename else ""


def infer_signup_role(spec_text):
    text = str(spec_text or "").strip().lower()
    if any(word in text for word in ["tank", "prot", "schutz", "def"]):
        return "tank"
    if any(word in text for word in ["heal", "heiler", "holy", "heilig", "resto", "restoration", "diszi", "disziplin", "discipline"]):
        return "heal"
    if any(word in text for word in ["dd", "dps", "damage", "fury", "arms", "waffen", "fire", "feuer", "frost", "shadow", "schatten", "combat", "assa", "feral", "balance", "ele", "enh", "retri", "survival", "marksman", "beastmaster", "affliction", "demonology", "destruction"]):
        return "dd"
    return "flex"


def signup_class_icon(class_name):
    key = str(class_name or "").strip().lower()
    aliases = {
        "krieger": "warrior",
        "druide": "druid",
        "schurke": "rogue",
        "jäger": "hunter",
        "jaeger": "hunter",
        "jager": "hunter",
        "priester": "priest",
        "magier": "mage",
        "hexenmeister": "warlock",
        "schamane": "shaman",
    }
    key = aliases.get(key, key)
    env_name, emoji_name = CLASS_EMOJI_ENV.get(key, ("", ""))
    raw = str(os.getenv(env_name, "") or "").strip()
    if raw.startswith("<:") or raw.startswith("<a:"):
        return raw
    if raw.isdigit() and len(raw) >= 15:
        return f"<:{emoji_name}:{raw}>"
    cached = class_emoji_cache.get(key)
    if cached:
        return cached
    return CLASS_EMOJI_FALLBACKS.get(key, "◆")


def signup_class_select_emoji(class_name):
    icon = signup_class_icon(class_name)
    if icon.startswith("<:") or icon.startswith("<a:"):
        try:
            return discord.PartialEmoji.from_str(icon)
        except Exception:
            pass
    key = str(class_name or "").strip().lower()
    aliases = {
        "krieger": "warrior",
        "druide": "druid",
        "schurke": "rogue",
        "jäger": "hunter",
        "jaeger": "hunter",
        "jager": "hunter",
        "priester": "priest",
        "magier": "mage",
        "hexenmeister": "warlock",
        "schamane": "shaman",
    }
    return CLASS_EMOJI_FALLBACKS.get(aliases.get(key, key), "◆")


def normalize_emoji_name(value):
    text = str(value or "").strip().lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9_]+", "", text)


def item_emoji_candidates(item_name):
    raw = str(item_name or "").strip().lower()
    raw = raw.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    normalized = normalize_emoji_name(raw)
    underscored = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", raw)).strip("_")
    candidates = []
    original_key = str(item_name or "").strip().lower()
    candidates.extend(PO_ITEM_EMOJI_ALIASES.get(original_key, []))
    for value in [normalized, underscored]:
        if not value:
            continue
        candidates.extend([value, f"item_{value}", f"loot_{value}", f"po_{value}"])
    result = []
    seen = set()
    for value in candidates:
        key = normalize_emoji_name(value)
        if key and key not in seen:
            result.append(key)
            seen.add(key)
    return result


def po_item_icon(item_name):
    for candidate in item_emoji_candidates(item_name):
        cached = item_emoji_cache.get(candidate)
        if cached:
            return cached
    return "◇"


def refresh_class_emoji_cache():
    found_classes = {}
    found_specs = {}
    found_items = {}
    all_emojis = []
    try:
        for guild in client.guilds:
            all_emojis.extend(getattr(guild, "emojis", []) or [])
    except Exception:
        return found_classes, found_specs, found_items

    by_name = {normalize_emoji_name(emoji.name): emoji for emoji in all_emojis}
    for class_key, names in CLASS_EMOJI_NAME_ALIASES.items():
        for name in names:
            emoji = by_name.get(normalize_emoji_name(name))
            if emoji:
                found_classes[class_key] = str(emoji)
                break
    for spec_key, names in SPEC_EMOJI_NAME_ALIASES.items():
        for name in names:
            emoji = by_name.get(normalize_emoji_name(name))
            if emoji:
                found_specs[spec_key] = str(emoji)
                break
    for emoji_name, emoji in by_name.items():
        found_items[emoji_name] = str(emoji)
    class_emoji_cache.clear()
    class_emoji_cache.update(found_classes)
    spec_emoji_cache.clear()
    spec_emoji_cache.update(found_specs)
    item_emoji_cache.clear()
    item_emoji_cache.update(found_items)
    return found_classes, found_specs, found_items


def signup_spec_icon_key(spec_text, role="", class_name=""):
    text = str(spec_text or role or "").strip().lower()
    if any(word in text for word in ["tank", "prot", "schutz", "def"]):
        return "tank"
    if any(word in text for word in ["disziplin", "discipline", "disc"]):
        return "discipline"
    if any(word in text for word in ["holy", "heilig"]):
        canonical_class = canonical_signup_class(class_name).lower()
        if canonical_class == "paladin":
            return "paladin_holy"
        if canonical_class == "priest":
            return "priest_holy"
        return "holy"
    if any(word in text for word in ["schatten", "shadow"]):
        return "shadow"
    if any(word in text for word in ["heal", "heiler", "resto", "restoration"]):
        return "heal"
    if any(word in text for word in ["arms", "waffen"]):
        return "arms"
    if any(word in text for word in ["fury"]):
        return "fury"
    if any(word in text for word in ["retri", "vergeltung"]):
        return "retri"
    if any(word in text for word in ["fire", "feuer"]):
        return "fire"
    if any(word in text for word in ["frost", "eis"]):
        return "frost"
    if any(word in text for word in ["arcane", "arkan"]):
        return "arcane"
    if any(word in text for word in ["assassination", "assa"]):
        return "assassination"
    if any(word in text for word in ["subtlety", "sub"]):
        return "subtlety"
    if any(word in text for word in ["combat", "kampf"]):
        return "combat"
    if any(word in text for word in ["affliction", "affli", "gebrechen"]):
        return "affliction"
    if any(word in text for word in ["demonology", "demo"]):
        return "demonology"
    if any(word in text for word in ["destruction", "destro"]):
        return "destruction"
    if any(word in text for word in ["survival"]):
        return "survival"
    if any(word in text for word in ["marksman", "marksmanship"]):
        return "marksman"
    if any(word in text for word in ["beastmaster", "beast mastery", "bm"]):
        return "beastmaster"
    if any(word in text for word in ["feral"]):
        return "feral"
    if any(word in text for word in ["balance", "eule", "moonkin"]):
        return "balance"
    if any(word in text for word in ["elemental", "ele"]):
        return "elemental"
    if any(word in text for word in ["enhancement", "enh"]):
        return "enhancement"
    return ""


def signup_spec_icon(spec_text, role="", class_name=""):
    text = str(spec_text or role or "").strip().lower()
    icon_key = signup_spec_icon_key(spec_text, role, class_name)
    if icon_key and spec_emoji_cache.get(icon_key):
        return spec_emoji_cache[icon_key]
    if icon_key and SPEC_EMOJI_FALLBACKS.get(icon_key):
        return SPEC_EMOJI_FALLBACKS[icon_key]
    if any(word in text for word in ["tank", "prot", "schutz", "def"]):
        return SPEC_EMOJI_FALLBACKS["tank"]
    if any(word in text for word in ["heal", "heiler", "holy", "resto", "restoration", "diszi"]):
        return SPEC_EMOJI_FALLBACKS["heal"]
    if any(word in text for word in ["fire", "feuer", "flamme"]):
        return "🔥"
    if any(word in text for word in ["frost", "eis"]):
        return "❄️"
    if any(word in text for word in ["shadow", "schatten"]):
        return "🌑"
    if any(word in text for word in ["fury", "arms", "waffen", "combat", "assa", "feral", "enh", "ele", "balance", "dd", "dps"]):
        return "⚔️"
    return "✦"


def normalize_player_key(value):
    text = str(value or "").strip().lower()
    replacements = {
        "ä": "a",
        "ö": "o",
        "ü": "u",
        "ß": "ss",
        "á": "a",
        "à": "a",
        "â": "a",
        "é": "e",
        "è": "e",
        "ê": "e",
        "í": "i",
        "ì": "i",
        "ó": "o",
        "ò": "o",
        "ú": "u",
        "ù": "u",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"[^a-z0-9]+", "", text)


def raid_key_from_text(value):
    text = str(value or "").strip().lower()
    if "naxx" in text:
        return "naxx"
    if "aq40" in text or "tem" in text or "qiraj 40" in text:
        return "aq40"
    if "bwl" in text or "blackwing" in text or "bla" in text:
        return "bwl"
    if "mc" in text or "molten" in text:
        return "mc"
    if "aq20" in text or "rui" in text or "ruins" in text or "qiraj 20" in text:
        return "aq20"
    if "zg" in text or "zul" in text:
        return "zg"
    if "ony" in text:
        return "ony"
    return ""


def raid_key_from_raid(raid):
    if not isinstance(raid, dict):
        return raid_key_from_text(raid)
    return raid_key_from_text(" ".join([
        str(raid.get("raid") or ""),
        str(raid.get("raidType") or ""),
        str(raid.get("raidName") or ""),
        str(raid.get("raidId") or ""),
    ]))


def load_p0_release_cache():
    global P0_RELEASE_CACHE, P0_RELEASE_CACHE_TIME
    now = time.time()
    if P0_RELEASE_CACHE_TIME and now - P0_RELEASE_CACHE_TIME < P0_RELEASE_CACHE_SECONDS:
        return P0_RELEASE_CACHE

    result = {}
    try:
        with urllib.request.urlopen(P0_RELEASE_CSV_URL, timeout=8) as response:
            content = response.read().decode("utf-8-sig")
        rows = list(csv.reader(StringIO(content)))
        if not rows:
            return result
        raid_columns = {}
        for index, header in enumerate(rows[0]):
            raid_key = raid_key_from_text(header)
            if raid_key:
                raid_columns[index] = raid_key
                result.setdefault(raid_key, set())
        for row in rows[1:]:
            for index, raid_key in raid_columns.items():
                if index < len(row):
                    player_key = normalize_player_key(row[index])
                    if player_key:
                        result.setdefault(raid_key, set()).add(player_key)
        P0_RELEASE_CACHE = result
        P0_RELEASE_CACHE_TIME = now
    except Exception as e:
        print("P0-Freigabeliste konnte nicht geladen werden:", e)
    return P0_RELEASE_CACHE


async def refresh_p0_release_cache_background(force=False):
    global P0_RELEASE_CACHE_TIME, P0_RELEASE_REFRESHING
    now = time.time()
    if not force and P0_RELEASE_CACHE_TIME and now - P0_RELEASE_CACHE_TIME < P0_RELEASE_CACHE_SECONDS:
        return
    if P0_RELEASE_REFRESHING:
        return
    P0_RELEASE_REFRESHING = True
    try:
        await asyncio.to_thread(load_p0_release_cache)
    except Exception as e:
        print("P0-Freigabeliste Hintergrundrefresh fehlgeschlagen:", e)
    finally:
        P0_RELEASE_REFRESHING = False


def schedule_p0_release_cache_refresh(force=False):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(refresh_p0_release_cache_background(force=force))


def has_p0_release(player_name, raid_key):
    key = normalize_player_key(player_name)
    if not key or not raid_key:
        return False
    try:
        if not P0_RELEASE_CACHE_TIME or time.time() - P0_RELEASE_CACHE_TIME >= P0_RELEASE_CACHE_SECONDS:
            schedule_p0_release_cache_refresh()
        return key in P0_RELEASE_CACHE.get(raid_key, set())
    except Exception as e:
        print("P0-Freigabe konnte nicht geprueft werden:", e)
        return False


def signup_spec_from_note(note, role=""):
    raw = str(note or "").strip()
    if raw.lower().startswith("skillung:"):
        return raw.split(":", 1)[1].strip()
    return raw or str(role or "").strip()


SIGNUP_CLASS_ORDER = [
    "Tank",
    "Warrior",
    "Druid",
    "Paladin",
    "Rogue",
    "Hunter",
    "Priest",
    "Mage",
    "Warlock",
    "Shaman",
    "Ohne Klasse",
]

def canonical_signup_class(class_name):
    key = str(class_name or "").strip().lower()
    aliases = {
        "warrior": "Warrior",
        "krieger": "Warrior",
        "druid": "Druid",
        "druide": "Druid",
        "paladin": "Paladin",
        "rogue": "Rogue",
        "schurke": "Rogue",
        "hunter": "Hunter",
        "jäger": "Hunter",
        "jaeger": "Hunter",
        "priest": "Priest",
        "priester": "Priest",
        "mage": "Mage",
        "magier": "Mage",
        "warlock": "Warlock",
        "hexenmeister": "Warlock",
        "shaman": "Shaman",
        "schamane": "Shaman",
    }
    return aliases.get(key, str(class_name or "").strip() or "Ohne Klasse")


def signup_class_sort_key(class_name):
    canonical = canonical_signup_class(class_name)
    try:
        return (SIGNUP_CLASS_ORDER.index(canonical), canonical.lower())
    except ValueError:
        return (len(SIGNUP_CLASS_ORDER), canonical.lower())


def signup_class_heading(class_name, count):
    canonical = canonical_signup_class(class_name)
    return f"{signup_class_icon(canonical)} {canonical} ({count})"


def signup_role_bucket(row):
    status = str(row.get("status") or "").strip().lower()
    if status == "absent":
        return "absent"
    if status == "tentative":
        return "tentative"
    if status == "bench":
        return "bench"

    role = str(row.get("role") or "").strip().lower()
    spec = signup_spec_from_note(row.get("note"), role).lower()
    if role == "tank" or any(word in spec for word in ["tank", "prot", "schutz", "def"]):
        return "tank"
    if role == "heal" or any(word in spec for word in ["heal", "heiler", "holy", "resto", "restoration", "diszi"]):
        return "heal"
    return "dd"


def signup_damage_range(row):
    class_name = canonical_signup_class(row.get("className") or row.get("klasse"))
    spec = signup_spec_from_note(row.get("note"), row.get("role")).lower()
    if class_name in {"Mage", "Warlock", "Hunter"}:
        return "ranged"
    if class_name == "Priest":
        return "ranged" if "shadow" in spec or "schatten" in spec else "ranged"
    if class_name == "Shaman":
        return "ranged" if any(word in spec for word in ["ele", "elemental"]) else "melee"
    if class_name == "Druid":
        return "ranged" if any(word in spec for word in ["balance", "eule", "moonkin"]) else "melee"
    return "melee"


def p0_player_suffix(player_name, raid_key):
    return " ★" if has_p0_release(player_name, raid_key) else ""


def format_signup_roster_line(row, raid_key=""):
    player = str(row.get("player") or row.get("char") or "-").strip() or "-"
    role = str(row.get("role") or "").strip()
    class_name = canonical_signup_class(row.get("className") or row.get("klasse"))
    spec = signup_spec_from_note(row.get("note"), role) or role or "Flex"
    return f"**{player}{p0_player_suffix(player, raid_key)}** · {signup_spec_icon(spec, role, class_name)}"


def raid_signup_roster_from_helper(helper):
    signups = []
    for row in helper.get("signups") or []:
        signups.append(row)
    for row in helper.get("externalSignups") or []:
        signups.append(row)

    roster = {
        "tank": [],
        "classes": {},
        "tentative": [],
        "bench": [],
        "absent": [],
    }
    counts = {
        "tank": 0,
        "heal": 0,
        "melee": 0,
        "ranged": 0,
        "signed": 0,
    }

    for row in signups:
        bucket = signup_role_bucket(row)
        if bucket == "absent":
            roster["absent"].append(row)
            continue
        if bucket == "tentative":
            roster["tentative"].append(row)
            continue
        if bucket == "bench":
            roster["bench"].append(row)
            continue

        counts["signed"] += 1
        if bucket == "tank":
            counts["tank"] += 1
            roster["tank"].append(row)
            continue
        if bucket == "heal":
            counts["heal"] += 1
        else:
            counts[signup_damage_range(row)] += 1

        class_name = canonical_signup_class(row.get("className") or row.get("klasse"))
        roster["classes"].setdefault(class_name, []).append(row)

    return signups, roster, counts


def raid_signup_status_line(helper):
    raid = helper.get("raid") or {}
    signups, roster, counts = raid_signup_roster_from_helper(helper)
    heal_slots = str(raid.get("healSlots") or "").strip()
    heal_text = f"{counts['heal']}/{heal_slots}" if heal_slots else str(counts["heal"])
    tank_icon = spec_emoji_cache.get("tank") or SPEC_EMOJI_FALLBACKS["tank"]
    melee_icon = class_emoji_cache.get("warrior") or CLASS_EMOJI_FALLBACKS["warrior"]
    ranged_icon = spec_emoji_cache.get("marksman") or class_emoji_cache.get("hunter") or CLASS_EMOJI_FALLBACKS["hunter"]
    heal_icon = spec_emoji_cache.get("heal") or SPEC_EMOJI_FALLBACKS["heal"]
    return (
        f"{tank_icon} Tanks **{counts['tank']}** · "
        f"{melee_icon} Melee **{counts['melee']}** · "
        f"{ranged_icon} Ranged **{counts['ranged']}** · "
        f"{heal_icon} Healers **{heal_text}**"
    )


def add_raid_signup_role_fields(embed, helper):
    raid = helper.get("raid") or {}
    _signups, _roster, counts = raid_signup_roster_from_helper(helper)
    heal_slots = str(raid.get("healSlots") or "").strip()
    heal_text = f"{counts['heal']}/{heal_slots}" if heal_slots else str(counts["heal"])
    tank_icon = spec_emoji_cache.get("tank") or SPEC_EMOJI_FALLBACKS["tank"]
    melee_icon = class_emoji_cache.get("warrior") or CLASS_EMOJI_FALLBACKS["warrior"]
    ranged_icon = spec_emoji_cache.get("marksman") or class_emoji_cache.get("hunter") or CLASS_EMOJI_FALLBACKS["hunter"]
    heal_icon = spec_emoji_cache.get("heal") or SPEC_EMOJI_FALLBACKS["heal"]
    value = (
        f"{tank_icon} Tanks **{counts['tank']}** · {melee_icon} Melee **{counts['melee']}**\n"
        f"{ranged_icon} Ranged **{counts['ranged']}** · {heal_icon} Healers **{heal_text}**"
    )
    embed.add_field(name="Rollen", value=value, inline=False)


def add_raid_signup_roster_fields(embed, helper):
    raid_key = raid_key_from_raid(helper.get("raid") or {})
    signups, roster, counts = raid_signup_roster_from_helper(helper)
    if not signups:
        embed.add_field(name="Anmeldungen", value="Noch keine Anmeldungen.", inline=False)
        return

    add_raid_signup_role_fields(embed, helper)

    fields = []
    if roster["tank"]:
        value = "\n".join(format_signup_roster_line(row, raid_key) for row in roster["tank"][:10])
        fields.append((f"🛡️ Tank ({len(roster['tank'])})", value[:1024]))

    for class_name in sorted(roster["classes"].keys(), key=signup_class_sort_key):
        rows = roster["classes"][class_name]
        value = "\n".join(format_signup_roster_line(row, raid_key) for row in rows[:8])
        if len(rows) > 8:
            value += f"\n+ {len(rows) - 8} weitere"
        fields.append((signup_class_heading(class_name, len(rows)), value[:1024]))

    for index, (name, value) in enumerate(fields):
        embed.add_field(name=name, value=value, inline=True)
        is_row_end = (index + 1) % 3 == 0
        is_last = index == len(fields) - 1
        if is_row_end and not is_last:
            for _ in range(3):
                embed.add_field(name="\u200b", value="\u200b", inline=True)

    while len(fields) % 3:
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        fields.append(("", ""))

    if roster["tentative"]:
        value = ", ".join(
            f"**{str(row.get('player') or row.get('char') or '-').strip()}{p0_player_suffix(str(row.get('player') or row.get('char') or '-').strip(), raid_key)}**"
            for row in roster["tentative"][:14]
        )
        embed.add_field(name=f"⚖️ Vorläufig ({len(roster['tentative'])})", value=value[:1024], inline=False)

    if roster["bench"]:
        value = ", ".join(
            f"**{str(row.get('player') or row.get('char') or '-').strip()}{p0_player_suffix(str(row.get('player') or row.get('char') or '-').strip(), raid_key)}**"
            for row in roster["bench"][:14]
        )
        embed.add_field(name=f"🪑 Bank ({len(roster['bench'])})", value=value[:1024], inline=False)

    if roster["absent"]:
        value = ", ".join(
            f"**{str(row.get('player') or row.get('char') or '-').strip()}{p0_player_suffix(str(row.get('player') or row.get('char') or '-').strip(), raid_key)}**"
            for row in roster["absent"][:18]
        )
        embed.add_field(name=f"🚫 Abwesenheit ({len(roster['absent'])})", value=value[:1024], inline=False)


def raid_signup_class_options():
    return [
        discord.SelectOption(label="Warrior", value="Warrior", emoji=signup_class_select_emoji("Warrior")),
        discord.SelectOption(label="Druid", value="Druid", emoji=signup_class_select_emoji("Druid")),
        discord.SelectOption(label="Paladin", value="Paladin", emoji=signup_class_select_emoji("Paladin")),
        discord.SelectOption(label="Rogue", value="Rogue", emoji=signup_class_select_emoji("Rogue")),
        discord.SelectOption(label="Hunter", value="Hunter", emoji=signup_class_select_emoji("Hunter")),
        discord.SelectOption(label="Priest", value="Priest", emoji=signup_class_select_emoji("Priest")),
        discord.SelectOption(label="Mage", value="Mage", emoji=signup_class_select_emoji("Mage")),
        discord.SelectOption(label="Warlock", value="Warlock", emoji=signup_class_select_emoji("Warlock")),
        discord.SelectOption(label="Shaman", value="Shaman", emoji=signup_class_select_emoji("Shaman")),
    ]


def raid_signup_summary_from_helper(helper):
    raid_key = raid_key_from_raid(helper.get("raid") or {})
    signups = []
    for row in helper.get("signups") or []:
        signups.append(row)
    for row in helper.get("externalSignups") or []:
        signups.append(row)

    if not signups:
        return "Noch keine Anmeldungen."

    grouped = {}
    for row in signups:
        class_name = str(row.get("className") or row.get("klasse") or "Ohne Klasse").strip() or "Ohne Klasse"
        grouped.setdefault(class_name, []).append(row)

    lines = []
    shown = 0
    for class_name in sorted(grouped.keys()):
        rows = grouped[class_name]
        lines.append(f"**{signup_class_heading(class_name, len(rows))}**")
        for row in rows[:8]:
            if shown >= 18:
                break
            player = str(row.get("player") or row.get("char") or "-").strip()
            role = str(row.get("role") or "").strip()
            spec = signup_spec_from_note(row.get("note"), role)
            lines.append(f"{signup_spec_icon(spec, role, class_name)} {player}{p0_player_suffix(player, raid_key)}")
            shown += 1
        if shown >= 18:
            break

    if len(signups) > shown:
        lines.append(f"... und {len(signups) - shown} weitere")

    result = "\n".join(lines).strip()
    if len(result) > 1000:
        return result[:980].rsplit("\n", 1)[0] + "\n..."
    return result or "Noch keine Anmeldungen."


async def refresh_raid_signup_message(interaction, raid, origin_channel_id=None, origin_message_id=None):
    try:
        raid_lookup_id = str(raid.get("raidId") or raid.get("id") or "").strip()
        raid_pin = str(raid.get("playerPin") or raid.get("prioPin") or "").strip()
        helper_queries = []
        if raid_lookup_id:
            helper_queries.append({
                "action": "getRaidHelper",
                "raidId": raid_lookup_id,
                "playerPin": raid_lookup_id,
                "t": int(time.time())
            })
            helper_queries.append({
                "action": "getRaidHelper",
                "raidId": raid_lookup_id,
                "t": int(time.time())
            })
        if raid_pin and raid_pin != raid_lookup_id:
            helper_queries.append({
                "action": "getRaidHelper",
                "playerPin": raid_pin,
                "t": int(time.time())
            })

        helper = None
        last_error = None
        for query_params in helper_queries:
            try:
                helper = await asyncio.to_thread(lichtloot_get, query_params)
                break
            except Exception as e:
                last_error = e
        if helper is None:
            raise last_error or RuntimeError("Raid-Anmelder konnte nicht geladen werden.")
        fresh_raid = helper.get("raid") if isinstance(helper, dict) else None
        if not fresh_raid:
            fresh_raid = raid
        embed = build_raid_announcement_embed(fresh_raid)
        add_raid_signup_roster_fields(embed, helper)
        target_message = getattr(interaction, "message", None)
        if origin_channel_id and origin_message_id:
            channel = client.get_channel(int(origin_channel_id))
            if channel is None:
                channel = await client.fetch_channel(int(origin_channel_id))
            target_message = await channel.fetch_message(int(origin_message_id))
        banner = raid_banner_file(fresh_raid)
        if banner:
            await target_message.edit(embed=embed, attachments=[banner], view=RaidSignupView(fresh_raid))
        else:
            await target_message.edit(embed=embed, view=RaidSignupView(fresh_raid))
    except Exception as e:
        print("Raid-Anmelder-Message konnte nicht aktualisiert werden:", e)


async def refresh_raid_signup_message_by_id(raid_id, channel_id=None, message_id=None):
    raid_id = str(raid_id or "").strip()
    if not raid_id:
        raise RuntimeError("Raid-Anmelder-Refresh: Raid-ID fehlt.")
    helper = await asyncio.to_thread(lichtloot_get, {
        "action": "getRaidHelper",
        "raidId": raid_id,
        "playerPin": raid_id,
        "t": int(time.time())
    })
    if not helper or not helper.get("success"):
        raise RuntimeError("Raid-Anmelder-Refresh: Raid wurde nicht gefunden.")
    raid = helper.get("raid") or {}
    channel_id = str(channel_id or raid.get("discordChannelId") or raid.get("discord_channel_id") or "").strip()
    message_id = str(message_id or raid.get("discordMessageId") or raid.get("discord_message_id") or "").strip()
    if not channel_id or not message_id:
        print(f"Raid-Anmelder-Refresh uebersprungen, Channel/Message fehlt: raid={raid_id} channel={channel_id} message={message_id}")
        return "missing_message"
    channel = client.get_channel(int(channel_id))
    if channel is None:
        channel = await client.fetch_channel(int(channel_id))
    target_message = await channel.fetch_message(int(message_id))
    embed = build_raid_announcement_embed(raid)
    add_raid_signup_roster_fields(embed, helper)
    banner = raid_banner_file(raid)
    if banner:
        await target_message.edit(embed=embed, attachments=[banner], view=RaidSignupView(raid))
    else:
        await target_message.edit(embed=embed, view=RaidSignupView(raid))
    print(f"Raid-Anmelder aktualisiert: {raid_id} in {channel_id}/{message_id}")
    return True


def raid_signup_notice_action_label(action):
    clean = str(action or "").strip().lower()
    if clean == "bench":
        return "auf die Bank gesetzt"
    if clean == "absent":
        return "auf abwesend gesetzt"
    if clean in {"deleted", "delete", "removed", "verwerfen"}:
        return "aus der Anmeldung entfernt"
    if clean == "signed":
        return "angemeldet"
    return "aktualisiert"


def raid_signup_notice_color(action):
    clean = str(action or "").strip().lower()
    if clean == "bench":
        return 0xf59e0b
    if clean == "absent":
        return 0x60a5fa
    if clean in {"deleted", "delete", "removed", "verwerfen"}:
        return 0xef4444
    if clean == "signed":
        return 0x22c55e
    return 0x38bdf8


async def send_raid_signup_notice(payload):
    user_id = str(payload.get("userId") or payload.get("discordUserId") or "").strip()
    if not user_id:
        return False
    user = await client.fetch_user(int(user_id))
    raid_name = str(payload.get("raidName") or "Raid").strip()
    raid_date = format_raid_announcement_date(payload.get("raidDate") or "")
    raid_time = format_raid_announcement_time(payload.get("raidTime") or "")
    player = str(payload.get("player") or "dein Charakter").strip()
    action_label = raid_signup_notice_action_label(payload.get("action"))
    message = str(payload.get("message") or "").strip()
    embed = discord.Embed(
        title="Raidanmeldung aktualisiert",
        description=f"Deine Anmeldung für **{raid_name}** wurde **{action_label}**.",
        color=raid_signup_notice_color(payload.get("action")),
    )
    embed.add_field(name="Charakter", value=player, inline=True)
    embed.add_field(name="Status", value=action_label, inline=True)
    if raid_date != "noch offen" or raid_time != "noch offen":
        embed.add_field(name="Termin", value=f"{raid_date} · {raid_time}", inline=False)
    if message:
        embed.add_field(name="Nachricht vom Raidlead", value=message[:1024], inline=False)
    await user.send(embed=embed)
    print(f"Raid-Anmelder-DM gesendet: user={user_id} raid={raid_name} player={player} action={payload.get('action')}")
    return True


async def send_own_raid_signup_confirmation(interaction, raid, char_name, class_name, spec):
    try:
        raid_name = str(raid.get("raidName") or raid.get("raid") or "Raid").strip()
        raid_date = format_raid_announcement_date(raid.get("raidDate") or "")
        raid_time = format_raid_announcement_time(raid.get("raidTime") or "")
        raid_key = str(raid.get("raidId") or raid.get("id") or raid_name).strip()
        cache_key = f"{interaction.user.id}:{raid_key}:{str(char_name).strip().lower()}"
        now = time.time()
        last_sent = RAID_SIGNUP_DM_CACHE.get(cache_key, 0)
        if now - last_sent < 120:
            return
        RAID_SIGNUP_DM_CACHE[cache_key] = now
        embed = discord.Embed(
            title="Raidanmeldung gespeichert",
            description=f"Du bist für **{raid_name}** angemeldet.",
            color=0x22c55e,
        )
        embed.add_field(name="Charakter", value=str(char_name or "-"), inline=True)
        embed.add_field(name="Klasse", value=str(class_name or "-"), inline=True)
        embed.add_field(name="Skillung", value=str(spec or "-"), inline=True)
        if raid_date != "noch offen" or raid_time != "noch offen":
            embed.add_field(name="Termin", value=f"{raid_date} · {raid_time}", inline=False)
        await interaction.user.send(embed=embed)
    except Exception as e:
        print("Raid-Anmelder-DM nach Anmeldung konnte nicht gesendet werden:", e)


def raid_signup_source(interaction, origin_channel_id=None, origin_message_id=None):
    channel_id = str(origin_channel_id or interaction.channel_id or "")
    message_id = str(origin_message_id or getattr(interaction.message, "id", "") or "")
    return f"DiscordSignup:{channel_id}:{message_id}"


async def get_current_raid_helper(raid):
    return await asyncio.to_thread(lichtloot_get, {
        "action": "getRaidHelper",
        "raidId": str(raid.get("raidId") or raid.get("id") or ""),
        "playerPin": str(raid.get("playerPin") or ""),
        "t": int(time.time())
    })


async def find_existing_discord_signup(raid, char_name, interaction):
    wanted_char = str(char_name or "").strip().lower()
    wanted_user = str(interaction.user.id)
    wanted_source = raid_signup_source(interaction)
    try:
        helper = await get_current_raid_helper(raid)
    except Exception:
        return {}

    for row in (helper.get("externalSignups") or []) + (helper.get("signups") or []):
        row_char = str(row.get("char") or row.get("player") or "").strip().lower()
        row_user = str(row.get("discordUserId") or "").strip()
        row_source = str(row.get("source") or "").strip()
        if row_char == wanted_char and (row_user == wanted_user or row_source == wanted_source):
            return row
    return {}


async def save_raid_signup_status(interaction, raid, char_name, status, note=""):
    existing = await find_existing_discord_signup(raid, char_name, interaction)
    if not existing:
        raise RuntimeError("Für diesen Charakter wurde keine Anmeldung von dir gefunden.")
    existing_note = str(existing.get("note") or "").strip()
    status_note = str(note or "").strip()
    if status == "bench":
        note_text = existing_note or "Bank"
        if status_note:
            note_text = f"{note_text} | Bank: {status_note}"
    elif status == "absent":
        note_text = existing_note or "Abwesend"
        if status_note:
            note_text = f"{note_text} | Abwesend: {status_note}"
    else:
        note_text = existing_note

    payload = {
        "action": "saveDiscordSignupRows",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "raidId": str(raid.get("raidId") or raid.get("id") or ""),
        "raid": raid.get("raid") or raid.get("raidName") or "",
        "raidDate": raid.get("raidDate") or "",
        "raidTime": raid.get("raidTime") or "",
        "discordChannelId": str(interaction.channel_id or ""),
        "raidHelperMessageId": str(getattr(interaction.message, "id", "") or ""),
        "rows": [{
            "char": char_name,
            "spieler": char_name,
            "klasse": str(existing.get("className") or existing.get("klasse") or ""),
            "role": str(existing.get("role") or ""),
            "status": status,
            "note": note_text,
            "discordUserId": str(interaction.user.id),
            "discordName": str(interaction.user.display_name),
            "source": raid_signup_source(interaction)
        }]
    }
    result = await asyncio.to_thread(lichtloot_post, payload)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Status konnte nicht gespeichert werden.")
    return result


class RaidSignupModal(discord.ui.Modal, title="Raid anmelden"):
    char_name = discord.ui.TextInput(
        label="Charaktername",
        placeholder="z. B. Burny",
        max_length=40
    )

    def __init__(self, raid, class_name, spec_label, spec_key, origin_channel_id=None, origin_message_id=None):
        super().__init__()
        self.raid = raid
        self.class_name = class_name
        self.spec_label = spec_label
        self.spec_key = spec_key
        self.origin_channel_id = origin_channel_id
        self.origin_message_id = origin_message_id

    async def on_submit(self, interaction):
        char_name = str(self.char_name.value or "").strip()
        spec = str(self.spec_label or "").strip()
        if not char_name:
            await interaction.response.send_message("Bitte Charaktername angeben.", ephemeral=True)
            return

        payload = {
            "action": "saveDiscordSignupRows",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "raidId": str(self.raid.get("raidId") or self.raid.get("id") or ""),
            "raid": self.raid.get("raid") or self.raid.get("raidName") or "",
            "raidDate": self.raid.get("raidDate") or "",
            "raidTime": self.raid.get("raidTime") or "",
            "discordChannelId": str(self.origin_channel_id or interaction.channel_id or ""),
            "raidHelperMessageId": str(self.origin_message_id or getattr(interaction.message, "id", "") or ""),
            "rows": [{
                "char": char_name,
                "spieler": char_name,
                "klasse": self.class_name,
                "role": infer_signup_role(spec),
                "status": "signed",
                "note": f"Skillung: {spec}",
                "discordUserId": str(interaction.user.id),
                "discordName": str(interaction.user.display_name),
                "source": raid_signup_source(interaction, self.origin_channel_id, self.origin_message_id)
            }]
        }

        try:
            result = await asyncio.to_thread(lichtloot_post, payload)
            if not result.get("success"):
                raise RuntimeError(result.get("error") or "Anmeldung konnte nicht gespeichert werden.")
            refresh_raid = dict(self.raid)
            if result.get("raidId"):
                refresh_raid["raidId"] = result.get("raidId")
            await interaction.response.send_message(
                f"✅ Anmeldung gespeichert: **{char_name}** · {self.class_name} · {spec}",
                ephemeral=True
            )
            await send_own_raid_signup_confirmation(interaction, refresh_raid, char_name, self.class_name, spec)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Anmeldung fehlgeschlagen: {e}", ephemeral=True)
            return

        try:
            await refresh_raid_signup_message(interaction, refresh_raid, self.origin_channel_id, self.origin_message_id)
        except Exception as e:
            print("Raid-Anmelder-Refresh nach Anmeldung fehlgeschlagen:", e)


class RaidSignupStatusModal(discord.ui.Modal):
    char_name = discord.ui.TextInput(
        label="Charaktername",
        placeholder="z. B. Ariee",
        max_length=40
    )
    note = discord.ui.TextInput(
        label="Notiz optional",
        placeholder="z. B. Arbeit, später da, Ersatzbank",
        required=False,
        max_length=100
    )

    def __init__(self, raid, status, title):
        super().__init__(title=title)
        self.raid = raid
        self.status = status

    async def on_submit(self, interaction):
        char_name = str(self.char_name.value or "").strip()
        note = str(self.note.value or "").strip()
        if not char_name:
            await interaction.response.send_message("Bitte Charaktername angeben.", ephemeral=True)
            return
        try:
            await save_raid_signup_status(interaction, self.raid, char_name, self.status, note)
            label = "auf die Bank gesetzt" if self.status == "bench" else "als abwesend markiert"
            await interaction.response.send_message(f"✅ **{char_name}** wurde {label}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Status konnte nicht geändert werden: {e}", ephemeral=True)
            return

        try:
            await refresh_raid_signup_message(interaction, self.raid)
        except Exception as e:
            print("Raid-Anmelder-Refresh nach Statusaenderung fehlgeschlagen:", e)


def signup_spec_select_emoji(spec_key):
    icon = spec_emoji_cache.get(spec_key) or SPEC_EMOJI_FALLBACKS.get(spec_key, "✦")
    if isinstance(icon, str) and (icon.startswith("<:") or icon.startswith("<a:")):
        try:
            return discord.PartialEmoji.from_str(icon)
        except Exception:
            pass
    return icon


def raid_signup_spec_options(class_name):
    specs = RAID_SIGNUP_SPECS.get(str(class_name or "").strip(), [("Flex", "flex")])
    options = []
    for label, key in specs:
        options.append(discord.SelectOption(
            label=label,
            value=key,
            emoji=signup_spec_select_emoji(key)
        ))
    return options


class RaidSignupSpecSelect(discord.ui.Select):
    def __init__(self, raid, class_name, origin_channel_id=None, origin_message_id=None):
        self.raid = raid
        self.class_name = class_name
        self.origin_channel_id = origin_channel_id
        self.origin_message_id = origin_message_id
        super().__init__(
            placeholder=f"Skillung für {class_name} wählen",
            min_values=1,
            max_values=1,
            options=raid_signup_spec_options(class_name)
        )

    async def callback(self, interaction):
        spec_key = self.values[0]
        specs = RAID_SIGNUP_SPECS.get(self.class_name, [])
        spec_label = next((label for label, key in specs if key == spec_key), spec_key)
        await interaction.response.send_modal(RaidSignupModal(
            self.raid,
            self.class_name,
            spec_label,
            spec_key,
            self.origin_channel_id,
            self.origin_message_id
        ))


class RaidSignupSpecView(discord.ui.View):
    def __init__(self, raid, class_name, origin_channel_id=None, origin_message_id=None):
        super().__init__(timeout=180)
        self.add_item(RaidSignupSpecSelect(raid, class_name, origin_channel_id, origin_message_id))


class RaidSignupClassSelect(discord.ui.Select):
    def __init__(self, raid):
        self.raid = raid
        super().__init__(
            custom_id="raid_signup_class_select",
            placeholder="Klasse wählen und Charakter anmelden",
            min_values=1,
            max_values=1,
            options=raid_signup_class_options()
        )

    async def callback(self, interaction):
        class_name = self.values[0]
        await interaction.response.send_message(
            f"Skillung für **{class_name}** wählen:",
            view=RaidSignupSpecView(
                self.raid,
                class_name,
                interaction.channel_id,
                getattr(interaction.message, "id", "")
            ),
            ephemeral=True
        )


class RaidSignupView(discord.ui.View):
    def __init__(self, raid):
        super().__init__(timeout=None)
        self.raid = raid
        self.add_item(RaidSignupClassSelect(raid))

    @discord.ui.button(label="Bank", emoji="🪑", style=discord.ButtonStyle.secondary, custom_id="raid_signup_bench")
    async def bench_signup(self, interaction, button):
        await interaction.response.send_modal(RaidSignupStatusModal(self.raid, "bench", "Auf die Bank setzen"))

    @discord.ui.button(label="Abwesend", emoji="🚫", style=discord.ButtonStyle.secondary, custom_id="raid_signup_absent")
    async def absent_signup(self, interaction, button):
        await interaction.response.send_modal(RaidSignupStatusModal(self.raid, "absent", "Als abwesend markieren"))


async def restore_active_raid_signup_views():
    await client.wait_until_ready()
    await asyncio.sleep(3)
    restored = 0
    refreshed = 0
    try:
        result = await asyncio.to_thread(lichtloot_get, {
            "action": "getActiveRaids",
            "t": int(time.time())
        })
        raids = result.get("allRaids") or result.get("raids") or []
        for raid in raids:
            raid_id = str(raid.get("raidId") or raid.get("id") or "").strip()
            channel_id = str(raid.get("discordChannelId") or raid.get("discord_channel_id") or "").strip()
            message_id = str(raid.get("discordMessageId") or raid.get("discord_message_id") or "").strip()
            if not raid_id or not channel_id or not message_id:
                continue
            try:
                client.add_view(RaidSignupView(raid), message_id=int(message_id))
                restored += 1
            except Exception as e:
                print(f"Raid-Anmelder-View konnte nicht registriert werden ({raid_id}): {e}")
            try:
                if await refresh_raid_signup_message_by_id(raid_id, channel_id, message_id):
                    refreshed += 1
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Raid-Anmelder-View konnte nicht aktualisiert werden ({raid_id}): {e}")
        print(f"Raid-Anmelder-Views wiederhergestellt: {restored}, aktualisiert: {refreshed}.")
    except Exception as e:
        print("Raid-Anmelder-Views konnten beim Start nicht wiederhergestellt werden:", e)


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


def split_raidhelper_signup_identity(value):
    aliases = split_prio_aliases(value)
    char_name = aliases[0] if aliases else normalize_prio_name(value)
    discord_name = aliases[1] if len(aliases) > 1 else ""

    return {
        "char": char_name,
        "spieler": char_name,
        "discordName": discord_name,
        "rawName": str(value or "").replace("**", "").replace("`", "").strip()
    }


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


def extract_signup_entries_from_text(text):
    """
    Liest RaidHelper-Anmeldungen mit getrennter Char-/Discord-Namen-Spalte.
    Beispiel: "Karuzy/Nick" wird zu char=Karuzy, discordName=Nick.
    """
    entries = {}

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
        identity = split_raidhelper_signup_identity(raw_name)
        key = prio_key(identity.get("char"))

        if identity.get("char") and key:
            entries[key] = identity

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

    return entries


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


def format_signup_identity_for_debug(value):
    if isinstance(value, dict):
        char_name = str(value.get("char") or value.get("spieler") or value.get("player") or "").strip()
        discord_name = str(value.get("discordName") or value.get("discord") or "").strip()
        if discord_name:
            return f"{char_name} (DC: {discord_name})"
        return char_name
    return str(value or "").strip()


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
    pin_match = re.search(r"Prio[-\s]*PIN\s*`?([A-Z0-9]{2,8})`?", text, re.IGNORECASE)
    raid_pin = pin_match.group(1).strip().upper() if pin_match else ""

    return {
        "raid": raid,
        "raidDate": raid_date,
        "raidTime": raid_time,
        "raidPin": raid_pin,
        "playerPin": raid_pin,
        "discordChannelId": str(source["channel_id"]),
        "raidHelperMessageId": str(source.get("resolved_message_id") or source.get("message_id") or "")
    }


def p0_supported_raids_for_channel(channel_id):
    wanted = int(channel_id)
    raids = []
    for raid in ["MC", "BWL", "AQ40", "NAXX"]:
        for source in DISCORD_RAIDHELPER_SOURCES.get(raid, []):
            if int(source.get("channel_id")) == wanted:
                raids.append(raid)
                break
    return raids


def p0_post_state_key(raid, channel_id):
    return f"{normalize_raid_name(raid)}:{int(channel_id)}"


def display_raid_name(raid):
    names = {
        "MC": "Molten Core",
        "BWL": "Blackwing Lair",
        "AQ40": "Ahn'Qiraj 40",
        "NAXX": "Naxxramas"
    }
    return names.get(normalize_raid_name(raid), normalize_raid_name(raid))


def p0_item_label(item):
    name = str(item.get("name") or item.get("itemName") or "-").strip() or "-"
    points = item.get("p0PlusPoints", 0)
    try:
        points_text = f"{float(points):g}"
    except Exception:
        points_text = str(points or "0")
    label = f"{name} · {points_text} P0+"
    return label[:100]


async def get_p0_context(raid, event_info=None):
    params = {
        "action": "lichtbotGetP0SignupContext",
        "raid": normalize_raid_name(raid)
    }
    if event_info:
        params.update({
            "raidDate": event_info.get("raidDate", ""),
            "raidTime": event_info.get("raidTime", ""),
            "raidPin": event_info.get("raidPin") or event_info.get("playerPin") or "",
            "prioPin": event_info.get("raidPin") or event_info.get("playerPin") or "",
            "playerPin": event_info.get("raidPin") or event_info.get("playerPin") or "",
            "discordChannelId": event_info.get("discordChannelId", ""),
            "discordMessageId": event_info.get("raidHelperMessageId", "")
        })
    return await asyncio.to_thread(lichtloot_get, params)


async def save_p0_signup(selection, interaction, char_name, player_pin):
    payload = {
        "action": "lichtbotSaveP0Signup",
        "raidId": selection["raid_id"],
        "raid": selection["raid"],
        "raidPin": selection.get("raid_pin") or "",
        "prioPin": selection.get("raid_pin") or "",
        "itemId": selection["item_id"],
        "itemName": selection["item_name"],
        "char": char_name,
        "server": "Everlook",
        "playerPin": player_pin,
        "discordUserId": str(interaction.user.id),
        "discordName": str(interaction.user.display_name),
        "discordChannelId": str(selection.get("origin_channel_id") or ""),
        "discordMessageId": str(selection.get("origin_message_id") or "")
    }
    return await asyncio.to_thread(lichtloot_post, payload)


def build_p0_post_text(context):
    raid = context.get("raid") or {}
    raid_name = raid.get("raidName") or display_raid_name(raid.get("raid") or context.get("raid"))
    raid_date = raid.get("raidDate") or raid.get("date") or ""
    raid_time = raid.get("raidTime") or raid.get("time") or ""
    raid_pin = str(raid.get("playerPin") or raid.get("prioPin") or raid.get("raidPin") or "").strip()
    signups = context.get("signups") or []

    text = f"⭐ **P0+ Wahl · {raid_name}**\n"
    if raid_date or raid_time:
        text += f"📌 **Raid:** {raid_date} {raid_time}".strip() + "\n"
    if raid_pin:
        text += f"🔑 **Prio-PIN:** `{raid_pin}`\n"
    text += "\n✅ **Aktuelle P0+ Wünsche:**\n"

    if signups:
        for row in signups:
            player = str(row.get("player") or row.get("char") or "-").strip() or "-"
            item = str(row.get("item") or row.get("itemName") or "-").strip() or "-"
            text += f"⭐ **{player}** → {item}{p0_approval_suffix(row)}\n"
    else:
        text += "-\n"

    text += "\n━━━━━━━━━━━━━━━\n"
    text += "📋 **Anmelden oder ändern:** `!p0`\n"
    text += "Klicke unten auf **P0+ eintragen** und gib Item + Char ein. Beim ersten Mal brauchst du deinen Mein-Lichtloot Login/PIN."
    return text


def is_p0_overview_message(message):
    text = str(getattr(message, "content", "") or "")
    return "⭐ **P0+ Wahl" in text and "Aktuelle P0+ Wünsche" in text


async def keep_latest_p0_overview_message(channel, preferred_message=None):
    messages = await find_recent_own_messages(channel, is_p0_overview_message, limit=100)
    if preferred_message and all(message.id != preferred_message.id for message in messages):
        messages.append(preferred_message)
    if not messages:
        return preferred_message

    keep = max(messages, key=lambda message: int(message.id))
    for message in messages:
        if message.id == keep.id:
            continue
        try:
            await message.delete()
            await asyncio.sleep(0.4)
        except Exception:
            pass
    return keep


async def cleanup_p0_overview_duplicates_for_known_channels():
    await client.wait_until_ready()
    await asyncio.sleep(10)
    channel_ids = set()
    for raid in ["MC", "BWL", "AQ40", "NAXX"]:
        for source in DISCORD_RAIDHELPER_SOURCES.get(raid, []):
            if source.get("channel_id"):
                channel_ids.add(int(source["channel_id"]))

    for delay in [0, 60]:
        if delay:
            await asyncio.sleep(delay)
        for channel_id in sorted(channel_ids):
            try:
                channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
                kept = await keep_latest_p0_overview_message(channel)
                if kept:
                    print(f"P0+-Doppelposts in Channel {channel_id} bereinigt, behalten: {kept.id}")
            except Exception as e:
                print(f"P0+-Doppelposts in Channel {channel_id} konnten nicht bereinigt werden: {e}")


def p0_item_search_key(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def find_p0_item(items, item_text):
    wanted = p0_item_search_key(item_text)
    if not wanted:
        return None, []

    exact = [
        item for item in items
        if p0_item_search_key(item.get("name") or item.get("itemName")) == wanted
    ]
    if exact:
        return exact[0], exact

    wanted_words = [word for word in wanted.split() if len(word) >= 3]
    matches = []
    for item in items:
        name = item.get("name") or item.get("itemName") or ""
        key = p0_item_search_key(name)
        if wanted in key or (wanted_words and all(word in key for word in wanted_words)):
            matches.append(item)

    if len(matches) == 1:
        return matches[0], matches
    return None, matches[:10]


def p0_item_points_text(item):
    points = item.get("p0PlusPoints", 0)
    try:
        return f"{float(points):g}"
    except Exception:
        return str(points or "0")


def p0_approval_suffix(row):
    status = str(row.get("approvalStatus") or "").strip().lower()
    if row.get("approved") or status == "approved":
        return " ✅"
    if row.get("rejected") or status == "rejected":
        return " ❌"
    return " ⏳"


def format_p0_item_signup_summary(signups):
    rows = []
    for row in signups or []:
        player = str(row.get("player") or row.get("char") or "-").strip() or "-"
        status = str(row.get("approvalStatus") or "").strip().lower()
        if row.get("approved") or status == "approved":
            label = "gültig"
        elif row.get("rejected") or status == "rejected":
            label = "abgelehnt"
        else:
            label = "wartet auf Prüfung"
        rows.append(f"**{player}** ({label})")
    if not rows:
        return "Auf diesem Item ist in diesem Raid noch keine weitere P0+ eingetragen."
    return "Auf diesem Item haben in diesem Raid P0+: " + ", ".join(rows) + "."


def normalize_p0_reviewer_name(value):
    return re.sub(r"[^a-z0-9äöüß]+", "", str(value or "").casefold())


def split_discord_name_list(value):
    names = []
    seen = set()
    for part in re.split(r"[,;\n]+", str(value or "")):
        name = part.strip()
        if not name:
            continue
        key = normalize_p0_reviewer_name(name)
        if key and key not in seen:
            names.append(name)
            seen.add(key)
    return names


def p0_review_requested_names(selection):
    return split_discord_name_list(
        selection.get("reviewer_names")
        or selection.get("reviewerName")
        or selection.get("reviewer_name")
        or ""
    )


def member_matches_p0_reviewer(member, wanted_names):
    names = {
        normalize_p0_reviewer_name(getattr(member, "display_name", "")),
        normalize_p0_reviewer_name(getattr(member, "name", ""))
    }
    return bool(names.intersection(wanted_names))


async def find_p0_review_members():
    wanted = P0_REVIEW_TEST_NAMES if P0_REVIEW_TEST_MODE else P0_REVIEW_LIVE_NAMES
    found = []
    seen = set()
    for guild in client.guilds:
        for member in getattr(guild, "members", []) or []:
            if member.bot or member.id in seen:
                continue
            if member_matches_p0_reviewer(member, wanted):
                found.append(member)
                seen.add(member.id)
        for name in wanted:
            try:
                queried = await guild.query_members(query=name, limit=5)
            except Exception:
                queried = []
            for member in queried:
                if member.bot or member.id in seen:
                    continue
                if member_matches_p0_reviewer(member, wanted):
                    found.append(member)
                    seen.add(member.id)
    return found


async def review_p0_signup(signup, status, interaction, selection):
    payload = {
        "action": "lichtbotReviewP0Signup",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "signupId": signup.get("id") or "",
        "status": status,
        "reviewerDiscordId": str(interaction.user.id),
        "reviewerDiscordName": str(interaction.user.display_name)
    }
    result = await asyncio.to_thread(lichtloot_post, payload)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or str(result))
    return result


class P0ReviewView(discord.ui.View):
    def __init__(self, signup, selection):
        super().__init__(timeout=86400)
        self.signup = signup
        self.selection = selection

    async def apply_review(self, interaction, status):
        await interaction.response.defer()
        try:
            result = await review_p0_signup(self.signup, status, interaction, self.selection)
            reviewed = result.get("signup") or self.signup
            label = "gültig" if status == "approved" else "abgelehnt"
            await interaction.message.edit(
                content=(
                    f"✅ P0+ geprüft: **{reviewed.get('player') or '-'}** → "
                    f"**{reviewed.get('item') or '-'}** ist **{label}**."
                ),
                view=None
            )
        except Exception as e:
            await interaction.followup.send(f"⚠️ Prüfung konnte nicht gespeichert werden: {e}", ephemeral=True)

    @discord.ui.button(label="P0+ gültig", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        await self.apply_review(interaction, "approved")

    @discord.ui.button(label="ungültig", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, button):
        await self.apply_review(interaction, "rejected")


async def send_p0_review_requests(selection, signup):
    requested_names = p0_review_requested_names(selection)
    reviewers = []
    missing = []
    blocked = []
    seen_reviewers = set()

    if requested_names:
        for name in requested_names:
            member = await find_discord_member_or_user(name)
            if member and not getattr(member, "bot", False) and getattr(member, "id", None) not in seen_reviewers:
                reviewers.append(member)
                seen_reviewers.add(member.id)
            else:
                missing.append(name)
    else:
        reviewers = await find_p0_review_members()

    raid_label = selection.get("raid") or ""
    event_info = selection.get("event_info") or {}
    raid_date = event_info.get("raidDate") or ""
    raid_time = event_info.get("raidTime") or ""
    pin = selection.get("raid_pin") or event_info.get("raidPin") or ""
    message_text = (
        "Bitte prüfe diese P0+-Anmeldung:\n"
        f"**Spieler:** {signup.get('player') or '-'}\n"
        f"**Item:** {signup.get('item') or selection.get('item_name') or '-'}\n"
        f"**Raid:** {raid_label} {raid_date} {raid_time}".strip() + "\n"
        f"**Prio-PIN:** {pin or '-'}"
    )
    sent = []

    for member in reviewers:
        try:
            view = P0ReviewView(signup, selection)
            await member.send(message_text, view=view)
            sent.append(member.display_name)
        except discord.Forbidden:
            print(f"P0-Pruefung: DM an {member.display_name} nicht erlaubt.")
            blocked.append(member.display_name)
        except Exception as e:
            print(f"P0-Pruefung: DM an {member.display_name} fehlgeschlagen: {e}")
            blocked.append(member.display_name)

    if not sent and not requested_names:
        try:
            channel_id = int(selection.get("origin_channel_id") or 0)
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
            target_names = "Ariee/Juksi" if P0_REVIEW_TEST_MODE else "Kaese/Blondi"
            await send_silent(
                channel,
                f"🔎 **P0+ Prüfung für {target_names}**\n{message_text}",
                view=P0ReviewView(signup, selection)
            )
            sent.append(f"Channelpost für {target_names}")
        except Exception as e:
            print(f"P0-Pruefung: Channel-Fallback fehlgeschlagen: {e}")
    return {
        "sent": sent,
        "missing": missing,
        "blocked": blocked
    }


async def update_p0_post(raid, origin_channel_id, event_info=None):
    key = p0_post_state_key(raid, origin_channel_id)
    lock = P0_POST_UPDATE_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        return await update_p0_post_locked(raid, origin_channel_id, event_info)


async def update_p0_post_locked(raid, origin_channel_id, event_info=None):
    context = await get_p0_context(raid, event_info)
    channel = client.get_channel(int(origin_channel_id)) or await client.fetch_channel(int(origin_channel_id))
    state = load_json(p0_post_file(), {})
    key = p0_post_state_key(raid, origin_channel_id)
    message_id = state.get(key)
    found_messages = await find_recent_own_messages(channel, is_p0_overview_message, limit=100)
    raid_data = context.get("raid") or {}
    text = build_p0_post_text(context)

    candidates = []
    if message_id:
        try:
            candidates.append(await channel.fetch_message(int(message_id)))
        except discord.NotFound:
            pass
        except Exception as e:
            print(f"P0+-Post {message_id} konnte nicht geladen werden:", e)

    candidate_ids = {message.id for message in candidates}
    candidates.extend(message for message in found_messages if message.id not in candidate_ids)
    target_message = candidates[0] if candidates else None

    view = P0ItemEntryView(
        raid,
        context.get("raidId") or raid_data.get("raidId") or raid_data.get("id") or "",
        context.get("items") or [],
        origin_channel_id,
        str(getattr(target_message, "id", "") or ""),
        event_info or {},
        context=context
    )

    msg = None
    if target_message:
        try:
            await target_message.edit(content=text, view=view)
            msg = target_message
        except Exception as e:
            print(f"P0+-Post {target_message.id} konnte nicht bearbeitet werden:", e)
            try:
                await target_message.delete()
            except Exception:
                pass
            msg = None

    for message in candidates:
        if msg and message.id == msg.id:
            continue
        try:
            await message.delete()
            await asyncio.sleep(0.4)
        except Exception:
            pass

    if not msg:
        view = P0ItemEntryView(
            raid,
            context.get("raidId") or raid_data.get("raidId") or raid_data.get("id") or "",
            context.get("items") or [],
            origin_channel_id,
            "",
            event_info or {},
            context=context
        )
        msg = await send_silent(channel, text, view=view)

    await asyncio.sleep(2)
    msg = await keep_latest_p0_overview_message(channel, msg) or msg

    state[key] = str(msg.id)
    save_json(p0_post_file(), state)
    return context


class P0SignupModal(discord.ui.Modal, title="P0+ eintragen"):
    raid_pin = discord.ui.TextInput(
        label="Prio-PIN / Raid-PIN",
        placeholder="z. B. XXX",
        required=False,
        max_length=12
    )
    item_name = discord.ui.TextInput(
        label="Item",
        placeholder="z. B. Donnerzorn, Gesegnete Klinge ...",
        required=True,
        max_length=100
    )
    char_name = discord.ui.TextInput(
        label="Charakter",
        placeholder="z. B. Ariee",
        required=True,
        max_length=32
    )
    player_pin = discord.ui.TextInput(
        label="Mein-Lichtloot Login/PIN",
        placeholder="Nur beim ersten Mal für diesen Char nötig",
        required=False,
        max_length=32
    )
    reviewer_names = discord.ui.TextInput(
        label="Freigabe an (DC-Namen)",
        placeholder="z. B. Schepperle, Ariee",
        required=False,
        max_length=120
    )

    def __init__(self, selection):
        super().__init__()
        self.selection = selection
        default_pin = str(selection.get("raid_pin") or "").strip()
        if default_pin:
            self.raid_pin.default = default_pin

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            item, matches = find_p0_item(
                self.selection.get("items") or [],
                str(self.item_name.value).strip()
            )
            if not item:
                if matches:
                    suggestions = "\n".join(
                        f"- {match.get('name') or match.get('itemName')} ({p0_item_points_text(match)} P0+)"
                        for match in matches[:10]
                    )
                    await interaction.followup.send(
                        "⚠️ Ich habe mehrere passende Items gefunden. Bitte gib den Namen genauer ein:\n"
                        f"{suggestions}",
                        ephemeral=True
                    )
                    return
                await interaction.followup.send(
                    "⚠️ Dieses Item habe ich in der Lichtloot-Liste für diesen Raid nicht gefunden. "
                    "Bitte prüfe die Schreibweise.",
                    ephemeral=True
                )
                return

            selection = dict(self.selection)
            entered_raid_pin = str(self.raid_pin.value or "").strip().upper()
            if entered_raid_pin:
                selection["raid_pin"] = entered_raid_pin
                selection["raid_id"] = entered_raid_pin
                event_info = dict(selection.get("event_info") or {})
                event_info["raidPin"] = entered_raid_pin
                event_info["playerPin"] = entered_raid_pin
                selection["event_info"] = event_info
            selection["item_id"] = str(item.get("id") or "")
            selection["item_name"] = str(item.get("name") or item.get("itemName") or "")
            entered_reviewers = ", ".join(split_discord_name_list(self.reviewer_names.value))
            if entered_reviewers:
                selection["reviewer_names"] = entered_reviewers
            result = await save_p0_signup(
                selection,
                interaction,
                str(self.char_name.value).strip(),
                str(self.player_pin.value).strip()
            )
            if not result.get("success"):
                raise RuntimeError(result.get("error") or str(result))

            signup = result.get("signup") or {}
            review_result = await send_p0_review_requests(selection, signup)
            await update_p0_post(
                selection["raid"],
                selection["origin_channel_id"],
                selection.get("event_info") or {}
            )
            item_summary = format_p0_item_signup_summary(result.get("itemSignups") or [signup])
            sent_reviewers = review_result.get("sent") or []
            missing_reviewers = review_result.get("missing") or []
            blocked_reviewers = review_result.get("blocked") or []
            review_text_parts = []
            if sent_reviewers:
                review_text_parts.append(f"Prüfung wurde an **{', '.join(sent_reviewers)}** geschickt.")
            else:
                review_text_parts.append("Prüf-Nachricht konnte noch an keinen Tester geschickt werden.")
            if missing_reviewers:
                review_text_parts.append(f"Nicht gefunden: **{', '.join(missing_reviewers)}**.")
            if blocked_reviewers:
                review_text_parts.append(f"DM nicht möglich bei: **{', '.join(blocked_reviewers)}**.")
            review_text = "\n".join(review_text_parts)
            await interaction.followup.send(
                f"✅ Gespeichert: **{signup.get('player') or self.char_name.value}** → **{signup.get('item') or selection['item_name']}**.\n"
                f"{item_summary}\n"
                f"{review_text}\n"
                "Deine Prioliste wurde in Lichtloot aktualisiert.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                "⚠️ P0+ konnte nicht gespeichert werden: "
                f"{e}\n\nFalls das dein erster Eintrag ist, trage bitte einmal deinen Mein-Lichtloot Login/PIN mit ein.",
                ephemeral=True
            )


class P0ItemEntryView(discord.ui.View):
    def __init__(self, raid, raid_id, items, origin_channel_id, origin_message_id="", event_info=None, context=None):
        super().__init__(timeout=900)
        self.raid = normalize_raid_name(raid)
        self.raid_id = raid_id
        self.items = items or []
        self.origin_channel_id = str(origin_channel_id)
        self.origin_message_id = str(origin_message_id or "")
        self.event_info = event_info or {}
        self.context = context or {"raid": {"raid": self.raid}, "items": self.items, "signups": []}

    @discord.ui.button(label="P0+ eintragen", style=discord.ButtonStyle.success)
    async def open_signup(self, interaction, button):
        selection = {
            "raid": self.raid,
            "raid_id": self.raid_id,
            "raid_pin": str((self.context.get("raid") or {}).get("playerPin") or (self.context.get("raid") or {}).get("prioPin") or self.event_info.get("raidPin") or ""),
            "origin_channel_id": self.origin_channel_id,
            "origin_message_id": self.origin_message_id,
            "event_info": self.event_info,
            "items": self.items
        }
        await interaction.response.send_modal(P0SignupModal(selection))


async def open_p0_signup_flow(message, raid):
    source = (DISCORD_RAIDHELPER_SOURCES.get(raid) or [{}])[0]
    event_info = {}
    if source.get("channel_id"):
        try:
            event_info = await get_raid_event_info_from_source(raid, source)
        except Exception as e:
            print(f"P0 RaidHelper-Datum konnte nicht gelesen werden ({raid}): {e}")

    try:
        context = await get_p0_context(raid, event_info)
    except Exception as e:
        if event_info:
            print(f"P0 Kontext mit Discord-Termin fehlgeschlagen ({raid}), Fallback ohne Termin: {e}")
            event_info = {}
            context = await get_p0_context(raid)
        else:
            raise

    items = context.get("items") or []
    if not items:
        await send_temp(message.channel, f"⚠️ Für {raid} wurden keine Lichtloot-Items gefunden.")
        return

    await message.channel.send(
        f"✅ {message.author.mention}, nutze bitte den vorhandenen P0+ Channelpost. "
        "Die Liste wird erst aktualisiert, wenn eine neue P0+ eingetragen wurde.",
        delete_after=20
    )


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
        return parse_json_api_response(response, "LichtLoot GET", url)


def lichtloot_post(payload):
    data = json.dumps(dict({"guild": current_guild_slug()}, **payload)).encode("utf-8")

    request = urllib.request.Request(
        LICHTLOOT_API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return parse_json_api_response(response, "LichtLoot POST", LICHTLOOT_API_URL)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        snippet = re.sub(r"\s+", " ", body[:400]).strip()
        raise RuntimeError(f"LichtLoot POST HTTP {error.code}: {snippet or error.reason}")


def parse_json_api_response(response, label, url):
    body = response.read().decode("utf-8", errors="replace")
    content_type = str(response.headers.get("Content-Type") or "").lower()
    if "json" not in content_type and body.lstrip().startswith("<"):
        parsed = urlparse(url)
        raise RuntimeError(f"{label}: API lieferte HTML statt JSON von {parsed.netloc or url}. Bitte LICHTLOOT_API_URL auf Railway /api/apps-script setzen.")
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        snippet = re.sub(r"\s+", " ", body[:220]).strip()
        raise RuntimeError(f"{label}: Ungueltige API-Antwort ({error}). Anfang: {snippet}")


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
    queue_payload_key = item.get("payload") if isinstance(item.get("payload"), str) else json.dumps(item.get("payload") or {}, sort_keys=True, default=str)
    queue_key = f"{update_type}:{row_number or item.get('id') or queue_payload_key}"
    now = time.time()
    for old_key, old_time in list(LICHTLOOT_QUEUE_RECENTLY_DONE.items()):
        if now - old_time > 300:
            LICHTLOOT_QUEUE_RECENTLY_DONE.pop(old_key, None)
    if queue_key in LICHTLOOT_QUEUE_IN_PROGRESS:
        print(f"LichtLoot-Queue-Eintrag bereits in Arbeit, uebersprungen: {queue_key}")
        return
    if queue_key in LICHTLOOT_QUEUE_RECENTLY_DONE:
        print(f"LichtLoot-Queue-Eintrag wurde gerade verarbeitet, uebersprungen: {queue_key}")
        return
    LICHTLOOT_QUEUE_IN_PROGRESS.add(queue_key)
    payload = {}

    try:
        raw_payload = item.get("payload") or {}
        payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload or "{}")
    except Exception:
        payload = {}

    try:
        if update_type == "worldbuff_update" and payload.get("deleted"):
            removed = await asyncio.to_thread(remove_deleted_worldbuff_from_all_caches, payload)
            print(f"Worldbuff-Loeschung aus Queue verarbeitet, {removed} Cache-Eintraege entfernt.")

        if update_type == "raid_announcement":
            posted = await post_raid_announcement_by_id(
                payload.get("raidId") or payload.get("id"),
                payload.get("channelId") or payload.get("discordChannelId")
            )
            if posted == "stale":
                print(f"Veraltete Raid-Ankuendigung aus Queue uebersprungen: {payload}")
                posted = True
            if not posted:
                raise RuntimeError(f"Raid-Ankuendigung konnte nicht gepostet werden: {payload}")
        elif update_type == "raid_announcement_refresh":
            refreshed = await refresh_raid_signup_message_by_id(
                payload.get("raidId") or payload.get("id"),
                payload.get("channelId") or payload.get("discordChannelId"),
                payload.get("messageId") or payload.get("discordMessageId") or payload.get("raidHelperMessageId")
            )
            if refreshed == "missing_message":
                print(f"Raid-Anmelder-Refresh ohne gespeicherte Discord-Nachricht uebersprungen: {payload}")
                refreshed = True
            if not refreshed:
                raise RuntimeError(f"Raid-Anmelder konnte nicht aktualisiert werden: {payload}")
        elif update_type == "raid_signup_notice":
            await send_raid_signup_notice(payload)
        elif update_type == "po_post":
            result = await post_standalone_po_list(payload)
            print(f"PO Post erstellt/aktualisiert: {result}")
        elif update_type == "po_post_delete":
            result = await delete_standalone_po_posts(payload)
            print(f"PO Post geloescht: {result}")
        elif update_type == "p0_post_refresh":
            channel_id = payload.get("channelId") or payload.get("discordChannelId")
            raid = payload.get("raid") or payload.get("raidName")
            if not channel_id or not raid:
                raise RuntimeError(f"P0-Post-Refresh unvollstaendig: {payload}")
            context = await update_p0_post(
                raid,
                channel_id,
                {
                    "raidDate": payload.get("raidDate", ""),
                    "raidTime": payload.get("raidTime", ""),
                    "raidPin": payload.get("raidPin") or payload.get("prioPin") or payload.get("playerPin") or "",
                    "discordChannelId": channel_id,
                    "raidHelperMessageId": payload.get("messageId") or payload.get("discordMessageId") or ""
                }
            )
            print(f"P0+-Post nach Freigabe aktualisiert: {context.get('raidId') or raid}")
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
        LICHTLOOT_QUEUE_RECENTLY_DONE[queue_key] = time.time()
    finally:
        LICHTLOOT_QUEUE_IN_PROGRESS.discard(queue_key)


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

    def signup_char_name(value):
        if isinstance(value, dict):
            return str(value.get("char") or value.get("spieler") or value.get("player") or "").strip()
        return str(value or "").strip()

    sorted_signups = sorted(signups.values(), key=lambda x: signup_char_name(x).lower())

    for signup in sorted_signups:
        if isinstance(signup, dict):
            char_name = signup_char_name(signup)
            discord_name = str(signup.get("discordName") or signup.get("discord") or "").strip()
            raw_name = str(signup.get("rawName") or "").strip()
        else:
            char_name = signup_char_name(signup)
            discord_name = ""
            raw_name = ""
        if not char_name:
            continue
        rows.append({
            "char": char_name,
            "spieler": char_name,
            "klasse": "",
            "status": "angemeldet",
            "discordName": discord_name,
            "quelle": source_name,
            "zeitstempel": now,
            "note": f"RaidHelper: {raw_name}" if raw_name and raw_name != char_name else ""
        })

    return rows


async def sync_discord_signup_rows_for_source(raid, source):
    raid = normalize_raid_name(raid)

    raid_message = await get_raid_helper_message(raid, source)
    text_msg = collect_message_text(raid_message)
    raid_date, raid_time = extract_raid_datetime_from_text(text_msg)
    signups = extract_signup_entries_from_text(text_msg)

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
        "queueToken": LICHTBOT_QUEUE_TOKEN,
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



PO_ITEM_ALIASES = {
    "brust4werte": "Formel: Brust - Große Werte",
    "gressil": "Gressil, Vorbote des Untergangs",
    "thc": "Die zehrende Kälte",
    "zehrendekalte": "Die zehrende Kälte",
    "diezehrendekalte": "Die zehrende Kälte"
}


def normalize_po_item_name(item_name):
    raw = str(item_name or "").strip()
    key = prio_key(raw)
    return PO_ITEM_ALIASES.get(key, raw)


def extract_po_from_line(line):
    raw = str(line or "").strip()
    if not raw:
        return None

    # Erkennt nur echte Einzelmeldungen: "PO Item" oder "P0 Item".
    match = re.match(r"^\s*(P0|PO)\b\s*[:\-–—]?\s*(.+)$", raw, re.IGNORECASE)
    if not match:
        return None

    item = match.group(2).strip()
    item = re.sub(r"<[^>]+>", "", item).strip()
    item = item[:120]

    if not item or len(item) < 3:
        return None
    if item.startswith("!"):
        return None
    if normalize_raid_name(item) in {"MC", "BWL", "AQ40", "NAXX", "ZG", "AQ20", "ONY"}:
        return None

    return normalize_po_item_name(item)


def is_plain_po_source_message(message):
    if getattr(getattr(message, "author", None), "bot", False):
        return False
    if getattr(message, "embeds", None):
        return False
    if getattr(message, "components", None):
        return False
    if getattr(message, "attachments", None):
        return False
    content = str(getattr(message, "content", "") or "")
    if not content.strip():
        return False
    return any(extract_po_from_line(line) for line in content.splitlines())


async def po_message_author_display_name(message):
    author = getattr(message, "author", None)
    guild = getattr(message, "guild", None) or getattr(getattr(message, "channel", None), "guild", None)
    member = None
    author_id = getattr(author, "id", None)
    if guild and author_id:
        member = guild.get_member(author_id)
        if member is None:
            try:
                member = await guild.fetch_member(author_id)
            except Exception:
                member = None
    for candidate in [
        getattr(member, "display_name", "") if member else "",
        getattr(member, "nick", "") if member else "",
        getattr(author, "display_name", ""),
        getattr(author, "global_name", ""),
        getattr(author, "name", ""),
        str(author or "")
    ]:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


async def get_po_entries_from_channel(channel_id, limit=800):
    channel = client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    entries = []
    names = {}
    messages_by_id = {}

    async for msg in channel.history(limit=limit):
        if msg.author == client.user or not is_plain_po_source_message(msg):
            continue

        message_text = str(getattr(msg, "content", "") or "")
        item = None

        for line in message_text.splitlines():
            item = extract_po_from_line(line)
            if item:
                break

        if not item:
            continue

        display_name = await po_message_author_display_name(msg)
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
            "discordUserId": str(getattr(msg.author, "id", "") or ""),
            "discordName": display_name,
            "preservePlayerName": True,
            "item": item,
            "messageId": str(msg.id),
            "createdAt": msg.created_at.isoformat()
        })
        messages_by_id[str(msg.id)] = msg

    return names, entries, messages_by_id


async def resolve_po_post_players(entries):
    if not entries:
        return entries
    try:
        result = await asyncio.to_thread(lichtloot_post, {
            "action": "lichtbotResolvePoPostPlayers",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "entries": json.dumps(entries or [], ensure_ascii=False)
        })
        resolved = result.get("entries") or []
        return resolved if isinstance(resolved, list) else entries
    except Exception as e:
        print(f"PO-Post-Spielernamen konnten nicht aufgeloest werden: {e}")
        return entries


async def get_po_entries_for_source(source, limit=800):
    names, entries, _ = await get_po_entries_from_channel(source["channel_id"], limit=limit)
    return names, entries


def po_entry_key(entry):
    message_id = str(entry.get("messageId") or "").strip()
    if message_id:
        return f"msg:{message_id}"
    player = prio_key(entry.get("player") or "")
    item = prio_key(entry.get("item") or "")
    return f"entry:{player}:{item}"


def merge_po_entries(saved_entries, fresh_entries):
    merged = {}
    for entry in saved_entries or []:
        key = po_entry_key(entry)
        if key:
            merged[key] = dict(entry)
    for entry in fresh_entries or []:
        key = po_entry_key(entry)
        if key:
            merged[key] = {**merged.get(key, {}), **dict(entry)}
    return list(merged.values())


async def load_saved_po_post_entries(payload, source_channel_id, target_channel_id):
    try:
        result = await asyncio.to_thread(lichtloot_get, {
            "action": "lichtbotGetPoPostEntries",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "postKey": payload.get("postKey") or payload.get("poPostKey") or "",
            "sourceChannelId": str(source_channel_id or ""),
            "targetChannelId": str(target_channel_id or ""),
            "raid": payload.get("raid") or ""
        })
    except Exception as e:
        print(f"Gespeicherte PO-Post-Eintraege konnten nicht geladen werden: {e}")
        return []
    entries = result.get("entries") or []
    return entries if isinstance(entries, list) else []


async def load_po_item_points(raid=""):
    try:
        result = await asyncio.to_thread(lichtloot_get, {"action": "getP0Plus"})
    except Exception as e:
        print(f"PO+-Punkte konnten nicht geladen werden: {e}")
        return {}
    wanted_raid = normalize_raid_name(raid)
    points_by_item = {}
    for row in result.get("entries") or []:
        row_raid = normalize_raid_name(row.get("raid") or "")
        if wanted_raid and row_raid and row_raid != wanted_raid:
            continue
        item_key = prio_key(row.get("item") or "")
        player = str(row.get("player") or "").strip()
        if not item_key or not player:
            continue
        try:
            points = float(row.get("count") or row.get("points") or 0)
        except Exception:
            points = 0
        if points <= 0:
            continue
        point_date = format_po_point_date(
            row.get("createdAt")
            or row.get("created_at")
            or row.get("updatedAt")
            or row.get("updated_at")
            or ""
        )
        points_by_item.setdefault(item_key, []).append({
            "player": player,
            "points": points,
            "date": point_date
        })
    return points_by_item


def annotate_po_entries_with_points(entries, points_by_item):
    annotated = []
    for entry in entries or []:
        copy = dict(entry)
        item_key = prio_key(copy.get("item") or "")
        holders = list(points_by_item.get(item_key, []))
        holders.sort(key=lambda row: (str(row.get("player") or "").lower(), float(row.get("points") or 0)))
        copy["itemP0PlusPoints"] = holders
        annotated.append(copy)
    return annotated


def po_points_suffix(entry):
    holders = entry.get("itemP0PlusPoints") or []
    if not holders:
        return ""
    parts = []
    for holder in holders[:6]:
        try:
            points = f"{float(holder.get('points') or 0):g}"
        except Exception:
            points = str(holder.get("points") or "0")
        parts.append(f"{holder.get('player')} {points}")
    suffix = ", ".join(parts)
    if len(holders) > 6:
        suffix += f", +{len(holders) - 6}"
    return f" ({suffix})"


def po_points_suffix_for_item(points_by_item, item_name):
    item_key = prio_key(item_name or "")
    holders = list((points_by_item or {}).get(item_key, []))
    if not holders:
        return ""
    return po_points_suffix({"itemP0PlusPoints": holders})


def format_po_point_date(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(BERLIN_TZ)
        return dt.strftime("%d.%m.%Y")
    except Exception:
        if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
            return f"{raw[8:10]}.{raw[5:7]}.{raw[0:4]}"
        return raw


def po_entry_time_suffix(entry):
    raw = str(
        entry.get("createdAt")
        or entry.get("poCreatedAt")
        or entry.get("po_created_at")
        or ""
    ).strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(BERLIN_TZ)
        return f" · {dt.strftime('%d.%m.%Y %H:%M')} Uhr"
    except Exception:
        return f" · {raw}"


def build_standalone_po_entries_text(entries):
    sorted_entries = sorted(
        entries or [],
        key=lambda item: (str(item.get("player") or "").lower(), str(item.get("item") or "").lower())
    )
    if not sorted_entries:
        return "Keine PO-Einträge gefunden. Nutzt im Quellchannel z. B. `PO Itemname` oder `P0 Itemname`."

    lines = []
    lines.append(f"Gefunden: **{len(sorted_entries)}** Eintrag/Einträge")
    lines.append("")
    for idx, entry in enumerate(sorted_entries, start=1):
        player = str(entry.get("player") or "-").strip()
        item = str(entry.get("item") or "-").strip()
        suffix = " ✅" if str(entry.get("approvalStatus") or "").lower() == "approved" else ""
        lines.append(f"{idx}. **{player}** → {item}{po_points_suffix(entry)}{suffix}")
    return "\n".join(lines)


def po_signup_group_by_item(payload):
    value = str(
        payload.get("groupBy")
        or payload.get("poGroupBy")
        or payload.get("sortBy")
        or ""
    ).strip().lower()
    return value in {"item", "items", "loot", "gegenstand", "gegenstaende", "gegenstände"}


def build_po_signup_entries_by_class_text(entries, include_points=True):
    all_entries = list(entries or [])
    if not all_entries:
        return "**Anmeldungen:**\nNoch keine PO-Anmeldung vorhanden."

    grouped = {}
    for entry in all_entries:
        class_name = canonical_signup_class(entry.get("className") or entry.get("class_name") or entry.get("klasse") or "Ohne Klasse")
        grouped.setdefault(class_name, []).append(entry)

    lines = [f"**Anmeldungen ({len(all_entries)}):**"]
    for class_name in sorted(grouped.keys(), key=signup_class_sort_key):
        rows = sorted(
            grouped[class_name],
            key=lambda item: (str(item.get("item") or "").lower(), str(item.get("player") or "").lower())
        )
        lines.append("")
        lines.append(f"__{signup_class_heading(class_name, len(rows))}__")
        rows_by_item = {}
        for entry in rows:
            item = str(entry.get("item") or "-").strip() or "-"
            rows_by_item.setdefault(item, []).append(entry)
        for item in sorted(rows_by_item.keys(), key=lambda value: value.lower()):
            item_rows = rows_by_item[item]
            players = []
            for entry in item_rows:
                player = str(entry.get("player") or "-").strip()
                status = str(entry.get("approvalStatus") or "").lower()
                suffix = " ✅" if status == "approved" else " ❌" if status == "rejected" else ""
                luck = " 🍀" if str(entry.get("luckBy") or entry.get("luck_by") or "").strip() else ""
                players.append(f"{player}{suffix}{luck}")
            points_text = po_points_suffix(item_rows[0]) if include_points else ""
            lines.append(f"{po_item_icon(item)} **{item}**{points_text} → {', '.join(players)}")
    return "\n".join(lines)


def build_po_signup_entries_by_item_text(entries, include_points=True):
    all_entries = list(entries or [])
    if not all_entries:
        return "**Anmeldungen:**\nNoch keine PO-Anmeldung vorhanden."

    grouped = {}
    for entry in all_entries:
        item_name = str(entry.get("item") or "-").strip() or "-"
        grouped.setdefault(item_name, []).append(entry)

    lines = [f"**Anmeldungen ({len(all_entries)}):**"]
    for item_name in sorted(grouped.keys(), key=lambda value: value.lower()):
        rows = sorted(
            grouped[item_name],
            key=lambda item: (
                signup_class_sort_key(canonical_signup_class(item.get("className") or item.get("class_name") or item.get("klasse") or "Ohne Klasse")),
                str(item.get("player") or "").lower()
            )
        )
        if lines:
            lines.append("━━━━━━━━━━━━━━━━")
        points_text = po_points_suffix(rows[0]) if include_points else ""
        lines.append(f"{po_item_icon(item_name)} **{item_name}{points_text} ({len(rows)})**")
        players = []
        for entry in rows:
            player = str(entry.get("player") or "-").strip()
            class_name = canonical_signup_class(entry.get("className") or entry.get("class_name") or entry.get("klasse") or "Ohne Klasse")
            status = str(entry.get("approvalStatus") or "").lower()
            suffix = " ✅" if status == "approved" else " ❌" if status == "rejected" else ""
            luck = " 🍀" if str(entry.get("luckBy") or entry.get("luck_by") or "").strip() else ""
            players.append(f"{signup_class_icon(class_name)} {player}{suffix}{luck}")
        lines.append(", ".join(players))
    return "\n".join(lines)


def build_po_signup_entries_text(entries, payload=None, include_points=True):
    if payload and po_signup_group_by_item(payload):
        return build_po_signup_entries_by_item_text(entries, include_points=include_points)
    return build_po_signup_entries_by_class_text(entries, include_points=include_points)


def is_po_signup_payload(payload):
    mode = str(payload.get("mode") or payload.get("poMode") or "").strip().lower()
    if mode in {"signup", "anmelder", "po_signup", "po-anmelder"}:
        return True
    post_key = str(payload.get("postKey") or payload.get("poPostKey") or "").strip().lower()
    title = str(payload.get("title") or "").strip().lower()
    if "po-anmelder" in post_key or "po_anmelder" in post_key or "anmelder" in title:
        return True
    return bool(po_signup_item_options(payload))


async def send_long_discord_text(channel, text):
    chunks = []
    current = ""
    for line in str(text or "").splitlines():
        candidate = (current + "\n" + line).strip() if current else line
        if len(candidate) > 1900:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    for chunk in chunks or ["-"]:
        await channel.send(chunk)


def po_post_state_key(payload):
    post_key = str(payload.get("postKey") or payload.get("poPostKey") or "").strip()
    if post_key:
        return "post:" + normalize_p0_reviewer_name(post_key)
    source = str(payload.get("sourceChannelId") or payload.get("channelId") or "").strip()
    target = str(payload.get("targetChannelId") or payload.get("discordChannelId") or source or "").strip()
    title = str(payload.get("title") or "PO Liste").strip().casefold()
    return f"{target}:{source}:{title}"


def is_standalone_po_message(message, payload):
    text = str(getattr(message, "content", "") or "")
    post_key = str(payload.get("postKey") or payload.get("poPostKey") or "").strip()
    if post_key and re.search(rf"Post-ID:\s*`?{re.escape(post_key)}`?", text, re.IGNORECASE):
        return True
    title = str(payload.get("title") or "PO Liste").strip() or "PO Liste"
    source_channel_id = str(payload.get("sourceChannelId") or payload.get("channelId") or "").strip()
    if f"📋 **{title}**" not in text and f"**{title}**" not in text:
        return False
    if source_channel_id and f"Quelle: <#{source_channel_id}>" not in text and "Post-ID:" not in text:
        return False
    return "PO-Post" in text or "PO-Einträge" in text or "Vollständige Liste" in text


def build_po_signup_post_text(payload, entries, full_text):
    title = str(payload.get("title") or "PO-Anmelder").strip() or "PO-Anmelder"
    raid = normalize_raid_name(payload.get("raid") or "")
    raid_date = format_raid_announcement_date(payload.get("raidDate") or payload.get("date") or "")
    raid_time = format_raid_announcement_time(payload.get("raidTime") or payload.get("time") or "")
    review_recipient = str(payload.get("reviewRecipient") or "").strip()
    raidlead_note = str(payload.get("note") or payload.get("message") or payload.get("raidleadMessage") or payload.get("extraMessage") or "").strip()
    if normalize_p0_reviewer_name(raidlead_note) in {
        normalize_p0_reviewer_name("Wähle unten dein Item aus und trage danach Charakter + Spielerlogin ein."),
        normalize_p0_reviewer_name("Anmelden: Unten ein Item auswählen, Charakter + Spielerlogin eintragen. Der Eintrag erscheint danach direkt hier im Post."),
        normalize_p0_reviewer_name("Unten ein Item auswählen, Charakter + Spielerlogin eintragen. Der Eintrag erscheint danach direkt hier im Post.")
    }:
        raidlead_note = ""
    post_key = str(payload.get("postKey") or payload.get("poPostKey") or "").strip()
    item_options = po_signup_item_options(payload)
    lines = [f"📋 **{title}**", "**PO-Anmelder**"]
    if post_key:
        lines.append(f"Post-ID: `{post_key}`")
    if raid:
        lines.append(f"Raid: **{display_raid_name(raid)}**")
    if raid_date != "noch offen" or raid_time != "noch offen":
        lines.append(f"Termin: **{raid_date} · {raid_time}**")
    if review_recipient:
        lines.append(f"Freigabe per DM an: **{review_recipient}**")
    lines.append("")
    lines.extend(str(full_text or "").splitlines())
    if raidlead_note:
        lines.append("")
        lines.append("**Hinweis:**")
        lines.append(raidlead_note[:500])
    text = "\n".join(lines)
    if len(text) <= 1900:
        return text
    compact_full_text = build_po_signup_entries_text(entries, payload, include_points=False)
    compact_lines = [f"📋 **{title}**", "**PO-Anmelder**"]
    if post_key:
        compact_lines.append(f"Post-ID: `{post_key}`")
    if raid:
        compact_lines.append(f"Raid: **{display_raid_name(raid)}**")
    if raid_date != "noch offen" or raid_time != "noch offen":
        compact_lines.append(f"Termin: **{raid_date} · {raid_time}**")
    compact_lines.extend(["", compact_full_text])
    compact_text = "\n".join(compact_lines)
    if len(compact_text) <= 1900:
        return compact_text
    kept = []
    used = 0
    for line in compact_lines:
        next_len = used + len(line) + (1 if kept else 0)
        if next_len > 1840:
            break
        kept.append(line)
        used = next_len
    kept.extend(["", "Liste ist zu lang für eine Discord-Nachricht."])
    return "\n".join(kept)[:1900]


def build_po_channel_post_text(payload, entries, full_text):
    if is_po_signup_payload(payload):
        return build_po_signup_post_text(payload, entries, full_text)
    title = str(payload.get("title") or "PO Liste").strip() or "PO Liste"
    raid = normalize_raid_name(payload.get("raid") or "")
    source_channel_id = str(payload.get("sourceChannelId") or "").strip()
    review_recipient = str(payload.get("reviewRecipient") or "").strip()
    raidlead_note = str(payload.get("note") or payload.get("message") or payload.get("raidleadMessage") or payload.get("extraMessage") or "").strip()
    post_key = str(payload.get("postKey") or payload.get("poPostKey") or "").strip()
    lines = [f"📋 **{title}**", "PO-Post"]
    if post_key:
        lines.append(f"Post-ID: `{post_key}`")
    if raid:
        lines.append(f"Raid: **{display_raid_name(raid)}**")
    if source_channel_id:
        lines.append(f"Quelle: <#{source_channel_id}>")
    if review_recipient:
        lines.append(f"Freigabe per DM an: **{review_recipient}**")
    if raidlead_note:
        lines.append("")
        lines.append("**Nachricht der Raidleitung:**")
        lines.append(raidlead_note[:700])
    command_lines = [
        "",
        "━━━━━━━━━━━━━━━",
        "**PO-Anmelder**",
        "Unten auf **PO eintragen** klicken und Item + Charakter eintragen.",
        "Eigene Einträge können über **PO-Eintrag löschen** entfernt werden."
    ]
    command_text = "\n".join(command_lines)
    if len(full_text) + len(command_text) > 1750:
        lines.append(f"Gefunden: **{len(entries or [])}** Eintrag/Einträge")
        lines.append("Vollständige Liste ist als Datei angehängt.")
        lines.extend(command_lines)
    else:
        lines.append("")
        lines.append(full_text)
        lines.extend(command_lines)
    return "\n".join(lines)[:1900]


def po_list_file(text):
    data = str(text or "-").encode("utf-8")
    return discord.File(BytesIO(data), filename="po-liste.txt")


def po_guide_file():
    try:
        if PO_GUIDE_IMAGE_PATH.exists():
            return discord.File(str(PO_GUIDE_IMAGE_PATH), filename="po-anleitung.jpeg")
    except Exception as e:
        print(f"PO-Anleitung konnte nicht angehaengt werden: {e}")
    return None


def stable_po_entry_for_fingerprint(entry):
    return {
        "player": str(entry.get("player") or "").strip(),
        "item": str(entry.get("item") or "").strip(),
        "messageId": str(entry.get("messageId") or entry.get("discordMessageId") or "").strip(),
        "createdAt": str(entry.get("createdAt") or entry.get("poCreatedAt") or "").strip(),
        "approvalStatus": str(entry.get("approvalStatus") or "").strip().lower(),
        "approvedBy": str(entry.get("approvedBy") or "").strip(),
        "luckBy": str(entry.get("luckBy") or entry.get("luck_by") or "").strip(),
        "points": [
            {
                "player": str(holder.get("player") or "").strip(),
                "points": str(holder.get("points") or "").strip()
            }
            for holder in entry.get("itemP0PlusPoints") or []
        ]
    }


def normalize_po_post_text_for_compare(text):
    return "\n".join(
        line
        for line in str(text or "").splitlines()
        if not re.match(r"^\s*Aktualisiert:\s*", line, re.IGNORECASE)
    ).strip()


def po_post_fingerprint(payload, entries, text):
    post_key = str(payload.get("postKey") or payload.get("poPostKey") or "").strip()
    source = str(payload.get("sourceChannelId") or payload.get("channelId") or "").strip()
    target = str(payload.get("targetChannelId") or payload.get("discordChannelId") or source or "").strip()
    title = str(payload.get("title") or "PO Liste").strip()
    payload_text = json.dumps(
        {
            "postKey": post_key,
            "source": source,
            "target": target,
            "title": title,
            "entries": [stable_po_entry_for_fingerprint(entry) for entry in entries or []],
            "text": normalize_po_post_text_for_compare(text)
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str
    )
    return hashlib.sha256(payload_text.encode("utf-8")).hexdigest()


async def load_po_post_approvals(payload):
    try:
        result = await asyncio.to_thread(lichtloot_get, {
            "action": "lichtbotGetPoPostApprovals",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "postKey": payload.get("postKey") or payload.get("poPostKey") or "",
            "sourceChannelId": str(payload.get("sourceChannelId") or payload.get("channelId") or ""),
            "targetChannelId": str(payload.get("targetChannelId") or payload.get("discordChannelId") or "")
        })
    except Exception as e:
        print(f"PO-Freigaben konnten nicht geladen werden: {e}")
        return {}
    approvals = {}
    for row in result.get("entries") or []:
        status = str(row.get("approvalStatus") or "").lower()
        message_id = str(row.get("messageId") or "").strip()
        player = str(row.get("player") or "").strip().lower()
        item = str(row.get("item") or "").strip().lower()
        if message_id:
            approvals[message_id] = status
        if player or item:
            approvals[f"{player}|{item}"] = status
    return approvals


def apply_po_post_approvals(entries, approvals, raid=""):
    raid_key = normalize_raid_name(raid)
    updated = []
    for entry in entries or []:
        copy = dict(entry)
        message_id = str(copy.get("messageId") or "").strip()
        player = str(copy.get("player") or "").strip().lower()
        item = str(copy.get("item") or "").strip().lower()
        status = approvals.get(message_id) or approvals.get(f"{player}|{item}") or ""
        if not status and has_p0_release(copy.get("player") or "", raid_key):
            status = "approved"
        if status:
            copy["approvalStatus"] = status
        updated.append(copy)
    return updated


async def upsert_standalone_po_post(channel, payload, entries, text):
    key = po_post_state_key(payload)
    lock = PO_POST_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        state = load_json(po_post_file(), {})
        state_entry = state.get(key)
        if isinstance(state_entry, dict):
            message_id = state_entry.get("messageId")
            previous_hash = state_entry.get("hash")
        else:
            message_id = state_entry
            previous_hash = ""
        current_hash = po_post_fingerprint(payload, entries, text)
        candidates = []
        if message_id:
            try:
                candidates.append(await channel.fetch_message(int(message_id)))
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"PO-Post {message_id} konnte nicht geladen werden:", e)

        found_messages = await find_recent_own_messages(
            channel,
            lambda message: is_standalone_po_message(message, payload),
            limit=500
        )
        candidate_ids = {message.id for message in candidates}
        candidates.extend(message for message in found_messages if message.id not in candidate_ids)
        target_message = candidates[0] if candidates else None
        post_text = build_po_channel_post_text(payload, entries, text)
        def make_files():
            files = []
            if len(text) > 1800:
                files.append(po_list_file(text))
            guide = None if is_po_signup_payload(payload) else po_guide_file()
            if guide:
                files.append(guide)
            return files or None

        target_has_guide = bool(
            target_message
            and any(
                str(getattr(attachment, "filename", "") or "").lower() == "po-anleitung.jpeg"
                for attachment in getattr(target_message, "attachments", []) or []
            )
        )
        guide_expected = (not is_po_signup_payload(payload)) and PO_GUIDE_IMAGE_PATH.exists()

        target_text_matches = (
            target_message
            and len(text) <= 1800
            and (not guide_expected or target_has_guide)
            and (not is_po_signup_payload(payload) or not getattr(target_message, "attachments", None))
            and normalize_po_post_text_for_compare(getattr(target_message, "content", "") or "")
                == normalize_po_post_text_for_compare(post_text)
        )
        target_file_post = bool(
            target_message
            and len(text) > 1800
            and (not guide_expected or target_has_guide)
            and (not is_po_signup_payload(payload) or not getattr(target_message, "attachments", None))
        )

        if target_message and previous_hash == current_hash and (target_text_matches or target_file_post):
            keep = target_message
            try:
                await keep.edit(view=PoSignupView(payload, entries))
            except Exception as e:
                print(f"PO-Post View konnte nicht aktualisiert werden: {e}")
            for message in candidates:
                if message.id == keep.id:
                    continue
                try:
                    await message.delete()
                    await asyncio.sleep(0.4)
                except Exception:
                    pass
            state[key] = {"messageId": str(keep.id), "hash": current_hash, "payload": payload}
            save_json(po_post_file(), state)
            return keep, False

        msg = None
        if target_message:
            try:
                await target_message.edit(content=post_text, attachments=[], files=make_files(), view=PoSignupView(payload, entries))
                msg = target_message
            except Exception as e:
                print(f"PO-Post {target_message.id} konnte nicht bearbeitet werden:", e)
                try:
                    await target_message.delete()
                except Exception:
                    pass

        for message in candidates:
            if msg and message.id == msg.id:
                continue
            try:
                await message.delete()
                await asyncio.sleep(0.4)
            except Exception:
                pass

        if not msg:
            files = make_files()
            if files:
                msg = await send_silent(channel, post_text, files=files, view=PoSignupView(payload, entries))
            else:
                msg = await send_silent(channel, post_text, view=PoSignupView(payload, entries))

        await asyncio.sleep(2)
        cleanup_messages = await find_recent_own_messages(
            channel,
            lambda message: is_standalone_po_message(message, payload),
            limit=500
        )
        keep = max(cleanup_messages or [msg], key=lambda message: int(message.id))
        for message in cleanup_messages:
            if message.id == keep.id:
                continue
            try:
                await message.delete()
                await asyncio.sleep(0.4)
            except Exception:
                pass

        state[key] = {"messageId": str(keep.id), "hash": current_hash, "payload": payload}
        save_json(po_post_file(), state)
        return keep, True


async def delete_standalone_po_posts(payload):
    channel_ids = []
    target_channel_id = payload.get("targetChannelId") or payload.get("discordChannelId")
    fallback_source_channel_id = payload.get("sourceChannelId") or payload.get("channelId")
    for value in [target_channel_id or fallback_source_channel_id]:
        text = str(value or "").strip()
        if text and text not in channel_ids:
            channel_ids.append(text)

    deleted = 0
    for channel_id in channel_ids:
        try:
            channel = client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
        except Exception as e:
            print(f"PO-Post-Loeschung: Channel {channel_id} konnte nicht geladen werden: {e}")
            continue

        message_id = str(payload.get("messageId") or payload.get("discordMessageId") or "").strip()
        if message_id:
            try:
                msg = await channel.fetch_message(int(message_id))
                if is_own_discord_message(msg) and is_standalone_po_message(msg, payload):
                    await msg.delete()
                    deleted += 1
                    await asyncio.sleep(0.25)
                elif is_own_discord_message(msg):
                    print(f"PO-Post-Loeschung: Nachricht {message_id} ist kein PO-Sammelpost, wird nicht geloescht.")
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"PO-Post-Loeschung: Nachricht {message_id} konnte nicht geloescht werden: {e}")

        matches = await find_recent_own_messages(
            channel,
            lambda message: is_standalone_po_message(message, payload),
            limit=500
        )
        for message in matches:
            try:
                await message.delete()
                deleted += 1
                await asyncio.sleep(0.25)
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"PO-Post-Loeschung: Nachricht {message.id} konnte nicht geloescht werden: {e}")

    state = load_json(po_post_file(), {})
    key = po_post_state_key(payload)
    state.pop(key, None)
    save_json(po_post_file(), state)
    return {"deleted": deleted, "postKey": payload.get("postKey") or payload.get("poPostKey") or ""}


async def refresh_saved_po_posts_for_source(source_channel_id, cleanup_source=False, post_key_filter=""):
    refreshed = []
    payloads = await po_post_payloads_for_source(source_channel_id, post_key_filter)
    for payload in payloads:
        try:
            run_payload = {**payload, "cleanupSource": cleanup_source}
            result = await post_standalone_po_list(run_payload)
            refreshed.append({**result, "key": payload.get("postKey") or payload.get("poPostKey") or ""})
        except Exception as e:
            print(f"Automatische PO-Post-Aktualisierung fehlgeschlagen ({payload.get('postKey') or '-'}): {e}")
    return refreshed


def saved_po_post_payloads_for_source(source_channel_id, post_key_filter=""):
    state = load_json(po_post_file(), {})
    channel_text = str(source_channel_id or "").strip()
    wanted_post_key = str(post_key_filter or "").strip()
    payloads = []
    for key, state_entry in list(state.items()):
        if not isinstance(state_entry, dict):
            continue
        payload = state_entry.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        saved_source = str(payload.get("sourceChannelId") or payload.get("channelId") or "").strip()
        saved_target = str(payload.get("targetChannelId") or payload.get("discordChannelId") or saved_source).strip()
        if channel_text not in {saved_source, saved_target}:
            continue
        saved_post_key = str(payload.get("postKey") or payload.get("poPostKey") or "").strip()
        if wanted_post_key and saved_post_key != wanted_post_key:
            continue
        payloads.append(payload)
    return payloads


async def railway_po_post_payloads_for_source(source_channel_id, post_key_filter=""):
    channel_text = str(source_channel_id or "").strip()
    wanted_post_key = str(post_key_filter or "").strip()
    results = []
    for channel_param in ("sourceChannelId", "targetChannelId"):
        try:
            result = await asyncio.to_thread(lichtloot_get, {
                "action": "lichtbotGetPoPostEntries",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                channel_param: channel_text,
                "postKey": wanted_post_key
            })
            results.extend(result.get("entries") or [])
        except Exception as e:
            print(f"PO-Post-Konfiguration konnte nicht aus Railway geladen werden ({channel_param}): {e}")
    by_key = {}
    for entry in results:
        post_key = str(entry.get("postKey") or "").strip()
        if wanted_post_key and post_key != wanted_post_key:
            continue
        if not post_key:
            continue
        by_key.setdefault(post_key, {
            "postKey": post_key,
            "sourceChannelId": str(entry.get("sourceChannelId") or channel_text),
            "targetChannelId": str(entry.get("targetChannelId") or entry.get("sourceChannelId") or channel_text),
            "raid": entry.get("raid") or "",
            "title": entry.get("title") or "PO Liste",
            "limit": 800
        })
    return list(by_key.values())


async def po_post_payloads_for_source(source_channel_id, post_key_filter=""):
    payloads = saved_po_post_payloads_for_source(source_channel_id, post_key_filter)
    if payloads:
        return payloads
    return await railway_po_post_payloads_for_source(source_channel_id, post_key_filter)


async def delete_po_post_entry_for_user(channel, user, item_text, post_key_filter="", player_name="", player_pin=""):
    item_text = normalize_po_item_name(item_text)
    player_name = str(player_name or "").strip()
    if not item_text:
        raise RuntimeError("Bitte Itemnamen angeben, z. B. `!podel THC`.")
    if not player_name:
        raise RuntimeError("Bitte Spielernamen/Charakter angeben.")

    payloads = await po_post_payloads_for_source(channel.id, post_key_filter)
    if not payloads:
        detail = f" mit Post-ID `{post_key_filter}`" if post_key_filter else ""
        raise RuntimeError(f"Kein gespeicherter PO-Post für diesen Channel{detail} gefunden.")

    deleted_total = 0
    deleted_messages = 0
    touched_post_keys = []
    for payload in payloads:
        source_channel_id = str(payload.get("sourceChannelId") or payload.get("channelId") or channel.id)
        target_channel_id = str(payload.get("targetChannelId") or payload.get("discordChannelId") or source_channel_id)
        post_key = str(payload.get("postKey") or payload.get("poPostKey") or "").strip()
        result = await asyncio.to_thread(lichtloot_post, {
            "action": "lichtbotDeletePoPostEntry",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "postKey": post_key,
            "sourceChannelId": source_channel_id,
            "targetChannelId": target_channel_id,
            "discordUserId": str(getattr(user, "id", "") or ""),
            "player": player_name,
            "playerPin": str(player_pin or ""),
            "item": item_text
        })
        deleted = int(result.get("deleted") or 0)
        if deleted <= 0:
            continue
        deleted_total += deleted
        touched_post_keys.append(post_key or "-")
        for entry in result.get("entries") or []:
            message_id = str(entry.get("messageId") or "").strip()
            if not message_id:
                continue
            try:
                source_message = await channel.fetch_message(int(message_id))
                await source_message.delete()
                deleted_messages += 1
                await asyncio.sleep(0.25)
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print(f"PO-Loeschung: Quellnachricht {message_id} konnte nicht geloescht werden, Rechte fehlen.")
            except Exception as e:
                print(f"PO-Loeschung: Quellnachricht {message_id} konnte nicht geloescht werden: {e}")
        await post_standalone_po_list(payload)

    return {
        "deleted": deleted_total,
        "deletedMessages": deleted_messages,
        "postKeys": touched_post_keys
    }


class PoDeleteModal(discord.ui.Modal):
    def __init__(self, channel_id, default_item="", default_post_key="", default_player=""):
        self.channel_id = str(channel_id)
        super().__init__(title="PO-Eintrag löschen")
        self.player_name = discord.ui.TextInput(
            label="Spieler / Charakter",
            placeholder="z. B. Ariee",
            default=str(default_player or "")[:50],
            required=True,
            max_length=50
        )
        self.item_name = discord.ui.TextInput(
            label="Item",
            placeholder="z. B. THC",
            default=str(default_item or "")[:100],
            required=True,
            max_length=120
        )
        self.player_pin = discord.ui.TextInput(
            label="LichtLoot Spielerlogin",
            placeholder="dein LichtLoot Spielerlogin",
            required=True,
            max_length=20
        )
        self.post_key = discord.ui.TextInput(
            label="Post-ID optional",
            placeholder="z. B. po-liste-mir1ao",
            default=str(default_post_key or "")[:80],
            required=False,
            max_length=80
        )
        self.add_item(self.player_name)
        self.add_item(self.item_name)
        self.add_item(self.player_pin)
        self.add_item(self.post_key)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        channel = client.get_channel(int(self.channel_id)) or await client.fetch_channel(int(self.channel_id))
        result = await delete_po_post_entry_for_user(
            channel,
            interaction.user,
            str(self.item_name.value or ""),
            str(self.post_key.value or ""),
            str(self.player_name.value or ""),
            str(self.player_pin.value or "")
        )
        deleted = int(result.get("deleted") or 0)
        if deleted <= 0:
            await interaction.followup.send(
                "⚠️ Kein eigener PO-Eintrag mit diesem Item gefunden.",
                ephemeral=True
            )
            return
        post_keys = ", ".join(sorted(set(result.get("postKeys") or []))) or "-"
        await interaction.followup.send(
            f"✅ Dein PO-Eintrag wurde gelöscht.\nPost: `{post_keys}`",
            ephemeral=True
        )


def po_delete_entry_options(entries):
    result = []
    seen = set()
    for idx, entry in enumerate(entries or []):
        player = str(entry.get("player") or "").strip()
        item = str(entry.get("item") or "").strip()
        if not player or not item:
            continue
        key = f"{prio_key(player)}|{prio_key(item)}"
        if key in seen:
            continue
        seen.add(key)
        result.append((str(idx), f"{player} · {item}"[:100], player, item))
        if len(result) >= 25:
            break
    return result


class PoDeleteConfirmModal(discord.ui.Modal):
    def __init__(self, payload, entry):
        self.payload = payload
        self.entry = entry
        player = str(entry.get("player") or "").strip()
        super().__init__(title="PO-Eintrag löschen")
        self.player_pin = discord.ui.TextInput(
            label=f"LichtLoot Login für {player}"[:45],
            placeholder="dein LichtLoot Spielerlogin",
            required=True,
            max_length=20
        )
        self.add_item(self.player_pin)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            source_channel_id = str(self.payload.get("sourceChannelId") or self.payload.get("channelId") or "").strip()
            channel = client.get_channel(int(source_channel_id)) or await client.fetch_channel(int(source_channel_id))
            result = await delete_po_post_entry_for_user(
                channel,
                interaction.user,
                str(self.entry.get("item") or ""),
                str(self.payload.get("postKey") or self.payload.get("poPostKey") or ""),
                str(self.entry.get("player") or ""),
                str(self.player_pin.value or "")
            )
            deleted = int(result.get("deleted") or 0)
            if deleted <= 0:
                await interaction.followup.send("⚠️ Dieser PO-Eintrag wurde nicht gefunden.", ephemeral=True)
                return
            await interaction.followup.send(
                f"✅ PO-Eintrag gelöscht: **{self.entry.get('player')}** → **{self.entry.get('item')}**.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"⚠️ PO-Eintrag konnte nicht gelöscht werden: `{e}`", ephemeral=True)


class PoDeleteEntrySelect(discord.ui.Select):
    def __init__(self, payload, entries):
        self.payload = payload
        self.entries = list(entries or [])
        options = []
        for value, label, _player, item in po_delete_entry_options(self.entries):
            options.append(discord.SelectOption(
                label=label,
                value=value,
                description=item[:100] if item and item not in label else None,
                emoji="🗑️"
            ))
        super().__init__(
            placeholder="PO-Eintrag zum Löschen auswählen",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"po_delete_select:{str(payload.get('postKey') or payload.get('poPostKey') or 'default').strip()[:56] or 'default'}"
        )

    async def callback(self, interaction):
        try:
            idx = int(self.values[0])
            entry = self.entries[idx]
            await interaction.response.send_modal(PoDeleteConfirmModal(self.payload, entry))
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"⚠️ PO-Eintrag konnte nicht vorbereitet werden: `{e}`", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ PO-Eintrag konnte nicht vorbereitet werden: `{e}`", ephemeral=True)


class PoDeleteEntryView(discord.ui.View):
    def __init__(self, payload, entries):
        super().__init__(timeout=180)
        if po_delete_entry_options(entries or []):
            self.add_item(PoDeleteEntrySelect(payload, entries or []))


class PoDeleteButton(discord.ui.Button):
    def __init__(self, channel_id, default_item="", default_post_key="", default_player="", payload=None, entries=None):
        post_key = str(default_post_key or "default").strip()[:70]
        super().__init__(
            label="PO-Eintrag löschen",
            style=discord.ButtonStyle.danger,
            custom_id=f"po_delete:{post_key or 'default'}"
        )
        self.channel_id = str(channel_id)
        self.default_item = default_item
        self.default_post_key = default_post_key
        self.default_player = default_player
        self.payload = payload or {}
        self.entries = list(entries or [])

    async def callback(self, interaction):
        if self.payload:
            await interaction.response.defer(ephemeral=True)
            entries = self.entries
            if not po_delete_entry_options(entries):
                source_channel_id = str(self.payload.get("sourceChannelId") or self.payload.get("channelId") or self.channel_id)
                target_channel_id = str(self.payload.get("targetChannelId") or self.payload.get("discordChannelId") or source_channel_id)
                entries = await load_saved_po_post_entries(self.payload, source_channel_id, target_channel_id)
            if po_delete_entry_options(entries):
                await interaction.followup.send(
                    "Wähle den PO-Eintrag aus, den du löschen möchtest.",
                    view=PoDeleteEntryView(self.payload, entries),
                    ephemeral=True
                )
                return
            await interaction.followup.send("⚠️ Keine PO-Einträge zum Löschen gefunden.", ephemeral=True)
            return
        await interaction.response.send_modal(PoDeleteModal(
            self.channel_id,
            self.default_item,
            self.default_post_key,
            self.default_player or infer_worldbuff_char_from_discord_name(interaction.user.display_name)
        ))


class PoDeleteView(discord.ui.View):
    def __init__(self, channel_id, default_item="", default_post_key="", default_player=""):
        super().__init__(timeout=180)
        self.add_item(PoDeleteButton(channel_id, default_item, default_post_key, default_player))


async def find_po_post_payload_for_signup(channel_id, raid="", post_key_filter=""):
    raid_key = normalize_raid_name(raid)
    payloads = await po_post_payloads_for_source(channel_id, post_key_filter)
    if raid_key:
        raid_matches = [
            payload for payload in payloads
            if normalize_raid_name(payload.get("raid") or "") == raid_key
        ]
        if raid_matches:
            return raid_matches[0]
    return payloads[0] if payloads else None


PO_SIGNUP_CLASS_SELECTIONS = {}


def po_signup_selection_key(payload, user_id):
    post_key = str(payload.get("postKey") or payload.get("poPostKey") or "default").strip()
    return f"{post_key}:{user_id}"


def selected_po_signup_class(payload, user):
    return PO_SIGNUP_CLASS_SELECTIONS.get(po_signup_selection_key(payload, getattr(user, "id", "")), "")


async def save_po_signup_from_modal(payload, user, item_name, char_name, player_pin, class_name=""):
    item_name = normalize_po_item_name(item_name)
    class_name = canonical_signup_class(class_name or selected_po_signup_class(payload, user) or "")
    source_channel_id = str(payload.get("sourceChannelId") or payload.get("channelId") or "")
    target_channel_id = str(payload.get("targetChannelId") or payload.get("discordChannelId") or source_channel_id)
    result = await asyncio.to_thread(lichtloot_post, {
        "action": "lichtbotSavePoPostEntry",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "postKey": payload.get("postKey") or payload.get("poPostKey") or "",
        "sourceChannelId": source_channel_id,
        "targetChannelId": target_channel_id,
        "raid": payload.get("raid") or "",
        "title": payload.get("title") or "PO Liste",
        "player": char_name,
        "server": "Everlook",
        "playerPin": player_pin,
        "className": class_name,
        "item": item_name,
        "discordUserId": str(getattr(user, "id", "") or ""),
        "discordName": getattr(user, "display_name", None) or getattr(user, "name", None) or str(user)
    })
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "PO-Eintrag konnte nicht gespeichert werden.")
    await post_standalone_po_list(payload)
    return result


def po_signup_item_options(payload):
    raw = payload.get("itemOptions") or payload.get("items") or payload.get("itemList") or ""
    if isinstance(raw, list):
        values = raw
    else:
        text = str(raw or "").strip()
        values = []
        if text:
            try:
                parsed = json.loads(text)
                values = parsed if isinstance(parsed, list) else []
            except Exception:
                values = re.split(r"[\n;,]+", text)

    result = []
    seen = set()
    for value in values:
        if isinstance(value, dict):
            label = str(value.get("label") or value.get("name") or value.get("item") or "").strip()
            description = str(value.get("description") or value.get("note") or "").strip()
        else:
            label = str(value or "").strip()
            description = ""
        label = normalize_po_item_name(label)
        key = p0_item_search_key(label)
        if not label or not key or key in seen:
            continue
        seen.add(key)
        result.append({"label": label[:100], "description": description[:100]})
        if len(result) >= 25:
            break
    return result


def po_luck_entry_options(entries):
    result = []
    seen = set()
    for idx, entry in enumerate(entries or []):
        player = str(entry.get("player") or "").strip()
        item = str(entry.get("item") or "").strip()
        if not player or not item:
            continue
        key = f"{prio_key(player)}|{prio_key(item)}"
        if key in seen:
            continue
        seen.add(key)
        label = f"{player} · {item}"
        result.append((str(idx), label[:100], player, item))
        if len(result) >= 25:
            break
    return result


def po_review_entry_options(entries):
    result = []
    seen = set()
    for idx, entry in enumerate(entries or []):
        status = str(entry.get("approvalStatus") or "").strip().lower()
        if status == "approved":
            continue
        player = str(entry.get("player") or "").strip()
        item = str(entry.get("item") or "").strip()
        if not player or not item:
            continue
        key = f"{prio_key(player)}|{prio_key(item)}"
        if key in seen:
            continue
        seen.add(key)
        label = f"{player} · {item}"
        result.append((str(idx), label[:100], player, item))
        if len(result) >= 25:
            break
    return result


async def po_signup_reviewer_allowed(payload, user):
    try:
        result = await asyncio.to_thread(lichtloot_get, {
            "action": "lichtbotCanReviewPoPost",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "discordUserId": str(getattr(user, "id", "") or ""),
            "discordName": getattr(user, "display_name", None) or getattr(user, "name", None) or str(user)
        })
        return bool(result.get("allowed"))
    except Exception as e:
        print(f"PO-Freigabe-Rollenpruefung fehlgeschlagen: {e}")
        return False


async def set_po_signup_luck(payload, entry, user):
    source_channel_id = str(payload.get("sourceChannelId") or payload.get("channelId") or "")
    target_channel_id = str(payload.get("targetChannelId") or payload.get("discordChannelId") or source_channel_id)
    result = await asyncio.to_thread(lichtloot_post, {
        "action": "lichtbotSetPoPostLuck",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "postKey": payload.get("postKey") or payload.get("poPostKey") or "",
        "sourceChannelId": source_channel_id,
        "targetChannelId": target_channel_id,
        "player": entry.get("player") or "",
        "item": entry.get("item") or "",
        "luckBy": getattr(user, "display_name", None) or getattr(user, "name", None) or str(user),
        "luckByDiscordId": str(getattr(user, "id", "") or "")
    })
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Kleeblatt konnte nicht gesetzt werden.")
    await post_standalone_po_list(payload)
    return result


async def review_po_signup_entry(payload, entry, user):
    source_channel_id = str(payload.get("sourceChannelId") or payload.get("channelId") or "")
    target_channel_id = str(payload.get("targetChannelId") or payload.get("discordChannelId") or source_channel_id)
    result = await asyncio.to_thread(lichtloot_post, {
        "action": "reviewPoPostEntry",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "postKey": payload.get("postKey") or payload.get("poPostKey") or "",
        "sourceChannelId": source_channel_id,
        "targetChannelId": target_channel_id,
        "messageId": entry.get("messageId") or entry.get("discordMessageId") or "",
        "status": "approved",
        "reviewer": getattr(user, "display_name", None) or getattr(user, "name", None) or str(user),
        "mode": payload.get("mode") or payload.get("poMode") or "signup",
        "note": payload.get("note") or payload.get("message") or payload.get("raidleadMessage") or "",
        "itemOptions": payload.get("itemOptions") or payload.get("items") or payload.get("itemList") or ""
    })
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "PO-Eintrag konnte nicht freigegeben werden.")
    await post_standalone_po_list(payload)
    return result


class PoSignupModal(discord.ui.Modal):
    def __init__(self, payload, default_char="", default_item="", default_class=""):
        self.payload = payload
        raid = display_raid_name(payload.get("raid") or "")
        super().__init__(title=f"PO eintragen {raid}"[:45])
        self.class_name = discord.ui.TextInput(
            label="Klasse",
            placeholder="z. B. Warrior",
            default=canonical_signup_class(default_class or "") if default_class else "",
            required=True,
            max_length=30
        )
        self.item_name = discord.ui.TextInput(
            label="Itemname",
            placeholder="z. B. THC",
            default=str(default_item or "")[:100],
            required=True,
            max_length=120
        )
        self.char_name = discord.ui.TextInput(
            label="Charaktername",
            placeholder="z. B. Glover",
            default=str(default_char or "")[:50],
            required=True,
            max_length=50
        )
        self.player_pin = discord.ui.TextInput(
            label="LichtLoot Spielerlogin",
            placeholder="dein LichtLoot Spielerlogin",
            required=True,
            max_length=20
        )
        self.add_item(self.class_name)
        self.add_item(self.item_name)
        self.add_item(self.char_name)
        self.add_item(self.player_pin)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            result = await save_po_signup_from_modal(
                self.payload,
                interaction.user,
                str(self.item_name.value or ""),
                str(self.char_name.value or ""),
                str(self.player_pin.value or ""),
                str(self.class_name.value or "")
            )
            entry = result.get("entry") or {}
            await interaction.followup.send(
                f"✅ PO gespeichert: **{entry.get('player') or self.char_name.value}** → **{entry.get('item') or self.item_name.value}**",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"⚠️ PO konnte nicht gespeichert werden: `{e}`", ephemeral=True)


class PoSignupButton(discord.ui.Button):
    def __init__(self, payload, default_item=""):
        raid = display_raid_name(payload.get("raid") or "")
        post_key = str(payload.get("postKey") or payload.get("poPostKey") or "default").strip()[:70]
        super().__init__(
            label=f"Eigenes Item eintragen {raid}"[:80],
            style=discord.ButtonStyle.primary,
            custom_id=f"po_signup:{post_key or 'default'}"
        )
        self.payload = payload
        self.default_item = default_item

    async def callback(self, interaction):
        default_char = infer_worldbuff_char_from_discord_name(interaction.user.display_name)
        default_class = selected_po_signup_class(self.payload, interaction.user)
        await interaction.response.send_modal(PoSignupModal(self.payload, default_char, self.default_item, default_class))


class PoSignupClassSelect(discord.ui.Select):
    def __init__(self, payload):
        self.payload = payload
        super().__init__(
            placeholder="Klasse wählen",
            min_values=1,
            max_values=1,
            options=raid_signup_class_options(),
            custom_id=f"po_class_select:{str(payload.get('postKey') or payload.get('poPostKey') or 'default').strip()[:60] or 'default'}"
        )

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        class_name = canonical_signup_class(self.values[0])
        PO_SIGNUP_CLASS_SELECTIONS[po_signup_selection_key(self.payload, getattr(interaction.user, "id", ""))] = class_name
        await interaction.followup.send(
            f"{signup_class_icon(class_name)} Klasse gespeichert: **{class_name}**. Jetzt Item auswählen oder eigenes Item eintragen.",
            ephemeral=True
        )


class PoSignupItemSelect(discord.ui.Select):
    def __init__(self, payload):
        self.payload = payload
        options = []
        for item in po_signup_item_options(payload):
            options.append(discord.SelectOption(
                label=item["label"],
                value=item["label"],
                description=item["description"] or None
            ))
        super().__init__(
            placeholder="Item auswählen und PO eintragen",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"po_item_select:{str(payload.get('postKey') or payload.get('poPostKey') or 'default').strip()[:60] or 'default'}"
        )

    async def callback(self, interaction):
        default_char = infer_worldbuff_char_from_discord_name(interaction.user.display_name)
        default_class = selected_po_signup_class(self.payload, interaction.user)
        await interaction.response.send_modal(PoSignupModal(self.payload, default_char, self.values[0], default_class))


class PoSignupLuckSelect(discord.ui.Select):
    def __init__(self, payload, entries):
        self.payload = payload
        self.entries = list(entries or [])
        options = []
        for value, label, _player, _item in po_luck_entry_options(self.entries):
            options.append(discord.SelectOption(
                label=label,
                value=value,
                emoji="🍀"
            ))
        super().__init__(
            placeholder="Spieler Glück wünschen",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"po_luck_select:{str(payload.get('postKey') or payload.get('poPostKey') or 'default').strip()[:60] or 'default'}"
        )

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            idx = int(self.values[0])
            entry = self.entries[idx]
            result = await set_po_signup_luck(self.payload, entry, interaction.user)
            saved = result.get("entry") or entry
            await interaction.followup.send(
                f"🍀 Glück gewünscht für **{saved.get('player') or entry.get('player')}** bei **{saved.get('item') or entry.get('item')}**.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"⚠️ Kleeblatt konnte nicht gesetzt werden: `{e}`", ephemeral=True)


class PoSignupReviewSelect(discord.ui.Select):
    def __init__(self, payload, entries):
        self.payload = payload
        self.entries = list(entries or [])
        options = []
        for value, label, _player, _item in po_review_entry_options(self.entries):
            options.append(discord.SelectOption(
                label=label,
                value=value,
                emoji="✅"
            ))
        super().__init__(
            placeholder="Item freigeben",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"po_review_select:{str(payload.get('postKey') or payload.get('poPostKey') or 'default').strip()[:58] or 'default'}"
        )

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            if not await po_signup_reviewer_allowed(self.payload, interaction.user):
                await interaction.followup.send("⚠️ Nur Gildenleitung, Raidoffiziere oder Gildenoffiziere können PO-Einträge freigeben.", ephemeral=True)
                return
            idx = int(self.values[0])
            entry = self.entries[idx]
            result = await review_po_signup_entry(self.payload, entry, interaction.user)
            saved = result.get("entry") or entry
            await interaction.followup.send(
                f"✅ Freigegeben: **{saved.get('player') or entry.get('player')}** → **{saved.get('item') or entry.get('item')}**.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"⚠️ Freigabe konnte nicht gespeichert werden: `{e}`", ephemeral=True)


class PoSignupView(discord.ui.View):
    def __init__(self, payload, entries=None):
        super().__init__(timeout=None)
        source_channel_id = str(payload.get("sourceChannelId") or payload.get("channelId") or "").strip()
        post_key = str(payload.get("postKey") or payload.get("poPostKey") or "").strip()
        self.add_item(PoSignupClassSelect(payload))
        if po_signup_item_options(payload):
            self.add_item(PoSignupItemSelect(payload))
        self.add_item(PoSignupButton(payload))
        if po_review_entry_options(entries or []):
            self.add_item(PoSignupReviewSelect(payload, entries or []))
        if po_luck_entry_options(entries or []):
            self.add_item(PoSignupLuckSelect(payload, entries or []))
        if source_channel_id:
            self.add_item(PoDeleteButton(source_channel_id, default_post_key=post_key, payload=payload, entries=entries or []))


async def find_discord_member_or_user(identifier):
    raw = str(identifier or "").strip()
    if not raw:
        return None
    id_match = re.search(r"\d{15,25}", raw)
    if id_match:
        user_id = int(id_match.group(0))
        user = client.get_user(user_id)
        if user:
            return user
        try:
            return await client.fetch_user(user_id)
        except Exception:
            pass

    wanted = raw.casefold().lstrip("@").strip()
    wanted_key = normalize_p0_reviewer_name(wanted)
    for guild in client.guilds:
        for member in getattr(guild, "members", []) or []:
            candidates = [
                str(getattr(member, "display_name", "") or ""),
                str(getattr(member, "global_name", "") or ""),
                str(getattr(member, "nick", "") or ""),
                str(getattr(member, "name", "") or ""),
                str(member)
            ]
            candidate_keys = {normalize_p0_reviewer_name(candidate) for candidate in candidates}
            if wanted_key in candidate_keys:
                return member
        partial_matches = []
        for member in getattr(guild, "members", []) or []:
            if getattr(member, "bot", False):
                continue
            candidates = [
                str(getattr(member, "display_name", "") or ""),
                str(getattr(member, "global_name", "") or ""),
                str(getattr(member, "nick", "") or ""),
                str(getattr(member, "name", "") or "")
            ]
            if any(wanted_key and wanted_key in normalize_p0_reviewer_name(candidate) for candidate in candidates):
                partial_matches.append(member)
        if len(partial_matches) == 1:
            return partial_matches[0]
        try:
            queried = await guild.query_members(query=raw, limit=10)
        except Exception:
            queried = []
        exact_queried = []
        for member in queried:
            if getattr(member, "bot", False):
                continue
            candidates = [
                str(getattr(member, "display_name", "") or ""),
                str(getattr(member, "global_name", "") or ""),
                str(getattr(member, "nick", "") or ""),
                str(getattr(member, "name", "") or ""),
                str(member)
            ]
            candidate_keys = {normalize_p0_reviewer_name(candidate) for candidate in candidates}
            if wanted_key in candidate_keys:
                exact_queried.append(member)
        if exact_queried:
            return exact_queried[0]
        if len(queried) == 1 and not getattr(queried[0], "bot", False):
            return queried[0]
    return None


async def send_po_review_dm(payload, entries):
    recipient = str(payload.get("reviewRecipient") or "").strip()
    if not recipient:
        return ""
    target = await find_discord_member_or_user(recipient)
    if not target:
        raise RuntimeError(f"Freigabe-Empfänger nicht gefunden: {recipient}")
    source_channel_id = str(payload.get("sourceChannelId") or "").strip()
    target_channel_id = str(payload.get("targetChannelId") or payload.get("discordChannelId") or "").strip()
    title = str(payload.get("title") or "PO Liste").strip() or "PO Liste"
    await target.send(
        "🔎 **PO-Freigabe**\n"
        f"Liste: **{title}**\n"
        f"Quelle: <#{source_channel_id}>\n"
        f"PO-Post: <#{target_channel_id}>\n"
        f"Einträge: **{len(entries or [])}**"
    )
    return getattr(target, "display_name", None) or getattr(target, "name", None) or str(target)


async def post_standalone_po_list(payload):
    source_channel_id = int(str(payload.get("sourceChannelId") or payload.get("channelId") or "0").strip() or "0")
    target_channel_id = int(str(payload.get("targetChannelId") or payload.get("discordChannelId") or source_channel_id or "0").strip() or "0")
    if not source_channel_id or not target_channel_id:
        raise RuntimeError("PO Post: Quelle oder Ziel-Channel fehlt.")

    limit = max(50, min(2000, int(payload.get("limit") or 800)))
    cleanup_source = str(payload.get("cleanupSource") or payload.get("cleanup") or "").strip().lower() in {"1", "true", "yes", "ja"}
    _, fresh_entries, source_messages = await get_po_entries_from_channel(source_channel_id, limit=limit)
    saved_entries = await load_saved_po_post_entries(payload, source_channel_id, target_channel_id)
    entries = merge_po_entries(saved_entries, fresh_entries)
    entries = await resolve_po_post_players(entries)
    entries = apply_po_post_approvals(entries, await load_po_post_approvals({
        **payload,
        "sourceChannelId": str(source_channel_id),
        "targetChannelId": str(target_channel_id)
    }), payload.get("raid") or "")
    points_by_item = await load_po_item_points(payload.get("raid") or "")
    entries = annotate_po_entries_with_points(entries, points_by_item)
    payload = {**payload, "_poPointsByItem": points_by_item}
    target_channel = client.get_channel(target_channel_id) or await client.fetch_channel(target_channel_id)
    text = build_po_signup_entries_text(entries, payload) if is_po_signup_payload(payload) else build_standalone_po_entries_text(entries)
    msg, changed = await upsert_standalone_po_post(target_channel, payload, entries, text)
    try:
        await asyncio.to_thread(lichtloot_post, {
            "action": "lichtbotSavePoPostEntries",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "postKey": payload.get("postKey") or payload.get("poPostKey") or "",
            "sourceChannelId": str(source_channel_id),
            "targetChannelId": str(target_channel_id),
            "raid": payload.get("raid") or "",
            "title": payload.get("title") or "PO Liste",
            "messageId": str(getattr(msg, "id", "") or ""),
            "entries": json.dumps(entries or [], ensure_ascii=False)
        })
    except Exception as e:
        print(f"PO-Post-Eintraege konnten nicht an LichtLoot gespeichert werden: {e}")

    deleted_source_messages = 0
    if cleanup_source:
        fresh_message_ids = {str(entry.get("messageId") or "").strip() for entry in fresh_entries or []}
        for message_id in sorted(fresh_message_ids):
            msg_to_delete = source_messages.get(message_id)
            if not msg_to_delete:
                continue
            if not is_plain_po_source_message(msg_to_delete):
                print(f"PO-Quellnachricht {message_id} wird nicht geloescht: keine einfache PO-Spielernachricht.")
                continue
            try:
                await msg_to_delete.delete()
                deleted_source_messages += 1
                await asyncio.sleep(0.25)
            except discord.Forbidden:
                print(f"PO-Quellnachricht {message_id} konnte nicht geloescht werden: Bot-Rechte fehlen.")
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"PO-Quellnachricht {message_id} konnte nicht geloescht werden: {e}")

    review_target = await send_po_review_dm(payload, entries) if changed else ""

    return {
        "entries": len(entries),
        "newEntries": len(fresh_entries or []),
        "deletedSourceMessages": deleted_source_messages,
        "targetChannelId": str(target_channel_id),
        "messageId": str(getattr(msg, "id", "") or ""),
        "changed": changed,
        "reviewTarget": review_target
    }


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
        await send_silent(channel, build_prio_check_text(result, report_title))

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
                    await send_silent(channel, f"⚠️ Der {raid} Prio-Check konnte nicht erstellt werden. Bitte Bot-Konsole prüfen.")
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
                    embed = build_raid_announcement_embed(raid)
                    banner = raid_banner_file(raid)
                    if banner:
                        await send_silent(channel, embed=embed, file=banner, view=RaidSignupView(raid))
                    else:
                        await send_silent(channel, embed=embed, view=RaidSignupView(raid))
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


async def post_raid_announcement_by_id(raid_id, channel_id=None):
    raid_id = str(raid_id or "").strip()
    if not raid_id:
        raise RuntimeError("Raid-Ankuendigung manuell: Raid-ID fehlt.")

    helper = None
    raid = None

    try:
        helper = await asyncio.to_thread(lichtloot_get, {
            "action": "getRaidHelper",
            "raidId": raid_id,
            "playerPin": raid_id,
            "t": int(time.time())
        })
        if helper and helper.get("success"):
            raid = helper.get("raid")
    except Exception as e:
        print("Raid-Ankuendigung manuell: direkter Raid-Lookup fehlgeschlagen:", e)

    if not raid:
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
        print(f"Raid-Ankuendigung manuell: Raid {raid_id} nicht gefunden, Queue-Eintrag ist veraltet.")
        return "stale"

    raid_name = normalize_raid_name(raid.get("raid") or raid.get("raidName") or "")
    channel_id = (
        str(channel_id or "").strip()
        or str(raid.get("discordChannelId") or raid.get("discord_channel_id") or "").strip()
        or DEFAULT_RAID_HELPER_CHANNEL_ID
        or str(get_primary_raid_channel_id(raid_name) or "").strip()
    )
    if not channel_id:
        raise RuntimeError(f"Raid-Ankuendigung manuell: Kein Channel fuer {raid_name} hinterlegt.")

    try:
        channel_numeric_id = int(channel_id)
    except Exception:
        raise RuntimeError(f"Raid-Ankuendigung manuell: Ungueltige Channel-ID {channel_id}.")

    channel = client.get_channel(channel_numeric_id)
    if channel is None:
        channel = await client.fetch_channel(channel_numeric_id)
    if channel is None:
        raise RuntimeError(f"Raid-Ankuendigung manuell: Channel {channel_id} nicht gefunden.")

    embed = build_raid_announcement_embed(raid)
    try:
        if not helper:
            helper = await asyncio.to_thread(lichtloot_get, {
                "action": "getRaidHelper",
                "raidId": str(raid.get("raidId") or raid.get("id") or ""),
                "playerPin": str(raid.get("playerPin") or ""),
                "t": int(time.time())
            })
        add_raid_signup_roster_fields(embed, helper)
    except Exception as e:
        print("Raid-Anmelder-Daten konnten beim Posten nicht geladen werden:", e)
        embed.add_field(name="Anmeldungen", value="Noch keine Anmeldungen.", inline=False)

    sent_message = None
    try:
        banner = raid_banner_file(raid)
        if banner:
            sent_message = await send_silent(channel, embed=embed, file=banner, view=RaidSignupView(raid))
        else:
            sent_message = await send_silent(channel, embed=embed, view=RaidSignupView(raid))
    except discord.HTTPException as e:
        print(f"Raid-Ankuendigung mit Auswahlfeld fehlgeschlagen, versuche Embed ohne Auswahlfeld: {e}")
        try:
            banner = raid_banner_file(raid)
            if banner:
                sent_message = await send_silent(channel, embed=embed, file=banner)
            else:
                sent_message = await send_silent(channel, embed=embed)
        except discord.HTTPException as embed_error:
            print(f"Raid-Ankuendigung als Embed fehlgeschlagen, versuche Klartext: {embed_error}")
            sent_message = await send_silent(channel, build_raid_announcement_text(raid))
    if sent_message:
        try:
            await asyncio.to_thread(lichtloot_post, {
                "action": "lichtbotSetRaidDiscordMessage",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                "raidId": str(raid.get("raidId") or raid.get("id") or raid_id),
                "discordChannelId": str(channel_id),
                "discordMessageId": str(sent_message.id)
            })
        except Exception as e:
            print("Raid-Anmelder-Message-ID konnte nicht gespeichert werden:", e)
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

    message_text = discord_message_search_text(message)
    new_buffs = [buff for buff in parse_ticker_message(message_text) if not is_deleted_worldbuff(buff)]

    if not new_buffs:
        return

    old_data = load_json(worldbuff_file(), [])

    added = merge_buffs_into_data(old_data, new_buffs)

    save_json(worldbuff_file(), old_data)
    await asyncio.to_thread(sync_worldbuff_ticker_cache_to_sheet, old_data)

    print(f"{len(new_buffs)} Worldbuffs aus Ticker übernommen oder geprüft, {added} neu gespeichert.")

    await update_worldbuff_overview_from_all_guilds()

    if any(normalize_buff(b["buff"]) == "Rend" for b in new_buffs):
        await update_hordenbuff_post(force=True)

    if not is_own_discord_message(message) and not is_worldbuff_poster_source_message(message):
        try:
            await message.delete()
            print(f"Worldbuff-Poster-Nachricht {message.id} aus Channel {message.channel.id} gelöscht.")
        except discord.Forbidden:
            print(f"Worldbuff-Poster-Nachricht {message.id} konnte nicht gelöscht werden: Bot-Rechte fehlen.")
        except discord.NotFound:
            pass
        except Exception as e:
            print(f"Worldbuff-Poster-Nachricht {message.id} konnte nicht gelöscht werden: {e}")


@client.event
async def on_ready():
    print(f"Bot online als {client.user}")
    print(f"Überwache Ticker-Channels: {sorted(TICKER_CHANNEL_IDS)}")
    print(f"Postet Übersicht in Channel: {POST_CHANNEL_ID}")
    print(f"Hordenbuff-Channels: {sorted(HORDENBUFF_CHANNEL_IDS)}")
    print(f"Loganalyse-Channels: {sorted(LOG_ANALYSIS_CHANNEL_IDS)}")
    found_class_emojis, found_spec_emojis, found_item_emojis = refresh_class_emoji_cache()
    print(f"Raid-Anmelder Klassenemojis gefunden: {', '.join(sorted(found_class_emojis.keys())) or 'keine'}")
    print(f"Raid-Anmelder Skillungsemojis gefunden: {', '.join(sorted(found_spec_emojis.keys())) or 'keine'}")
    print(f"PO-Item Emojis gefunden: {len(found_item_emojis)}")
    print("Version 4.9.3 gestartet: Raid-Ankuendigung Hotfix signup_deadline + stale Queue aktiv.")
    schedule_p0_release_cache_refresh(force=True)

    if not hasattr(client, "raid_signup_view_restore_started"):
        client.raid_signup_view_restore_started = True
        client.loop.create_task(restore_active_raid_signup_views())

    if not hasattr(client, "hordenbuff_task_started"):
        client.hordenbuff_task_started = True
        client.loop.create_task(hordenbuff_reminder_loop())

    if not hasattr(client, "lichtloot_queue_task_started"):
        client.lichtloot_queue_task_started = True
        client.loop.create_task(lichtloot_queue_loop())

    if not hasattr(client, "discord_channel_sync_started"):
        client.discord_channel_sync_started = True
        client.loop.create_task(discord_channel_sync_loop())

    if not hasattr(client, "worldbuff_startup_task_started"):
        client.worldbuff_startup_task_started = True
        client.loop.create_task(update_worldbuff_overview_from_all_guilds())

    if not hasattr(client, "p0_duplicate_cleanup_started"):
        client.p0_duplicate_cleanup_started = True
        client.loop.create_task(cleanup_p0_overview_duplicates_for_known_channels())

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

    token = CURRENT_GUILD_SLUG.set(guild_slug_for_channel(after.channel.id))
    try:
        #for raid in get_raid_names_for_channel(after.channel.id):
        #  schedule_prio_check_update(raid, f"Nachricht im {raid}-Channel bearbeitet")

        await handle_log_analysis_message(after)
        await handle_ticker_update(after)
        if is_plain_po_source_message(after):
            await asyncio.sleep(1)
            refreshed = await refresh_saved_po_posts_for_source(after.channel.id, cleanup_source=True)
            if refreshed:
                print(f"PO-Post nach Bearbeitung automatisch aktualisiert: {refreshed}")
    finally:
        CURRENT_GUILD_SLUG.reset(token)


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    CURRENT_GUILD_SLUG.set(guild_slug_for_channel(message.channel.id))

    await handle_log_analysis_message(message)

    content = message.content.strip()
    lower = content.lower()

    if is_plain_po_source_message(message):
        await asyncio.sleep(1)
        refreshed = await refresh_saved_po_posts_for_source(message.channel.id, cleanup_source=True)
        if refreshed:
            print(f"PO-Post nach neuer PO-Nachricht automatisch aktualisiert: {refreshed}")

    if lower.startswith("!syncchannels") or lower.startswith("!channel-sync"):
        try:
            result = await sync_accessible_discord_channels()
            saved = int(result.get("saved", 0) or 0)
            await message.channel.send(f"✅ Discord-Channel neu synchronisiert: **{saved}** Channel gespeichert.", delete_after=30)
        except Exception as e:
            await message.channel.send(f"⚠️ Channel-Sync fehlgeschlagen: `{e}`", delete_after=30)
        return

    if lower.startswith("!popost") or lower.startswith("!po-post") or lower.startswith("!poliste"):
        parts = content.split()
        post_key = parts[1].strip() if len(parts) > 1 else ""
        try:
            result_message = await message.channel.send("🔄 **PO-Post wird aktualisiert und Quellnachrichten werden aufgeräumt...**")
            refreshed = await refresh_saved_po_posts_for_source(
                message.channel.id,
                cleanup_source=True,
                post_key_filter=post_key
            )
            if not refreshed:
                detail = f" mit Post-ID `{post_key}`" if post_key else ""
                await result_message.edit(content=f"⚠️ Kein gespeicherter PO-Post für diesen Channel{detail} gefunden.")
                client.loop.create_task(delete_message_later(result_message, 25))
                await delete_command_message(message)
                return
            total_entries = sum(int(item.get("entries") or 0) for item in refreshed)
            new_entries = sum(int(item.get("newEntries") or 0) for item in refreshed)
            deleted = sum(int(item.get("deletedSourceMessages") or 0) for item in refreshed)
            await result_message.edit(
                content=(
                    "✅ **PO-Post aktualisiert.**\n"
                    f"Posts: **{len(refreshed)}** | Einträge: **{total_entries}** | "
                    f"neu aus Channel: **{new_entries}** | gelöscht: **{deleted}**"
                )
            )
            client.loop.create_task(delete_message_later(result_message, 25))
            await delete_command_message(message)
        except Exception as e:
            err = str(e)
            if len(err) > 1500:
                err = err[:1500] + " …"
            await message.channel.send(f"⚠️ **PO-Post Fehler:**\n```{err}```", delete_after=45)
        return

    if lower.startswith("!po ") or lower.startswith("!p0 "):
        parts = content.split()
        raid = normalize_raid_name(parts[1] if len(parts) > 1 else "")
        if raid not in {"AQ40", "NAXX", "BWL", "MC"}:
            await message.channel.send("⚠️ Bitte Raid angeben: `!p0 aq40`, `!p0 naxx`, `!p0 bwl` oder `!p0 mc`.", delete_after=25)
            await delete_command_message(message)
            return
        post_key = parts[2].strip() if len(parts) > 2 else ""
        payload = await find_po_post_payload_for_signup(message.channel.id, raid, post_key)
        if not payload:
            detail = f" und Post-ID `{post_key}`" if post_key else ""
            await message.channel.send(f"⚠️ Kein gespeicherter PO-Post für **{raid}** in diesem Channel{detail} gefunden.", delete_after=30)
            await delete_command_message(message)
            return
        await message.channel.send(
            f"🧾 **{display_raid_name(raid)} PO eintragen**",
            view=PoSignupView(payload),
            delete_after=180
        )
        await delete_command_message(message)
        return

    if lower.startswith("!podel") or lower.startswith("!podelete") or lower.startswith("!poloeschen") or lower.startswith("!polöschen"):
        parts = content.split()
        default_post_key = ""
        default_item = ""
        default_player = infer_worldbuff_char_from_discord_name(message.author.display_name)
        if len(parts) > 1:
            rest = parts[1:]
            if rest and rest[0].lower().startswith("po-liste-"):
                default_post_key = rest[0]
                rest = rest[1:]
            if len(rest) >= 2:
                default_player = rest[0]
                default_item = " ".join(rest[1:]).strip()
            else:
                default_item = " ".join(rest).strip()
        await message.channel.send(
            "🧾 **Eigenen PO-Eintrag löschen**",
            view=PoDeleteView(message.channel.id, default_item, default_post_key, default_player),
            delete_after=180
        )
        await delete_command_message(message)
        return

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
                signups = extract_signup_entries_from_text(text_msg)

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
                signups = extract_signup_entries_from_text(text_msg)

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
                signups = extract_signup_entries_from_text(text_msg)

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
                signups = extract_signup_entries_from_text(text)
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
        status_message = await message.channel.send("🔄 **Worldbuffs und Hordenbuffs werden aktualisiert...**")
        try:
            worldbuff_count = await asyncio.wait_for(update_worldbuff_post(sync_ticker=True), timeout=60)
            hordenbuff_count = await asyncio.wait_for(update_hordenbuff_post(force=True), timeout=45)
            await status_message.edit(
                content=(
                    "✅ **Buff-Posts aktualisiert.**\n"
                    f"Worldbuff-Post: **{worldbuff_count or 0}** | "
                    f"Hordenbuff-Post: **{hordenbuff_count or 0}**"
                )
            )
            client.loop.create_task(delete_message_later(status_message, 25))
        except asyncio.TimeoutError:
            await status_message.edit(content="⏱️ **Buff-Update dauert zu lange.** Bitte in Railway prüfen, der Bot hängt beim Laden der Buff-Daten.")
        except Exception as e:
            err = str(e)
            if len(err) > 1200:
                err = err[:1200] + " …"
            await status_message.edit(content=f"⚠️ **Buff-Update Fehler:**\n```{err}```")
        await delete_command_message(message)
        return

    if lower in ["!p0", "!p0+", "!po", "!po+"] or lower.startswith(("!p0 ", "!p0+ ", "!po ", "!po+ ")):
        parts = content.split()
        if len(parts) > 1:
            raid = normalize_raid_name(parts[1])
        else:
            channel_raids = p0_supported_raids_for_channel(message.channel.id)
            raid = channel_raids[0] if channel_raids else ""

        if raid not in {"MC", "BWL", "AQ40", "NAXX"}:
            await send_temp(
                message.channel,
                "Bitte nutze `!p0` im MC/BWL/AQ40/Naxx-Raidchannel oder gib den Raid an: `!p0 mc`, `!p0 bwl`, `!p0 aq40`, `!p0 naxx`."
            )
            await delete_command_message(message)
            return

        await open_p0_signup_flow(message, raid)
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
        status_message = await message.channel.send("🔄 **Hordenbuff-Post wird aktualisiert...**")
        try:
            hordenbuff_count = await asyncio.wait_for(update_hordenbuff_post(force=True), timeout=45)
            if hordenbuff_count:
                await status_message.edit(content=f"✅ **Hordenbuff-Post aktualisiert.** Posts: **{hordenbuff_count}**")
            else:
                await status_message.edit(content="⚠️ **Hordenbuff wurde nicht aktualisiert.** Kein Zielpost oder kein kommender Rend-Termin gefunden.")
            client.loop.create_task(delete_message_later(status_message, 25))
        except asyncio.TimeoutError:
            await status_message.edit(content="⏱️ **Hordenbuff-Update dauert zu lange.** Bitte Railway-Logs prüfen.")
        except Exception as e:
            err = str(e)
            if len(err) > 1200:
                err = err[:1200] + " …"
            await status_message.edit(content=f"⚠️ **Hordenbuff-Update Fehler:**\n```{err}```")
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


async def run_discord_bot_with_backoff():
    login_backoff_seconds = 30 * 60
    while True:
        try:
            await client.start(TOKEN, reconnect=True)
            login_backoff_seconds = 30 * 60
        except discord.HTTPException as error:
            text = str(error)
            if getattr(error, "status", None) == 429 or "Too Many Requests" in text or "Access denied" in text:
                wait_seconds = max(login_backoff_seconds, 65 * 60)
                print(f"Discord blockt den Login wegen zu vieler Neustarts. Warte {int(wait_seconds / 60)} Minuten und versuche es erneut.")
                await close_discord_client_after_failed_start()
                await asyncio.sleep(wait_seconds)
                login_backoff_seconds = min(wait_seconds * 2, 4 * 60 * 60)
                continue
            print(f"Discord-Login fehlgeschlagen: {error}. Neuer Versuch in 5 Minuten.")
            await close_discord_client_after_failed_start()
            await asyncio.sleep(5 * 60)
        except Exception as error:
            print(f"Bot ist beim Starten abgestürzt: {error}. Neuer Versuch in 5 Minuten.")
            await close_discord_client_after_failed_start()
            await asyncio.sleep(5 * 60)


async def close_discord_client_after_failed_start():
    try:
        if not client.is_closed():
            await client.close()
    except Exception as close_error:
        print(f"Discord-Client konnte nach Fehlstart nicht sauber geschlossen werden: {close_error}")
    try:
        client.clear()
    except Exception:
        pass


start_public_api_server()
asyncio.run(run_discord_bot_with_backoff())
