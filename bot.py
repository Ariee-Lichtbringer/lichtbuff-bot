import discord
from discord import app_commands
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
import zipfile
import unicodedata
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

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
LICHTBOT_QUEUE_TOKEN = os.getenv("LICHTBOT_QUEUE_TOKEN", "")

TICKER_CHANNEL_ID = 1283706980103356448
POST_CHANNEL_ID = 1281152286772695071
HORDENBUFF_CHANNEL_ID = 1510764309062615220
LOG_ANALYSIS_CHANNEL_ID = 1279032487628242995
PLAYER_LOGIN_APPROVAL_CHANNEL_ID = int(os.getenv("PLAYER_LOGIN_APPROVAL_CHANNEL_ID", "0") or 0)
WORLDBUFF_REPLACEMENT_GUILD_CHANNEL_ID = int(os.getenv("WORLDBUFF_REPLACEMENT_GUILD_CHANNEL_ID", "1118795108968574987") or 1118795108968574987)
WORLDBUFF_REPLACEMENT_WORLDBUFF_CHANNEL_ID = int(os.getenv("WORLDBUFF_REPLACEMENT_WORLDBUFF_CHANNEL_ID", str(POST_CHANNEL_ID)) or POST_CHANNEL_ID)
WORLDBUFF_REPLACEMENT_GUILD_CHANNEL_NAMES = [
    value.strip().lower()
    for value in os.getenv(
        "WORLDBUFF_REPLACEMENT_GUILD_CHANNEL_NAMES",
        "gildenintern,gilden-intern,gilden intern,intern,gildenchat,gilden-chat"
    ).split(",")
    if value.strip()
]
WORLDBUFF_POSTER_MESSAGE_IDS = {
    value.strip()
    for value in os.getenv("WORLDBUFF_POSTER_MESSAGE_IDS", "1526256966027055114").split(",")
    if value.strip()
}

TICKER_CHANNEL_IDS = {
    TICKER_CHANNEL_ID,
    POST_CHANNEL_ID
}

HORDENBUFF_CHANNEL_IDS = {
    HORDENBUFF_CHANNEL_ID
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
    "warrior": ["classicon_warrior", "krieger", "warrior"],
    "druid": ["classicon_druid", "druide", "druid"],
    "paladin": ["classicon_paladin", "pala", "paladin"],
    "rogue": ["classicon_rogue", "schurke", "rogue"],
    "hunter": ["classicon_hunter", "jäger", "jaeger", "jager", "hunter"],
    "priest": ["classicon_priest", "priester", "priest"],
    "mage": ["classicon_mage", "magier", "mage"],
    "warlock": ["classicon_warlock", "hexenmeister", "hexer", "warlock"],
    "shaman": ["classicon_shaman", "schamane", "shaman"],
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
LICHTLOOT_GUILD_SLUG = os.getenv("LICHTLOOT_GUILD_SLUG", "lichtloot")
NACHTLOOT_GUILD_SLUG = os.getenv("NACHTLOOT_GUILD_SLUG", "nachtloot")
WORLDBUFF_BACKUP_CHANNEL_ID = "1529393614247952434"
P0PLUS_BACKUP_CHANNEL_ID = "1529393614247952434"
NACHTLOOT_WORLDBUFF_BACKUP_CHANNEL_ID = "1531288515994718318"
WORLDBUFF_GUILD_SLUGS = []
GUILD_REGISTRY = {}
DISCORD_GUILD_SLUGS = {}
CHANNEL_GUILD_SLUGS = {}

# Alter CSV-Export bleibt nur noch als expliziter Notfall-Fallback.
# Die Wahrheit fuer Worldbuff-Termine ist Railway/Gildenleitung.
CSV_URL = "https://docs.google.com/spreadsheets/d/1eItzaMGhpJ28vv4sDA8wwmu0YhUxcbiz-2VLiCVyjv4/export?format=csv&gid=1498762908"
CSV_CACHE_CONTENT = ""
CSV_CACHE_TIME = None
CSV_CACHE_SECONDS = 300
ALLOW_WORLDBUFF_CSV_FALLBACK = os.getenv("ALLOW_WORLDBUFF_CSV_FALLBACK", "").strip().lower() in {"1", "true", "yes", "ja"}
WORLDBUFF_API_CACHE_ROWS = []
WORLDBUFF_API_CACHE_TIME = None
WORLDBUFF_API_CACHE_BY_GUILD = {}
WORLDBUFF_API_CACHE_TIME_BY_GUILD = {}
WORLDBUFF_API_CACHE_SECONDS = 60
WORLDBUFF_CHANNEL_CACHE = {}
WORLDBUFF_CHANNEL_CACHE_TIME = {}
WORLDBUFF_CHANNEL_CACHE_SECONDS = 120
WORLDBUFF_TICKER_LAST_POST_SCAN_LIMIT = int(
    os.getenv("WORLDBUFF_TICKER_LAST_POST_SCAN_LIMIT", "25") or 25
)
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
WB_POSTER_CACHE_FILE = "wb_poster_worldbuffs.json"
DELETED_WORLDBUFF_FILE = "deleted_worldbuffs.json"
POST_FILE = "last_post.json"
HORDENBUFF_FILE = "hordenbuff.json"
HORDENBUFF_CLEANUP_FILE = "hordenbuff_cleanup.json"
LICHTLOOT_QUEUE_IN_PROGRESS = set()
LICHTLOOT_QUEUE_RECENTLY_DONE = {}
HORDENBUFF_CLEANUP_DELAY_MINUTES = 5
HORDENBUFF_CLEANUP_WINDOW_MINUTES = 45
HORDENBUFF_UPDATE_MIN_SECONDS = 30
DISCORD_RATE_LIMIT_FALLBACK_SECONDS = 300
LICHTLOOT_QUEUE_CHECK_SECONDS = 30
LICHTLOOT_URL = "https://lichtloot.de"
PUBLIC_API_CACHE_SECONDS = int(os.getenv("PUBLIC_API_CACHE_SECONDS", "45"))
PUBLIC_API_PORT = int(os.getenv("PORT") or os.getenv("PUBLIC_API_PORT", "8000"))
DELETE_WORLDBUFF_POSTER_SOURCE_MESSAGES = False
WORLDBUFF_TICKER_SYNC_LOCK = asyncio.Lock()
WORLDBUFF_DATABASE_SYNC_LOCK = threading.Lock()

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

# Eigene Discord-Emojis der jeweiligen Gilde. Discord liefert beim Start die
# fuer den Bot sichtbaren Server-Emojis; falls eines fehlt, verwenden wir
# weiterhin den bisherigen farbigen Punkt als sicheren Ersatz.
BUFF_CUSTOM_EMOJI_NAMES = {
    "Hakkar": "zgbuff",
    "ZG": "zgbuff",
    "Ony": "onybuff",
    "Onyxia": "onybuff",
    "Nef": "neffbuff",
    "Nefarian": "neffbuff",
    "Rend": "rendbuff",
}


def get_buff_emoji(buff):
    normalized = normalize_buff(buff)
    emoji_name = BUFF_CUSTOM_EMOJI_NAMES.get(normalized)
    if emoji_name:
        for discord_guild in getattr(client, "guilds", []):
            emoji = discord.utils.get(getattr(discord_guild, "emojis", []), name=emoji_name)
            if emoji is not None:
                return emoji
    return BUFF_EMOJIS.get(normalized, BUFF_EMOJIS.get(str(buff or ""), "⚪"))

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
# Für die vertrauliche SpielerLogin-Freigabe muss der Bot Mitglieder der
# Discord-Rolle "Offiziere" ermitteln und ihnen direkt schreiben können.
intents.members = True

client = discord.Client(intents=intents)
command_tree = app_commands.CommandTree(client)

hordenbuff_update_lock = asyncio.Lock()
hordenbuff_last_update_at = 0
hordenbuff_rate_limited_until = 0
CURRENT_GUILD_SLUG = contextvars.ContextVar("CURRENT_GUILD_SLUG", default=LICHTLOOT_GUILD_SLUG)
class_emoji_cache = {}
spec_emoji_cache = {}
item_emoji_cache = {}


def normalize_guild_slug(value):
    slug_value = str(value or "").strip().lower()
    return slug_value or LICHTLOOT_GUILD_SLUG


def configured_worldbuff_guild_slugs():
    slugs = [normalize_guild_slug(slug) for slug in WORLDBUFF_GUILD_SLUGS if normalize_guild_slug(slug)]
    if GUILD_REGISTRY:
        slugs.extend(normalize_guild_slug(slug) for slug in GUILD_REGISTRY.keys())
    return list(dict.fromkeys(slugs))


async def refresh_guild_registry():
    global GUILD_REGISTRY, DISCORD_GUILD_SLUGS, WORLDBUFF_GUILD_SLUGS, CHANNEL_GUILD_SLUGS
    if not LICHTBOT_QUEUE_TOKEN:
        return GUILD_REGISTRY

    params = urllib.parse.urlencode({
        "action": "lichtbotListGuilds",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "t": int(time.time())
    })
    url = LICHTLOOT_API_URL + "?" + params
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            result = parse_json_api_response(response, "LichtLoot Bot-Gilden", url)
    except Exception as error:
        print("Bot-Gildenliste konnte nicht geladen werden:", error)
        return GUILD_REGISTRY

    if not result.get("success"):
        print("Bot-Gildenliste Antwort:", result)
        return GUILD_REGISTRY

    registry = {}
    discord_map = {}
    for row in result.get("guilds") or []:
        slug_value = normalize_guild_slug(row.get("slug"))
        if not slug_value:
            continue
        registry[slug_value] = row
        discord_guild_id = str(row.get("discordGuildId") or "").strip()
        if discord_guild_id:
            discord_map[discord_guild_id] = slug_value

    public_url = LICHTLOOT_API_URL + "?" + urllib.parse.urlencode({
        "action": "listGuilds",
        "t": int(time.time())
    })
    try:
        with urllib.request.urlopen(public_url, timeout=30) as response:
            public_result = parse_json_api_response(response, "LichtLoot Gildenlayout", public_url)
        for row in public_result.get("guilds") or []:
            slug_value = normalize_guild_slug(row.get("slug"))
            if slug_value in registry:
                registry[slug_value].update(row)
            elif slug_value:
                registry[slug_value] = row
    except Exception as error:
        print("Gildenlayouts konnten nicht geladen werden:", error)

    GUILD_REGISTRY = registry
    DISCORD_GUILD_SLUGS = discord_map
    WORLDBUFF_GUILD_SLUGS = configured_worldbuff_guild_slugs()
    configured_channel_slugs = {}
    for slug_value, data in GUILD_REGISTRY.items():
        layout = data.get("layout") if isinstance(data, dict) else {}
        if not isinstance(layout, dict):
            layout = {}
        for configured_key in (
            "worldbuffChannelId", "worldbuffBackupChannelId",
            "hordenbuffChannelId", "p0PlusBackupChannelId", "logSourceChannelId", "logAnalysisChannelId"
        ):
            channel_id = clean_channel_id_value(layout.get(configured_key))
            if channel_id:
                numeric_channel_id = int(channel_id)
                configured_channel_slugs[numeric_channel_id] = slug_value
                if configured_key == "worldbuffChannelId":
                    TICKER_CHANNEL_IDS.add(numeric_channel_id)
                if configured_key == "hordenbuffChannelId":
                    HORDENBUFF_CHANNEL_IDS.add(numeric_channel_id)
                if configured_key in ("logSourceChannelId", "logAnalysisChannelId"):
                    LOG_ANALYSIS_CHANNEL_IDS.add(numeric_channel_id)
    CHANNEL_GUILD_SLUGS.update(configured_channel_slugs)
    print(
        "Bot-Gilden geladen: "
        + (", ".join(f"{slug}#{data.get('discordGuildId') or '-'}" for slug, data in GUILD_REGISTRY.items()) or "keine")
    )
    return GUILD_REGISTRY


def guild_slug_for_channel(channel_id):
    return CHANNEL_GUILD_SLUGS.get(int(channel_id), "")


def guild_slug_for_message(message):
    """Eine Gilde wird ausschließlich über die registrierte Discord-Server-ID bestimmt."""
    return guild_slug_for_discord_server(getattr(message, "guild", None), "")


def guild_slug_for_discord_guild(discord_guild_id, fallback=""):
    mapped = DISCORD_GUILD_SLUGS.get(str(discord_guild_id or "").strip())
    return normalize_guild_slug(mapped) if mapped else ""


def guild_slug_for_discord_server(guild, fallback=""):
    mapped = DISCORD_GUILD_SLUGS.get(str(getattr(guild, "id", "") or "").strip())
    if mapped:
        return normalize_guild_slug(mapped)
    return ""


async def sync_discord_roles_to_lichtloot():
    if not LICHTBOT_QUEUE_TOKEN:
        return
    for discord_guild in client.guilds:
        guild_slug = guild_slug_for_discord_server(discord_guild, "")
        if not guild_slug:
            continue
        # Der lokale Discord-Cache kann direkt nach dem Start noch leer sein.
        # Fuer die Namensauswahl in der Gildenleitung laden wir die Mitglieder
        # deshalb aktiv vom Discord-Server und verwenden den Cache nur als Fallback.
        discord_members = list(discord_guild.members)
        try:
            fetched_members = [member async for member in discord_guild.fetch_members(limit=None)]
            if fetched_members:
                discord_members = fetched_members
        except Exception as error:
            print(
                f"Discord-Mitglieder fuer {guild_slug} konnten nicht aktiv geladen werden; "
                f"verwende Cache mit {len(discord_members)} Eintraegen: {error}"
            )
        roles = [
            {
                "id": str(role.id),
                "name": str(role.name),
                "color": int(getattr(role.color, "value", 0) or 0),
                "position": int(getattr(role, "position", 0) or 0),
                "discordGuildId": str(discord_guild.id),
            }
            for role in discord_guild.roles
            if not role.is_default()
        ]
        members = [
            {
                "id": str(member.id),
                "username": str(member.name),
                "displayName": str(member.display_name or member.name),
                "globalName": str(getattr(member, "global_name", "") or ""),
                "avatarUrl": str(member.display_avatar.url) if getattr(member, "display_avatar", None) else "",
                "bot": bool(member.bot),
                "discordGuildId": str(discord_guild.id),
            }
            for member in discord_members
            if not member.bot
        ]
        token = CURRENT_GUILD_SLUG.set(guild_slug)
        try:
            await asyncio.to_thread(lichtloot_post, {
                "action": "lichtbotSaveDiscordRoles",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                "roles": roles,
            })
            print(f"Discord-Rollen fuer {guild_slug} synchronisiert: {len(roles)}")
            await asyncio.to_thread(lichtloot_post, {
                "action": "lichtbotSaveDiscordMembers",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                "members": members,
            })
            print(f"Discord-Mitglieder fuer {guild_slug} synchronisiert: {len(members)}")
        except Exception as error:
            print(f"Discord-Rollen/Mitglieder fuer {guild_slug} konnten nicht synchronisiert werden: {error}")
        finally:
            CURRENT_GUILD_SLUG.reset(token)


def current_guild_slug():
    return CURRENT_GUILD_SLUG.get()


def current_guild_layout():
    registry_entry = GUILD_REGISTRY.get(current_guild_slug()) or {}
    layout = registry_entry.get("layout") if isinstance(registry_entry, dict) else {}
    return layout if isinstance(layout, dict) else {}


def lichtbuff_self_signup_buttons_enabled(guild_slug=None):
    slug_value = normalize_guild_slug(guild_slug or current_guild_slug())
    guild = GUILD_REGISTRY.get(slug_value) or {}
    layout = guild.get("layout") if isinstance(guild, dict) else {}
    if not isinstance(layout, dict):
        layout = {}
    return layout.get("lichtbuffSelfSignupButtons") is not False


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
    guild_slug = current_guild_slug()
    configured_channel_id = clean_channel_id_value(current_guild_layout().get("hordenbuffChannelId"))
    if configured_channel_id:
        return {int(configured_channel_id)}

    registry_entry = GUILD_REGISTRY.get(guild_slug) or {}
    discord_guild_id = str(registry_entry.get("discordGuildId") or "").strip()
    discord_guild = client.get_guild(int(discord_guild_id)) if discord_guild_id.isdigit() else None
    if discord_guild:
        ranked = sorted(
            getattr(discord_guild, "text_channels", []),
            key=lambda channel: (
                hordenbuff_channel_rank(channel),
                int(getattr(channel, "position", 999999) or 999999)
            )
        )
        if ranked and hordenbuff_channel_rank(ranked[0]) < 99:
            return {int(ranked[0].id)}

    return set()


def hordenbuff_channel_rank(channel):
    name = str(getattr(channel, "name", "") or "").strip().lower()
    category = str(getattr(getattr(channel, "category", None), "name", "") or "").strip().lower()
    combined = f"{category} {name}"
    if "rend-buff" in name or "rend_buff" in name or "rendbuff" in name:
        return 0
    if "rend" in name:
        return 1
    if "hordenbuff" in name or "horde-buff" in name:
        return 2
    if "rend" in combined or "hordenbuff" in combined:
        return 3
    return 99


def ticker_channel_ids_for_current_guild():
    guild_slug = current_guild_slug()
    channel_ids = set()
    layout = current_guild_layout()
    for key in ("worldbuffChannelId",):
        configured_channel_id = clean_channel_id_value(layout.get(key))
        if configured_channel_id:
            channel_ids.add(int(configured_channel_id))
    for discord_guild in getattr(client, "guilds", []) or []:
        if guild_slug_for_discord_server(discord_guild, "") != guild_slug:
            continue
        for channel in getattr(discord_guild, "text_channels", []) or []:
            name = str(getattr(channel, "name", "") or "").strip().casefold().replace("-", "").replace("_", "")
            if "worldbuff" in name or "wordbuff" in name or "wbticker" in name:
                channel_ids.add(int(channel.id))
    return channel_ids


def clean_channel_id_value(value):
    text = str(value or "").strip()
    return text if text.isdigit() else ""


async def fetch_accessible_discord_channel(channel_id):
    channel_id = clean_channel_id_value(channel_id)
    if not channel_id:
        return None
    try:
        return client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    except Exception:
        return None


def backup_channel_rank(channel, kind="backup"):
    name = str(channel.get("name") or channel.get("channelName") or "").strip().lower()
    category = str(channel.get("category") or channel.get("categoryName") or "").strip().lower()
    combined = f"{category} {name}".strip()
    has_backup = "backup" in combined or "sicherung" in combined
    has_worldbuff = "worldbuff" in combined or "wb" in combined or "buff" in combined
    if has_worldbuff and has_backup:
        return 0
    if name in {"wb", "worldbuff", "worldbuffs"}:
        return 1
    if has_backup:
        return 4
    return 99


async def resolve_backup_channel_id(payload, kind="backup"):
    layout_key = "worldbuffBackupChannelId" if kind == "worldbuff" else "p0PlusBackupChannelId"
    configured_channel_id = clean_channel_id_value(
        payload.get("channelId") or payload.get("targetChannelId") or current_guild_layout().get(layout_key)
    )
    if configured_channel_id and await fetch_accessible_discord_channel(configured_channel_id):
        return configured_channel_id

    if configured_channel_id:
        print(f"Backup-Channel nicht erreichbar fuer {current_guild_slug()}: {configured_channel_id}")

    if not LICHTBOT_QUEUE_TOKEN:
        return configured_channel_id

    lookup_guild_slug = current_guild_slug()
    token = CURRENT_GUILD_SLUG.set(lookup_guild_slug)
    try:
        result = lichtloot_get({
            "action": "guildGetDiscordBotChannels",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "t": int(time.time())
        })
    except Exception as error:
        print(f"Backup-Channel-Fallback konnte Channel-Liste fuer {lookup_guild_slug} nicht laden: {error}")
        return configured_channel_id
    finally:
        CURRENT_GUILD_SLUG.reset(token)

    channels = result.get("channels") or []
    ranked = sorted(
        [channel for channel in channels if clean_channel_id_value(channel.get("id") or channel.get("channelId"))],
        key=lambda channel: (
            backup_channel_rank(channel, kind),
            int(channel.get("position") or 999999),
            str(channel.get("name") or channel.get("channelName") or "").lower()
        )
    )

    for channel in ranked:
        if backup_channel_rank(channel, kind) >= 99:
            break
        channel_id = clean_channel_id_value(channel.get("id") or channel.get("channelId"))
        if await fetch_accessible_discord_channel(channel_id):
            print(
                "Backup-Channel-Fallback: "
                f"{lookup_guild_slug} nutzt #{channel.get('name') or channel.get('channelName')} ({channel_id})"
            )
            return channel_id

    return configured_channel_id


def worldbuff_replacement_channel_ids(target, payload=None):
    payload = payload or {}
    direct_channel_id = clean_channel_id_value(
        payload.get("targetChannelId")
        or payload.get("channelId")
    )
    if direct_channel_id:
        return [int(direct_channel_id)]

    configured_channel_id = clean_channel_id_value(
        get_configured_worldbuff_channel_id()
    )
    return [int(configured_channel_id)] if configured_channel_id else []


def worldbuff_channel_rank(channel):
    name = str(channel.get("name") or channel.get("channelName") or "").strip().lower()
    category = str(channel.get("category") or channel.get("categoryName") or "").strip().lower()
    combined = f"{category} {name}".strip()
    if name in {"worldbuffs", "worldbuff", "wordbuffs", "wordbuff"}:
        return 0
    if "worldbuff" in name or "wordbuff" in name:
        return 1
    if "worldbuff" in combined or "wordbuff" in combined:
        return 2
    if name in {"buffs", "buff", "wb"}:
        return 3
    if "buff" in name:
        return 4
    return 99


def get_configured_worldbuff_channel_id():
    guild_slug = current_guild_slug()
    layout = current_guild_layout()
    configured_channel_id = clean_channel_id_value(
        layout.get("worldbuffChannelId")
    )
    if configured_channel_id:
        return configured_channel_id

    now = time.time()
    cached = WORLDBUFF_CHANNEL_CACHE.get(guild_slug)
    cached_at = WORLDBUFF_CHANNEL_CACHE_TIME.get(guild_slug, 0)
    if cached and now - cached_at < WORLDBUFF_CHANNEL_CACHE_SECONDS:
        return cached

    if LICHTBOT_QUEUE_TOKEN:
        try:
            result = lichtloot_get({
                "action": "guildGetDiscordBotChannels",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                "t": int(time.time())
            })
            channels = result.get("channels") or []
            ranked = sorted(
                [channel for channel in channels if str(channel.get("id") or channel.get("channelId") or "").strip()],
                key=lambda channel: (
                    worldbuff_channel_rank(channel),
                    int(channel.get("position") or 999999),
                    str(channel.get("name") or channel.get("channelName") or "").lower()
                )
            )
            if ranked and worldbuff_channel_rank(ranked[0]) < 99:
                channel_id = str(ranked[0].get("id") or ranked[0].get("channelId") or "").strip()
                WORLDBUFF_CHANNEL_CACHE[guild_slug] = channel_id
                WORLDBUFF_CHANNEL_CACHE_TIME[guild_slug] = now
                return channel_id
        except Exception as error:
            print(f"Worldbuff-Zielchannel fuer {guild_slug} konnte nicht aus Railway geladen werden: {error}")

    return ""


def can_post_worldbuff_overview():
    return bool(get_configured_worldbuff_channel_id())


def is_ticker_channel(channel_id):
    return int(channel_id) in TICKER_CHANNEL_IDS


def is_worldbuff_poster_source_message(message):
    return str(getattr(message, "id", "") or "") in WORLDBUFF_POSTER_MESSAGE_IDS


def is_wbposter_bot_message(message):
    """Nur echte WBPoster-App-Nachrichten zum automatischen Löschen zulassen."""
    if is_worldbuff_poster_source_message(message):
        return True
    author = getattr(message, "author", None)
    author_name = " ".join([
        str(getattr(author, "name", "") or ""),
        str(getattr(author, "display_name", "") or ""),
        str(getattr(author, "global_name", "") or ""),
    ]).casefold()
    return "wbposter" in author_name.replace(" ", "")


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


def get_gildenleitung_worldbuff_rows(days="all"):
    result = railway_get({
        "action": "guildGetWorldbuffs",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "source": "railway",
        "days": days
    })
    if not result or not result.get("success"):
        return []
    rows = result.get("buffs") or result.get("entries") or []
    return rows if isinstance(rows, list) else []


def get_open_worldbuff_signup_slots(limit=25):
    today = datetime.now(BERLIN_TZ).date()
    # Nachtloot plant seine offenen WB-Slots mehrere Monate im Voraus.
    # 180 Tage stellen sicher, dass zehn wöchentliche Slots je Buff im
    # Discord-Dropdown auswählbar bleiben.
    max_date = today + timedelta(days=180)
    slots = []
    seen = set()
    row_order = 0

    rows = get_gildenleitung_worldbuff_rows(days="all")
    rows = filter_nachtloot_alternating_worldbuff_rows(rows)

    for row in rows:
        buff = normalize_buff(row.get("buff", ""))
        if buff not in ["Nef", "Ony", "Hakkar"]:
            continue
        if row.get("charakter"):
            continue
        if not is_open_worldbuff_status(row.get("status")):
            continue
        gilde = row.get("gilde", "")
        if not is_own_worldbuff_guild(gilde):
            continue

        try:
            slot_date = datetime.strptime(row.get("datum", ""), "%d.%m.%Y").date()
        except:
            continue

        if slot_date < today or slot_date > max_date:
            continue

        # Ony und Nef teilen sich auf der Worldbuff-Seite einen gemeinsamen
        # Tagesplatz. Solange er frei ist, darf der Spieler auswählen, welchen
        # der beiden Buffs er wirft. Nach der Anmeldung wird der Termin in
        # Railway auf den gewählten Buff umgestellt und ist insgesamt belegt.
        choice_buffs = [buff]
        if current_guild_slug() != NACHTLOOT_GUILD_SLUG:
            if buff == "Ony":
                choice_buffs.append("Nef")
            elif buff == "Nef":
                choice_buffs.append("Ony")

        for choice_index, choice_buff in enumerate(choice_buffs):
            key = "|".join([
                choice_buff,
                row.get("datum", ""),
                row.get("uhrzeit", ""),
                current_guild_slug().upper()
            ])
            if key in seen:
                continue
            seen.add(key)

            slots.append({
                "rowNumber": row.get("eventId") or row.get("rowNumber", ""),
                "buff": choice_buff,
                "original_buff": buff,
                "datum": row.get("datum", ""),
                "tag": row.get("tag", ""),
                "uhrzeit": row.get("uhrzeit", ""),
                "gilde": gilde,
                "sort_date": slot_date,
                "row_order": row_order,
                "choice_order": choice_index
            })

        row_order += 1

    slots.sort(key=lambda row: (row["sort_date"], row.get("uhrzeit", ""), row.get("row_order", 0), row.get("choice_order", 0)))
    return slots[:limit]


def claim_worldbuff_slot_in_sheet(slot, charakter, discord_name, discord_user_id=""):
    payload = {
        "action": "lichtbotClaimWorldbuffSlot",
        "queueToken": LICHTBOT_QUEUE_TOKEN,
        "rowNumber": slot.get("rowNumber", ""),
        "buff": slot.get("buff", ""),
        "datum": slot.get("datum", ""),
        "uhrzeit": slot.get("uhrzeit", ""),
        "gilde": slot.get("gilde", ""),
        "charakter": charakter,
        "discord": discord_name,
        "discordUserId": str(discord_user_id or ""),
        "status": "bestätigt",
        "source": "railway"
    }

    result = railway_post(payload)
    clear_worldbuff_csv_cache()
    return result


async def worldbuff_signup_core(slot, charakter, discord_name, discord_user_id=""):
    charakter = str(charakter or "").strip()
    if not slot:
        return "⚠️ Dieser Worldbuff-Termin wurde nicht gefunden."
    if not charakter:
        return "Bitte trage einen Charakternamen ein."

    result = await asyncio.to_thread(
        claim_worldbuff_slot_in_sheet, slot, charakter, discord_name, discord_user_id
    )

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
        interaction_guild_slug = guild_slug_for_discord_server(
            getattr(interaction, "guild", None),
            ""
        )
        if not interaction_guild_slug:
            await interaction.response.send_message("Dieser Discord-Server ist keiner freigeschalteten Gilde zugeordnet.", ephemeral=True)
            return
        token = CURRENT_GUILD_SLUG.set(interaction_guild_slug)
        try:
            await interaction.response.defer(ephemeral=True)
            result_text = await worldbuff_signup_core(
                self.slot,
                str(self.charakter.value or ""),
                interaction.user.display_name,
                interaction.user.id
            )
            await interaction.followup.send(result_text, ephemeral=True)
        finally:
            CURRENT_GUILD_SLUG.reset(token)


class WorldbuffSignupSelect(discord.ui.Select):
    def __init__(self, slots, buff_filter=""):
        self.slots = slots
        options = []
        for index, slot in enumerate(slots):
            label = f"{slot.get('buff')} · {slot.get('datum')} {slot.get('uhrzeit')}"
            tag = str(slot.get("tag") or "").strip()
            description = f"{tag + ' · ' if tag else ''}{slot.get('gilde') or 'Lichtbringer'}"
            options.append(discord.SelectOption(
                label=label[:100],
                description=description[:100],
                value=str(index),
                emoji=get_buff_emoji(slot.get("buff"))
            ))
        buff_label = normalize_buff(buff_filter) if buff_filter else "Worldbuff"
        super().__init__(
            placeholder=f"{buff_label}-Termin auswählen",
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
    def __init__(self, slots, buff_filter=""):
        super().__init__(timeout=180)
        if slots:
            self.add_item(WorldbuffSignupSelect(slots, buff_filter=buff_filter))


class WorldbuffBuffButton(discord.ui.Button):
    def __init__(self, buff, label, style, emoji):
        self.buff = buff
        super().__init__(
            label=label,
            style=style,
            emoji=emoji,
            custom_id=f"worldbuff_pick:{buff.lower()}"
        )

    async def callback(self, interaction):
        interaction_guild_slug = guild_slug_for_discord_server(
            getattr(interaction, "guild", None),
            ""
        )
        if not interaction_guild_slug:
            await interaction.response.send_message("Dieser Discord-Server ist keiner freigeschalteten Gilde zugeordnet.", ephemeral=True)
            return
        token = CURRENT_GUILD_SLUG.set(interaction_guild_slug)
        try:
            if not lichtbuff_self_signup_buttons_enabled(interaction_guild_slug):
                await interaction.response.send_message(
                    "⚠️ Die Selbsteintragung ist für diese Gilde derzeit ausgeschaltet.",
                    ephemeral=True
                )
                return
            buff = normalize_buff(self.buff)
            slots = await asyncio.to_thread(get_open_worldbuff_signup_slots, 75)
            slots = [slot for slot in slots if normalize_buff(slot.get("buff")) == buff]

            if not slots:
                await interaction.response.send_message(
                    f"⚠️ Aktuell ist kein freier {buff}-Termin verfügbar.",
                    ephemeral=True
                )
                return

            await interaction.response.send_message(
                f"✅ **{buff} eintragen**\n"
                "Wähle einen freien Termin aus. Danach öffnet sich das Feld für deinen Charakternamen.",
                view=WorldbuffSignupView(slots[:25], buff_filter=buff),
                ephemeral=True
            )
        finally:
            CURRENT_GUILD_SLUG.reset(token)


class WorldbuffBuffPickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WorldbuffBuffButton("Hakkar", "Hakkar", discord.ButtonStyle.success, get_buff_emoji("Hakkar")))
        self.add_item(WorldbuffBuffButton("Ony", "Ony", discord.ButtonStyle.danger, get_buff_emoji("Ony")))
        self.add_item(WorldbuffBuffButton("Nef", "Nef", discord.ButtonStyle.danger, get_buff_emoji("Nef")))




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


class RendActionModal(discord.ui.Modal):
    def __init__(self, mode):
        self.mode = mode
        titles = {
            "ally": "Rend benötigt",
            "helper": "Als Helfer anmelden",
            "takeover": "Direkte Übernahme",
            "delete": "Rend-Eintrag entfernen",
        }
        super().__init__(title=titles.get(mode, "Rend-Anmeldung"), timeout=180)

        self.ally_char = None
        self.horde_char = None
        if mode in {"ally", "takeover", "delete"}:
            self.ally_char = discord.ui.TextInput(
                label="Ally-Char" if mode != "delete" else "Charaktername entfernen",
                placeholder="z. B. Ariee",
                required=True,
                max_length=50,
            )
            self.add_item(self.ally_char)
        if mode in {"helper", "takeover"}:
            self.horde_char = discord.ui.TextInput(
                label="Horden-Char / Helfer",
                placeholder="z. B. Miimi",
                required=True,
                max_length=50,
            )
            self.add_item(self.horde_char)

    async def on_submit(self, interaction):
        interaction_guild_slug = guild_slug_for_discord_server(
            getattr(interaction, "guild", None),
            ""
        )
        if not interaction_guild_slug:
            await interaction.response.send_message("Dieser Discord-Server ist keiner freigeschalteten Gilde zugeordnet.", ephemeral=True)
            return
        token = CURRENT_GUILD_SLUG.set(interaction_guild_slug)
        try:
            await interaction.response.defer(ephemeral=True)
            ally_char = str(self.ally_char.value or "") if self.ally_char else ""
            horde_char = str(self.horde_char.value or "") if self.horde_char else ""
            if self.mode == "delete":
                result_text = await hordenbuff_delete_core(ally_char)
            else:
                result_text = await hordenbuff_signup_core(
                    ally_char=ally_char,
                    horde_char=horde_char,
                    author_name=interaction.user.display_name
                )
            await interaction.followup.send(result_text, ephemeral=True)
        finally:
            CURRENT_GUILD_SLUG.reset(token)


class RendActionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Rend-Aktion auswählen …",
            min_values=1,
            max_values=1,
            custom_id="hordenbuff:rend_action",
            options=[
                discord.SelectOption(
                    label="Ich benötige Rend",
                    description="Ally-Char für den aktiven Termin eintragen",
                    value="ally",
                    emoji=get_buff_emoji("Rend"),
                ),
                discord.SelectOption(
                    label="Ich helfe mit einem Horden-Char",
                    description="Als freier Helfer eintragen oder automatisch zuteilen",
                    value="helper",
                    emoji="🛡️",
                ),
                discord.SelectOption(
                    label="Bestimmten Spieler übernehmen",
                    description="Ally-Char und Horden-Helfer direkt zuordnen",
                    value="takeover",
                    emoji="🤝",
                ),
                discord.SelectOption(
                    label="Meinen Eintrag entfernen",
                    description="Ally- oder Horden-Char aus dem aktiven Termin löschen",
                    value="delete",
                    emoji="🗑️",
                ),
            ],
        )

    async def callback(self, interaction):
        await interaction.response.send_modal(RendActionModal(self.values[0]))


class RendSignupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RendActionSelect())


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


def current_worldbuff_guild_label():
    guild_slug = current_guild_slug()
    if guild_slug == LICHTLOOT_GUILD_SLUG:
        return "Lichtbringer"
    data = GUILD_REGISTRY.get(guild_slug) or {}
    return str(data.get("name") or data.get("guildName") or guild_slug).strip() or guild_slug


def current_worldbuff_guild_names():
    guild_slug = current_guild_slug()
    data = GUILD_REGISTRY.get(guild_slug) or {}
    names = {
        guild_slug,
        data.get("name"),
        data.get("guildName"),
        data.get("guild_name"),
        data.get("lootName"),
        data.get("loot_name"),
        data.get("displayName"),
    }
    if guild_slug == LICHTLOOT_GUILD_SLUG:
        names.update({"Lichtbringer", "LichtLoot", "lichtloot"})
    elif guild_slug == NACHTLOOT_GUILD_SLUG:
        names.update({"Nachtloot", "NachtLoot", "Nachtwächter", "Die Nachtwächter"})
    return {
        re.sub(r"\s+", " ", str(name or "").strip()).casefold()
        for name in names
        if str(name or "").strip()
    }


def is_own_worldbuff_guild(gilde):
    value = re.sub(r"\s+", " ", str(gilde or "").strip()).casefold()
    return value in current_worldbuff_guild_names()


def filter_worldbuff_rows_for_current_guild(rows):
    if current_guild_slug() == LICHTLOOT_GUILD_SLUG:
        return list(rows or [])
    return [
        row for row in rows or []
        if (
            is_own_worldbuff_guild((row or {}).get("gilde", ""))
            or (
                current_guild_slug() == NACHTLOOT_GUILD_SLUG
                and str((row or {}).get("source") or "").strip().casefold() == "wb_poster"
            )
        )
    ]


def filter_nachtloot_alternating_worldbuff_rows(rows):
    """Nachtloot übernimmt Buff und Termin exakt aus der Worldbuff-Seite."""
    entries = list(rows or [])
    if current_guild_slug() != NACHTLOOT_GUILD_SLUG:
        return entries

    def slot_key(row):
        buff = normalize_buff((row or {}).get("buff", ""))
        buff_group = "Ony/Nef" if buff in ["Ony", "Nef"] else buff
        return (str((row or {}).get("datum") or ""), buff_group)

    # Pro Nachtwaechter-Tag gibt es genau einen Hakkar- und einen
    # Ony/Nef-Slot. Fuer die Auswahl gilt exakt dieselbe Prioritaet wie in
    # collapseWorldbuffDailySlots() auf der NachtLoot-Leitungsseite.
    own_by_slot = {}

    def page_priority(row):
        score = 0
        caster = str((row or {}).get("charakter") or "").strip()
        status = re.sub(r"[🟡🟢✅🔴🟠⚪]", "", str((row or {}).get("status") or "")).strip().casefold()
        source = str((row or {}).get("source") or "").strip().casefold()
        guild = str((row or {}).get("gilde") or "").strip().casefold()
        if caster:
            score += 1000
        if "bestätigt" in status or "bestaetigt" in status:
            score += 200
        if "railway" in source or "player-worldbuff" in source:
            score += 80
        if "sheet" in source:
            score += 30
        if "lichtbringer" in guild:
            score += 20
        if guild and guild != "-":
            score += 5
        return score

    for index, row in enumerate(entries):
        if not isinstance(row, dict) or not is_own_worldbuff(row):
            continue
        key = slot_key(row)
        current = own_by_slot.get(key)
        score = page_priority(row)
        # Wie auf der Seite wird bei Gleichstand die erste Zeile behalten.
        if current is None or score > current[0]:
            own_by_slot[key] = (score, row)

    selected_ids = {id(value[1]) for value in own_by_slot.values()}
    return [
        row for row in entries
        if not (isinstance(row, dict) and is_own_worldbuff(row)) or id(row) in selected_ids
    ]


def get_shared_wb_poster_rows():
    """WB-Poster-Cache des Hauptservers fuer Nachtloot mitverwenden."""
    rows = load_json(WB_POSTER_CACHE_FILE, [])
    if not rows:
        # Kompatibilitaet mit dem bisherigen Cache bis der naechste
        # WB-Poster-Post eingelesen wurde.
        rows = load_json(DATA_FILE, [])
    return [
        {**row, "source": "wb_poster"}
        for row in rows or []
        if isinstance(row, dict) and not is_deleted_worldbuff(row)
    ]


def merge_shared_wb_poster_rows(data):
    poster_rows = get_shared_wb_poster_rows()
    merge_ticker_buffs_preserving_railway(data, poster_rows)

    # Wenn derselbe Termin bereits aus Railway vorhanden ist, fuegt der
    # Deduplizierer keine zweite Zeile an. Wir kennzeichnen ihn trotzdem als
    # WB-Poster-Termin, damit er im Nachtwächter-Post sichtbar bleibt.
    poster_keys = {make_buff_key(row) for row in poster_rows}
    poster_identity = {make_overview_dedupe_key(row) for row in poster_rows}
    for row in data:
        if make_buff_key(row) in poster_keys or make_overview_dedupe_key(row) in poster_identity:
            row["source"] = "wb_poster"


def is_lichtbringer_buff(buff_data):
    try:
        return is_lichtbringer(str((buff_data or {}).get("gilde", "")))
    except Exception:
        return False


def is_own_worldbuff(buff_data):
    try:
        return is_own_worldbuff_guild((buff_data or {}).get("gilde", ""))
    except Exception:
        return False


def make_buff_key(buff_data):
    datum = buff_data["datum"]
    zeit = buff_data["uhrzeit"]
    buff = normalize_buff(buff_data["buff"])
    gilde = buff_data["gilde"]

    if is_own_worldbuff_guild(gilde):
        label = "LICHTBRINGER" if current_guild_slug() == LICHTLOOT_GUILD_SLUG else current_worldbuff_guild_label()
        return f"{datum}|{zeit}|{buff}|{label}"

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

    if is_own_worldbuff_guild(value):
        return "LICHTBRINGER" if current_guild_slug() == LICHTLOOT_GUILD_SLUG else current_worldbuff_guild_label()
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


def make_buff_time_key(buff_data):
    datum = buff_data.get("datum", "")
    zeit = buff_data.get("uhrzeit", "")
    buff = normalize_buff(buff_data.get("buff", ""))
    return f"{datum}|{zeit}|{buff}"


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
    guild_slug = current_guild_slug()
    cached_rows = WORLDBUFF_API_CACHE_BY_GUILD.get(guild_slug)
    cached_time = WORLDBUFF_API_CACHE_TIME_BY_GUILD.get(guild_slug)
    if cached_rows and cached_time:
        if (now - cached_time).total_seconds() < WORLDBUFF_API_CACHE_SECONDS:
            return list(cached_rows)

    try:
        result = lichtloot_get({
            "action": "guildGetWorldbuffs",
            "source": "railway",
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

        WORLDBUFF_API_CACHE_BY_GUILD[guild_slug] = rows
        WORLDBUFF_API_CACHE_TIME_BY_GUILD[guild_slug] = now
        WORLDBUFF_API_CACHE_ROWS = rows
        WORLDBUFF_API_CACHE_TIME = now
        print(f"Apps-Script-Worldbuffs fuer {guild_slug}: {len(rows)} Buff-Zeilen gelesen.")
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
    # WBPoster nutzt je nach Buff unterschiedliche Symbolpräfixe. Neben den
    # bisherigen Statuspunkten werden auch Herz, Drache und Farbfelder erkannt.
    prefix = r"^(?:(?:<a?:[A-Za-z0-9_]+:\d+>|[🟢🔴🟠⚪🟡✅❌🔥🌿☠️💀❤️❤🐉🟦🟥•\-–—])\ufe0f?\s*)?"
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
        # WBPoster trennt seine Tabellenspalten teilweise mit dem sichtbaren
        # Unicode-Braille-Leerzeichen U+2800. Python behandelt dieses Zeichen
        # nicht als normales Whitespace; ohne Ersetzung wird der aktuelle Post
        # übersprungen und ein älterer, anders formatierter Ticker eingelesen.
        line = "".join(
            " " if char == "\u2800" or unicodedata.category(char) in {"Zs", "Zl", "Zp", "Cf"} else char
            for char in line
        )
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

        # Robuster WBPoster-Fallback: Die App ändert gelegentlich Emojis,
        # Spaltentrenner oder die Menge der Abstände. Relevant ist nur die
        # Reihenfolge Buff -> Datum -> Uhrzeit -> Gilde.
        if not match:
            flexible_match = re.search(
                r"(?P<buff>Hakkar|ZG|Ony|Onyxia|Nef|Nefarian|Rend)"
                r".*?(?P<datum>\d{1,2}\.\d{1,2}\.\d{4})"
                r".*?(?P<uhrzeit>\d{1,2}:\d{2})"
                r"\s*(?P<gilde>.+?)\s*$",
                line,
                re.IGNORECASE,
            )
            if flexible_match:
                buffs.append({
                    "buff": normalize_buff(flexible_match.group("buff")),
                    "datum": flexible_match.group("datum"),
                    "tag": make_tag_from_date(flexible_match.group("datum")),
                    "uhrzeit": flexible_match.group("uhrzeit"),
                    "gilde": re.sub(
                        r"^(?:Mo|Di|Mi|Do|Fr|Sa|So|Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\s+",
                        "",
                        flexible_match.group("gilde").strip(),
                        flags=re.IGNORECASE,
                    ),
                    "source": "wb_poster",
                })
                continue

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
                "gilde": re.sub(r"^(?:Mo|Di|Mi|Do|Fr|Sa|So|Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\s+", "", gilde.strip(), flags=re.IGNORECASE),
                "source": "wb_poster",
            })

    return buffs


def import_buffs_aus_sheet():
    rows = get_worldbuff_rows_from_apps_script(days=14)
    source = "Railway"

    if not rows and ALLOW_WORLDBUFF_CSV_FALLBACK:
        rows = iter_worldbuff_sheet_rows()
        source = "CSV"

    sheet_buffs = []

    for row in rows:
        sheet_buffs.append({
            "rowNumber": row.get("rowNumber") or row.get("eventId", ""),
            "buff": row.get("buff", ""),
            "datum": row.get("datum", ""),
            "tag": row.get("tag", ""),
            "uhrzeit": row.get("uhrzeit", ""),
            "gilde": row.get("gilde", ""),
            "charakter": row.get("charakter", ""),
            "status": row.get("status", ""),
            "source": row.get("source", "")
        })

    if not sheet_buffs:
        print("Keine Worldbuff-Zeilen aus Railway geladen.")
    else:
        print(f"Worldbuffs via {source}: {len(sheet_buffs)} Buff-Zeilen gelesen.")

    return sheet_buffs


def import_werfer_aus_sheet():
    werfer = {}
    rows = get_worldbuff_rows_from_apps_script(days=14)
    if not rows and ALLOW_WORLDBUFF_CSV_FALLBACK:
        rows = iter_worldbuff_sheet_rows()

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

    result = lichtloot_post(payload)
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
        with WORLDBUFF_DATABASE_SYNC_LOCK:
            result = lichtloot_post(payload)
        if isinstance(result, dict) and result.get("success"):
            clear_worldbuff_csv_cache()
        print(f"Worldbuffticker-Railway-Sync: {result}")
        return result
    except Exception as e:
        print(f"Worldbuffticker-Sync Fehler: {e}")
        return {"success": False, "error": str(e)}


def clear_worldbuff_csv_cache():
    global CSV_CACHE_CONTENT, CSV_CACHE_TIME, WORLDBUFF_PLAN_CACHE_CONTENT, WORLDBUFF_PLAN_CACHE_TIME
    global WORLDBUFF_API_CACHE_ROWS, WORLDBUFF_API_CACHE_TIME

    CSV_CACHE_CONTENT = ""
    CSV_CACHE_TIME = None
    WORLDBUFF_PLAN_CACHE_CONTENT = ""
    WORLDBUFF_PLAN_CACHE_TIME = None
    WORLDBUFF_API_CACHE_ROWS = []
    WORLDBUFF_API_CACHE_TIME = None
    WORLDBUFF_API_CACHE_BY_GUILD.clear()
    WORLDBUFF_API_CACHE_TIME_BY_GUILD.clear()
    WORLDBUFF_CHANNEL_CACHE.clear()
    WORLDBUFF_CHANNEL_CACHE_TIME.clear()


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


def merge_ticker_buffs_preserving_railway(data, ticker_buffs):
    allowed_ticker_buffs = []
    for buff in ticker_buffs:
        if not isinstance(buff, dict) or is_deleted_worldbuff(buff):
            continue
        allowed_ticker_buffs.append(buff)
    if allowed_ticker_buffs:
        return merge_buffs_into_data(data, allowed_ticker_buffs)
    return 0


def remove_shadowed_lichtbringer_ticker_buffs(rows):
    own_slots = {
        make_buff_time_key(buff)
        for buff in rows
        if isinstance(buff, dict) and is_own_worldbuff(buff)
    }

    return [
        buff for buff in rows
        if not (
            isinstance(buff, dict)
            and is_lichtbringer_buff(buff)
            and not is_own_worldbuff(buff)
            and make_buff_time_key(buff) in own_slots
        )
    ]


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


def format_worldbuff_overview_row(emoji, buff, zeit, gilde, werfer_text=""):
    """Formatiert Uhrzeit und Gilde im Discord-Embed als feste Spalten."""
    buff_text = str(buff or "").strip()
    zeit_text = str(zeit or "").strip()
    gilde_text = str(gilde or "").strip()
    # Der längste angezeigte Buffname (Hakkar) hat sechs Zeichen. In einem
    # Inline-Codeblock verwendet Discord eine Festbreitenschrift, sodass die
    # Uhrzeiten und Gildennamen auch bei Ony, Nef und Rend exakt fluchten.
    row = f"{buff_text:<6}  {zeit_text:<5}  {gilde_text}{werfer_text}"
    return f"{emoji} `{row.rstrip()}`"


def display_worldbuff_name(buff_data, charakter=""):
    """Zeigt freie Lichtbringer-Ony/Nef-Slots als echte Wahltermine an."""
    buff = normalize_buff((buff_data or {}).get("buff", ""))
    if (
        buff in ["Ony", "Nef"]
        and is_lichtbringer(str((buff_data or {}).get("gilde", "")))
        and not str(charakter or "").strip()
        and is_open_worldbuff_status((buff_data or {}).get("status"))
    ):
        return "Ony/Nef"
    return buff


def build_overview():
    sheet_buffs = import_buffs_aus_sheet()
    data = list(sheet_buffs)
    local_ticker_buffs = [
        buff for buff in load_json(worldbuff_file(), [])
        if isinstance(buff, dict) and not is_deleted_worldbuff(buff)
    ]
    if local_ticker_buffs:
        merge_ticker_buffs_preserving_railway(data, local_ticker_buffs)
    if current_guild_slug() == NACHTLOOT_GUILD_SLUG:
        merge_shared_wb_poster_rows(data)
    data = filter_worldbuff_rows_for_current_guild(data)
    data = filter_nachtloot_alternating_worldbuff_rows(data)

    werfer = import_werfer_aus_sheet()

    if not data:
        return "📢 **Worldbuff Übersicht**\n\nKeine Worldbuffs gefunden."

    heute = datetime.now(BERLIN_TZ).date()
    # Einschliesslich heute genau fuenf Kalendertage anzeigen.
    ende = heute + timedelta(days=4)

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

    data = remove_shadowed_lichtbringer_ticker_buffs(gefiltert)

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
    text += "_Nächste 5 Tage · Eintragen über die Auswahl unten_\n"

    current_date = ""

    for b in data:
        datum = b["datum"]
        tag_kurz = b.get("tag") or make_tag_from_date(datum)
        tag_lang = TAG_LANG.get(tag_kurz, tag_kurz)
        zeit = b["uhrzeit"]
        gilde = b["gilde"]

        if datum != current_date:
            text += f"\n**{tag_lang}, {datum}**\n"
            current_date = datum

        werfer_text = ""

        key = make_buff_key(b)
        info = werfer.get(key)
        charakter = b.get("charakter") or (info and info.get("charakter")) or ""
        buff = display_worldbuff_name(b, charakter)
        emoji = get_buff_emoji(normalize_buff(b["buff"]))

        if charakter:
            if is_lichtbringer(gilde):
                werfer_text = f" - 🔵 {charakter}"
            else:
                werfer_text = f" - ⚔️ {charakter}"

        text += format_worldbuff_overview_row(
            emoji, buff, zeit, gilde, werfer_text
        ) + "\n"

    return text


def current_worldbuff_announcement_block(max_lines=8):
    sheet_buffs = import_buffs_aus_sheet()
    data = list(sheet_buffs)
    local_ticker_buffs = [
        buff for buff in load_json(worldbuff_file(), [])
        if isinstance(buff, dict) and not is_deleted_worldbuff(buff)
    ]
    if local_ticker_buffs:
        merge_ticker_buffs_preserving_railway(data, local_ticker_buffs)
    if current_guild_slug() == NACHTLOOT_GUILD_SLUG:
        merge_shared_wb_poster_rows(data)
    data = filter_worldbuff_rows_for_current_guild(data)
    data = filter_nachtloot_alternating_worldbuff_rows(data)

    if not data:
        return ""

    werfer = import_werfer_aus_sheet()
    today = datetime.now(BERLIN_TZ).date()
    max_date = today + timedelta(days=4)
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

    rows = remove_shadowed_lichtbringer_ticker_buffs(rows)
    rows.sort(key=lambda item: (datetime.strptime(item["datum"], "%d.%m.%Y"), item.get("uhrzeit", "")))
    if not rows:
        return ""

    lines = []
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

        gilde = buff.get("gilde", "")
        key = make_buff_key(buff)
        info = werfer.get(key)
        charakter = buff.get("charakter") or (info and info.get("charakter")) or ""
        buff_name = display_worldbuff_name(buff, charakter)
        werfer_text = f" - {'🔵' if is_lichtbringer(gilde) else '⚔️'} {charakter}" if charakter else ""
        emoji = get_buff_emoji(normalize_buff(buff.get("buff", "")))
        lines.append(format_worldbuff_overview_row(
            emoji,
            buff_name,
            buff.get("uhrzeit", ""),
            gilde,
            werfer_text
        ))
        added += 1

    return "\n".join(lines).strip()


def build_worldbuff_signup_embed():
    slots = get_open_worldbuff_signup_slots(limit=75)
    counts = {"Hakkar": 0, "Ony": 0, "Nef": 0}
    next_slots = {"Hakkar": [], "Ony": [], "Nef": []}

    for slot in slots:
        buff = normalize_buff(slot.get("buff"))
        if buff not in counts:
            continue
        counts[buff] += 1
        if len(next_slots[buff]) < 3:
            next_slots[buff].append(slot)

    embed = discord.Embed(
        title="Worldbuff eintragen",
        description=(
            "Wähle unten **Hakkar**, **Ony** oder **Nef**. "
            "Danach erscheinen die freien Termine und du trägst deinen Charakter ein."
        ),
        color=0x22C55E
    )

    for buff in ["Hakkar", "Ony", "Nef"]:
        preview = []
        for slot in next_slots[buff]:
            tag = str(slot.get("tag") or "").strip()
            prefix = f"{tag} " if tag else ""
            preview.append(f"{prefix}{slot.get('datum')} · {slot.get('uhrzeit')}")
        value = "\n".join(preview) if preview else "Aktuell kein freier Termin"
        if counts[buff] > len(preview):
            value += f"\n… und {counts[buff] - len(preview)} weitere"
        embed.add_field(
            name=f"{get_buff_emoji(buff)} {buff}",
            value=value,
            inline=True
        )

    embed.set_footer(text="Ein belegter Termin kann nicht durch einen anderen Spieler überschrieben werden.")
    return embed


def build_worldbuff_guide_embed():
    return build_worldbuff_signup_embed()


def build_worldbuff_post_embed(overview_text, self_signup_enabled=True):
    embed = build_worldbuff_signup_embed()
    signup_text = str(embed.description or "").strip()
    overview_lines = str(overview_text or "").strip().splitlines()

    # Die Ueberschrift steht bereits im Embed-Titel und wird nicht doppelt
    # ausgegeben. Alle weiteren Inhalte bleiben innerhalb desselben Embeds.
    if overview_lines and overview_lines[0].startswith("📢 **Worldbuff"):
        overview_lines = overview_lines[1:]
    overview = "\n".join(overview_lines).strip()
    if self_signup_enabled:
        signup_section = f"**Termin eintragen**\n{signup_text}"
    elif current_guild_slug() == NACHTLOOT_GUILD_SLUG:
        signup_section = "ℹ️ **Nef und Ony wechseln sich bei den Nachtwächtern wochenweise ab.**"
    else:
        signup_section = "ℹ️ **Selbsteintragung kommt noch für diese Gilde.**"
    description = f"{overview}\n\n{signup_section}".strip()
    if len(description) > 4096:
        description = description[:4092].rstrip() + " …"

    embed.title = "Worldbuffs & Anmeldung" if self_signup_enabled else "Worldbuffs"
    embed.description = description
    if not self_signup_enabled:
        embed.clear_fields()
        embed.set_footer(text=None)
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
        embed.title in {"Worldbuff eintragen", "Worldbuffs & Anmeldung", "Worldbuffs"}
        for embed in getattr(message, "embeds", []) or []
    )


def is_hordenbuff_overview_message(message):
    content = message.content or ""
    if content.startswith("🪓 **Horde-Rend Koordination**"):
        return True

    return any(
        embed.title == "Hordenbuffs eintragen" or "Hordenbuff-Anmeldung" in str(embed.title or "")
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


async def _sync_recent_ticker_messages_unlocked(limit=None):
    if limit is None:
        limit = WORLDBUFF_TICKER_LAST_POST_SCAN_LIMIT

    cached_rows = await asyncio.to_thread(load_json, worldbuff_file(), [])
    found_buffs = []
    wbposter_messages_to_delete = []
    readable_ticker_channels = 0
    authoritative_poster_seen = False

    for channel_id in ticker_channel_ids_for_current_guild():
        try:
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
        except Exception as e:
            print(f"Ticker-Channel {channel_id} konnte nicht geladen werden:", e)
            continue

        try:
            readable_ticker_channels += 1
            latest_ticker_message = None
            latest_buffs = []

            # Nur den neuesten Post verwenden, der tatsaechlich lesbare
            # Worldbuff-Termine enthaelt. Das kleine Suchfenster erlaubt
            # Hinweise oder Bot-Statusmeldungen nach dem eigentlichen Post,
            # ohne die gesamte Channel-Historie einzulesen.
            async for msg in channel.history(limit=limit, oldest_first=False):
                parsed_buffs = parse_ticker_message(discord_message_search_text(msg))
                if is_wbposter_bot_message(msg):
                    authoritative_poster_seen = True
                    # Der neueste WBPoster ist der maßgebliche vollständige
                    # Snapshot. Niemals auf einen älteren WBPoster zurückfallen,
                    # falls sich das Format des aktuellen Posts geändert hat.
                    latest_ticker_message = msg
                    latest_buffs = parsed_buffs
                    if not parsed_buffs:
                        print(
                            f"Neuesten WBPoster {msg.id} in Channel {channel_id} gefunden, "
                            "aber keine Terminzeilen erkannt. Alter WBPoster wird nicht verwendet."
                        )
                    break
                if parsed_buffs:
                    latest_ticker_message = msg
                    latest_buffs = parsed_buffs
                    break

            if latest_ticker_message and latest_buffs:
                found_buffs.extend(latest_buffs)
                if DELETE_WORLDBUFF_POSTER_SOURCE_MESSAGES and is_wbposter_bot_message(latest_ticker_message):
                    wbposter_messages_to_delete.append(latest_ticker_message)
                print(
                    f"Letzten Ticker-Post {latest_ticker_message.id} aus Channel "
                    f"{channel_id} gelesen: {len(latest_buffs)} Buff-Zeilen."
                )
            elif latest_ticker_message:
                print(
                    f"Aktueller WBPoster {latest_ticker_message.id} in Channel "
                    f"{channel_id} enthielt keine lesbaren Termine."
                )
            else:
                print(
                    f"Kein lesbarer Worldbuff-Ticker-Post unter den letzten "
                    f"{limit} Nachrichten in Channel {channel_id} gefunden."
                )
        except Exception as e:
            readable_ticker_channels -= 1
            print(f"Letzter Ticker-Post aus Channel {channel_id} konnte nicht gelesen werden:", e)
            continue

    found_buffs = [buff for buff in found_buffs if not is_deleted_worldbuff(buff)]

    if found_buffs:
        # Ungefilterter gemeinsamer Poster-Cache: enthaelt auch Lichtbringer
        # und alle weiteren im WB-Poster genannten Gilden. Der neueste Post
        # ist ein vollstaendiger Snapshot und ersetzt deshalb den alten Cache.
        # Ein Merge wuerde nach Zeitkorrekturen jede fruehere Uhrzeit behalten.
        await asyncio.to_thread(save_json, WB_POSTER_CACHE_FILE, found_buffs)

    if not found_buffs and not cached_rows and not readable_ticker_channels:
        return 0

    railway_rows = await asyncio.to_thread(import_buffs_aus_sheet)
    combined_rows = list(railway_rows)

    # Wenn kein Ticker-Channel erreichbar war, bleibt der letzte Cache als
    # Ausfallsicherung erhalten. Sobald ein Channel gelesen werden konnte,
    # wird der alte Ticker-Cache dagegen vollständig durch dessen letzten
    # Post ersetzt.
    if not readable_ticker_channels:
        merge_ticker_buffs_preserving_railway(combined_rows, cached_rows)
    added = merge_ticker_buffs_preserving_railway(combined_rows, found_buffs)

    await asyncio.to_thread(save_json, worldbuff_file(), [
        buff for buff in combined_rows
        if not is_own_worldbuff(buff)
    ])

    # In Railway wird der originale, vollständige WBPoster-Datensatz
    # gespeichert. Die gefilterte combined_rows-Liste ist nur der lokale
    # Anzeigecache und darf keine Termine anderer oder der eigenen Gilde
    # aus dem Datenbankimport entfernen.
    database_rows = found_buffs if found_buffs else ([] if authoritative_poster_seen else cached_rows)
    database_sync_result = None
    if database_rows:
        database_sync_result = await asyncio.to_thread(
            sync_worldbuff_ticker_cache_to_sheet,
            database_rows,
        )

    database_sync_ok = bool(isinstance(database_sync_result, dict) and database_sync_result.get("success"))
    for wbposter_message in wbposter_messages_to_delete if database_sync_ok else []:
        try:
            await wbposter_message.delete()
            print(f"WBPoster-Nachricht {wbposter_message.id} nach erfolgreicher Übernahme gelöscht.")
        except discord.Forbidden:
            print(f"WBPoster-Nachricht {wbposter_message.id} konnte nicht gelöscht werden: Recht 'Nachrichten verwalten' fehlt.")
        except discord.NotFound:
            pass
        except Exception as error:
            print(f"WBPoster-Nachricht {wbposter_message.id} konnte nicht gelöscht werden: {error}")

    print(f"Letzte Ticker-Posts geprüft: {len(found_buffs)} Buff-Zeilen gefunden, {added} neu gespeichert.")
    return added


async def sync_recent_ticker_messages(limit=None):
    # Ticker-Scans werden von mehreren Start-, Intervall- und Befehlswegen
    # ausgelöst. Sie dürfen nicht gleichzeitig Cache und Railway beschreiben.
    async with WORLDBUFF_TICKER_SYNC_LOCK:
        return await _sync_recent_ticker_messages_unlocked(limit=limit)


async def update_worldbuff_post(sync_ticker=True, force_repost=False, refresh_registry=True):
    if refresh_registry:
        await refresh_guild_registry()
    channel_id = get_configured_worldbuff_channel_id()
    if not channel_id:
        print(f"Worldbuff-Uebersicht fuer {current_guild_slug()} uebersprungen: kein Zielchannel konfiguriert.")
        return 0

    try:
        channel = client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    except Exception as error:
        print(f"Ziel-Channel {channel_id} konnte nicht geladen werden: {error}")
        return 0

    if sync_ticker:
        await sync_recent_ticker_messages()
    text = await asyncio.to_thread(build_overview)
    self_signup_enabled = lichtbuff_self_signup_buttons_enabled()
    guide_embed = await asyncio.to_thread(build_worldbuff_post_embed, text, self_signup_enabled)
    signup_view = WorldbuffBuffPickerView() if self_signup_enabled else None
    existing_messages = await fetch_worldbuff_post_messages(channel)
    known_message_ids = {message.id for message in existing_messages}
    recent_messages = await find_recent_own_messages(
        channel,
        is_worldbuff_overview_message,
        limit=500 if current_guild_slug() == NACHTLOOT_GUILD_SLUG else 100,
    )

    if recent_messages:
        if not existing_messages:
            print(f"Worldbuff-Uebersicht im Channel wiedergefunden: {len(recent_messages)} Nachricht(en).")
        existing_messages.extend(message for message in recent_messages if message.id not in known_message_ids)

    if force_repost and existing_messages and current_guild_slug() != NACHTLOOT_GUILD_SLUG:
        for old_msg in existing_messages:
            try:
                await old_msg.delete()
                await asyncio.sleep(0.4)
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"Worldbuff-Uebersicht konnte zum Neu-Posten nicht geloescht werden: {e}")
        existing_messages = []

    if existing_messages:
        msg = existing_messages[0]
        await msg.edit(content="", embed=guide_embed, view=signup_view)
        await delete_extra_messages(existing_messages)
    else:
        # Der gespeicherte Post kann nach einem Botwechsel, einer geloeschten
        # lokalen Cache-Datei oder einer manuell entfernten Nachricht fehlen.
        # In diesem Fall muss sich auch der Nachtwaechter-Post selbst heilen.
        # Die Suche oben verhindert weiterhin doppelte Posts des aktuellen Bots.
        if current_guild_slug() == NACHTLOOT_GUILD_SLUG:
            print(
                "Worldbuff-Uebersicht fuer Nachtwaechter wurde nicht gefunden; "
                "erstelle einen neuen Zielpost."
            )
        msg = await send_silent(channel, embed=guide_embed, view=signup_view)
    save_json(worldbuff_post_file(), {"message_id": msg.id, "message_ids": [msg.id]})
    return 1


async def sync_recent_ticker_messages_for_all_guilds(limit=None):
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


async def update_worldbuff_overview_from_all_guilds(force_repost=False):
    # Layout-Schalter koennen jederzeit in der Gildenleitung geaendert werden.
    # Vor jedem Uebersichts-Update frisch laden, damit der Bot nicht bis zum
    # naechsten Neustart mit einem alten Wert weiterarbeitet.
    await refresh_guild_registry()
    updated_count = 0
    guild_slugs = configured_worldbuff_guild_slugs()
    for guild_slug in guild_slugs:
        token = CURRENT_GUILD_SLUG.set(guild_slug)
        try:
            updated_count += await update_worldbuff_post(
                sync_ticker=guild_slug == LICHTLOOT_GUILD_SLUG,
                force_repost=force_repost,
                refresh_registry=False
            )
        except Exception as error:
            print(f"Worldbuff-Update fuer {guild_slug} fehlgeschlagen:", error)
        finally:
            CURRENT_GUILD_SLUG.reset(token)
    return updated_count


async def wbposter_database_sync_loop():
    """Polling-Fallback: Discord-Ereignisse können ausbleiben, Railway bleibt die Quelle."""
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            await sync_recent_ticker_messages_for_all_guilds(limit=max(50, WORLDBUFF_TICKER_LAST_POST_SCAN_LIMIT))
            clear_worldbuff_csv_cache()
            await update_worldbuff_overview_from_all_guilds(force_repost=False)
        except Exception as error:
            print(f"Regelmäßiger WBPoster-Railway-Abgleich fehlgeschlagen: {error}")
        await asyncio.sleep(120)


def get_hordenbuff_schedule_rows():
    """
    Beide Gilden verwenden dieselben Rend-Wurfzeiten aus der LichtLoot-
    Hordenbuff-Liste. Die Anmeldedaten werden spaeter weiterhin aus der
    Hordenbuff-Liste im jeweiligen Gildenkontext geladen.
    """
    token = CURRENT_GUILD_SLUG.set(LICHTLOOT_GUILD_SLUG)
    try:
        return iter_hordenbuff_railway_rows()
    finally:
        CURRENT_GUILD_SLUG.reset(token)


def sync_hordenbuff_schedule_to_nachtloot():
    if not LICHTBOT_QUEUE_TOKEN:
        print("Rend-Termin-Sync nach NachtLoot uebersprungen: LICHTBOT_QUEUE_TOKEN fehlt.")
        return 0

    source_rows = get_hordenbuff_schedule_rows()
    token = CURRENT_GUILD_SLUG.set(NACHTLOOT_GUILD_SLUG)
    try:
        target_rows = iter_hordenbuff_railway_rows()
        existing = {
            (str(row.get("datum") or ""), str(row.get("uhrzeit") or ""))
            for row in target_rows
            if normalize_buff(row.get("buff", "Rend")) == "Rend"
        }
        copied = 0
        seen = set()

        for row in source_rows:
            if normalize_buff(row.get("buff", "Rend")) != "Rend":
                continue

            key = (str(row.get("datum") or ""), str(row.get("uhrzeit") or ""))
            if not all(key) or key in existing or key in seen:
                continue
            seen.add(key)

            result = railway_post({
                "action": "guildCreateBuffTerm",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                "target": "hordenbuff",
                "buff": "Rend",
                "datum": key[0],
                "uhrzeit": key[1],
                "gilde": "Horde",
                "status": "offen",
                "note": "Rend-Termin automatisch aus LichtLoot übernommen"
            })
            if result.get("success"):
                copied += 1
                existing.add(key)
            else:
                print(f"Rend-Termin {key[0]} {key[1]} konnte nicht nach NachtLoot kopiert werden:", result)

        if copied:
            clear_hordenbuff_csv_cache()
            print(f"{copied} Rend-Termin(e) automatisch nach NachtLoot uebertragen.")
        return copied
    finally:
        CURRENT_GUILD_SLUG.reset(token)


def get_upcoming_horden_rend_entries(limit=None):
    rows = get_hordenbuff_schedule_rows()
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
    buffs = get_hordenbuff_schedule_rows()
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
            text += f"{get_buff_emoji('Rend')} {item_tag}, {item['datum']} um {item['uhrzeit']}\n"
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
    text += "📋 **Anmeldung ohne Befehle**\n"
    text += "Wähle unten im Menü, ob du Rend benötigst, helfen möchtest, "
    text += "jemanden direkt übernimmst oder deinen Eintrag entfernst.\n"

    return text


def build_hordenbuff_post_embed(rend, data):
    text = build_hordenbuff_text(rend, data)
    lines = text.splitlines()
    if lines and lines[0].startswith("🪓 **Horde-Rend"):
        lines = lines[1:]
    description = "\n".join(lines).strip()
    if len(description) > 4096:
        description = description[:4092].rstrip() + " …"

    embed = discord.Embed(
        title=f"{get_buff_emoji('Rend')} Hordenbuff-Anmeldung",
        description=description,
        color=0xF97316,
    )
    embed.set_footer(text="Alle Aktionen funktionieren über das Auswahlmenü unter diesem Embed.")
    return embed


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
            guide_embed = build_hordenbuff_post_embed(rend, data)
            signup_view = RendSignupView()
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
                    msg = await send_silent(channel, embed=guide_embed, view=signup_view)
                else:
                    await msg.edit(content="", embed=guide_embed, view=signup_view)

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


async def update_hordenbuff_posts_for_all_guilds(force=False):
    await asyncio.to_thread(sync_hordenbuff_schedule_to_nachtloot)
    updated_count = 0
    for guild_slug in configured_worldbuff_guild_slugs():
        token = CURRENT_GUILD_SLUG.set(guild_slug)
        try:
            updated_count += await update_hordenbuff_post(force=force)
        except Exception as e:
            print(f"Hordenbuff-Update fuer {guild_slug} fehlgeschlagen:", e)
        finally:
            CURRENT_GUILD_SLUG.reset(token)
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


async def hordenbuff_delete_core(charakter):
    rend = await asyncio.to_thread(get_next_horden_rend_safe)

    if not rend:
        return "⚠️ Es wurde kein kommender Rend-Termin gefunden."

    charakter = clean_hordenbuff_name(charakter)
    if not charakter:
        return "⚠️ Bitte gib den Charakter an, der entfernt werden soll."

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
    return f"✅ **{charakter}** wurde aus der Rend-Anmeldung entfernt."


async def delete_rend_entry(message, charakter):
    result_text = await hordenbuff_delete_core(charakter)
    await send_temp(message.channel, result_text)
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
        for guild_slug in configured_worldbuff_guild_slugs():
            token = CURRENT_GUILD_SLUG.set(guild_slug)
            try:
                await process_hordenbuff_reminders_for_current_guild()
            except Exception as e:
                print(f"Fehler im Hordenbuff-Reminder fuer {guild_slug}:", e)
            finally:
                CURRENT_GUILD_SLUG.reset(token)

        await asyncio.sleep(60)



DISCORD_CHANNEL_SYNC_INTERVAL_SECONDS = 900




async def sync_accessible_discord_channels():
    if not LICHTBOT_QUEUE_TOKEN:
        print("Discord-Channel-Sync uebersprungen: LICHTBOT_QUEUE_TOKEN fehlt.")
        return {"success": False, "error": "LICHTBOT_QUEUE_TOKEN fehlt."}

    await refresh_guild_registry()
    channels_by_guild = {}
    for guild in client.guilds:
        guild_slug = guild_slug_for_discord_server(guild, "")
        if not guild_slug:
            print(f"Discord-Channel-Sync: Server {guild.name} ({guild.id}) ist keiner LichtLoot-Gilde zugeordnet, uebersprungen.")
            continue

        member = guild.me or guild.get_member(client.user.id)
        if member is None:
            continue

        for channel in getattr(guild, "text_channels", []):
            permissions = channel.permissions_for(member)
            if not permissions.view_channel or not permissions.send_messages:
                continue
            channels_by_guild.setdefault(guild_slug, []).append({
                "id": str(channel.id),
                "name": channel.name,
                "type": "text",
                "category": channel.category.name if channel.category else "",
                "position": int(getattr(channel, "position", 0) or 0),
                "canSend": True,
                "discordGuildId": str(guild.id),
                "discordGuildName": guild.name,
            })

    total_saved = 0
    results = {}
    for guild_slug, channels in channels_by_guild.items():
        token = CURRENT_GUILD_SLUG.set(normalize_guild_slug(guild_slug))
        try:
            result = await asyncio.to_thread(lichtloot_post, {
                "action": "lichtbotSaveDiscordChannels",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                # Beide Discord-Bots schreiben in dieselbe Channel-Liste.
                # Deshalb nur erreichbare Channels ergaenzen/aktualisieren und
                # niemals die vom jeweils anderen Bot gefundenen Channels loeschen.
                "channels": channels
            })
            saved = int(result.get("saved", 0) or 0)
            total_saved += saved
            results[guild_slug] = saved
            print(f"Discord-Channel-Sync gespeichert: {saved} Channels fuer {guild_slug}.")
        finally:
            CURRENT_GUILD_SLUG.reset(token)

    return {"success": True, "saved": total_saved, "guilds": results}


async def discord_channel_sync_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            await sync_accessible_discord_channels()
        except Exception as e:
            print("Discord-Channel-Sync Fehler:", e)
        await asyncio.sleep(DISCORD_CHANNEL_SYNC_INTERVAL_SECONDS)






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


def normalize_raid_name(value):
    raw = str(value or "").strip().upper().replace("-", " ").replace("_", " ")
    aliases = {
        "ONYXIA": "ONY",
        "ONY": "ONY",
        "NAXXRAMAS": "NAXX",
        "NAXX": "NAXX",
        "MOLTEN CORE": "MC",
        "BLACKWING LAIR": "BWL",
        "ZUL GURUB": "ZG",
        "ZUL'GURUB": "ZG",
        "AHN QIRAJ 20": "AQ20",
        "AHN QIRAJ 40": "AQ40",
    }
    return aliases.get(raw, raw)

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




def build_worldbuff_backup_export_text(payload):
    days = str(payload.get("days") or "all").strip()
    count = str(payload.get("count") or "0").strip()
    label = "alle offenen Termine" if days == "all" else f"naechste {days} Tage"
    return "\n".join([
        "📄 **Worldbuff-Sicherung exportiert**",
        "",
        f"**Zeitraum:** {label}",
        f"**Termine:** {count}",
        "",
        "Die Excel-Datei enthält den aktuellen Worldbuff-Stand aus Railway."
    ])


def xlsx_col_name(index):
    name = ""
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name or "A"


def xlsx_xml_escape(value):
    return (
        str(value if value is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_xlsx_file(sheets):
    normalized_sheets = []
    for idx, sheet in enumerate(sheets or []):
        name = str(sheet.get("name") or f"Tabelle {idx + 1}").strip()[:31] or f"Tabelle {idx + 1}"
        name = re.sub(r"[\[\]\*:/\\?]", "-", name)
        rows = sheet.get("rows") if isinstance(sheet.get("rows"), list) else []
        normalized_sheets.append({"name": name, "rows": rows})
    if not normalized_sheets:
        normalized_sheets = [{"name": "Daten", "rows": [["Keine Daten"]]}]

    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
""" + "".join(
            f'  <Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>\n'
            for i in range(len(normalized_sheets))
        ) + "</Types>")
        zf.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""")
        zf.writestr("xl/workbook.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
""" + "".join(
            f'    <sheet name="{xlsx_xml_escape(sheet["name"])}" sheetId="{i + 1}" r:id="rId{i + 1}"/>\n'
            for i, sheet in enumerate(normalized_sheets)
        ) + "  </sheets>\n</workbook>")
        zf.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
""" + "".join(
            f'  <Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>\n'
            for i in range(len(normalized_sheets))
        ) + "</Relationships>")
        for sheet_index, sheet in enumerate(normalized_sheets, start=1):
            rows_xml = []
            for row_index, row in enumerate(sheet["rows"], start=1):
                values = row if isinstance(row, list) else [row]
                cells = []
                for col_index, value in enumerate(values, start=1):
                    ref = f"{xlsx_col_name(col_index)}{row_index}"
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{xlsx_xml_escape(value)}</t></is></c>')
                rows_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
            zf.writestr(f"xl/worksheets/sheet{sheet_index}.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
""" + "\n".join(rows_xml) + "\n  </sheetData>\n</worksheet>")
    out.seek(0)
    return out




async def post_worldbuff_backup_export_from_queue(payload):
    channel_id = await resolve_backup_channel_id(payload, "worldbuff")
    sheets = payload.get("sheets") if isinstance(payload.get("sheets"), list) else []
    if not channel_id:
        print("Worldbuff-Sicherung ohne ChannelId uebersprungen.")
        return
    if not sheets:
        print("Worldbuff-Sicherung ohne Tabelleninhalt uebersprungen.")
        return

    filename = str(payload.get("filename") or "worldbuff-sicherung.xlsx").strip()
    if not filename.lower().endswith(".xlsx"):
        filename = re.sub(r"\.[^.]+$", "", filename) + ".xlsx"
    safe_filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", filename).strip(".-") or "worldbuff-sicherung.xlsx"
    channel = await fetch_accessible_discord_channel(channel_id)
    if channel is None:
        raise RuntimeError(f"Worldbuff-Backup-Channel nicht erreichbar: {channel_id}")
    data = build_xlsx_file(sheets)
    file = discord.File(data, filename=safe_filename)
    await send_silent(channel, build_worldbuff_backup_export_text(payload), file=file)
    print(f"Worldbuff-Sicherung gepostet: {safe_filename} in {channel_id}")


def build_worldbuff_replacement_embed(payload, channel, worldbuff_channel_id=""):
    buff = str(payload.get("buff") or "Worldbuff").strip() or "Worldbuff"
    datum = str(payload.get("datum") or payload.get("date") or "").strip()
    uhrzeit = str(payload.get("uhrzeit") or payload.get("time") or "").strip()
    gilde = str(payload.get("gilde") or payload.get("guild") or "").strip()
    charakter = str(payload.get("charakter") or payload.get("caster") or "").strip()
    note = str(payload.get("note") or "").strip()
    buff_emoji = get_buff_emoji(buff)
    guild_id = str(getattr(getattr(channel, "guild", None), "id", "") or "")
    channel_id = clean_channel_id_value(worldbuff_channel_id) or str(getattr(channel, "id", "") or "")
    channel_url = f"https://discord.com/channels/{guild_id}/{channel_id}" if guild_id and channel_id else ""
    embed = discord.Embed(
        title="🔔 Ersatz für Worldbuff gesucht",
        description=f"Für **{buff}** wird ein neuer Werfer gesucht.",
        color=0xF59E0B,
        url=channel_url or None,
    )
    embed.add_field(name="🌍 Worldbuff", value=f"{buff_emoji} **{buff}**", inline=False)
    embed.add_field(name="📅 Datum", value=datum or "-", inline=True)
    embed.add_field(name="⏰ Uhrzeit", value=f"{uhrzeit} Uhr" if uhrzeit else "-", inline=True)
    if gilde:
        embed.add_field(name="📣 Worldbuff-Gilde", value=gilde, inline=False)
    if charakter:
        embed.add_field(name="🧙 Bisheriger Werfer", value=charakter, inline=False)
    if note:
        embed.add_field(name="📝 Hinweis", value=note[:1024], inline=False)
    if channel_url:
        embed.add_field(name="🔗 Termin übernehmen", value=f"[Direkt zum WB-Channel]({channel_url})", inline=False)
    icon_url = getattr(buff_emoji, "url", None)
    if icon_url:
        embed.set_thumbnail(url=str(icon_url))
    else:
        emoji_match = re.match(r"<a?:[^:]+:(\d+)>", str(buff_emoji))
        if emoji_match:
            embed.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_match.group(1)}.png?size=128&quality=lossless")
    embed.set_footer(text="Automatische Nachricht des Lichtbuff-Bots")
    return embed


async def post_worldbuff_replacement_from_queue(payload):
    sent = 0
    worldbuff_channel_id = clean_channel_id_value(
        payload.get("worldbuffChannelId") or get_configured_worldbuff_channel_id()
    )
    for channel_id in worldbuff_replacement_channel_ids(payload.get("target"), payload):
        try:
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
            await send_silent(
                channel,
                embed=build_worldbuff_replacement_embed(payload, channel, worldbuff_channel_id)
            )
            sent += 1
        except Exception as error:
            print(f"Worldbuff-Ersatzsuche konnte nicht in Channel {channel_id} gepostet werden: {error}")
    if not sent:
        raise RuntimeError(f"Worldbuff-Ersatzsuche konnte in keinen Zielchannel gepostet werden: {payload}")
    print(f"Worldbuff-Ersatzsuche gepostet: {sent} Channel(s).")


def build_boss_token_notice_text(payload):
    raid = normalize_raid_name(payload.get("raid") or payload.get("raidName") or "")
    raid_label = raid or str(payload.get("raidName") or "Raid").strip() or "Raid"
    player = str(payload.get("player") or payload.get("charakter") or "Spieler").strip() or "Spieler"
    server = str(payload.get("server") or "").strip()
    token = str(payload.get("token") or "").strip()
    if not token:
        if raid == "BWL":
            token = "Kopf von Nefarian"
        elif raid == "ONY":
            token = "Kopf von Onyxia"
        elif raid == "ZG":
            token = "Herz von Hakkar"
        else:
            token = "Boss-Item"
    player_label = f"{player}-{server}" if server else player
    raid_date = str(payload.get("raidDate") or "").strip()
    raid_time = str(payload.get("raidTime") or "").strip()
    lines = [
        "📣 **Worldbuff-Hinweis**",
        "",
        f"**{player_label}** hat den **{token}** erhalten.",
        f"**Raid:** {raid_label}"
    ]
    if raid_date or raid_time:
        lines.append(f"**Termin:** {raid_date}" + (f" · {raid_time} Uhr" if raid_time else ""))
    lines.extend(["", "Bitte für die Worldbuff-Planung beachten."])
    return "\n".join(lines)


async def post_boss_token_notice_from_queue(payload):
    channel_id = str(payload.get("channelId") or POST_CHANNEL_ID).strip()
    if not channel_id:
        print("Bosskopf-/Herz-Meldung ohne ChannelId uebersprungen.")
        return
    channel = client.get_channel(int(channel_id))
    if channel is None:
        channel = await client.fetch_channel(int(channel_id))
    await send_silent(channel, build_boss_token_notice_text(payload))
    print(f"Bosskopf-/Herz-Meldung gepostet in {channel_id}: {payload.get('player')} {payload.get('token')}")


def normalized_discord_name(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().casefold())


def member_matches_configured_names(member, configured_names):
    candidates = {
        normalized_discord_name(getattr(member, "name", "")),
        normalized_discord_name(getattr(member, "display_name", "")),
        normalized_discord_name(getattr(member, "global_name", "")),
    }
    candidates.discard("")
    return any(wanted == candidate or wanted in candidate for wanted in configured_names for candidate in candidates)


def render_notification_template(template, values):
    text = str(template or "")
    for key, value in values.items():
        text = text.replace("{" + str(key) + "}", str(value or ""))
    return text.strip()


async def post_player_login_approval_notice(payload):
    guild_slug = normalize_guild_slug(payload.get("guildSlug") or payload.get("guild") or current_guild_slug())
    guild_name = str(payload.get("guildName") or (GUILD_REGISTRY.get(guild_slug) or {}).get("name") or guild_slug).strip()
    registry_entry = GUILD_REGISTRY.get(guild_slug) or {}
    discord_guild_id = str(registry_entry.get("discordGuildId") or "").strip()
    discord_guild = client.get_guild(int(discord_guild_id)) if discord_guild_id.isdigit() else None
    if discord_guild is None:
        raise RuntimeError(f"Für {guild_slug} ist keine erreichbare Discord-Server-ID registriert.")

    configured_role_ids = {
        int(str(role_id)) for role_id in (payload.get("notificationRoleIds") or [])
        if str(role_id).isdigit()
    }
    configured_names = {
        normalized_discord_name(name) for name in (payload.get("notificationNames") or [])
        if str(name or "").strip()
    }
    wanted_roles = {"offiziere"}
    roles = [
        role for role in getattr(discord_guild, "roles", [])
        if (configured_role_ids and int(getattr(role, "id", 0) or 0) in configured_role_ids)
        or (not configured_role_ids and normalized_discord_name(getattr(role, "name", "")) in wanted_roles)
    ]
    if not roles and not configured_names:
        raise RuntimeError(f'Die konfigurierte Benachrichtigungsrolle wurde auf {discord_guild.name} nicht gefunden.')

    character = str(payload.get("character") or "Unbekannt").strip()
    server = str(payload.get("server") or "").strip()
    class_name = str(payload.get("className") or "").strip()
    character_label = f"{character}-{server}" if server else character
    lines = [
        "🔐 **Neuer SpielerLogin wartet auf Freigabe**",
        "",
        f"**Gilde:** {guild_name}",
        f"**Charakter:** {character_label}",
    ]
    if class_name:
        lines.append(f"**Klasse:** {class_name}")
    approval_url = f"{LICHTLOOT_URL.rstrip('/')}/gildenleitung.html?" + urllib.parse.urlencode({
        "guild": guild_slug,
        "panel": "spielerlogins",
        "player": character,
    })
    lines.extend([
        "",
        "Bitte den neuen SpielerLogin in der Gildenleitung prüfen und freigeben.",
        f"🔗 **[Direkt zur Spielerfreigabe]({approval_url})**"
    ])
    default_message = "\n".join(line for line in lines if line is not None)
    message = render_notification_template(payload.get("messageTemplate"), {
        "gilde": guild_name, "charakter": character, "server": server,
        "klasse": class_name, "link": approval_url
    }) or default_message
    role_ids = {int(role.id) for role in roles}
    recipients = [
        member for member in getattr(discord_guild, "members", [])
        if not getattr(member, "bot", False)
        and (any(int(getattr(role, "id", 0) or 0) in role_ids for role in getattr(member, "roles", []))
             or member_matches_configured_names(member, configured_names))
    ]
    recipients = list({int(member.id): member for member in recipients}.values())
    if not recipients:
        try:
            fetched_members = [member async for member in discord_guild.fetch_members(limit=None)]
            recipients = [
                member for member in fetched_members
                if not getattr(member, "bot", False)
                and (any(int(getattr(role, "id", 0) or 0) in role_ids for role in getattr(member, "roles", []))
                     or member_matches_configured_names(member, configured_names))
            ]
            recipients = list({int(member.id): member for member in recipients}.values())
        except Exception as error:
            raise RuntimeError(f'Discord-Mitglieder für die Rolle "Offiziere" konnten nicht geladen werden: {error}') from error
    if not recipients:
        raise RuntimeError(f'Keine Discord-Mitglieder mit der Rolle "Offiziere" auf {discord_guild.name} gefunden.')
    delivered = 0
    failed = []
    for member in recipients:
        try:
            await member.send(message, silent=True)
            delivered += 1
        except Exception as error:
            failed.append(f"{member} ({error})")
    if delivered == 0:
        raise RuntimeError('Direktnachricht an die Rolle "Offiziere" konnte niemandem zugestellt werden.')
    print(f"SpielerLogin-Freigabehinweis fuer {guild_slug} per DM an {delivered} Empfaenger gesendet; Fehler: {len(failed)}.")






def configured_discord_link(data):
    source = data or {}
    raw_url = str(source.get("linkUrl") or "").strip()
    links = []
    if raw_url.startswith("["):
        try:
            parsed = json.loads(raw_url)
            if isinstance(parsed, list):
                links = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            links = []
    if not links:
        links = [{"url": raw_url, "text": source.get("linkText"), "icon": source.get("linkIcon")}]
    formatted = []
    for item in links[:10]:
        url = str((item or {}).get("url") or "").strip()
        if not re.match(r"^https?://", url, re.I):
            continue
        icon = str((item or {}).get("icon") or "").strip()
        text = str((item or {}).get("text") or "").strip()
        label = " ".join(part for part in (icon, text) if part).strip() or "Link"
        label = label.replace("[", "").replace("]", "")[:80] or "Link"
        formatted.append(f"[{label}]({url})")
    return "\n".join(formatted)


































def normalize_emoji_name(value):
    text = str(value or "").strip().lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9_]+", "", text)












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














































































































































































# Kompatibilität für alte Debug-Befehle/Funktionsnamen












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
    pattern = re.compile(r"https?://(?:[a-z0-9-]+\.)*warcraftlogs\.com/reports/[A-Za-z0-9]+[^\s<>)\]]*", re.IGNORECASE)

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


def collect_message_text(message):
    parts = []
    if getattr(message, "content", None):
        parts.append(str(message.content))
    for embed in getattr(message, "embeds", []) or []:
        if getattr(embed, "title", None):
            parts.append(str(embed.title))
        if getattr(embed, "description", None):
            parts.append(str(embed.description))
        for field in getattr(embed, "fields", []) or []:
            parts.append(str(getattr(field, "name", "") or ""))
            parts.append(str(getattr(field, "value", "") or ""))
    return "\n".join(part for part in parts if part)


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

            guild_token = CURRENT_GUILD_SLUG.set(
                normalize_guild_slug(CHANNEL_GUILD_SLUGS.get(int(channel_id)) or guild_slug_for_message(msg))
            )
            try:
                saved = await handle_log_analysis_message(msg, announce=False)
            finally:
                CURRENT_GUILD_SLUG.reset(guild_token)
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
    owned_types = {
        "worldbuff_update",
        "hordenbuff_update",
        "worldbuff_player_change_notice",
        "worldbuff_replacement",
        "boss_token_notice",
        "worldbuff_backup_export",
        "log_analysis_post",
    }
    if update_type not in owned_types:
        print(f"{update_type or '?'} ignoriert: dieser Auftrag gehoert nicht dem Lichtbuff-Hauptbot.")
        return "not_owned"

    row_number = item.get("rowNumber")
    queue_guild_slug = normalize_guild_slug(
        item.get("guild") or item.get("guildSlug") or current_guild_slug()
    )
    raw_payload = item.get("payload") or {}
    try:
        payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload or "{}")
    except Exception:
        payload = {}
    payload.setdefault("guildSlug", queue_guild_slug)

    queue_payload_key = (
        raw_payload if isinstance(raw_payload, str)
        else json.dumps(raw_payload, sort_keys=True, default=str)
    )
    queue_key = f"{queue_guild_slug}:{update_type}:{row_number or item.get('id') or queue_payload_key}"
    now = time.time()
    for old_key, old_time in list(LICHTLOOT_QUEUE_RECENTLY_DONE.items()):
        if now - old_time > 300:
            LICHTLOOT_QUEUE_RECENTLY_DONE.pop(old_key, None)
    if queue_key in LICHTLOOT_QUEUE_IN_PROGRESS or queue_key in LICHTLOOT_QUEUE_RECENTLY_DONE:
        return "duplicate"

    LICHTLOOT_QUEUE_IN_PROGRESS.add(queue_key)
    try:
        if update_type == "worldbuff_update" and payload.get("deleted"):
            removed = await asyncio.to_thread(remove_deleted_worldbuff_from_all_caches, payload)
            print(f"Worldbuff-Loeschung verarbeitet, {removed} Cache-Eintraege entfernt.")

        if update_type == "log_analysis_post":
            await post_log_analysis_from_queue(payload)
        elif update_type == "worldbuff_backup_export":
            await post_worldbuff_backup_export_from_queue(payload)
        elif update_type == "worldbuff_replacement":
            await post_worldbuff_replacement_from_queue(payload)
        elif update_type == "boss_token_notice":
            await post_boss_token_notice_from_queue(payload)
        elif update_type == "worldbuff_player_change_notice":
            await send_worldbuff_player_change_notice(payload)
        elif update_type == "worldbuff_update":
            clear_worldbuff_csv_cache()
            await update_worldbuff_overview_from_all_guilds()
        elif update_type == "hordenbuff_update":
            await update_hordenbuff_posts_for_all_guilds(force=True)

        if resolve_old_queue and row_number:
            await asyncio.to_thread(lichtloot_post, {
                "action": "lichtbotResolveQueue",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                "rowNumber": row_number,
            })
        LICHTLOOT_QUEUE_RECENTLY_DONE[queue_key] = time.time()
        return True
    finally:
        LICHTLOOT_QUEUE_IN_PROGRESS.discard(queue_key)



async def send_worldbuff_player_change_notice(payload):
    recipient_name = str(payload.get("recipient") or "").strip().lower()
    targets = list(payload.get("targets") or [])
    if recipient_name:
        targets.append({"type": "name", "value": recipient_name})
    character = str(payload.get("character") or "Unbekannter Charakter").strip()
    action = str(payload.get("action") or "").strip().lower()
    action_label = str(payload.get("actionLabel") or "geändert").strip()
    reason = str(payload.get("reason") or "-").strip()
    old_slot = str(payload.get("from") or "-").strip()
    new_slot = str(payload.get("to") or "").strip()
    uses_new_appointment = action in {"moved", "changed"} and bool(payload.get("newDate") or payload.get("newTime"))
    buff = normalize_buff((payload.get("newBuff") if uses_new_appointment else payload.get("buff")) or old_slot.split(" · ", 1)[0])
    guild_name = str(payload.get("guildName") or payload.get("guildSlug") or "-").strip()
    worldbuff_guild = str((payload.get("newWorldbuffGuild") if uses_new_appointment else payload.get("worldbuffGuild")) or "").strip()
    date_text = str((payload.get("newDate") if uses_new_appointment else payload.get("date")) or "").strip()
    time_text = str((payload.get("newTime") if uses_new_appointment else payload.get("time")) or "").strip()
    try:
        date_display = datetime.strptime(date_text[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        date_display = date_text or "-"
    time_display = time_text[:5] if time_text else "-"
    buff_emoji = get_buff_emoji(buff)

    def apply_buff_thumbnail(embed):
        icon_url = getattr(buff_emoji, "url", None)
        if icon_url:
            embed.set_thumbnail(url=str(icon_url))
            return
        emoji_match = re.match(r"<a?:[^:]+:(\d+)>", str(buff_emoji))
        if emoji_match:
            embed.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_match.group(1)}.png?size=128&quality=lossless")

    def add_appointment_fields(embed):
        embed.add_field(name="🏰 Gilde", value=guild_name or "-", inline=True)
        embed.add_field(name="👤 Charakter", value=character, inline=True)
        embed.add_field(name="🌍 Worldbuff", value=f"{buff_emoji} **{buff or 'Worldbuff'}**", inline=False)
        embed.add_field(name="📅 Datum", value=date_display, inline=True)
        embed.add_field(name="⏰ Uhrzeit", value=f"{time_display} Uhr" if time_display != "-" else "-", inline=True)
        if worldbuff_guild and normalized_discord_name(worldbuff_guild) != normalized_discord_name(guild_name):
            embed.add_field(name="📣 Worldbuff-Gilde", value=worldbuff_guild, inline=False)
        apply_buff_thumbnail(embed)

    # Persönliche Bestätigung an den Spieler, der den Termin übernommen hat.
    player_sent = False
    player_user_id = str(payload.get("playerDiscordUserId") or "").strip()
    if player_user_id.isdigit():
        try:
            player_user = client.get_user(int(player_user_id)) or await client.fetch_user(int(player_user_id))
            player_titles = {
                "registered": "✅ Du bist für einen Worldbuff eingetragen",
                "changed": "🔄 Dein Worldbuff-Termin wurde geändert",
                "moved": "🔄 Dein Worldbuff-Termin wurde verschoben",
                "cancelled": "❌ Dein Worldbuff-Termin wurde abgesagt",
                "reminder": "🔔 Erinnerung an deinen Worldbuff-Termin",
            }
            player_descriptions = {
                "registered": f"Dein Termin für **{buff or 'den Worldbuff'}** wurde erfolgreich gespeichert.",
                "changed": f"Die Gildenleitung hat deinen Termin für **{buff or 'den Worldbuff'}** geändert.",
                "moved": f"Dein Termin für **{buff or 'den Worldbuff'}** wurde verschoben.",
                "cancelled": f"Dein Termin für **{buff or 'den Worldbuff'}** wurde entfernt.",
                "reminder": f"Zur Erinnerung: Du bist für **{buff or 'diesen Worldbuff'}** als Werfer eingetragen.",
            }
            player_embed = discord.Embed(
                title=player_titles.get(action, "🌍 Dein Worldbuff-Termin wurde aktualisiert"),
                description=player_descriptions.get(action, f"Dein Termin für **{buff or 'den Worldbuff'}** wurde aktualisiert."),
                color=0x22C55E if action == "registered" else (0xEF4444 if action == "cancelled" else 0xF59E0B),
            )
            add_appointment_fields(player_embed)
            player_embed.set_footer(text="Automatische Nachricht des Lichtbuff-Bots")
            await player_user.send(embed=player_embed)
            player_sent = True
            print(f"Worldbuff-Bestaetigung per DM an {player_user} gesendet.")
        except Exception as error:
            print(f"Worldbuff-Bestaetigung an Spieler fehlgeschlagen: {error}")

    if payload.get("notifyStaff") is False:
        return 1 if player_sent else 0

    template_message = render_notification_template(payload.get("messageTemplate"), {
        "charakter": character, "aktion": action_label, "termin": old_slot,
        "neuer_termin": new_slot, "grund": reason
    })
    staff_embed = discord.Embed(
        title="🌍 Neue Worldbuff-Anmeldung" if action == "registered" else f"🌍 Worldbuff-Termin {action_label}",
        description=template_message or (
            f"**{character}** hat sich für **{buff or 'einen Worldbuff'}** eingetragen."
            if action == "registered"
            else f"**{character}** hat einen Worldbuff-Termin **{action_label}**."
        ),
        color=0x3B82F6 if action == "registered" else (0xEF4444 if action == "cancelled" else 0xF59E0B),
    )
    add_appointment_fields(staff_embed)
    if new_slot:
        staff_embed.add_field(name="➡️ Neuer Termin", value=new_slot, inline=False)
    if reason and reason != "-":
        staff_embed.add_field(name="📝 Grund", value=reason[:1024], inline=False)
    staff_embed.set_footer(text="Automatische Nachricht des Lichtbuff-Bots")

    wanted_names = {
        normalized_discord_name(target.get("value") or target.get("name"))
        for target in targets if str(target.get("type") or "name").lower() == "name"
    }
    wanted_role_ids = {
        str(target.get("value") or target.get("id") or "").strip()
        for target in targets if str(target.get("type") or "").lower() == "role"
    }
    sent = set()
    guild_slug = normalize_guild_slug(payload.get("guildSlug") or payload.get("guild") or current_guild_slug())
    registry_entry = GUILD_REGISTRY.get(guild_slug) or {}
    discord_guild_id = str(registry_entry.get("discordGuildId") or "").strip()
    selected_guild = client.get_guild(int(discord_guild_id)) if discord_guild_id.isdigit() else None
    if not selected_guild and (wanted_names or wanted_role_ids):
        raise RuntimeError(f"Für {guild_slug} ist keine erreichbare Discord-Server-ID registriert.")
    guilds = [selected_guild] if selected_guild else []
    for guild in guilds:
        for member in guild.members:
            member_names = {
                normalized_discord_name(getattr(member, "name", "")),
                normalized_discord_name(getattr(member, "display_name", "")),
                normalized_discord_name(getattr(member, "global_name", "")),
            }
            member_roles = {str(role.id) for role in getattr(member, "roles", [])}
            if not (wanted_names.intersection(member_names) or wanted_role_ids.intersection(member_roles)):
                continue
            if member.id in sent or member.bot:
                continue
            try:
                await member.send(embed=staff_embed)
                sent.add(member.id)
                print(f"Worldbuff-Aenderung per DM an {member} gesendet.")
            except Exception as error:
                print(f"Worldbuff-DM an {member} fehlgeschlagen: {error}")
    if not sent:
        print("Kein Discord-Empfaenger fuer die Worldbuff-Aenderung gefunden.")
    return len(sent)


async def lichtloot_queue_loop():
    await client.wait_until_ready()

    if not LICHTBOT_QUEUE_TOKEN:
        print("LichtLoot-Queue deaktiviert: LICHTBOT_QUEUE_TOKEN fehlt.")
        return

    await refresh_guild_registry()
    print(f"LichtLoot-Queue aktiv: pruefe alle {LICHTLOOT_QUEUE_CHECK_SECONDS} Sekunden auf Updates.")

    while not client.is_closed():
        try:
            result = await asyncio.to_thread(lichtloot_get, {
                "action": "lichtbotGetQueueAllGuilds",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                "limit": 500,
                "types": "worldbuff_update,hordenbuff_update,worldbuff_player_change_notice,worldbuff_replacement,boss_token_notice,worldbuff_backup_export",
                "t": int(time.time())
            })

            if result.get("success"):
                items = result.get("items", [])
                if items:
                    update_types = ", ".join(str(item.get("type") or "?") for item in items)
                    print(f"LichtLoot-Queue: {len(items)} Update(s) gefunden: {update_types}")

                for item in items:
                    guild_slug = normalize_guild_slug(item.get("guild") or item.get("guildSlug") or LICHTLOOT_GUILD_SLUG)
                    token = CURRENT_GUILD_SLUG.set(guild_slug)
                    try:
                        await handle_lichtloot_queue_item(item)
                    except Exception as item_error:
                        print(f"Fehler beim Verarbeiten eines LichtLoot-Queue-Eintrags fuer {guild_slug}:", item_error)
                        if str(item.get("type") or "").strip() == "player_login_approval_notice" and item.get("rowNumber"):
                            await asyncio.to_thread(lichtloot_post, {
                                "action": "lichtbotResolveQueue",
                                "queueToken": LICHTBOT_QUEUE_TOKEN,
                                "rowNumber": item.get("rowNumber")
                            })
                            print(f"Nicht zustellbaren alten SpielerLogin-Hinweis fuer {guild_slug} aus der Queue entfernt.")
                    finally:
                        CURRENT_GUILD_SLUG.reset(token)
            else:
                print("LichtLoot-Queue Antwort:", result)

            railway_result = await asyncio.to_thread(railway_get, {
                "action": "lichtbotGetQueueAllGuilds",
                "queueToken": LICHTBOT_QUEUE_TOKEN,
                "limit": 500,
                "types": "worldbuff_update,hordenbuff_update,worldbuff_player_change_notice,worldbuff_replacement,boss_token_notice,worldbuff_backup_export",
                "t": int(time.time())
            })

            if railway_result.get("success"):
                railway_items = railway_result.get("items", [])
                if railway_items:
                    update_types = ", ".join(str(item.get("type") or "?") for item in railway_items)
                    print(f"Railway-Queue: {len(railway_items)} Update(s) gefunden: {update_types}")

                for item in railway_items:
                    guild_slug = normalize_guild_slug(item.get("guild") or item.get("guildSlug") or LICHTLOOT_GUILD_SLUG)
                    token = CURRENT_GUILD_SLUG.set(guild_slug)
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
                        print(f"Fehler beim Verarbeiten eines Railway-Queue-Eintrags fuer {guild_slug}:", item_error)
                        if str(item.get("type") or "").strip() == "player_login_approval_notice" and item.get("rowNumber"):
                            await asyncio.to_thread(railway_post, {
                                "action": "lichtbotResolveQueue",
                                "queueToken": LICHTBOT_QUEUE_TOKEN,
                                "rowNumber": item.get("rowNumber")
                            })
                            print(f"Nicht zustellbaren alten Railway-SpielerLogin-Hinweis fuer {guild_slug} aus der Queue entfernt.")
                    finally:
                        CURRENT_GUILD_SLUG.reset(token)
            else:
                print("Railway-Queue Antwort:", railway_result)

        except Exception as e:
            print("Fehler im LichtLoot-Queue-Loop:", e)

        await asyncio.sleep(LICHTLOOT_QUEUE_CHECK_SECONDS)




































































def truncate_discord_text(value, limit):
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + "…"








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













































































































































async def handle_ticker_update(message):
    if not is_ticker_channel(message.channel.id) and not is_wbposter_bot_message(message):
        return

    message_text = discord_message_search_text(message)
    new_buffs = [buff for buff in parse_ticker_message(message_text) if not is_deleted_worldbuff(buff)]

    if not new_buffs:
        return

    # Eine WBPoster-Nachricht enthaelt immer den vollstaendigen aktuellen
    # Stand. Alte Zeitstaende duerfen nicht mit dem neuen Stand verschmelzen.
    if is_wbposter_bot_message(message):
        save_json(WB_POSTER_CACHE_FILE, new_buffs)
    else:
        poster_rows = load_json(WB_POSTER_CACHE_FILE, [])
        merge_buffs_into_data(poster_rows, new_buffs)
        save_json(WB_POSTER_CACHE_FILE, poster_rows)

    cached_rows = load_json(worldbuff_file(), [])
    railway_rows = await asyncio.to_thread(import_buffs_aus_sheet)
    combined_rows = list(railway_rows)
    merge_ticker_buffs_preserving_railway(combined_rows, cached_rows)
    added = merge_ticker_buffs_preserving_railway(combined_rows, new_buffs)

    ticker_rows = [
        buff for buff in combined_rows
        if not is_own_worldbuff(buff)
    ]

    save_json(worldbuff_file(), ticker_rows)
    # Den WBPoster-Post unverändert und vollständig an Railway übergeben.
    database_sync_result = await asyncio.to_thread(sync_worldbuff_ticker_cache_to_sheet, new_buffs)
    database_sync_ok = bool(isinstance(database_sync_result, dict) and database_sync_result.get("success"))

    print(
        f"{len(new_buffs)} Worldbuffs aus Ticker übernommen oder geprüft, "
        f"{added} neu gespeichert, {len(ticker_rows)} Ticker-Termine im Cache."
    )

    await update_worldbuff_overview_from_all_guilds(force_repost=True)

    if any(normalize_buff(b["buff"]) == "Rend" for b in new_buffs):
        await update_hordenbuff_posts_for_all_guilds(force=True)

    if (
        DELETE_WORLDBUFF_POSTER_SOURCE_MESSAGES
        and database_sync_ok
        and not is_own_discord_message(message)
        and is_wbposter_bot_message(message)
    ):
        try:
            await message.delete()
            print(f"Worldbuff-Poster-Nachricht {message.id} aus Channel {message.channel.id} gelöscht.")
        except discord.Forbidden:
            print(f"Worldbuff-Poster-Nachricht {message.id} konnte nicht gelöscht werden: Bot-Rechte fehlen.")
        except discord.NotFound:
            pass
        except Exception as e:
            print(f"Worldbuff-Poster-Nachricht {message.id} konnte nicht gelöscht werden: {e}")
    elif not is_own_discord_message(message):
        print(
            f"Worldbuff-Poster-Quelle {message.id} aus Channel {message.channel.id} gelesen und behalten."
        )


def set_interaction_guild_context(interaction):
    guild_slug = guild_slug_for_discord_server(interaction.guild, "")
    if not guild_slug:
        raise RuntimeError("Dieser Discord-Server ist keiner LichtLoot-Gilde zugeordnet.")
    return CURRENT_GUILD_SLUG.set(guild_slug)


worldbuff_commands = app_commands.Group(
    name="worldbuff",
    description="Worldbuff-Termine und die Worldbuff-Übersicht verwalten",
)


@worldbuff_commands.command(name="aktualisieren", description="Aktualisiert die Worldbuff-Übersicht im festgelegten Channel")
async def slash_worldbuff_update(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    token = None
    try:
        token = set_interaction_guild_context(interaction)
        count = await asyncio.wait_for(
            update_worldbuff_post(sync_ticker=True, force_repost=False),
            timeout=60,
        )
        if count:
            channel_id = get_configured_worldbuff_channel_id()
            await interaction.followup.send(
                f"✅ Worldbuff-Liste aktualisiert. Ziel: <#{channel_id}>",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "⚠️ Worldbuff-Liste wurde nicht aktualisiert. Bitte Worldbuff-Channel und Termine prüfen.",
                ephemeral=True,
            )
    except Exception as error:
        await interaction.followup.send(f"⚠️ Worldbuff-Update fehlgeschlagen: {error}", ephemeral=True)
    finally:
        if token is not None:
            CURRENT_GUILD_SLUG.reset(token)


@worldbuff_commands.command(name="termin", description="Trägt einen neuen Worldbuff-Termin in LichtLoot ein")
@app_commands.describe(
    datum="Datum im Format JJJJ-MM-TT",
    uhrzeit="Uhrzeit im Format HH:MM",
    buff="Worldbuff für diesen Termin",
    charakter="Optional: Charakter, der den Buff stellt",
    notiz="Optionale Notiz zum Termin",
)
@app_commands.choices(buff=[
    app_commands.Choice(name="Hakkar", value="Hakkar"),
    app_commands.Choice(name="Onyxia", value="Ony"),
    app_commands.Choice(name="Nefarian", value="Nef"),
])
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_worldbuff_term(
    interaction: discord.Interaction,
    datum: str,
    uhrzeit: str,
    buff: app_commands.Choice[str],
    charakter: str = "",
    notiz: str = "",
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    token = None
    try:
        token = set_interaction_guild_context(interaction)
        try:
            parsed_date = datetime.strptime(datum.strip(), "%Y-%m-%d")
            parsed_time = datetime.strptime(uhrzeit.strip(), "%H:%M")
        except ValueError:
            await interaction.followup.send(
                "⚠️ Bitte Datum als `JJJJ-MM-TT` und Uhrzeit als `HH:MM` eingeben.",
                ephemeral=True,
            )
            return

        guild_data = GUILD_REGISTRY.get(current_guild_slug()) or {}
        result = await asyncio.to_thread(lichtloot_post, {
            "action": "lichtbotCreateWorldbuffTerm",
            "queueToken": LICHTBOT_QUEUE_TOKEN,
            "target": "worldbuff",
            "datum": parsed_date.strftime("%Y-%m-%d"),
            "uhrzeit": parsed_time.strftime("%H:%M"),
            "buff": buff.value,
            "gilde": str(guild_data.get("name") or current_guild_slug()),
            "charakter": charakter.strip(),
            "discordName": interaction.user.display_name,
            "status": "bestätigt" if charakter.strip() else "offen",
            "note": notiz.strip(),
        })
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "LichtLoot hat den Termin nicht gespeichert.")

        await update_worldbuff_post(sync_ticker=False, force_repost=False)
        await interaction.followup.send(
            f"✅ {buff.value} am {parsed_date.strftime('%d.%m.%Y')} um {parsed_time.strftime('%H:%M')} wurde in LichtLoot gespeichert.",
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(f"⚠️ Worldbuff-Termin konnte nicht gespeichert werden: {error}", ephemeral=True)
    finally:
        if token is not None:
            CURRENT_GUILD_SLUG.reset(token)


@slash_worldbuff_term.error
async def slash_worldbuff_term_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        text = "⚠️ Du benötigst die Discord-Berechtigung ‚Server verwalten‘, um Termine anzulegen."
    else:
        text = f"⚠️ Worldbuff-Termin konnte nicht gestartet werden: {error}"
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


command_tree.add_command(worldbuff_commands)


@command_tree.command(name="hordenbuff", description="Aktualisiert den Hordenbuff-/Rend-Anmelder")
async def slash_hordenbuff_update(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    token = None
    try:
        token = set_interaction_guild_context(interaction)
        count = await asyncio.wait_for(update_hordenbuff_post(force=True), timeout=45)
        if count:
            await interaction.followup.send(
                f"✅ Hordenbuff-Anmelder aktualisiert. Posts: {count}",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "⚠️ Hordenbuff wurde nicht aktualisiert. Bitte Hordenbuff-Channel und kommenden Rend-Termin prüfen.",
                ephemeral=True,
            )
    except Exception as error:
        await interaction.followup.send(f"⚠️ Hordenbuff-Update fehlgeschlagen: {error}", ephemeral=True)
    finally:
        if token is not None:
            CURRENT_GUILD_SLUG.reset(token)




@client.event
async def on_ready():
    print(f"Bot online als {client.user}")
    await refresh_guild_registry()
    await sync_discord_roles_to_lichtloot()
    if not hasattr(client, "slash_commands_synced"):
        client.slash_commands_synced = True
        for discord_guild in client.guilds:
            try:
                command_tree.copy_global_to(guild=discord_guild)
                synced = await command_tree.sync(guild=discord_guild)
                print(f"Slash-Befehle fuer {discord_guild.name} synchronisiert: {len(synced)}")
            except Exception as error:
                print(f"Slash-Befehle fuer {discord_guild.name} konnten nicht synchronisiert werden: {error}")
    print(f"Überwache Ticker-Channels: {sorted(TICKER_CHANNEL_IDS)}")
    print("Postet Worldbuff-Uebersichten in den gildenabhaengig gespeicherten Worldbuff-Channel.")
    print(f"Hordenbuff-Channels: {sorted(HORDENBUFF_CHANNEL_IDS)}")
    print(f"Loganalyse-Channels: {sorted(LOG_ANALYSIS_CHANNEL_IDS)}")
    print("Version 4.9.9 gestartet: Worldbuff-Termine kommen aus der Gildenleitung.")

    if not hasattr(client, "worldbuff_picker_view_registered"):
        client.worldbuff_picker_view_registered = True
        client.add_view(WorldbuffBuffPickerView())

    if not hasattr(client, "hordenbuff_action_view_registered"):
        client.hordenbuff_action_view_registered = True
        client.add_view(RendSignupView())

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

    if not hasattr(client, "wbposter_database_sync_started"):
        client.wbposter_database_sync_started = True
        client.loop.create_task(wbposter_database_sync_loop())

    if not hasattr(client, "hordenbuff_startup_task_started"):
        client.hordenbuff_startup_task_started = True
        client.loop.create_task(update_hordenbuff_posts_for_all_guilds(force=True))

    if not hasattr(client, "log_analysis_history_sync_started"):
        client.log_analysis_history_sync_started = True
        client.loop.create_task(sync_recent_log_analyses())

@client.event
async def on_message_edit(before, after):
    if after.author == client.user:
        return

    guild_slug = guild_slug_for_message(after)
    if not guild_slug:
        return

    token = CURRENT_GUILD_SLUG.set(guild_slug)
    try:
        await handle_log_analysis_message(after)
        await handle_ticker_update(after)
    finally:
        CURRENT_GUILD_SLUG.reset(token)


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    guild_slug = guild_slug_for_message(message)
    if not guild_slug:
        if getattr(message, "guild", None) is not None:
            print(
                "Nachricht von nicht zugeordnetem Discord-Server ignoriert: "
                f"{message.guild.name} ({message.guild.id}), Channel {message.channel.id}."
            )
        return

    CURRENT_GUILD_SLUG.set(guild_slug)

    await handle_log_analysis_message(message)

    content = message.content.strip()
    lower = content.lower()



    if lower.startswith("!syncchannels") or lower.startswith("!channel-sync"):
        try:
            result = await sync_accessible_discord_channels()
            saved = int(result.get("saved", 0) or 0)
            await message.channel.send(f"✅ Discord-Channel neu synchronisiert: **{saved}** Channel gespeichert.", delete_after=30)
        except Exception as e:
            await message.channel.send(f"⚠️ Channel-Sync fehlgeschlagen: `{e}`", delete_after=30)
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

    if lower == "!wb":
        status_message = await message.channel.send("🔄 **Worldbuffs und Hordenbuffs werden aktualisiert...**")
        try:
            worldbuff_count = await asyncio.wait_for(
                update_worldbuff_post(sync_ticker=current_guild_slug() == LICHTLOOT_GUILD_SLUG),
                timeout=60
            )
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


    if lower in ["!worldbuff", "!worldbuffs"]:
        status_message = await message.channel.send("🔄 **Worldbuff-Post wird aktualisiert...**")
        try:
            # Vor dem Posten nur den letzten lesbaren Ticker-Post einlesen.
            # Der Sync durchsucht nicht mehr die komplette Channel-Historie.
            count = await asyncio.wait_for(
                update_worldbuff_post(
                    sync_ticker=current_guild_slug() == LICHTLOOT_GUILD_SLUG,
                    force_repost=True
                ),
                timeout=60
            )
            if count:
                target_channel_id = get_configured_worldbuff_channel_id()
                await status_message.edit(
                    content=(
                        f"✅ **Worldbuff-Post aktualisiert.** Posts: **{count}** · "
                        f"Ziel: <#{target_channel_id}>"
                    )
                )
            else:
                await status_message.edit(content="⚠️ **Worldbuff-Post wurde nicht aktualisiert.** Kein Zielchannel oder keine Termine gefunden.")
            client.loop.create_task(delete_message_later(status_message, 15))
        except asyncio.TimeoutError:
            await status_message.edit(content="⏱️ **Worldbuff-Update dauert zu lange.** Bitte Railway-Logs prüfen.")
        except Exception as error:
            print(f"Manuelles Worldbuff-Update fehlgeschlagen: {error}")
            await status_message.edit(
                content="⚠️ **Worldbuff-Post fehlgeschlagen.** Der genaue Fehler steht in den Railway-Logs."
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


if not TOKEN:
    raise SystemExit("DISCORD_TOKEN fehlt.")

start_public_api_server()
asyncio.run(run_discord_bot_with_backoff())
