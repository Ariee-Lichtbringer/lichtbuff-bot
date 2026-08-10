import asyncio
import contextvars
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import discord
from discord import app_commands

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


TOKEN = os.getenv("PO_BOT_TOKEN", "") or os.getenv("DISCORD_TOKEN", "")
TEST_GUILD_ID = str(os.getenv("PO_BOT_GUILD_ID", "") or "").strip()
LICHTLOOT_DISCORD_GUILD_ID = str(
    os.getenv("LICHTLOOT_DISCORD_GUILD_ID", "") or TEST_GUILD_ID
).strip()
NACHTLOOT_DISCORD_GUILD_ID = str(os.getenv("NACHTLOOT_DISCORD_GUILD_ID", "") or "").strip()
GUILD_SLUG = os.getenv("LICHTLOOT_GUILD", "") or os.getenv("LICHTLOOT_GUILD_SLUG", "") or "lichtloot"
if GUILD_SLUG.strip().lower() == "lichtbringer":
    GUILD_SLUG = "lichtloot"
CURRENT_GUILD_SLUG = contextvars.ContextVar("CURRENT_GUILD_SLUG", default=GUILD_SLUG)
GUILD_REGISTRY = {}
DISCORD_GUILD_SLUGS = {}
RAILWAY_API_URL = "https://lichtloot-production.up.railway.app/api/apps-script"


def normalize_api_url(value):
    url = str(value or "").strip().rstrip("/")
    if not url:
        return RAILWAY_API_URL
    parsed = urllib.parse.urlparse(url)
    if parsed.path.rstrip("/").endswith("/api/apps-script"):
        return url
    return url + "/api/apps-script"


API_URL = normalize_api_url(
    os.getenv("PO_BOT_API_URL", "") or os.getenv("LICHTLOOT_RAILWAY_API_URL", "") or RAILWAY_API_URL
)
QUEUE_TOKEN = os.getenv("LICHTBOT_QUEUE_TOKEN", "")
BOT_STARTED_AT = time.time()


def normalize_guild_slug(value):
    slug_value = str(value or "").strip().lower()
    if slug_value == "lichtbringer":
        return "lichtloot"
    return slug_value or GUILD_SLUG


def guild_display_name(value="", payload=None):
    payload = payload or {}
    raw_name = clean(
        value
        or payload.get("guildName")
        or payload.get("gilde")
        or payload.get("guild")
        or payload.get("guildSlug")
    )
    guild_slug = normalize_guild_slug(
        payload.get("guildSlug") or payload.get("guild") or raw_name
    )
    if guild_slug == "lichtloot":
        return "Lichtbringer"
    if guild_slug == "nachtloot":
        return "Die Nachtwächter"
    registry_entry = GUILD_REGISTRY.get(guild_slug) or {}
    return clean(
        registry_entry.get("name")
        or registry_entry.get("guildName")
        or raw_name
        or guild_slug
    )


def current_guild_slug():
    return normalize_guild_slug(CURRENT_GUILD_SLUG.get())


def payload_guild_slug(payload):
    payload = payload or {}
    visible_guild = " ".join(
        clean(payload.get(key)).lower()
        for key in ("guildName", "displayGuild", "gilde")
        if clean(payload.get(key))
    )
    if "nachtloot" in visible_guild or "nachtw" in visible_guild:
        return "nachtloot"
    if "lichtbringer" in visible_guild:
        return "lichtloot"
    return normalize_guild_slug(
        payload.get("guildSlug")
        or payload.get("guild")
        or current_guild_slug()
    )


def guild_slug_for_discord_guild(discord_guild_id, fallback=""):
    mapped = DISCORD_GUILD_SLUGS.get(str(discord_guild_id or "").strip())
    if mapped:
        return normalize_guild_slug(mapped)
    return normalize_guild_slug(fallback) if clean(fallback) else ""


def guild_slug_for_discord_server(guild, fallback=""):
    mapped = DISCORD_GUILD_SLUGS.get(str(getattr(guild, "id", "") or "").strip())
    if mapped:
        return normalize_guild_slug(mapped)
    guild_name = str(getattr(guild, "name", "") or "").strip().lower()
    if "nachtloot" in guild_name or "nachtw" in guild_name:
        return "nachtloot"
    if "lichtloot" in guild_name or "lichtbringer" in guild_name:
        return "lichtloot"
    if guild_name and GUILD_REGISTRY:
        for slug_value, data in GUILD_REGISTRY.items():
            candidates = [
                slug_value,
                data.get("name"),
                data.get("guildName"),
                data.get("guild_name"),
                data.get("lootName"),
                data.get("loot_name")
            ]
            if any(candidate and str(candidate).strip().lower() in guild_name for candidate in candidates):
                return normalize_guild_slug(slug_value)
    return normalize_guild_slug(fallback) if clean(fallback) else ""


def payload_for_interaction(payload, interaction):
    next_payload = dict(payload or {})
    server_slug = guild_slug_for_discord_server(getattr(interaction, "guild", None), "")
    guild_slug = server_slug or payload_guild_slug(next_payload)
    next_payload["guildSlug"] = guild_slug
    return next_payload


def fetch_bot_guilds():
    if not QUEUE_TOKEN:
        return []
    params = urllib.parse.urlencode({
        "action": "lichtbotListGuilds",
        "queueToken": QUEUE_TOKEN,
        "t": int(time.time()),
    })
    url = API_URL + "?" + params
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            result = parse_api_response(response, "Bot-Gilden", url)
    except Exception as error:
        print(f"PO-Bot Gildenliste konnte nicht geladen werden: {error}")
        return []
    if not result.get("success"):
        print(f"PO-Bot Gildenliste Antwort: {result}")
        return []
    return result.get("guilds") or []


async def refresh_guild_registry():
    global GUILD_REGISTRY, DISCORD_GUILD_SLUGS
    guilds = await asyncio.to_thread(fetch_bot_guilds)
    registry = {}
    discord_map = {}
    for row in guilds:
        slug_value = normalize_guild_slug(row.get("slug"))
        registry[slug_value] = row
        discord_guild_id = str(row.get("discordGuildId") or "").strip()
        if discord_guild_id:
            discord_map[discord_guild_id] = slug_value
    if registry:
        GUILD_REGISTRY = registry
        DISCORD_GUILD_SLUGS = discord_map
    print("PO-Bot Gilden geladen: " + (", ".join(f"{slug}#{data.get('discordGuildId') or '-'}" for slug, data in GUILD_REGISTRY.items()) or "keine"))
    return GUILD_REGISTRY


def normalize_role_name(value):
    text = re.sub(r"[^a-z0-9]+", "", str(value or "").strip().casefold())
    if text.startswith("po"):
        text = "p0" + text[2:]
    return text


PO_REVIEW_ROLE_NAMES = {
    normalize_role_name(value)
    for value in os.getenv(
        "PO_REVIEW_ROLE_NAMES",
        "PO Freigabe"
    ).split(",")
    if value.strip()
}
STATE_FILE = Path(os.getenv("PO_BOT_STATE_FILE", "po_bot_posts.json"))
QUEUE_CHECK_SECONDS = int(os.getenv("PO_BOT_QUEUE_CHECK_SECONDS", "10") or "10")
PRIO_SERVER = os.getenv("PO_BOT_PRIO_SERVER", "Lichtbringer")
PO_HELP_IMAGE_FILENAME = "po-anmelder-hinweis.png"
PO_HELP_IMAGE_PATH = Path(os.getenv("PO_BOT_HELP_IMAGE", str(Path(__file__).with_name(PO_HELP_IMAGE_FILENAME))))
RAID_ANNOUNCEMENT_GUIDE_IMAGE_PATH = Path(
    os.getenv(
        "PO_BOT_RAID_ANNOUNCEMENT_GUIDE_IMAGE",
        str(Path(__file__).resolve().parent / "assets" / "po-und-prio-anleitung.png"),
    )
)
NACHTLOOT_HELP_CHANNEL_ID = int(
    os.getenv("NACHTLOOT_HELP_CHANNEL_ID", "1533899479734947881") or "1533899479734947881"
)
NACHTLOOT_HELP_MARKER = "LichtLoot-Hilfe · Nachtloot"
NACHTLOOT_HELP_ROLE_NAMES = {
    normalize_role_name(value)
    for value in (
        "Gildenleitung",
        "Gildenmeister",
        "Offizier",
        "Offiziere",
        "Gildenoffiziere",
        "Raidoffizier",
        "Raidoffiziere",
        "PO Freigabe",
        "PO-Freigabe",
        "P0 Freigabe",
        "P0-Freigabe",
    )
}
RAID_BANNER_DIR = Path(__file__).resolve().parent / "raid-banners"
LICHTLOOT_PRIO_URL = os.getenv("LICHTLOOT_PRIO_URL", "")
LICHTLOOT_URL = os.getenv("LICHTLOOT_URL", "https://lichtloot.de")

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
    "warrior": ["classicon_warrior"],
    "druid": ["classicon_druid"],
    "paladin": ["classicon_paladin"],
    "rogue": ["classicon_rogue"],
    "hunter": ["classicon_hunter"],
    "priest": ["classicon_priest"],
    "mage": ["classicon_mage"],
    "warlock": ["classicon_warlock"],
    "shaman": ["classicon_shaman"],
}

CLASS_LABELS_DE = {
    "warrior": "Krieger",
    "druid": "Druide",
    "paladin": "Paladin",
    "rogue": "Schurke",
    "hunter": "Jäger",
    "priest": "Priester",
    "mage": "Magier",
    "warlock": "Hexenmeister",
    "shaman": "Schamane",
}

PO_ITEM_EMOJI_ALIASES = {
    "amulett von veknilash": ["amulett_von_veknilash"],
    "auge von c'thun": ["auge_von_cthun_"],
    "auge des todes": ["auge_des_todes"],
    "armreifen der königlichen erlösung": ["armreifen_der_kniglichen_erlsung"],
    "band von accuria": ["band_von_accuria"],
    "band der ausbrennung": ["band_der_ausbrennung_"],
    "band der unerhörten gebete": ["_band_der_unerhrten_gebete", "band_der_unerhrten_gebete"],
    "band der unnatürlichen kräfte": ["band_der_unnatrlichen_krfte_", "band_der_unnatuerlichen_kraefte"],
    "die gebundene essenz saphirons": ["die_gebundene_essenz_saphirons"],
    "gebundene essenz von saphiron": ["die_gebundene_essenz_saphirons"],
    "die zehrende kälte": ["die_zehrende_klte", "die_zehrende_kaelte"],
    "drachenfangzahn-talisman": ["_drachenfangzahntalisman", "drachenfangzahntalisman", "drachenfangzahn_talisman"],
    "drachenfangzahn talisman": ["_drachenfangzahntalisman", "drachenfangzahntalisman", "drachenfangzahn_talisman"],
    "fetisch des sandhäschers": ["fetisch_des_sandhschers", "fetisch_des_sandhaeschers"],
    "formel: brust - große werte": ["formel_brust__groe_werte_"],
    "gressil, vorbote des untergangs": ["gressil_vorbote_des_untergangs"],
    "gurt des ansturms": ["gurt_des_ansturms_"],
    "handschützer der erhabenheit": [
        "handschtzer_der_erhabenheit",
        "handschutzer_der_erhabenheit",
        "handschuetzer_der_erhabenheit",
    ],
    "hammer des wirbelnden nethers": ["hammer_des_wirbelnden_nethers_"],
    "krone der zerstörung": ["krone_der_zerstrung_", "krone_der_zerstoerung_", "krone_der_zerstoerung"],
    "maladath, runenverzierte klinge des schwarzen drachenschwarms": ["maladath"],
    "ring des märtyrers": ["ring_des_mrtyrers"],
    "saphirons linkes auge": ["saphirons_linkes_auge"],
    "schild der geißelung": ["_schild_der_geielung", "schild_der_geisselung"],
    "schlägermal": ["_schlgermal", "schlaegermal"],
    "schneller razzashiraptor": ["schneller_razzashiraptor"],
    "schneller zulianischer tiger": ["schneller_zulianischer_tiger", "schneller_zullianischer_tiger"],
    "szepter des falschen propheten": ["szepter_des_falschen_propheten"],
    "stulpen des friedensbewahrers": ["stulpen_des_friedensbewahrers"],
    "stulpen der vernichtung": ["stulpen_der_vernichtung"],
    "stulpen der dunklen stürme": ["stulpen_der_dunklen_strme"],
    "blaues schmuckstück der hakkari": ["blaues_schmuckstck_der_hakkari", "blaues_schmuckstueck_der_hakkari"],
    "kriegsklinge der hakkari": ["kriegsklinge_der_hakkari"],
    "neltharions träne": ["_neltharions_trne", "neltharions_trne", "neltharions_traene"],
    "prestor's talisman der verschwörung": ["prestors_talisman_der_verschwrung", "prestors_talisman_der_verschwoerung"],
    "prestors talisman der verschwörung": ["prestors_talisman_der_verschwrung", "prestors_talisman_der_verschwoerung"],
    "urzeitlicher hakkarigötze": ["urzeitlicher_hakkarigtze", "urzeitlicher_hakkarigoetze"],
    "unbarmherzige klinge": ["unbarmherzige_klinge"],
    "umhang des geballten hasses": ["umhang_des_geballten_hasses"],
    "wappen des schlächters": ["wappen_des_schlchters_", "wappen_des_schlaechters"],
    "zulianischer tigerbalgumhang": ["zulianischer_tigerbalgumhang"],
    "chromatisch gehärtetes schwert": ["chromatisch_gehrttetes_schwert", "chromatisch_gehaertetes_schwert"],
}

RAID_NAMES = {
    "MC": "Molten Core",
    "BWL": "Blackwing Lair",
    "AQ20": "AQ20",
    "AQ40": "Ahn'Qiraj 40",
    "ZG": "ZG",
    "ZG-MITTWOCH": "ZG Mittwoch",
    "ZG-PRIME": "ZG PRIME",
    "ZG-LATE": "ZG LATE",
    "NAXX": "Naxxramas",
}

user_classes = {}
class_emoji_cache = {}
spec_emoji_cache = {}
item_emoji_cache = {}
# Ein Refresh darf Anmelder erst rendern, nachdem Discord die Application-
# Emojis geliefert hat. Sonst werden kurzzeitig Unicode-Ersatzsymbole in die
# Nachricht geschrieben und bleiben dort bis zum nächsten Refresh stehen.
emoji_cache_ready = asyncio.Event()
RAID_SIGNUP_DM_CACHE = {}
p0plus_cache = {}
P0PLUS_CACHE_SECONDS = int(os.getenv("PO_BOT_P0PLUS_CACHE_SECONDS", "60") or "60")
empty_queue_log_at = 0
slash_commands_synced_for_guilds = False


def clean(value):
    return str(value or "").strip()


def normalize_raid(value):
    # Discord-Titel enthalten je nach Vorlage Leerzeichen, Bindestriche oder
    # Apostrophe (z. B. AHN'QIRAJ 20). Für die Raid-Zuordnung werden nur
    # Buchstaben und Zahlen berücksichtigt.
    text = re.sub(r"[^A-Z0-9]+", "", clean(value).upper())
    if text in {"ZGMITTWOCH", "ZULGURUBMITTWOCH"}:
        return "ZG-MITTWOCH"
    if text in {"ZGPRIME", "ZULGURUBPRIME"}:
        return "ZG-PRIME"
    if text in {"ZGLATE", "ZULGURUBLATE"}:
        return "ZG-LATE"
    if text in {"MOLTENCORE"}:
        return "MC"
    if text in {"BLACKWINGLAIR"}:
        return "BWL"
    if text in {"AQ", "AHNQIRAJ", "AHNQIRAJ40"}:
        return "AQ40"
    if text in {"AQ20", "AHNQIRAJ20", "RUINSOFAHNQIRAJ"}:
        return "AQ20"
    if text in {"ZULGURUB", "ZG20"}:
        return "ZG"
    if text in {"NAXXRAMAS"}:
        return "NAXX"
    return text or "RAID"


def display_raid(value):
    raid = normalize_raid(value)
    return RAID_NAMES.get(raid, raid)


def po_release_required_for_raid(value):
    return normalize_raid(value) in {"MC", "BWL", "AQ40", "NAXX", "ZG-MITTWOCH", "ZG-PRIME", "ZG-LATE"}


def loot_raid(value):
    raid = normalize_raid(value)
    return "ZG" if raid in {"ZG-MITTWOCH", "ZG-PRIME", "ZG-LATE"} else raid


def slug(value):
    text = clean(value).lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "po"


def class_key(class_name):
    key = clean(class_name).lower()
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
        "hexer": "warlock",
        "schamane": "shaman",
    }
    return aliases.get(key, key)


def class_display_name(class_name):
    key = class_key(class_name)
    return CLASS_LABELS_DE.get(key, clean(class_name))


def normalize_emoji_name(value):
    text = clean(value).lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9_]+", "", text)


def item_emoji_candidates(item_name):
    raw = clean(item_name).lower()
    raw = raw.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    normalized = normalize_emoji_name(raw)
    underscored = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", raw)).strip("_")
    candidates = []
    original_key = clean(item_name).lower()
    candidates.extend(PO_ITEM_EMOJI_ALIASES.get(original_key, []))
    for value in [normalized, underscored]:
        if value:
            candidates.extend([value, f"item_{value}", f"loot_{value}", f"po_{value}"])
    result = []
    seen = set()
    for value in candidates:
        key = normalize_emoji_name(value)
        if key and key not in seen:
            result.append(key)
            seen.add(key)
        short_key = short_emoji_name(key)
        if short_key and short_key not in seen:
            result.append(short_key)
            seen.add(short_key)
    return result


def short_emoji_name(value):
    key = normalize_emoji_name(value)
    if not key:
        return ""
    if len(key) <= 32:
        return key
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:6]
    return f"{key[:25]}_{digest}"[:32]


def primary_item_emoji_name(item_name):
    for candidate in item_emoji_candidates(item_name):
        name = short_emoji_name(candidate)
        if len(name) >= 2:
            return name
    return ""


async def refresh_emoji_cache():
    found_classes = {}
    found_specs = {}
    found_items = {}
    guild_emojis = []
    application_emojis = []
    for guild in getattr(client, "guilds", []) or []:
        try:
            # Beim frühen Botstart kann guild.emojis noch unvollständig sein.
            # Die direkte Discord-Abfrage stellt sicher, dass bereits auf dem
            # Server gespeicherte PO-Item-Emojis sofort verfügbar sind.
            fetched = await guild.fetch_emojis()
            guild_emojis.extend(fetched or [])
        except Exception as exc:
            cached = list(getattr(guild, "emojis", []) or [])
            guild_emojis.extend(cached)
            print(
                f"PO Server-Emojis konnten für {getattr(guild, 'name', guild.id)} "
                f"nicht direkt geladen werden; Cache mit {len(cached)} Emojis wird verwendet: {exc}"
            )

    # Emojis aus dem Developer Portal gehören der App und sind nicht in
    # guild.emojis enthalten. Sie müssen separat über die App geladen werden.
    try:
        application_emojis = list(await client.fetch_application_emojis())
    except Exception as exc:
        print(f"PO App-Emojis konnten nicht geladen werden: {exc}")

    # Klassen und Skillungen kommen ausschließlich aus der eigenen Emoji-
    # Datenbank der Discord-App. Dadurch können gleichnamige, veraltete
    # Server-Emojis nie wieder unbemerkt verwendet werden.
    app_by_name = {normalize_emoji_name(emoji.name): emoji for emoji in application_emojis}
    for key, names in CLASS_EMOJI_NAME_ALIASES.items():
        for name in names:
            emoji = app_by_name.get(normalize_emoji_name(name))
            if emoji:
                found_classes[key] = str(emoji)
                break
    for key, names in SPEC_EMOJI_NAME_ALIASES.items():
        for name in names:
            emoji = app_by_name.get(normalize_emoji_name(name))
            if emoji:
                found_specs[key] = str(emoji)
                break
    # Item-Emojis dürfen weiterhin aus Server und App stammen. Bei gleichem
    # Namen hat die eigene App-Datenbank Vorrang.
    by_name = {normalize_emoji_name(emoji.name): emoji for emoji in guild_emojis}
    by_name.update(app_by_name)
    for emoji_name, emoji in by_name.items():
        found_items[emoji_name] = str(emoji)
    class_emoji_cache.clear()
    class_emoji_cache.update(found_classes)
    spec_emoji_cache.clear()
    spec_emoji_cache.update(found_specs)
    item_emoji_cache.clear()
    item_emoji_cache.update(found_items)
    print(
        f"PO Emoji-Cache: {len(application_emojis)} Application-Emojis, "
        f"{len(guild_emojis)} Server-Emojis, {len(found_items)} insgesamt."
    )
    return found_classes, found_specs, found_items


def class_icon(class_name):
    key = class_key(class_name)
    # Keine fest eingetragenen alten Emoji-IDs mehr: maßgeblich ist nur der
    # beim Start aus der Discord-App geladene Cache.
    return class_emoji_cache.get(key) or CLASS_EMOJI_FALLBACKS.get(key, "◆")


def select_emoji(icon):
    if icon.startswith("<:") or icon.startswith("<a:"):
        try:
            return discord.PartialEmoji.from_str(icon)
        except Exception:
            return None
    return icon or None


def class_select_emoji(class_name):
    return select_emoji(class_icon(class_name)) or CLASS_EMOJI_FALLBACKS.get(class_key(class_name), "◆")


def item_icon(item_name):
    for candidate in item_emoji_candidates(item_name):
        cached = item_emoji_cache.get(candidate)
        if cached:
            return cached
    return "◇"


def item_select_emoji(item_name):
    icon = item_icon(item_name)
    return select_emoji(icon) if icon != "◇" else None


async def send_silent(channel, *args, **kwargs):
    kwargs.setdefault("allowed_mentions", discord.AllowedMentions.none())
    try:
        kwargs.setdefault("silent", True)
        return await channel.send(*args, **kwargs)
    except TypeError:
        kwargs.pop("silent", None)
        return await channel.send(*args, **kwargs)


FREE_DISCORD_EMBED_COLORS = {
    "sky": 0x38BDF8,
    "purple": 0x8B5CF6,
    "gold": 0xFACC15,
    "green": 0x22C55E,
    "red": 0xEF4444,
}


async def post_free_discord_embed_from_queue(payload):
    channel_id = clean(payload.get("channelId") or payload.get("discordChannelId"))
    if not channel_id:
        raise RuntimeError("Discord-Channel fuer das freie Embed fehlt.")
    channel = client.get_channel(int(channel_id))
    if channel is None:
        channel = await client.fetch_channel(int(channel_id))

    embed_type = clean(payload.get("embedType")).lower() or "custom"
    raw_points = payload.get("points") or []
    if isinstance(raw_points, str):
        try:
            raw_points = json.loads(raw_points)
        except Exception:
            raw_points = raw_points.splitlines()
    points = [clean(point) for point in raw_points if clean(point)]
    number_icons = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    embed = discord.Embed(
        title=clean(payload.get("title")) or None,
        description=clean(payload.get("description")) or None,
        color=FREE_DISCORD_EMBED_COLORS.get(clean(payload.get("color")).lower(), 0x38BDF8),
    )
    if embed_type == "meeting":
        meeting_bits = []
        if clean(payload.get("meetingDate")):
            meeting_bits.append(f"📅 **Datum:** {clean(payload.get('meetingDate'))}")
        if clean(payload.get("meetingTime")):
            meeting_bits.append(f"🕒 **Uhrzeit:** {clean(payload.get('meetingTime'))} Uhr")
        if clean(payload.get("meetingLocation")):
            meeting_bits.append(f"📍 **Ort:** {clean(payload.get('meetingLocation'))}")
        if meeting_bits:
            embed.add_field(name="Termin", value="\n".join(meeting_bits), inline=False)

    if points:
        point_lines = [
            f"{number_icons[index] if embed_type == 'poll' and index < len(number_icons) else '•'} {point}"
            for index, point in enumerate(points)
        ]
        chunks, current = [], ""
        for line in point_lines:
            candidate = f"{current}\n{line}".strip()
            if current and len(candidate) > 1000:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)
        section_title = clean(payload.get("sectionTitle")) or (
            "Antwortmöglichkeiten" if embed_type == "poll" else "Tagesordnung" if embed_type == "meeting" else "Inhalte"
        )
        for index, chunk in enumerate(chunks):
            embed.add_field(name=section_title if index == 0 else "\u200b", value=chunk, inline=False)

    footer = clean(payload.get("footer"))
    if footer:
        embed.set_footer(text=footer[:2048])
    message = await send_silent(channel, embed=embed)
    reactions = number_icons[: min(len(points), 10)] if embed_type == "poll" else (["✅", "❔", "❌"] if embed_type == "meeting" else [])
    for reaction in reactions:
        try:
            await message.add_reaction(reaction)
        except Exception as error:
            print(f"Reaktion fuer freies Embed konnte nicht gesetzt werden: {error}")
    return bool(message)


RAID_SIGNUP_SPECS = {
    "Warrior": [("Waffen", "arms"), ("Furor", "fury"), ("Tank", "tank")],
    "Druid": [("Heilung", "heal"), ("Tank", "tank"), ("FeralDD", "feral"), ("Eule", "balance")],
    "Paladin": [("Heilig", "paladin_holy"), ("Vergeltung", "retri"), ("Tank", "tank")],
    "Rogue": [("Assassination", "assassination"), ("Combat", "combat"), ("Subtlety", "subtlety")],
    "Hunter": [("Survival", "survival"), ("Marksman", "marksman"), ("Beastmaster", "beastmaster")],
    "Priest": [("Disziplin", "discipline"), ("Heilig", "priest_holy"), ("Schatten", "shadow")],
    "Mage": [("Feuer", "fire"), ("Frost", "frost"), ("Arkan", "arcane")],
    "Warlock": [("Gebrechen", "affliction"), ("Dämonologie", "demonology"), ("Zerstörung", "destruction")],
    "Shaman": [("Heilung", "heal"), ("Elemental", "elemental"), ("Enhancement", "enhancement")],
}

SPEC_EMOJI_FALLBACKS = {
    "tank": "🛡️",
    "heal": "➕",
    "druid_heal": "➕",
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
    "druid_heal": ["HeilungDuDu", "heilung_dudu", "druid_heal", "druid_restoration"],
    "holy": ["holy", "heilig"],
    "paladin_holy": ["holy_pala", "paladin_holy", "pala_holy", "palaholy", "holy_paladin", "heilig_paladin"],
    "priest_holy": ["holy_priester", "priest_holy", "priester_holy", "holy_priest", "heilig_priester"],
    "discipline": ["disziplin", "discipline", "disc"],
    "shadow": ["schatten", "shadow"],
    "arms": ["arms", "waffen"],
    "fury": ["fury", "furor"],
    "retri": ["retri", "ret", "vergeltung"],
    "fire": ["feuer", "fire"],
    "frost": ["frost", "eis"],
    "arcane": ["arkan", "arcane"],
    "assassination": ["assassination", "assa"],
    "subtlety": ["subtlety", "sub"],
    "combat": ["combat", "kampf"],
    "affliction": ["affliction", "affli", "gebrechen"],
    "demonology": ["demonology", "demo", "daemonologie", "dämonologie"],
    "destruction": ["destruction", "destro", "zerstoerung", "zerstörung"],
    "feral": ["feraldd", "feral"],
    "balance": ["eule", "balance", "moonkin"],
    "survival": ["survival"],
    "marksman": ["marksman", "marksmanship"],
    "beastmaster": ["beastmaster", "beast_mastery", "beast mastery", "bm"],
    "elemental": ["elemental", "ele"],
    "enhancement": ["enhancement", "enh"],
}

# Feste WoW-Iconnamen für die Discord-Application-Emojis. Sie werden über
# dieselbe Bildquelle geladen wie die Lootitem-Icons.
RAID_APPLICATION_EMOJI_ICONS = {
    "classicon_warrior": "classicon_warrior", "classicon_druid": "classicon_druid",
    "classicon_paladin": "classicon_paladin", "classicon_rogue": "classicon_rogue",
    "classicon_hunter": "classicon_hunter", "classicon_priest": "classicon_priest",
    "classicon_mage": "classicon_mage", "classicon_warlock": "classicon_warlock",
    "classicon_shaman": "classicon_shaman",
    "tank": "inv_shield_06", "heilung": "spell_holy_flashheal",
    "melee": "ability_dualwield", "range": "ability_marksmanship",
    "waffen": "ability_warrior_savageblow", "fury": "ability_warrior_innerrage",
    "holy_pala": "spell_holy_holybolt", "retri": "spell_holy_auraoflight",
    "disziplin": "spell_holy_powerwordshield", "holy_priester": "spell_holy_guardianspirit",
    "schatten": "spell_shadow_shadowwordpain", "feuer": "spell_fire_firebolt02",
    "frost": "spell_frost_frostbolt02", "arkan": "spell_holy_magicalsentry",
    "assa": "ability_rogue_eviscerate", "combat": "ability_backstab",
    "subtlety": "ability_stealth", "affliction": "spell_shadow_deathcoil",
    "demo": "spell_shadow_metamorphosis", "destro": "spell_shadow_rainoffire",
    "feral": "ability_druid_catform", "eule": "spell_nature_starfall",
    "survival": "ability_hunter_camouflage", "marksman": "ability_marksmanship",
    "beastmaster": "ability_hunter_beasttaming", "elemental": "spell_nature_lightningshield",
    "enhancement": "ability_shaman_stormstrike",
    "beutelilia": "inv_misc_bag_10", "beuteorange": "inv_misc_bag_19",
    "Beutegrun": "inv_misc_bag_11",
}


def format_raid_announcement_date(value):
    raw = clean(value)
    if not raw:
        return "noch offen"
    if re.match(r"^\d{4}-\d{2}-\d{2}T", raw):
        raw = raw[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d.%m.%Y")
        except ValueError:
            pass
    return raw


def format_raid_announcement_day_and_date(value):
    raw = clean(value)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(raw, fmt)
            weekday = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][parsed.weekday()]
            return f"{weekday}, {parsed.strftime('%d.%m.%Y')}"
        except ValueError:
            pass
    return format_raid_announcement_date(value)


def format_raid_announcement_time(value):
    raw = clean(value)
    if not raw:
        return "noch offen"
    match = re.search(r"(\d{1,2}):(\d{2})", raw)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)} Uhr"
    return raw


def raid_announcement_image_url(raid):
    raid_key = normalize_raid((raid or {}).get("raid") or (raid or {}).get("raidName")).lower()
    image_raid_key = "zg" if raid_key in {"zg-mittwoch", "zg-prime", "zg-late"} else raid_key
    guild_slug = normalize_guild_slug((raid or {}).get("guildSlug") or "")
    guild_name = clean((raid or {}).get("guild") or (raid or {}).get("gilde")).lower()
    if "nachtloot" in guild_name or "nachtw" in guild_name:
        guild_slug = "nachtloot"
    if not (raid or {}).get("guildSlug") and guild_name:
        for slug_value, data in GUILD_REGISTRY.items():
            candidates = [
                slug_value,
                data.get("name"),
                data.get("guildName"),
                data.get("guild_name"),
                data.get("lootName"),
                data.get("loot_name"),
            ]
            if any(candidate and clean(candidate).lower() == guild_name for candidate in candidates):
                guild_slug = normalize_guild_slug(slug_value)
                break
    registry_entry = GUILD_REGISTRY.get(guild_slug) or {}
    layout = registry_entry.get("layout") or {}
    images = layout.get("raidImages") if isinstance(layout, dict) else {}
    guild_image = clean((images or {}).get(raid_key) or (images or {}).get(image_raid_key))
    if guild_slug != "lichtloot":
        if guild_image:
            return urllib.parse.urljoin(LICHTLOOT_URL.rstrip("/") + "/", guild_image)
        return ""
    explicit = clean((raid or {}).get("raidImageUrl") or (raid or {}).get("imageUrl"))
    if explicit.startswith(("http://", "https://")):
        return explicit
    if image_raid_key in {"zg", "aq20", "aq40", "bwl", "mc", "naxx", "ony"}:
        return f"https://lichtloot-production.up.railway.app/images/raid-banners/{image_raid_key}.jpg"
    return ""


def custom_emoji(name, fallback):
    """Use a guild or Developer-Portal app emoji and keep a portable fallback."""
    emoji = discord.utils.get(getattr(client, "emojis", []), name=name)
    if emoji:
        return str(emoji)
    # refresh_emoji_cache lädt zusätzlich die Application Emojis aus dem
    # Discord Developer Portal. Dadurch funktionieren dort gespeicherte
    # Lootbag-, Rollen-, Klassen- und Skillungsbilder genauso wie Server-Emojis.
    app_emoji = item_emoji_cache.get(normalize_emoji_name(name))
    return app_emoji or fallback


WORLDBUFF_EMOJIS = {
    "Hakkar": ("zgbuff", "🟢"),
    "Ony": ("onybuff", "🔴"),
    "Nef": ("neffbuff", "🔴"),
    "Rend": ("rendbuff", "🟠"),
}


def normalize_worldbuff_name(value):
    name = clean(value)
    lowered = name.lower()
    if lowered in {"hakkar", "zg"}:
        return "Hakkar"
    if lowered in {"ony", "onyxia"}:
        return "Ony"
    if lowered in {"nef", "nefarian"}:
        return "Nef"
    if lowered == "rend":
        return "Rend"
    return name or "Buff"


def worldbuff_emoji(buff):
    emoji_name, fallback = WORLDBUFF_EMOJIS.get(buff, ("", "⚪"))
    return custom_emoji(emoji_name, fallback) if emoji_name else fallback


def format_worldbuff_announcement_row(buff, row_time, guild, caster=""):
    """Use the same compact fixed-width columns as the Worldbuff channel."""
    caster_suffix = f" - ⚔️ {caster}" if caster else ""
    row = f"{buff:<6}  {row_time:<5}  {guild}{caster_suffix}"
    return f"{worldbuff_emoji(buff)} `{row.rstrip()}`"


def build_raid_announcement_embed(raid):
    raid = raid or {}
    raid_name = clean(raid.get("raidName") or display_raid(raid.get("raid")) or "Raid")
    description = clean(raid.get("description")) or "Raidanmeldung ist geöffnet."
    embed = discord.Embed(title=raid_name.upper(), description=description[:3900], color=0x7c3aed)
    embed.add_field(name="Raidlead", value=clean(raid.get("createdBy") or raid.get("erstelltVon") or "Gildenleitung"), inline=True)
    embed.add_field(
        name="Tag / Datum",
        value=f"**__{format_raid_announcement_day_and_date(raid.get('raidDate'))}__**",
        inline=True,
    )
    embed.add_field(
        name="Uhrzeit",
        value=f"**__{format_raid_announcement_time(raid.get('raidTime'))}__**",
        inline=True,
    )
    loot_master = clean(raid.get("lootMaster") or raid.get("pluendermeister"))
    if loot_master:
        embed.add_field(name="Plündermeister", value=loot_master, inline=False)
    deadline = format_raid_announcement_time(raid.get("signupDeadline") or raid.get("signup_deadline"))
    if deadline != "noch offen":
        embed.add_field(name="Anmeldeschluss", value=deadline, inline=False)
    slots = []
    for label, key in [("Gesamt", "maxPlayers"), ("Tanks", "tankSlots"), ("Heals", "healSlots"), ("DD", "ddSlots")]:
        value = clean(raid.get(key))
        if value:
            slots.append(f"{label} {value}")
    if slots:
        embed.add_field(name="Slots", value=" · ".join(slots), inline=False)
    embed.add_field(name="Prio-PIN", value=f"`{clean(raid.get('playerPin')) or '-'}`", inline=True)
    raid_guild_slug = normalize_guild_slug(raid.get("guildSlug") or current_guild_slug())
    worldbuff_block = current_worldbuff_announcement_block(
        raid_guild_slug,
        raid_date=raid.get("raidDate") or raid.get("raid_date"),
    )
    if worldbuff_block:
        embed.add_field(name="Aktuelle Worldbuffs", value=worldbuff_block[:1024], inline=False)
    embed.add_field(
        name="Prios auf LichtLoot",
        value=(
            f"{custom_emoji('beutelilia', '🟣')} **P1–P3 Lootbag**  ·  "
            f"{custom_emoji('beuteorange', '🟠')} **PO eingetragen**  ·  "
            f"{custom_emoji('Beutegrun', '🟢')} **PO freigegeben**"
        ),
        inline=False,
    )
    attachment_name = raid_banner_attachment_name(raid)
    if attachment_name:
        embed.set_image(url=f"attachment://{attachment_name}")
    else:
        image_url = raid_announcement_image_url(raid)
        if image_url:
            embed.set_image(url=image_url)
    embed.set_footer(text="Bitte meldet euch im Discord an und tragt eure Prios rechtzeitig ein.")
    return embed


def raid_banner_attachment_name(raid):
    if payload_guild_slug(raid) != "lichtloot":
        return ""
    raid_key = normalize_raid(raid.get("raid") or raid.get("raidName")).lower()
    filename = {
        "zg": "zg.jpg", "aq20": "aq20.jpg", "aq40": "aq40.jpg",
        "bwl": "bwl.jpg", "mc": "mc.jpg", "naxx": "naxx.jpg", "ony": "ony.jpg",
    }.get(raid_key, "")
    return filename if filename and (RAID_BANNER_DIR / filename).exists() else ""


def raid_banner_file(raid):
    filename = raid_banner_attachment_name(raid)
    if not filename:
        return None, ""
    return discord.File(str(RAID_BANNER_DIR / filename), filename=filename), filename


def add_raid_signup_links_field(embed, raid):
    raid_id = clean((raid or {}).get("raidId") or (raid or {}).get("id"))
    guild_slug = payload_guild_slug(raid or {})
    edit_url = (
        f"{LICHTLOOT_URL.rstrip('/')}/gildenleitung.html?"
        + urllib.parse.urlencode({"guild": guild_slug, "raidHelper": raid_id})
    )
    embed.add_field(
        name="\u200b",
        value=" | ".join([
            f"[Webansicht]({LICHTLOOT_URL.rstrip('/')}/)",
            f"[Comp]({edit_url})",
            f"[Gcal]({edit_url})",
            f"[Bearbeiten]({edit_url})",
        ]),
        inline=False,
    )


def parse_raid_worldbuff_date(value):
    raw = clean(value)
    for date_format in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw[:10], date_format).date()
        except (TypeError, ValueError):
            continue
    return None


def current_worldbuff_announcement_block(guild_slug=None, raid_date=None, max_lines=8):
    resolved_guild_slug = normalize_guild_slug(guild_slug or current_guild_slug())
    try:
        result = api_get({
            "action": "guildGetWorldbuffs",
            "queueToken": QUEUE_TOKEN,
            "guild": resolved_guild_slug,
            "guildSlug": resolved_guild_slug,
            "source": "railway",
            "days": "all",
            "t": int(time.time()),
        })
    except Exception as error:
        print(f"Worldbuffs fuer Raidanmelder konnten nicht geladen werden: {error}")
        return ""
    rows = result.get("buffs") or result.get("entries") or []
    selected_raid_date = parse_raid_worldbuff_date(raid_date)
    # Im Raidanmelder sind ausschließlich die für die Vorbereitung relevanten
    # Termine sichtbar: der Vortag und der eigentliche Raidtag.
    allowed_dates = None
    if selected_raid_date:
        allowed_dates = {selected_raid_date - timedelta(days=1), selected_raid_date}
    else:
        today = datetime.now().date()
        allowed_dates = {today, today + timedelta(days=1)}
    upcoming = []
    deduplicated = {}
    for row in rows:
        try:
            row_date = datetime.strptime(clean(row.get("datum") or row.get("date")), "%d.%m.%Y").date()
        except Exception:
            continue
        if row_date not in allowed_dates:
            continue
        row_time = clean(row.get("uhrzeit") or row.get("time"))
        buff = normalize_worldbuff_name(row.get("buff") or row.get("type"))
        guild = clean(row.get("gilde") or row.get("guild"))
        # Gleicher Buff, gleiche Gilde und gleiche Uhrzeit werden nur einmal
        # gezeigt, auch wenn Railway und ein Import dieselben Daten liefern.
        dedupe_key = (row_date, row_time, buff.lower(), guild.lower())
        existing = deduplicated.get(dedupe_key)
        existing_caster = clean((existing or {}).get("charakter") or (existing or {}).get("character"))
        new_caster = clean(row.get("charakter") or row.get("character"))
        if existing is None or (new_caster and not existing_caster):
            deduplicated[dedupe_key] = row
    for (row_date, row_time, _buff, _guild), row in deduplicated.items():
        upcoming.append((row_date, row_time, row))
    upcoming.sort(key=lambda item: (item[0], item[1]))
    lines = []
    current_date = None
    for row_date, row_time, row in upcoming[:max_lines]:
        if row_date != current_date:
            weekday = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][row_date.weekday()]
            lines.append(f"**{weekday}, {row_date.strftime('%d.%m.%Y')}**")
            current_date = row_date
        buff = normalize_worldbuff_name(row.get("buff") or row.get("type"))
        guild = clean(row.get("gilde") or row.get("guild"))
        caster = clean(row.get("charakter") or row.get("character"))
        lines.append(format_worldbuff_announcement_row(buff, row_time, guild, caster))
    remaining = max(0, len(upcoming) - max_lines)
    if remaining:
        lines.append(f"… und {remaining} weitere Worldbuff-Termine im Worldbuff-Post.")
    return "\n".join(lines)


def build_raid_announcement_text(raid):
    raid = raid or {}
    lines = [
        f"**{clean(raid.get('raidName') or display_raid(raid.get('raid')) or 'Raid').upper()}**",
        "",
        clean(raid.get("description")) or "Raidanmeldung ist geöffnet.",
        "",
        f"📣 **Raidlead:** {clean(raid.get('createdBy') or raid.get('erstelltVon') or 'Gildenleitung')}",
        f"🗓️ **Datum:** {format_raid_announcement_date(raid.get('raidDate'))}",
        f"⏰ **Start:** {format_raid_announcement_time(raid.get('raidTime'))}",
    ]
    loot_master = clean(raid.get("lootMaster") or raid.get("pluendermeister"))
    if loot_master:
        lines.append(f"🪙 **Plündermeister:** {loot_master}")
    lines.extend([
        "",
        f"🔑 **Prio-PIN:** `{clean(raid.get('playerPin')) or '-'}`",
        f"🌐 **Webansicht:** {LICHTLOOT_URL}",
    ])
    return "\n".join(lines)[:1900]


def canonical_signup_class(class_name):
    key = clean(class_name).lower()
    return {
        "warrior": "Warrior", "krieger": "Warrior",
        "druid": "Druid", "druide": "Druid",
        "paladin": "Paladin",
        "rogue": "Rogue", "schurke": "Rogue",
        "hunter": "Hunter", "jäger": "Hunter", "jaeger": "Hunter",
        "priest": "Priest", "priester": "Priest",
        "mage": "Mage", "magier": "Mage",
        "warlock": "Warlock", "hexenmeister": "Warlock",
        "shaman": "Shaman", "schamane": "Shaman",
    }.get(key, clean(class_name) or "Ohne Klasse")


def signup_spec_from_note(note, role=""):
    raw = clean(note)
    if raw.lower().startswith("skillung:"):
        return raw.split(":", 1)[1].strip()
    return raw or clean(role)


def signup_spec_for_row(row):
    """Liest die Skillung aus allen von Website und Bot verwendeten Feldern."""
    row = row or {}
    explicit = clean(
        row.get("specialization")
        or row.get("specialisation")
        or row.get("spec")
        or row.get("skillung")
    )
    return explicit or signup_spec_from_note(row.get("note"), row.get("role"))


def infer_signup_role(spec_text):
    text = clean(spec_text).lower()
    if any(word in text for word in ["multi char", "multi-char", "multichar", "mehrere chars"]):
        return "multi"
    if any(word in text for word in ["tank", "prot", "schutz", "def"]):
        return "tank"
    if any(word in text for word in ["heal", "heiler", "heilung", "holy", "heilig", "resto", "wiederherstellung", "diszi", "discipline"]):
        return "heal"
    return "dd"


def signup_spec_icon_key(spec_text, role="", class_name=""):
    text = clean(spec_text or role).lower()
    canonical_class = canonical_signup_class(class_name).lower()
    if any(word in text for word in ["tank", "prot", "schutz", "def"]):
        return "tank"
    if any(word in text for word in ["disziplin", "discipline", "disc"]):
        return "discipline"
    if any(word in text for word in ["holy", "heilig"]):
        if canonical_class == "paladin":
            return "paladin_holy"
        if canonical_class == "priest":
            return "priest_holy"
        return "holy"
    if any(word in text for word in ["schatten", "shadow"]):
        return "shadow"
    if any(word in text for word in ["heal", "heiler", "heilung", "resto", "restoration", "wiederherstellung"]):
        if canonical_class == "druid":
            return "druid_heal"
        return "heal"
    checks = [
        ("arms", ["arms", "waffen"]),
        ("fury", ["fury", "furor"]),
        ("retri", ["retri", "vergeltung"]),
        ("fire", ["fire", "feuer"]),
        ("frost", ["frost", "eis"]),
        ("arcane", ["arcane", "arkan"]),
        ("assassination", ["assassination", "assa"]),
        ("subtlety", ["subtlety", "sub"]),
        ("combat", ["combat", "kampf"]),
        ("affliction", ["affliction", "affli", "gebrechen"]),
        ("demonology", ["demonology", "demo", "daemonologie", "dämonologie"]),
        ("destruction", ["destruction", "destro", "zerstoerung", "zerstörung"]),
        ("survival", ["survival"]),
        ("marksman", ["marksman", "marksmanship"]),
        ("beastmaster", ["beastmaster", "beast mastery", "bm"]),
        ("feral", ["feral", "wildheit"]),
        ("balance", ["balance", "eule", "moonkin", "gleichgewicht"]),
        ("elemental", ["elemental", "ele"]),
        ("enhancement", ["enhancement", "enh"]),
    ]
    for key, words in checks:
        if any(word in text for word in words):
            return key
    return ""


def signup_spec_icon(spec_text, role="", class_name=""):
    text = clean(spec_text or role).lower()
    icon_key = signup_spec_icon_key(spec_text, role, class_name)
    if icon_key and spec_emoji_cache.get(icon_key):
        return spec_emoji_cache[icon_key]
    if icon_key and SPEC_EMOJI_FALLBACKS.get(icon_key):
        return SPEC_EMOJI_FALLBACKS[icon_key]
    if any(word in text for word in ["tank", "prot", "schutz", "def"]):
        return SPEC_EMOJI_FALLBACKS["tank"]
    if any(word in text for word in ["heal", "heiler", "heilung", "holy", "resto", "restoration", "wiederherstellung", "diszi"]):
        return SPEC_EMOJI_FALLBACKS["heal"]
    if any(word in text for word in ["fire", "feuer", "flamme"]):
        return "🔥"
    if any(word in text for word in ["frost", "eis"]):
        return "❄️"
    if any(word in text for word in ["shadow", "schatten"]):
        return "🌑"
    if text in {"", "dd", "dps", "damage", "flex"} and clean(class_name):
        return class_icon(class_name)
    if any(word in text for word in ["fury", "arms", "waffen", "combat", "assa", "feral", "enh", "ele", "balance", "dd", "dps"]):
        return "⚔️"
    return "✦"


def signup_spec_select_emoji(spec_label, spec_key="", class_name=""):
    icon = signup_spec_icon(spec_label or spec_key, spec_key, class_name)
    if icon.startswith("<:") or icon.startswith("<a:"):
        try:
            return discord.PartialEmoji.from_str(icon)
        except Exception:
            return None
    return select_emoji(icon)


def raid_signup_class_options():
    labels = [
        ("Krieger", "Warrior"),
        ("Druide", "Druid"),
        ("Paladin", "Paladin"),
        ("Schurke", "Rogue"),
        ("Jäger", "Hunter"),
        ("Priester", "Priest"),
        ("Magier", "Mage"),
        ("Hexenmeister", "Warlock"),
    ]
    return [discord.SelectOption(label=label, value=value, emoji=class_select_emoji(value)) for label, value in labels]


def raid_signup_source(interaction, origin_channel_id=None, origin_message_id=None):
    return f"DiscordSignup:{origin_channel_id or interaction.channel_id}:{origin_message_id or getattr(interaction.message, 'id', '')}"


def add_raid_signup_roster_fields(embed, helper):
    rows = list((helper or {}).get("signups") or []) + list((helper or {}).get("externalSignups") or [])
    if not rows:
        embed.add_field(name="Anmeldungen", value="Noch keine Anmeldungen.", inline=False)
        add_raid_signup_links_field(embed, (helper or {}).get("raid") or {})
        return
    signup_order = sorted(
        rows,
        key=lambda row: (
            clean(row.get("createdAt") or row.get("created_at") or "9999-12-31T23:59:59"),
            clean(row.get("id")),
            clean(row.get("player") or row.get("char")).lower(),
        ),
    )
    signup_positions = {id(row): index + 1 for index, row in enumerate(signup_order)}
    raid = (helper or {}).get("raid") or {}
    active_rows = [
        row for row in rows
        if clean(row.get("status")).lower() not in {
            "absent", "abwesend", "bench", "bank",
            "late", "spät", "spaet",
            "tentative", "vorläufig", "vorlaeufig",
        }
        and clean(row.get("role")).lower() not in {"multi", "multichar", "multi-char", "multi char"}
    ]
    role_counts = {"tank": 0, "heal": 0, "melee": 0, "ranged": 0}

    def compact_signup_role(row):
        role = clean(row.get("role")).lower()
        spec = signup_spec_for_row(row)
        resolved_role = role if role in {"tank", "heal", "dd"} else infer_signup_role(spec)
        if resolved_role in {"tank", "heal"}:
            return resolved_role
        cls = canonical_signup_class(row.get("className") or row.get("klasse"))
        spec_key = clean(spec).lower()
        if cls in {"Mage", "Warlock", "Hunter", "Priest"}:
            return "ranged"
        if cls == "Druid" and any(value in spec_key for value in ("balance", "eule", "moonkin", "gleichgewicht")):
            return "ranged"
        if cls == "Shaman" and any(value in spec_key for value in ("elemental", " ele", "ele ")):
            return "ranged"
        return "melee"

    for row in active_rows:
        role_counts[compact_signup_role(row)] += 1
    tank_max = clean(raid.get("tankSlots"))
    heal_max = clean(raid.get("healSlots"))
    dd_max = clean(raid.get("ddSlots"))
    max_players = clean(raid.get("maxPlayers"))
    bank_statuses = {"bench", "bank"}
    total_signed = sum(
        1 for row in rows
        if clean(row.get("status")).lower() not in {"absent", "abwesend", *bank_statuses}
    )
    bank_count = sum(
        1 for row in rows
        if clean(row.get("status")).lower() in bank_statuses
    )
    bank_suffix = f" (+{bank_count})" if bank_count else ""
    tank_role_icon = signup_spec_icon("Tank", "tank", "Warrior")
    heal_role_icon = custom_emoji("heilung", SPEC_EMOJI_FALLBACKS["heal"])
    melee_role_icon = custom_emoji("melee", "⚔️")
    ranged_role_icon = custom_emoji("range", "🏹")
    embed.add_field(
        name="👥 Gesamt angemeldet",
        value=f"**{total_signed}{bank_suffix}{('/' + max_players) if max_players else ''}**\n\u200b",
        inline=False,
    )
    embed.add_field(
        name="Rollenverteilung",
        value=(
            f"{tank_role_icon} **Tanks {role_counts['tank']}{('/' + tank_max) if tank_max else ''}**  ·  "
            f"{melee_role_icon} **Melee {role_counts['melee']}**  ·  "
            f"{ranged_role_icon} **Ranged {role_counts['ranged']}**  ·  "
            f"{heal_role_icon} **Heiler {role_counts['heal']}{('/' + heal_max) if heal_max else ''}**\n\u200b"
        ),
        inline=False,
    )

    grouped = {}
    raid_key = normalize_raid(raid.get("raid") or "").lower()
    for row in active_rows:
        role = clean(row.get("role")).lower()
        resolved_role = role if role in {"tank", "heal", "dd"} else infer_signup_role(signup_spec_for_row(row))
        group = "Tank" if resolved_role == "tank" else canonical_signup_class(row.get("className") or row.get("klasse"))
        grouped.setdefault(group, []).append(row)
    order = ["Tank", "Warrior", "Druid", "Paladin", "Rogue", "Hunter", "Priest", "Mage", "Warlock", "Shaman", "Ohne Klasse"]
    german_class_names = {
        "Tank": "Tank",
        "Warrior": "Krieger",
        "Druid": "Druide",
        "Paladin": "Paladin",
        "Rogue": "Schurke",
        "Hunter": "Jäger",
        "Priest": "Priester",
        "Mage": "Magier",
        "Warlock": "Hexenmeister",
        "Shaman": "Schamane",
        "Ohne Klasse": "Ohne Klasse",
    }
    sorted_classes = sorted(grouped, key=lambda value: order.index(value) if value in order else 99)
    for class_index, cls in enumerate(sorted_classes):
        lines = []
        # Gleiche Skillungen stehen innerhalb einer Klasse geschlossen
        # untereinander. Die Skillungsgruppen richten sich nach der jeweils
        # frühesten Anmeldung; innerhalb jeder Gruppe gilt anschließend die
        # globale Anmeldenummer.
        def row_spec_group(row):
            spec = signup_spec_for_row(row) or clean(row.get("role")) or "Flex"
            return signup_spec_icon_key(
                spec,
                row.get("role"),
                row.get("className") or row.get("klasse") or cls,
            ) or clean(spec).casefold()

        spec_first_position = {}
        for row in grouped[cls]:
            spec_group = row_spec_group(row)
            position = signup_positions.get(id(row), 10**9)
            spec_first_position[spec_group] = min(
                position,
                spec_first_position.get(spec_group, 10**9),
            )
        class_rows = sorted(
            grouped[cls],
            key=lambda row: (
                spec_first_position.get(row_spec_group(row), 10**9),
                signup_positions.get(id(row), 10**9),
                clean(row.get("player") or row.get("char")).casefold(),
            ),
        )
        for row in class_rows[:8]:
            player = clean(row.get("player") or row.get("char")) or "-"
            position = signup_positions.get(id(row), 0)
            po_status = clean(row.get("poApprovalStatus") or row.get("po_approval_status")).lower()
            if po_status in {"approved", "freigegeben"}:
                prio_icon = f" {custom_emoji('Beutegrun', '🟢')}"
            elif po_status in {"pending", "offen", "wartet"}:
                prio_icon = f" {custom_emoji('beuteorange', '🟠')}"
            elif row.get("hasPrio") is True or clean(row.get("hasPrio")).lower() in {"1", "true", "yes", "ja"}:
                prio_icon = f" {custom_emoji('beutelilia', '🟣')}"
            else:
                prio_icon = ""
            spec = signup_spec_for_row(row) or "Flex"
            star = " ★" if any(
                row.get(key) is True or clean(row.get(key)).lower() in {"1", "true", "yes", "ja", "freigegeben"}
                for key in ("p0Released", "poReleased", "p0PlusReleased", "poPlusReleased")
            ) else ""
            lines.append(
                f"{signup_spec_icon(spec, row.get('role'), cls)} "
                f"`{position}` **{player}{star}**{prio_icon}"
            )
        embed.add_field(
            name=(
                f"{tank_role_icon if cls == 'Tank' else class_icon(cls)} "
                f"__{german_class_names.get(cls, cls)} ({len(grouped[cls])})__"
            ),
            # Discord stapelt Inline-Felder auf schmalen Handybildschirmen.
            # Die unsichtbare Schlusszeile erzeugt dort einen sauberen Abstand
            # zwischen den Klassen, ohne die Dreispaltenansicht am PC aufzulösen.
            value=(("\n".join(lines) or "\u200b") + "\n\u200b")[:1024],
            inline=True,
        )
        # Discord ordnet Inline-Felder in Dreierreihen an. Eine leere, volle
        # Zeile trennt die nächste Dreiergruppe optisch von der vorherigen.
        if (class_index + 1) % 3 == 0 and class_index + 1 < len(sorted_classes):
            embed.add_field(name="\u200b", value="\u200b", inline=False)
    status_groups = [
        ("🔄 Multi Char", {"__multi_role__"}),
        ("🪑 Bank", {"bench", "bank"}),
        ("🕒 Spät", {"late", "spät", "spaet"}),
        ("⚖️ Vorläufig", {"tentative", "vorläufig", "vorlaeufig"}),
        ("🚫 Abwesenheit", {"absent", "abwesend"}),
    ]
    def row_matches_status_group(row, statuses):
        if "__multi_role__" in statuses:
            return clean(row.get("role")).lower() in {"multi", "multichar", "multi-char", "multi char"}
        return clean(row.get("status")).lower() in statuses

    visible_status_groups = [
        (label, [row for row in rows if row_matches_status_group(row, statuses)])
        for label, statuses in status_groups
    ]
    visible_status_groups = [(label, status_rows) for label, status_rows in visible_status_groups if status_rows]
    if visible_status_groups:
        embed.add_field(name="\u200b", value="\u200b", inline=False)
    for label, status_rows in visible_status_groups:
        players = [
            f"{class_icon(canonical_signup_class(row.get('className') or row.get('klasse')))} "
            f"`{signup_positions.get(id(row), 0)}` **{clean(row.get('player') or row.get('char'))}**"
            + (
                " *(automatisch gebencht)*"
                if "automatisch gebencht" in clean(row.get("note")).casefold()
                else ""
            )
            for row in sorted(status_rows, key=lambda row: signup_positions.get(id(row), 0))
        ]
        embed.add_field(
            name=f"__{label} ({len(players)})__",
            value=("\n".join(filter(None, players)) + "\n\u200b")[:1024],
            inline=True,
        )
    add_raid_signup_links_field(embed, (helper or {}).get("raid") or {})


def normalized_prio_player_name(value):
    text = clean(value).casefold()
    for source, target in {
        "ä": "a", "ö": "o", "ü": "u", "ß": "ss",
        "á": "a", "à": "a", "â": "a", "é": "e", "è": "e", "ê": "e",
        "í": "i", "ì": "i", "ó": "o", "ò": "o", "ú": "u", "ù": "u",
    }.items():
        text = text.replace(source, target)
    return re.sub(r"[^a-z0-9]+", "", text)


def configured_discord_name_matches(configured_names, member_names):
    """Match exact Discord names and harmless display-name suffixes."""
    for configured in configured_names or set():
        if not configured:
            continue
        for member_name in member_names or set():
            if not member_name:
                continue
            if configured == member_name:
                return True
            if len(configured) >= 4 and member_name.startswith(configured):
                return True
    return False


def hydrate_helper_prio_flags(helper, guild_slug):
    if not helper or not helper.get("success"):
        return helper
    raid = helper.get("raid") or {}
    params = {
        "action": "getPublishedPrios",
        "guild": normalize_guild_slug(guild_slug),
        "guildSlug": normalize_guild_slug(guild_slug),
        "raidId": clean(raid.get("raidId") or raid.get("id")),
        "playerPin": clean(raid.get("playerPin") or raid.get("prioPin") or raid.get("raidPin")),
        "t": int(time.time()),
    }
    try:
        result = api_get(params)
        prio_players = {
            normalized_prio_player_name(row.get("player") or row.get("Spieler"))
            for row in result.get("prios") or []
            if normalized_prio_player_name(row.get("player") or row.get("Spieler"))
        }
        for row in list(helper.get("signups") or []) + list(helper.get("externalSignups") or []):
            player_key = normalized_prio_player_name(row.get("player") or row.get("char"))
            # getRaidHelper gleicht auch verbundene Raid-Datensätze ab. Eine
            # dort bereits erkannte Prio darf durch die zusätzliche Abfrage
            # eines einzelnen Raid-Datensatzes nicht wieder gelöscht werden.
            already_has_prio = (
                row.get("hasPrio") is True
                or clean(row.get("hasPrio")).lower() in {"1", "true", "yes", "ja"}
            )
            row["hasPrio"] = already_has_prio or bool(player_key and player_key in prio_players)
    except Exception as error:
        print(f"Prio-Symbole konnten nicht geladen werden: {error}")
    return helper


async def get_raid_helper_by_id(raid_id, guild_slug=None):
    resolved_guild_slug = normalize_guild_slug(guild_slug or current_guild_slug())
    helper = await asyncio.to_thread(api_get, {
        "action": "getRaidHelper",
        "guild": resolved_guild_slug,
        "guildSlug": resolved_guild_slug,
        "raidId": raid_id,
        "playerPin": raid_id,
        "t": int(time.time())
    })
    return await asyncio.to_thread(hydrate_helper_prio_flags, helper, resolved_guild_slug)


def raid_signup_row_count(helper):
    return len((helper or {}).get("signups") or []) + len((helper or {}).get("externalSignups") or [])


def raid_helper_snapshot_from_payload(payload):
    payload = payload or {}
    raid = dict(payload.get("raidSnapshot") or {})
    if not raid:
        raid_key = clean(payload.get("raid"))
        raid_id = clean(payload.get("raidId") or payload.get("id"))
        player_pin = clean(payload.get("playerPin") or payload.get("prioPin") or payload.get("raidPin"))
        raid = {
            "raidId": raid_id,
            "id": raid_id,
            "raid": raid_key,
            "raidName": display_raid(raid_key) or raid_key.upper() or "Raid",
            "raidDate": clean(payload.get("raidDate") or payload.get("date")),
            "raidTime": clean(payload.get("raidTime") or payload.get("time")),
            "discordChannelId": clean(payload.get("channelId") or payload.get("discordChannelId")),
            "playerPin": player_pin,
            "prioPin": player_pin,
            "createdBy": clean(payload.get("createdBy") or payload.get("raidlead") or payload.get("lead") or "Gildenleitung"),
            "guild": clean(payload.get("guild") or payload.get("guildSlug")),
            "guildSlug": clean(payload.get("guildSlug") or payload.get("guild")),
            "description": clean(payload.get("description")),
            "signupDeadline": clean(payload.get("signupDeadline") or payload.get("deadline")),
            "maxPlayers": clean(payload.get("maxPlayers")),
            "tankSlots": clean(payload.get("tankSlots")),
            "healSlots": clean(payload.get("healSlots")),
            "ddSlots": clean(payload.get("ddSlots")),
            "raidImageUrl": clean(payload.get("raidImageUrl") or payload.get("imageUrl")),
        }
    return {
        "success": True,
        "raid": raid,
        "signups": payload.get("signups") or [],
        "externalSignups": payload.get("externalSignups") or [],
    }


async def get_raid_helper_for_refresh(payload_or_raid_id):
    if isinstance(payload_or_raid_id, dict):
        payload = payload_or_raid_id
        guild_slug = payload_guild_slug(payload)
        candidates = []
        for key in ["raidId", "id", "playerPin", "prioPin", "raidPin"]:
            value = clean(payload.get(key))
            if value and value not in candidates:
                candidates.append(value)
        for candidate in candidates:
            try:
                helper = await get_raid_helper_by_id(candidate, guild_slug)
                if helper and helper.get("success"):
                    return helper
            except Exception:
                pass
        raid = clean(payload.get("raid"))
        raid_date = clean(payload.get("raidDate"))
        if raid and raid_date:
            helper = await asyncio.to_thread(api_get, {
                "action": "getRaidHelper",
                "guild": guild_slug,
                "guildSlug": guild_slug,
                "raid": raid,
                "raidDate": raid_date,
                "raidTime": clean(payload.get("raidTime")),
                "t": int(time.time())
            })
            return await asyncio.to_thread(hydrate_helper_prio_flags, helper, guild_slug)
        return {}
    return await get_raid_helper_by_id(clean(payload_or_raid_id), current_guild_slug())


def combined_po_payload_for_message(message_id):
    wanted = clean(message_id)
    if not wanted:
        return None, None, None
    state = load_state()
    for state_key, payload in state.items():
        if (
            isinstance(payload, dict)
            and clean(payload.get("messageId")) == wanted
            and combined_raid_snapshot(payload)
        ):
            return state, state_key, dict(payload)
    return state, None, None


async def edit_raid_message_preserving_po(message, raid, helper):
    # The Discord server is the final authority for the guild when an existing
    # signup post is refreshed. This prevents incomplete queue snapshots from
    # ever applying another guild's banner or signup data to the message.
    raid = dict(raid or {})
    message_guild_slug = guild_slug_for_discord_server(
        getattr(message, "guild", None),
        payload_guild_slug(raid),
    )
    raid["guildSlug"] = message_guild_slug
    state, state_key, po_payload = combined_po_payload_for_message(getattr(message, "id", ""))
    if not po_payload:
        embed = build_raid_announcement_embed(raid)
        add_raid_signup_roster_fields(embed, helper)
        banner, _ = raid_banner_file(raid)
        if banner:
            await message.edit(embed=embed, attachments=[banner], view=RaidSignupView(raid))
        else:
            await message.edit(embed=embed, attachments=[], view=RaidSignupView(raid))
        return

    po_payload["combinedRaidSnapshot"] = raid
    po_payload["combinedRaidSignups"] = list((helper or {}).get("signups") or [])
    po_payload["combinedRaidExternalSignups"] = list((helper or {}).get("externalSignups") or [])
    state[state_key] = po_payload
    save_state(state)
    items = await items_for_payload(po_payload)
    entries = await load_entries(po_payload)
    p0plus_labels = await load_p0plus_labels(po_payload.get("raid") or "")
    embeds, view = po_message_parts(po_payload, entries, p0plus_labels, items)
    banner, _ = raid_banner_file(raid)
    if banner:
        await message.edit(embeds=embeds, attachments=[banner], view=view)
    else:
        await message.edit(embeds=embeds, attachments=[], view=view)
    register_po_view(client, po_payload, items, entries)


async def refresh_raid_signup_message_by_id(raid_id, channel_id=None, message_id=None, payload=None):
    helper = await get_raid_helper_for_refresh(payload or clean(raid_id))
    fallback_helper = raid_helper_snapshot_from_payload(payload) if payload else {}
    if raid_signup_row_count(helper) == 0 and raid_signup_row_count(fallback_helper) > 0:
        helper = fallback_helper
    if not helper or not helper.get("success"):
        raise RuntimeError("Raid-Anmelder-Refresh: Raid wurde nicht gefunden.")
    raid = dict(helper.get("raid") or {})
    payload_data = payload or {}
    payload_raid = payload_data.get("raidSnapshot") if isinstance(payload_data.get("raidSnapshot"), dict) else {}
    # Die beim Speichern vorgemerkten Werte sind der neueste Stand. Sie müssen
    # einen eventuell noch zwischengespeicherten API-Snapshot überschreiben.
    for key in (
        "raid", "raidName", "raidDate", "raidTime", "description", "createdBy",
        "maxPlayers", "tankSlots", "healSlots", "ddSlots", "signupDeadline",
        "raidImageUrl", "discordChannelId", "discordMessageId"
    ):
        value = payload_data.get(key)
        if value in (None, ""):
            value = payload_raid.get(key)
        if value not in (None, ""):
            raid[key] = value
    helper = dict(helper)
    helper["raid"] = raid
    channel_id = clean(channel_id or raid.get("discordChannelId") or raid.get("discord_channel_id"))
    message_id = clean(message_id or raid.get("discordMessageId") or raid.get("discord_message_id"))
    if not channel_id or not message_id:
        return "missing_message"
    channel = client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    try:
        message = await channel.fetch_message(int(message_id))
    except discord.NotFound:
        # Die gespeicherte ID kann auf einen inzwischen gelöschten alten
        # Raid-Helper-/Bot-Post zeigen. Der Channel-Refresh sucht danach den
        # aktuellen eigenen Anmelder und verknüpft ihn neu.
        return "missing_message"
    # Discord erlaubt nur dem ursprünglichen Autor, eine Nachricht zu ändern.
    # Alte Raidanmelder können noch auf eine Nachricht des früheren Hauptbots
    # zeigen. Solche Queue-Aufträge dürfen nicht endlos erneut versucht werden,
    # weil sie sonst Discords Rate-Limit auslösen und den ganzen Bot ausbremsen.
    if not client.user or message.author.id != client.user.id:
        print(
            "Raidanmelder Refresh verworfen: Nachricht stammt von einem anderen Bot "
            f"({message_id}, Autor {message.author.id})."
        )
        return "foreign_message"
    try:
        await edit_raid_message_preserving_po(message, raid, helper)
    except discord.Forbidden as error:
        if getattr(error, "code", None) == 50005:
            print(
                "Raidanmelder Refresh verworfen: Discord-Nachricht gehört einem anderen Bot "
                f"({message_id})."
            )
            return "foreign_message"
        raise
    print(f"Raidanmelder Refresh: {clean(raid.get('raidId') or raid_id)} mit {raid_signup_row_count(helper)} Anmeldung(en) gerendert.")
    return True


async def refresh_raid_signup_message(interaction, raid, origin_channel_id=None, origin_message_id=None, optimistic_signup=None):
    try:
        raid_lookup_id = clean((raid or {}).get("raidId") or (raid or {}).get("id"))
        raid_pin = clean((raid or {}).get("playerPin") or (raid or {}).get("prioPin"))
        guild_slug = guild_slug_for_discord_server(
            getattr(interaction, "guild", None),
            payload_guild_slug(raid or {})
        )
        # Der tatsächlich benutzte PO-Bot-Anmelder ist ab jetzt die einzige
        # aktive Discord-Quelle dieses Raids. Damit werden alte Raid-Helper-
        # Nachrichten nicht mehr mit dem neuen Anmelder vermischt.
        active_channel_id = clean(origin_channel_id or interaction.channel_id)
        active_message_id = clean(origin_message_id or getattr(interaction.message, "id", ""))
        if raid_lookup_id and active_channel_id and active_message_id:
            await asyncio.to_thread(api_post, {
                "action": "lichtbotSetRaidDiscordMessage",
                "queueToken": QUEUE_TOKEN,
                "guild": guild_slug,
                "guildSlug": guild_slug,
                "raidId": raid_lookup_id,
                "discordChannelId": active_channel_id,
                "discordMessageId": active_message_id,
            })
            raid = dict(raid or {})
            raid["discordChannelId"] = active_channel_id
            raid["discordMessageId"] = active_message_id
        helper_queries = []
        if raid_lookup_id:
            helper_queries.append({"action": "getRaidHelper", "guild": guild_slug, "guildSlug": guild_slug, "raidId": raid_lookup_id, "playerPin": raid_lookup_id, "t": int(time.time())})
            helper_queries.append({"action": "getRaidHelper", "guild": guild_slug, "guildSlug": guild_slug, "raidId": raid_lookup_id, "t": int(time.time())})
        if raid_pin and raid_pin != raid_lookup_id:
            helper_queries.append({"action": "getRaidHelper", "guild": guild_slug, "guildSlug": guild_slug, "playerPin": raid_pin, "t": int(time.time())})

        helper = None
        last_error = None
        for query_params in helper_queries:
            try:
                helper = await asyncio.to_thread(api_get, query_params)
                if helper and helper.get("success"):
                    break
            except Exception as error:
                last_error = error
        if helper is None:
            raise last_error or RuntimeError("Raid-Anmelder konnte nicht geladen werden.")
        helper = await asyncio.to_thread(hydrate_helper_prio_flags, helper, guild_slug)
        if optimistic_signup:
            helper = dict(helper)
            optimistic_user_id = clean(optimistic_signup.get("discordUserId"))
            optimistic_char = clean(optimistic_signup.get("char") or optimistic_signup.get("player")).lower()
            # Beim Charakterwechsel muss die alte Anmeldung desselben
            # Discord-Nutzers sofort aus dem gerenderten Snapshot verschwinden.
            # Die API hat sie bereits ersetzt, aber ein unmittelbar folgender
            # GET kann noch einen kurzen alten Stand liefern.
            def keep_signup(row):
                row_char = clean(row.get("char") or row.get("player")).lower()
                row_user_id = clean(row.get("discordUserId") or row.get("discord_user_id"))
                if optimistic_user_id and row_user_id == optimistic_user_id:
                    return row_char == optimistic_char
                return True

            helper["signups"] = [row for row in (helper.get("signups") or []) if keep_signup(row)]
            helper["externalSignups"] = [row for row in (helper.get("externalSignups") or []) if keep_signup(row)]
            all_rows = list(helper["signups"]) + list(helper["externalSignups"])
            matching_row = next((row for row in all_rows if clean(row.get("char") or row.get("player")).lower() == optimistic_char), None)
            if matching_row:
                database_has_prio = matching_row.get("hasPrio") is True or clean(matching_row.get("hasPrio")).lower() in {"1", "true", "yes", "ja"}
                optimistic_has_prio = optimistic_signup.get("hasPrio") is True or clean(optimistic_signup.get("hasPrio")).lower() in {"1", "true", "yes", "ja"}
                matching_row.update({key: value for key, value in optimistic_signup.items() if value not in (None, "")})
                matching_row["hasPrio"] = database_has_prio or optimistic_has_prio
            elif optimistic_char:
                helper["externalSignups"].append(optimistic_signup)
        fresh_raid = helper.get("raid") or raid or {}
        fresh_raid = dict(fresh_raid)
        fresh_raid["guildSlug"] = guild_slug
        target = getattr(interaction, "message", None)
        if origin_channel_id and origin_message_id:
            channel = client.get_channel(int(origin_channel_id)) or await client.fetch_channel(int(origin_channel_id))
            target = await channel.fetch_message(int(origin_message_id))
        if target:
            await edit_raid_message_preserving_po(target, fresh_raid, helper)
            print(f"Raidanmelder direkt aktualisiert: {clean(fresh_raid.get('raidId') or raid_lookup_id)} mit {raid_signup_row_count(helper)} Anmeldung(en).")
    except Exception as error:
        print(f"Raid-Anmelder-Message konnte nicht aktualisiert werden: {error}")
        raise


async def edit_raid_signup_message_from_helper(raid, helper, origin_channel_id=None, origin_message_id=None):
    helper = helper or {}
    fresh_raid = helper.get("raid") or raid or {}
    channel_id = clean(origin_channel_id or fresh_raid.get("discordChannelId") or fresh_raid.get("discord_channel_id"))
    message_id = clean(origin_message_id or fresh_raid.get("discordMessageId") or fresh_raid.get("discord_message_id"))
    if not channel_id or not message_id:
        raise RuntimeError("Raid-Anmelder direktes Update: Discord-Nachricht fehlt.")
    channel = client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    message = await channel.fetch_message(int(message_id))
    await edit_raid_message_preserving_po(message, fresh_raid, helper)
    print(f"Raidanmelder direkt aktualisiert: {clean(fresh_raid.get('raidId') or fresh_raid.get('id'))} mit {raid_signup_row_count(helper)} Anmeldung(en).")


async def post_raid_announcement_by_id(raid_id, channel_id=None, payload=None, force_new=False):
    payload = payload or {}
    helper = await get_raid_helper_for_refresh(payload or clean(raid_id))
    fallback_helper = raid_helper_snapshot_from_payload(payload) if payload else {}
    if (not helper or not helper.get("success")) and fallback_helper.get("raid"):
        helper = fallback_helper
    raid = helper.get("raid") if helper and helper.get("success") else None
    if not raid:
        return "stale"
    raid = dict(raid)
    payload_raid = payload.get("raidSnapshot") if isinstance(payload.get("raidSnapshot"), dict) else {}
    for key in (
        "raid", "raidName", "raidDate", "raidTime", "createdBy", "guild", "guildSlug", "guildName",
        "maxPlayers", "tankSlots", "healSlots", "ddSlots", "description", "raidImageUrl",
        "lootMaster", "pluendermeister", "statusNotifyTargets"
    ):
        value = payload.get(key)
        if value in (None, ""):
            value = payload_raid.get(key)
        if value not in (None, ""):
            raid[key] = value
    channel_id = clean(channel_id or raid.get("discordChannelId") or raid.get("discord_channel_id"))
    if not channel_id:
        raise RuntimeError("Raid-Ankuendigung: Kein Channel hinterlegt.")
    channel = client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    existing_message_id = "" if force_new else clean(
        payload.get("messageId")
        or payload.get("discordMessageId")
        or raid.get("discordMessageId")
        or raid.get("discord_message_id")
    )
    if existing_message_id:
        try:
            existing_message = await channel.fetch_message(int(existing_message_id))
            await edit_raid_message_preserving_po(existing_message, raid, helper)
            await asyncio.to_thread(api_post, {
                "action": "lichtbotSetRaidDiscordMessage",
                "queueToken": QUEUE_TOKEN,
                "guild": payload_guild_slug(raid),
                "guildSlug": payload_guild_slug(raid),
                "raidId": clean(raid.get("raidId") or raid.get("id") or raid_id),
                "discordChannelId": channel_id,
                "discordMessageId": existing_message_id
            })
            print(f"Bestehender Raidanmelder aktualisiert: {raid_id} in {channel_id}/{existing_message_id}")
            return True
        except (discord.NotFound, discord.Forbidden):
            print(f"Bestehender Raidanmelder nicht erreichbar, erstelle neu: {raid_id} in {channel_id}/{existing_message_id}")
    embed = build_raid_announcement_embed(raid)
    add_raid_signup_roster_fields(embed, helper)
    banner, _ = raid_banner_file(raid)
    try:
        if banner:
            message = await send_silent(channel, embed=embed, file=banner, view=RaidSignupView(raid))
        else:
            message = await send_silent(channel, embed=embed, view=RaidSignupView(raid))
    except discord.HTTPException:
        message = await send_silent(channel, build_raid_announcement_text(raid))
    if message:
        await asyncio.to_thread(api_post, {
            "action": "lichtbotSetRaidDiscordMessage",
            "queueToken": QUEUE_TOKEN,
            "guild": payload_guild_slug(raid),
            "guildSlug": payload_guild_slug(raid),
            "raidId": clean(raid.get("raidId") or raid.get("id") or raid_id),
            "discordChannelId": channel_id,
            "discordMessageId": str(message.id)
        })
        # Nach der Umstellung auf die neue Message-ID erneut laden: Der erste
        # Snapshot kann noch alte Raid-Helper-Zeilen enthalten haben. Der
        # zweite Snapshot wird bereits strikt auf den neuen PO-Bot-Post gefiltert.
        fresh_helper = await get_raid_helper_for_refresh({
            **raid,
            "raidId": clean(raid.get("raidId") or raid.get("id") or raid_id),
            "discordChannelId": channel_id,
            "discordMessageId": str(message.id),
        })
        if fresh_helper and fresh_helper.get("success"):
            await edit_raid_message_preserving_po(message, fresh_helper.get("raid") or raid, fresh_helper)
    return True


class RaidSignupPinModal(discord.ui.Modal, title="Mein SpielerLogin/PIN"):
    player_pin = discord.ui.TextInput(
        label="Mein SpielerLogin/PIN",
        placeholder="Dein SpielerLogin/PIN",
        max_length=20
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
        player_pin = clean(self.player_pin.value)
        guild_slug = payload_guild_slug(payload_for_interaction(self.raid, interaction))
        try:
            result = await asyncio.to_thread(api_get, {
                "action": "getCharactersByPin",
                "guild": guild_slug,
                "guildSlug": guild_slug,
                "pin": player_pin,
                "playerPin": player_pin,
                "t": int(time.time())
            })
            characters = result if isinstance(result, list) else (result.get("characters") or result.get("chars") or [])
            characters = [entry for entry in characters if clean(entry.get("name"))]
            if not characters:
                await interaction.response.send_message("⚠️ Für diesen SpielerLogin/PIN wurden keine Charaktere gefunden.", ephemeral=True)
                return
            await interaction.response.send_message(
                "Charakter für die Anmeldung wählen:",
                view=RaidSignupCharacterView(
                    self.raid,
                    self.class_name,
                    self.spec_label,
                    self.spec_key,
                    player_pin,
                    characters,
                    self.origin_channel_id,
                    self.origin_message_id
                ),
                ephemeral=True
            )
        except Exception as error:
            await interaction.response.send_message(f"⚠️ SpielerLogin/PIN konnte nicht geladen werden: {error}", ephemeral=True)


class RaidSignupCharacterSelect(discord.ui.Select):
    def __init__(self, raid, class_name, spec_label, spec_key, player_pin, characters, origin_channel_id=None, origin_message_id=None):
        self.raid = raid
        self.class_name = class_name
        self.spec_label = spec_label
        self.spec_key = spec_key
        self.player_pin = player_pin
        self.characters = list(characters or [])[:25]
        self.origin_channel_id = origin_channel_id
        self.origin_message_id = origin_message_id
        options = []
        for index, character in enumerate(self.characters):
            char_class = canonical_signup_class(character.get("className") or character.get("Klasse") or character.get("class_name") or class_name)
            label = clean(character.get("name"))
            server = clean(character.get("server"))
            description = " · ".join(part for part in [server, class_display_name(char_class)] if part)[:100]
            options.append(discord.SelectOption(
                label=label[:100],
                value=str(index),
                description=description,
                emoji=class_select_emoji(char_class)
            ))
        super().__init__(placeholder="Charakter wählen", min_values=1, max_values=1, options=options)

    async def callback(self, interaction):
        character = self.characters[int(self.values[0])]
        char_name = clean(character.get("name"))
        server = clean(character.get("server"))
        char_class = canonical_signup_class(character.get("className") or character.get("Klasse") or character.get("class_name") or self.class_name)
        guild_slug = payload_guild_slug(payload_for_interaction(self.raid, interaction))
        signup_status = "signed"
        signup_note = f"Skillung: {self.spec_label}"
        automatically_benched = False
        try:
            capacity_helper = await get_raid_helper_for_refresh(self.raid)
            capacity_raid = (capacity_helper or {}).get("raid") or self.raid
            maximum = int(clean(capacity_raid.get("maxPlayers") or capacity_raid.get("max_players") or "0") or 0)
            capacity_rows = list((capacity_helper or {}).get("signups") or []) + list((capacity_helper or {}).get("externalSignups") or [])
            wanted_user = str(interaction.user.id)
            existing_signup = any(
                clean(row.get("discordUserId")) == wanted_user
                or clean(row.get("char") or row.get("player")).casefold() == char_name.casefold()
                for row in capacity_rows
            )
            occupied = sum(
                1 for row in capacity_rows
                if clean(row.get("status")).lower() not in {
                    "absent", "abwesend", "bench", "bank"
                }
                and clean(row.get("role")).lower() not in {
                    "multi", "multichar", "multi-char", "multi char"
                }
            )
            if maximum > 0 and occupied >= maximum and not existing_signup:
                signup_status = "bench"
                signup_note = f"Skillung: {self.spec_label} (automatisch gebencht)"
                automatically_benched = True
        except Exception as error:
            print(f"Automatische Bench-Prüfung konnte nicht durchgeführt werden: {error}")
        result = await asyncio.to_thread(api_post, {
            "action": "saveRaidSignup",
            "queueToken": QUEUE_TOKEN,
            "guild": guild_slug,
            "guildSlug": guild_slug,
            "raidId": clean(self.raid.get("raidId") or self.raid.get("id")),
            "playerPin": self.player_pin,
            "pin": self.player_pin,
            "char": char_name,
            "player": char_name,
            "server": server,
            "raid": self.raid.get("raid") or self.raid.get("raidName") or "",
            "raidDate": self.raid.get("raidDate") or "",
            "raidTime": self.raid.get("raidTime") or "",
            "role": infer_signup_role(self.spec_label),
            "signupRole": infer_signup_role(self.spec_label),
            "status": signup_status,
            "signupStatus": signup_status,
            "specialization": self.spec_label,
            "skillung": self.spec_label,
            "note": signup_note,
            "discordUserId": str(interaction.user.id),
            "discordName": str(interaction.user.display_name),
            "source": raid_signup_source(interaction, self.origin_channel_id, self.origin_message_id)
        })
        if not result.get("success"):
            await interaction.response.send_message(f"⚠️ Anmeldung fehlgeschlagen: {result.get('error') or 'unbekannter Fehler'}", ephemeral=True)
            return
        saved_signup = result.get("signup") or {}
        saved_status = clean(saved_signup.get("status") or signup_status).lower()
        if result.get("automaticallyBenched") is True or saved_status in {"bench", "bank"} and "automatisch gebencht" in clean(saved_signup.get("note") or signup_note).casefold():
            automatically_benched = True
            signup_status = "bench"
            signup_note = clean(saved_signup.get("note") or signup_note)
        refresh_raid = dict(self.raid)
        if result.get("raid"):
            refresh_raid.update(result.get("raid") or {})
        if result.get("raidId"):
            refresh_raid["raidId"] = result.get("raidId")
        await interaction.response.edit_message(
            content=(
                f"✅ Anmeldung gespeichert: **{char_name}** · {class_display_name(char_class)} · {self.spec_label}"
                + (" **(automatisch gebencht)**" if automatically_benched else "")
            ),
            view=None
        )
        if automatically_benched:
            await send_raid_player_status_confirmation(
                interaction, refresh_raid, char_name, "bench", "automatisch gebencht"
            )
        else:
            await send_raid_signup_confirmation(
                interaction,
                refresh_raid,
                char_name,
                char_class,
                self.spec_label
            )
        await send_raid_staff_action_notice(
            interaction,
            refresh_raid,
            char_name,
            "bench" if automatically_benched else "signed",
            (
                "automatisch gebencht"
                if automatically_benched
                else f"{class_display_name(char_class)} · {self.spec_label}"
            ),
        )
        try:
            await refresh_raid_signup_message(
                interaction,
                refresh_raid,
                self.origin_channel_id,
                self.origin_message_id,
                {
                    "char": char_name,
                    "player": char_name,
                    "className": char_class,
                    "klasse": char_class,
                    "hasPrio": bool((result.get("signup") or {}).get("hasPrio")),
                    "role": infer_signup_role(self.spec_label),
                    "status": signup_status,
                    "specialization": self.spec_label,
                    "skillung": self.spec_label,
                    "note": signup_note,
                    "discordUserId": str(interaction.user.id),
                    "discordName": str(interaction.user.display_name),
                    "source": raid_signup_source(interaction, self.origin_channel_id, self.origin_message_id),
                },
            )
        except Exception as error:
            print(f"Raid-Anmelder direkter Refresh nach Anmeldung fehlgeschlagen, nutze Snapshot-Fallback: {error}")
            try:
                helper = result.get("helper") or {
                    "success": True,
                    "raid": result.get("raid") or refresh_raid,
                    "signups": result.get("signups") or [],
                    "externalSignups": result.get("externalSignups") or [],
                }
                await edit_raid_signup_message_from_helper(refresh_raid, helper, self.origin_channel_id, self.origin_message_id)
            except Exception as fallback_error:
                print(f"Raid-Anmelder Snapshot-Fallback fehlgeschlagen: {fallback_error}")
        try:
            refresh_guild_slug = payload_guild_slug(refresh_raid)
            await asyncio.to_thread(api_post, {
                "action": "guildQueueRaidAnnouncementRefresh",
                "queueToken": QUEUE_TOKEN,
                "guild": refresh_guild_slug,
                "guildSlug": refresh_guild_slug,
                "raidId": clean(refresh_raid.get("raidId") or refresh_raid.get("id")),
                "playerPin": clean(refresh_raid.get("playerPin") or refresh_raid.get("prioPin") or ""),
                "prioPin": clean(refresh_raid.get("playerPin") or refresh_raid.get("prioPin") or ""),
                "raid": clean(refresh_raid.get("raid") or ""),
                "raidDate": clean(refresh_raid.get("raidDate") or ""),
                "raidTime": clean(refresh_raid.get("raidTime") or ""),
                "channelId": clean(self.origin_channel_id or interaction.channel_id),
                "messageId": clean(self.origin_message_id or getattr(interaction.message, "id", ""))
            })
        except Exception as error:
            print(f"Raid-Anmelder Queue-Refresh nach Anmeldung fehlgeschlagen: {error}")


class RaidSignupCharacterView(discord.ui.View):
    def __init__(self, raid, class_name, spec_label, spec_key, player_pin, characters, origin_channel_id=None, origin_message_id=None):
        super().__init__(timeout=180)
        self.add_item(RaidSignupCharacterSelect(raid, class_name, spec_label, spec_key, player_pin, characters, origin_channel_id, origin_message_id))
        self.add_item(RaidSignupAccountSwitchButton(
            raid,
            class_name,
            spec_label,
            spec_key,
            origin_channel_id,
            origin_message_id,
        ))


class RaidSignupAccountSwitchButton(discord.ui.Button):
    def __init__(self, raid, class_name, spec_label, spec_key, origin_channel_id=None, origin_message_id=None):
        super().__init__(
            label="Anderen LichtLoot-Account verwenden",
            style=discord.ButtonStyle.secondary,
            emoji="🔄",
        )
        self.raid = raid
        self.class_name = class_name
        self.spec_label = spec_label
        self.spec_key = spec_key
        self.origin_channel_id = origin_channel_id
        self.origin_message_id = origin_message_id

    async def callback(self, interaction):
        await interaction.response.send_modal(RaidSignupPinModal(
            self.raid,
            self.class_name,
            self.spec_label,
            self.spec_key,
            self.origin_channel_id,
            self.origin_message_id,
        ))


class RaidSignupModal(discord.ui.Modal, title="Raid anmelden"):
    char_name = discord.ui.TextInput(label="Charaktername", placeholder="z. B. Ariee", max_length=40)

    def __init__(self, raid, class_name, spec_label, spec_key, origin_channel_id=None, origin_message_id=None):
        super().__init__()
        self.raid = raid
        self.class_name = class_name
        self.spec_label = spec_label
        self.spec_key = spec_key
        self.origin_channel_id = origin_channel_id
        self.origin_message_id = origin_message_id

    async def on_submit(self, interaction):
        await interaction.response.send_message(
            "Bitte nutze die neue Anmeldung mit SpielerLogin/PIN und Charakter-Auswahl.",
            ephemeral=True
        )


class RaidSignupSpecSelect(discord.ui.Select):
    def __init__(self, raid, class_name, origin_channel_id=None, origin_message_id=None):
        self.raid = raid
        self.class_name = class_name
        self.origin_channel_id = origin_channel_id
        self.origin_message_id = origin_message_id
        options = [
            discord.SelectOption(label=label, value=key, emoji=signup_spec_select_emoji(label, key, class_name))
            for label, key in RAID_SIGNUP_SPECS.get(class_name, [("Flex", "flex")])
        ]
        super().__init__(placeholder=f"Skillung wählen", min_values=1, max_values=1, options=options)

    async def callback(self, interaction):
        spec_key = self.values[0]
        spec_label = next((label for label, key in RAID_SIGNUP_SPECS.get(self.class_name, []) if key == spec_key), spec_key)
        characters = await load_po_linked_characters(interaction.user.id, self.raid)
        matching_characters = [
            character for character in characters
            if canonical_signup_class(character.get("className")) == self.class_name
        ]
        if matching_characters:
            player_pin = clean(matching_characters[0].get("playerPin"))
            await interaction.response.send_message(
                "Charakter für die Anmeldung wählen:",
                view=RaidSignupCharacterView(
                    self.raid,
                    self.class_name,
                    spec_label,
                    spec_key,
                    player_pin,
                    matching_characters,
                    self.origin_channel_id,
                    self.origin_message_id,
                ),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(RaidSignupPinModal(self.raid, self.class_name, spec_label, spec_key, self.origin_channel_id, self.origin_message_id))


class RaidSignupSpecView(discord.ui.View):
    def __init__(self, raid, class_name, origin_channel_id=None, origin_message_id=None):
        super().__init__(timeout=180)
        self.add_item(RaidSignupSpecSelect(raid, class_name, origin_channel_id, origin_message_id))


class RaidSignupClassSelect(discord.ui.Select):
    def __init__(self, raid):
        self.raid = raid
        super().__init__(custom_id="raid_signup_class_select", placeholder="Klasse wählen und Charakter anmelden", min_values=1, max_values=1, options=raid_signup_class_options())

    async def callback(self, interaction):
        class_name = self.values[0]
        class_label = class_display_name(class_name)
        await interaction.response.send_message(f"Skillung für **{class_label}** wählen:", view=RaidSignupSpecView(self.raid, class_name, interaction.channel_id, getattr(interaction.message, "id", "")), ephemeral=True)


class RaidSignupStatusModal(discord.ui.Modal):
    char_name = discord.ui.TextInput(label="Charaktername", placeholder="z. B. Ariee", max_length=40)
    note = discord.ui.TextInput(
        label="Notiz optional",
        placeholder="z. B. Arbeit, später da, Ersatzbank",
        required=False,
        max_length=100,
    )

    def __init__(self, raid, status, title):
        super().__init__(title=title)
        self.raid = raid
        self.status = status

    async def on_submit(self, interaction):
        char_name = clean(self.char_name.value)
        note = clean(self.note.value)
        if not char_name:
            await interaction.response.send_message("Bitte Charaktername angeben.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            helper = await get_raid_helper_for_refresh(self.raid)
            wanted_user = str(interaction.user.id)
            wanted_source = raid_signup_source(interaction)
            existing = next((
                row for row in (helper.get("externalSignups") or []) + (helper.get("signups") or [])
                if clean(row.get("char") or row.get("player")).lower() == char_name.lower()
                and (
                    clean(row.get("discordUserId")) == wanted_user
                    or clean(row.get("source")) == wanted_source
                )
            ), None)
            existing = existing or {}
            existing_note = clean(existing.get("note"))
            if self.status == "bench":
                saved_note = note or existing_note or "Bank"
            elif self.status == "late":
                saved_note = f"Spät: {note}" if note else (existing_note or "Spät")
            elif self.status == "multi":
                saved_note = note or existing_note or "Multi Char"
            elif self.status == "absent":
                saved_note = note or existing_note or "Abwesend"
            else:
                saved_note = note or existing_note
            result = await asyncio.to_thread(api_post, {
                "action": "saveDiscordSignupRows",
                "queueToken": QUEUE_TOKEN,
                "guild": payload_guild_slug(self.raid),
                "guildSlug": payload_guild_slug(self.raid),
                "raidId": clean(self.raid.get("raidId") or self.raid.get("id")),
                "raid": clean(self.raid.get("raid") or self.raid.get("raidName")),
                "raidDate": clean(self.raid.get("raidDate")),
                "raidTime": clean(self.raid.get("raidTime")),
                "discordChannelId": str(interaction.channel_id or ""),
                "raidHelperMessageId": str(getattr(interaction.message, "id", "") or ""),
                "rows": [{
                    "char": char_name,
                    "spieler": char_name,
                    "klasse": clean(existing.get("className") or existing.get("klasse")),
                    "role": "multi" if self.status == "multi" else (clean(existing.get("role")) or infer_signup_role(note)),
                    "status": "signed" if self.status == "multi" else self.status,
                    "note": saved_note,
                    "discordUserId": wanted_user,
                    "discordName": str(interaction.user.display_name),
                    "source": raid_signup_source(interaction),
                }],
            })
            if not result.get("success"):
                raise RuntimeError(result.get("error") or "Status konnte nicht gespeichert werden.")
            fresh_raid = (helper or {}).get("raid") or self.raid
            label = {
                "bench": "auf die Bank gesetzt",
                "late": "als verspätet markiert",
                "multi": "als Multi Char angemeldet",
                "tentative": "als vorläufig markiert",
                "absent": "als abwesend markiert",
            }.get(self.status, "aktualisiert")
            await interaction.followup.send(f"✅ **{char_name}** wurde {label}.", ephemeral=True)
            await send_raid_player_status_confirmation(interaction, fresh_raid, char_name, self.status, note)
            await send_raid_staff_action_notice(interaction, fresh_raid, char_name, self.status, note)
            await refresh_raid_signup_message(interaction, self.raid)
        except Exception as error:
            await interaction.followup.send(f"⚠️ Status konnte nicht geändert werden: {error}", ephemeral=True)


class RaidSignupChangeView(discord.ui.View):
    def __init__(self, raid):
        super().__init__(timeout=180)
        self.add_item(RaidSignupClassSelect(raid))


class RaidSignupView(discord.ui.View):
    def __init__(self, raid):
        super().__init__(timeout=None)
        self.raid = raid
        self.add_item(RaidSignupClassSelect(raid))

    @discord.ui.button(label="Bank", emoji="🪑", style=discord.ButtonStyle.secondary, custom_id="raid_signup_bench")
    async def bench_signup(self, interaction, button):
        await interaction.response.send_modal(RaidSignupStatusModal(self.raid, "bench", "Auf die Bank setzen"))

    @discord.ui.button(label="Spät", emoji="🕒", style=discord.ButtonStyle.secondary, custom_id="raid_signup_late")
    async def late_signup(self, interaction, button):
        await interaction.response.send_modal(RaidSignupStatusModal(self.raid, "late", "Verspätung eintragen"))

    @discord.ui.button(label="Multi Char", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="raid_signup_multi")
    async def multi_signup(self, interaction, button):
        await interaction.response.send_modal(RaidSignupStatusModal(self.raid, "multi", "Als Multi Char anmelden"))

    @discord.ui.button(label="Vorläufig", emoji="⚖️", style=discord.ButtonStyle.secondary, custom_id="raid_signup_tentative")
    async def tentative_signup(self, interaction, button):
        await interaction.response.send_modal(RaidSignupStatusModal(self.raid, "tentative", "Vorläufig anmelden"))

    @discord.ui.button(label="Abwesenheit", emoji="🚫", style=discord.ButtonStyle.secondary, custom_id="raid_signup_absent")
    async def absent_signup(self, interaction, button):
        await interaction.response.send_modal(RaidSignupStatusModal(self.raid, "absent", "Als abwesend markieren"))

    @discord.ui.button(label="Ändern", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id="raid_signup_change")
    async def change_signup(self, interaction, button):
        await interaction.response.send_message(
            "Wähle deine Klasse, um Charakter oder Skillung zu ändern:",
            view=RaidSignupChangeView(self.raid),
            ephemeral=True,
        )


async def restore_active_raid_signup_views():
    await client.wait_until_ready()
    try:
        result = await asyncio.to_thread(api_get, {"action": "getActiveRaids", "t": int(time.time())})
        restored = 0
        refreshed = 0
        for raid in result.get("allRaids") or result.get("raids") or []:
            channel_id = clean(raid.get("discordChannelId") or raid.get("discord_channel_id"))
            message_id = clean(raid.get("discordMessageId") or raid.get("discord_message_id"))
            if channel_id and message_id:
                client.add_view(RaidSignupView(raid), message_id=int(message_id))
                restored += 1
                try:
                    result_state = await refresh_raid_signup_message_by_id(
                        clean(raid.get("raidId") or raid.get("id")),
                        channel_id,
                        message_id,
                        raid,
                    )
                    if result_state not in {"missing_message", "foreign_author"}:
                        refreshed += 1
                except Exception as error:
                    print(f"Raid-Anmelder konnte beim Start nicht neu gerendert werden ({message_id}): {error}")
                await asyncio.sleep(0.35)
        print(f"Raid-Anmelder-Views im PO-Bot wiederhergestellt: {restored}, mit Application-Emojis aktualisiert: {refreshed}.")
    except Exception as error:
        print(f"Raid-Anmelder-Views konnten beim PO-Bot-Start nicht wiederhergestellt werden: {error}")


async def sync_accessible_discord_channels():
    if not QUEUE_TOKEN:
        print("PO Discord-Channel-Sync uebersprungen: LICHTBOT_QUEUE_TOKEN fehlt.")
        return {"success": False, "error": "LICHTBOT_QUEUE_TOKEN fehlt."}

    await refresh_guild_registry()
    channels_by_guild = {}
    for guild in client.guilds:
        guild_slug = guild_slug_for_discord_server(guild, "")
        if not guild_slug:
            if not DISCORD_GUILD_SLUGS:
                guild_slug = GUILD_SLUG
            else:
                print(f"PO Discord-Channel-Sync: Server {guild.name} ({guild.id}) ist keiner LichtLoot-Gilde zugeordnet, uebersprungen.")
                continue

        member = guild.me or guild.get_member(client.user.id)
        if member is None:
            continue

        for channel in getattr(guild, "text_channels", []):
            permissions = channel.permissions_for(member)
            if not permissions.view_channel or not permissions.send_messages:
                continue
            channels_by_guild.setdefault(normalize_guild_slug(guild_slug), []).append({
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
            result = await asyncio.to_thread(api_post, {
                "action": "lichtbotSaveDiscordChannels",
                "queueToken": QUEUE_TOKEN,
                "channels": channels
            })
            saved = int(result.get("saved", 0) or 0)
            total_saved += saved
            results[guild_slug] = saved
            print(f"PO Discord-Channel-Sync gespeichert: {saved} Channels fuer {guild_slug}.")
        finally:
            CURRENT_GUILD_SLUG.reset(token)

    return {"success": True, "saved": total_saved, "guilds": results}


async def discord_channel_sync_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            await sync_accessible_discord_channels()
        except Exception as error:
            print(f"PO Discord-Channel-Sync Fehler: {error}")
        await asyncio.sleep(300)


def api_get(params):
    guild_slug = normalize_guild_slug((params or {}).get("guild") or (params or {}).get("guildSlug") or current_guild_slug())
    query_params = {**(params or {}), "guild": guild_slug, "guildSlug": guild_slug}
    query = urllib.parse.urlencode(query_params)
    url = API_URL + "?" + query
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return parse_api_response(response, "GET", url)
    except urllib.error.HTTPError as error:
        try:
            raw = error.read().decode("utf-8")
            parsed = json.loads(raw)
            detail = parsed.get("error") or raw
        except Exception:
            detail = error.reason or str(error)
        raise RuntimeError(f"HTTP Error {error.code}: {detail}") from error


def api_post(payload):
    guild_slug = payload_guild_slug(payload)
    data = json.dumps({**(payload or {}), "guild": guild_slug, "guildSlug": guild_slug}).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return parse_api_response(response, "POST", API_URL)
    except urllib.error.HTTPError as error:
        try:
            raw = error.read().decode("utf-8")
            parsed = json.loads(raw)
            detail = parsed.get("error") or raw
        except Exception:
            detail = error.reason or str(error)
        raise RuntimeError(f"HTTP Error {error.code}: {detail}") from error


def parse_api_response(response, method, url):
    raw = response.read().decode("utf-8")
    content_type = response.headers.get("Content-Type", "")
    if "json" not in content_type.lower() and raw.lstrip().startswith("<"):
        raise RuntimeError(f"LichtLoot API {method} liefert HTML statt JSON. Bitte API-URL pruefen: {url}")
    return json.loads(raw)


def payload_lichtloot_raid_pin(payload):
    return clean(
        payload.get("lichtlootPlayerPin")
        or payload.get("playerPin")
        or payload.get("lichtlootRaidId")
        or payload.get("raidPin")
        or payload.get("prioPin")
    )


def payload_with_lichtloot_id(payload):
    raid_pin = payload_lichtloot_raid_pin(payload)
    if not raid_pin:
        return dict(payload or {})
    return {
        **(payload or {}),
        "lichtlootPlayerPin": raid_pin,
        "playerPin": raid_pin,
        "lichtlootRaidId": raid_pin,
        "raidPin": raid_pin,
        "prioPin": raid_pin,
    }


def payload_with_lichtloot_id_from_sources(payload, *sources):
    raid_pin = payload_lichtloot_raid_pin(payload)
    if not raid_pin:
        for source in sources:
            raid_pin = payload_lichtloot_raid_pin(source or {})
            if raid_pin:
                break

    if raid_pin:
        result = payload_with_lichtloot_id({**(payload or {}), "raidPin": raid_pin})
    else:
        result = dict(payload or {})

    lead_pin = clean((payload or {}).get("lichtlootLeadPin") or (payload or {}).get("leadPin"))
    if not lead_pin:
        for source in sources:
            lead_pin = clean((source or {}).get("lichtlootLeadPin") or (source or {}).get("leadPin"))
            if lead_pin:
                break
    if lead_pin:
        result["lichtlootLeadPin"] = lead_pin
        result["leadPin"] = lead_pin

    return result


def payload_with_saved_lichtloot_id(payload):
    post_key = clean((payload or {}).get("postKey") or (payload or {}).get("poPostKey") or (payload or {}).get("postId"))
    stored = {}
    if post_key:
        state = load_state()
        stored = state.get(po_post_state_key(payload)) or state.get(post_key) or {}
    result = payload_with_lichtloot_id_from_sources(payload, stored)
    for key in ("raid", "date", "time", "title", "guildName", "guild", "createdBy", "created_by", "poRoles"):
        if not clean(result.get(key)) and clean(stored.get(key)):
            result[key] = stored.get(key)
    for target, sources in {
        "date": ("raidDate", "datum"),
        "time": ("raidTime", "uhrzeit"),
        "guildName": ("displayGuild", "gilde"),
        "createdBy": ("erstelltVon", "creator"),
    }.items():
        if clean(result.get(target)):
            continue
        for source in sources:
            if clean((payload or {}).get(source)):
                result[target] = payload.get(source)
                break
            if clean(stored.get(source)):
                result[target] = stored.get(source)
                break
    raid_date, raid_time = payload_raid_schedule(result, stored)
    if raid_date:
        result["date"] = raid_date
        result["raidDate"] = raid_date
    if raid_time:
        result["time"] = raid_time
        result["raidTime"] = raid_time
    return result


def normalize_post_date(value):
    text = clean(value)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        year, month, day = text.split("-")
        return f"{day}.{month}.{year}"
    return text


def normalize_post_time(value):
    text = clean(value)
    return re.sub(r"\s*Uhr\s*$", "", text, flags=re.I)


def po_schedule_from_post_key(payload):
    post_key = clean(
        (payload or {}).get("postKey")
        or (payload or {}).get("poPostKey")
        or (payload or {}).get("postId")
    )
    match = re.search(r"(?:^|-)(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(?:-|$)", post_key)
    if not match:
        return "", ""
    year, month, day, hour, minute = match.groups()
    return f"{year}-{month}-{day}", f"{hour}:{minute}"


def payload_raid_schedule(payload, *sources):
    candidates = [payload or {}, *(source or {} for source in sources)]
    raid_date = ""
    raid_time = ""
    for candidate in candidates:
        raid_date = raid_date or clean(candidate.get("raidDate") or candidate.get("date") or candidate.get("datum"))
        raid_time = raid_time or clean(candidate.get("raidTime") or candidate.get("time") or candidate.get("uhrzeit"))
    if not raid_date or not raid_time:
        fallback_date, fallback_time = po_schedule_from_post_key(payload)
        raid_date = raid_date or fallback_date
        raid_time = raid_time or fallback_time
    return raid_date, raid_time


def lichtloot_prio_url(payload=None):
    payload = payload or {}
    guild_slug = payload_guild_slug(payload)
    raid_key = normalize_raid(payload.get("raid") or payload.get("raidName")).lower()
    raid_key = {
        "zg-mittwoch": "zg",
        "zg-prime": "zg",
        "zg-late": "zg",
    }.get(raid_key, raid_key)
    loot_pages = {
        "mc": "mc-loot.html",
        "bwl": "bwl-loot.html",
        "aq40": "aq40-loot.html",
        "naxx": "naxx-loot.html",
        "zg": "zg-loot.html",
        "aq20": "aq20-loot.html",
        "ony": "ony-loot.html",
    }
    raid_pin = payload_lichtloot_raid_pin(payload)
    page = loot_pages.get(raid_key)
    if page and raid_pin:
        query = urllib.parse.urlencode({"guild": guild_slug, "pin": raid_pin})
        return f"{LICHTLOOT_URL.rstrip('/')}/loot/{page}?{query}"
    query = urllib.parse.urlencode({"guild": guild_slug})
    return f"{LICHTLOOT_URL.rstrip('/')}/index.html?{query}"


def guild_prio_link_icon(payload):
    guild_slug = payload_guild_slug(payload)
    if guild_slug == "nachtloot":
        return custom_emoji("GildeniconNW", "🌙")
    return custom_emoji("GildeniconLB", "⚜️")


def build_fixed_po_header(payload):
    raid_name = display_raid(payload.get("raid") or "")
    raid_date, raid_time = payload_raid_schedule(payload)
    date = normalize_post_date(raid_date)
    time_value = normalize_post_time(raid_time)
    guild_name = guild_display_name(payload=payload)
    created_by = clean(payload.get("createdBy") or payload.get("created_by") or payload.get("erstelltVon")) or "Gildenleitung"
    lichtloot_id = payload_lichtloot_raid_pin(payload)
    lines = [
        f"📣 Neuer Raid: {raid_name}",
        f"🗓️ Datum: {date or '-'}",
        f"⏰ Start: {time_value or '-'} Uhr",
        f"🏰 Gilde: {guild_name}",
        f"👤 Erstellt von: {created_by}",
        "",
        f"🔑 Prio-PIN: {lichtloot_id or '-'}",
        f"**[{guild_prio_link_icon(payload)} Hier kannst du deine P1–P3 eintragen.]({lichtloot_prio_url(payload)})**",
        "",
        "Bitte tragt eure Prios rechtzeitig ein.",
        "",
        "**LichtLoot**",
    ]
    if lichtloot_id:
        lines.append(f"ID: `{lichtloot_id}`")
    lines.append("PO wird mit LichtLoot synchronisiert.")
    lines.append(
        f"{custom_emoji('beuteorange', '🟠')} **PO eingetragen:** wartet noch auf Freigabe."
    )
    lines.append(
        f"{custom_emoji('Beutegrun', '🟢')} **PO freigegeben:** wurde durch die Gildenleitung freigegeben."
    )
    lines.append("")
    return lines


def looks_like_generated_po_header(text):
    value = clean(text)
    if not value:
        return False
    markers = [
        "Neuer Raid:",
        "Prios eintragen:",
        "Prio-PIN:",
        "Bitte tragt eure Prios rechtzeitig ein.",
    ]
    return sum(1 for marker in markers if marker in value) >= 2


def po_post_note(payload):
    note = clean(payload.get("note") or payload.get("message") or payload.get("description"))
    if looks_like_generated_po_header(note):
        return ""
    return note


def generated_pin(seed, length):
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    digest = hashlib.sha256(f"{seed}-{time.time()}".encode("utf-8")).hexdigest()
    value = int(digest, 16)
    return "".join(chars[(value >> (index * 5)) % len(chars)] for index in range(length))


def ensure_payload_lichtloot_raid(payload):
    payload = payload_with_saved_lichtloot_id(payload)
    if payload_lichtloot_raid_pin(payload):
        return payload
    prio_pin = generated_pin(payload.get("postKey") or payload.get("raid") or "po", 3)
    lead_pin = generated_pin((payload.get("postKey") or "") + "-lead", 4)
    result = api_post({
        "action": "lichtbotCreateRaid",
        "queueToken": QUEUE_TOKEN,
        "guild": payload_guild_slug(payload),
        "guildSlug": payload_guild_slug(payload),
        "raid": payload.get("raid") or "",
        "raidName": display_raid(payload.get("raid") or ""),
        "raidDate": payload.get("date") or payload.get("raidDate") or payload.get("datum") or "",
        "raidTime": payload.get("time") or payload.get("raidTime") or payload.get("uhrzeit") or "",
        "playerPin": prio_pin,
        "prioPin": prio_pin,
        "leadPin": lead_pin,
        "guildName": payload.get("guildName") or payload.get("gilde") or payload_guild_slug(payload),
        "createdBy": payload.get("createdBy") or payload.get("created_by") or payload.get("erstelltVon") or "Gildenleitung",
        "status": "geschlossen",
        "p0PlusFreigabe": "geöffnet",
        "raidHelperEnabled": "false",
        "raidId": payload.get("postKey") or "",
    })
    raid_pin = clean(result.get("playerPin") or result.get("prioPin") or prio_pin)
    canonical_raid_id = clean(
        result.get("raidId")
        or result.get("id")
        or payload.get("raidId")
        or payload.get("postKey")
        or raid_pin
    )
    return payload_with_lichtloot_id_from_sources({
        **payload,
        "raidId": canonical_raid_id,
        "lichtlootCanonicalRaidId": canonical_raid_id,
        "raidPin": raid_pin,
        "prioPin": raid_pin,
        "lichtlootRaidId": raid_pin,
        "lichtlootPlayerPin": raid_pin,
        "lichtlootLeadPin": clean(result.get("leadPin") or lead_pin),
        "leadPin": clean(result.get("leadPin") or lead_pin),
    }, result)


def save_po_signup_prio(payload, player, class_name, item, player_login="", item_id=""):
    raid_pin = payload_lichtloot_raid_pin(payload)
    if not raid_pin:
        return None

    login = clean(player_login)
    class_name = class_display_name(class_name)
    post_key = clean((payload or {}).get("postKey") or (payload or {}).get("poPostKey") or (payload or {}).get("postId"))
    if po_release_required_for_raid(payload.get("raid") or ""):
        release_check = api_post({
            "action": "lichtbotCheckPoRelease",
            "queueToken": QUEUE_TOKEN,
            "guild": payload_guild_slug(payload),
            "guildSlug": payload_guild_slug(payload),
            "postKey": post_key,
            "raid": payload.get("raid") or "",
            "player": player,
            "playerPin": login,
            "spielerLogin": login,
            "server": clean(payload.get("server")),
        })
        if release_check and release_check.get("success") and release_check.get("allowed") is False:
            return {
                "success": False,
                "error": release_check.get("message") or "du hast keine P0+ Freigabe wende dich an den Raidlead"
            }
    return api_post({
        "action": "lichtbotSavePoSignupPrio",
        "queueToken": QUEUE_TOKEN,
        "guild": payload_guild_slug(payload),
        "guildSlug": payload_guild_slug(payload),
        "postKey": post_key,
        "poPostKey": post_key,
        "raidId": post_key,
        "sourceChannelId": payload_source_channel_id(payload),
        "targetChannelId": payload_target_channel_id(payload),
        "raidPin": raid_pin,
        "prioPin": raid_pin,
        "lichtlootRaidId": raid_pin,
        "playerPin": login,
        "spielerLogin": login,
        "player": player,
        "raid": payload.get("raid") or "",
        "raidDate": payload.get("date") or payload.get("raidDate") or payload.get("datum") or "",
        "raidTime": payload.get("time") or payload.get("raidTime") or payload.get("uhrzeit") or "",
        "server": clean(payload.get("server")),
        "className": class_name,
        "item": item,
        "itemId": clean(item_id),
    })


async def load_po_linked_characters(discord_user_id, payload=None):
    if not discord_user_id:
        return []
    try:
        result = await asyncio.to_thread(api_get, {
            "action": "lichtbotGetPoLinkedCharacters",
            "queueToken": QUEUE_TOKEN,
            "guildSlug": payload_guild_slug(payload) if payload else current_guild_slug(),
            "guild": payload_guild_slug(payload) if payload else current_guild_slug(),
            "discordUserId": str(discord_user_id),
            "t": int(time.time()),
        })
    except Exception as error:
        print(f"PO bekannte Charaktere konnten nicht geladen werden ({discord_user_id}): {error}")
        return []
    chars = []
    seen = set()
    for row in result.get("characters") or result.get("entries") or []:
        name = clean(row.get("name") or row.get("player") or row.get("char"))
        pin = clean(row.get("playerPin") or row.get("pin") or row.get("spielerLogin"))
        key = f"{name.lower()}|{pin.lower()}"
        if not name or not pin or key in seen:
            continue
        seen.add(key)
        chars.append({
            "name": name,
            "server": clean(row.get("server")),
            "className": class_display_name(row.get("className") or row.get("class_name")),
            "playerPin": pin,
        })
    return chars[:25]


async def load_po_characters_by_pin(player_pin, payload=None):
    player_pin = clean(player_pin)
    if not player_pin:
        return [], ""
    try:
        result = await asyncio.to_thread(api_get, {
            "action": "getCharactersByPin",
            "queueToken": QUEUE_TOKEN,
            "guildSlug": payload_guild_slug(payload) if payload else current_guild_slug(),
            "guild": payload_guild_slug(payload) if payload else current_guild_slug(),
            "pin": player_pin,
            "t": int(time.time()),
        })
    except Exception as error:
        print(f"PO Charaktere per SpielerLogin konnten nicht geladen werden ({player_pin}): {error}")
        return [], str(error)
    if not result.get("success"):
        return [], clean(result.get("error") or "SpielerLogin konnte nicht geprüft werden.")
    chars = []
    seen = set()
    for row in result.get("characters") or result.get("entries") or result.get("chars") or []:
        name = clean(row.get("name") or row.get("player") or row.get("char"))
        server = clean(row.get("server"))
        key = f"{name.lower()}|{server.lower()}"
        if not name or key in seen:
            continue
        seen.add(key)
        chars.append({
            "name": name,
            "server": server,
            "className": class_display_name(row.get("className") or row.get("class_name")),
            "playerPin": player_pin,
        })
    return chars[:25], ""


def load_state():
    try:
        return json.loads(STATE_FILE.read_text("utf-8"))
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


def po_variant_state_key(payload, player, item_name):
    post_key = clean((payload or {}).get("postKey") or (payload or {}).get("poPostKey") or (payload or {}).get("postId"))
    guild_key = normalize_guild_slug((payload or {}).get("guildSlug") or (payload or {}).get("guild"))
    return "|".join([guild_key, post_key, slug(player), slug(item_name)])


def po_post_state_key(payload_or_key):
    if isinstance(payload_or_key, dict):
        guild_key = normalize_guild_slug(payload_or_key.get("guildSlug") or payload_or_key.get("guild"))
        post_key = clean(payload_or_key.get("postKey") or payload_or_key.get("poPostKey") or payload_or_key.get("postId"))
    else:
        guild_key = current_guild_slug()
        post_key = clean(payload_or_key)
    return f"{guild_key}:{post_key}" if post_key else ""


def remember_po_item_variant(payload, player, item):
    item_id = po_item_id_value(item)
    item_slot = clean(item.get("slot") or item.get("Slot")) if isinstance(item, dict) else ""
    item_boss = clean(item.get("boss") or item.get("Boss")) if isinstance(item, dict) else ""
    item_name = po_item_name_value(item)
    key = po_variant_state_key(payload, player, item_name)
    if not key or not item_name or not (item_id or item_slot or item_boss):
        return

    state = load_state()
    variants = state.setdefault("_poItemVariants", {})
    variants[key] = {
        "itemId": item_id,
        "itemSlot": item_slot,
        "itemBoss": item_boss,
    }
    save_state(state)


def apply_po_item_variants(payload, entries):
    variants = (load_state().get("_poItemVariants") or {})
    result = []
    for entry in entries or []:
        patched = dict(entry or {})
        if po_entry_item_id(patched) or po_entry_item_slot(patched) or po_entry_item_boss(patched):
            result.append(patched)
            continue

        key = po_variant_state_key(payload, patched.get("player"), po_entry_item_name(patched))
        stored = variants.get(key) or {}
        if stored:
            patched["itemId"] = clean(stored.get("itemId"))
            patched["itemSlot"] = clean(stored.get("itemSlot"))
            patched["itemBoss"] = clean(stored.get("itemBoss"))
        result.append(patched)
    return result


async def load_raid_items(raid):
    try:
        result = await asyncio.to_thread(api_get, {"action": "getLootItems", "raid": loot_raid(raid)})
    except Exception as error:
        print(f"Lootitems konnten nicht geladen werden ({raid}): {error}")
        return []
    seen = set()
    items = []
    for row in result.get("items") or []:
        name = clean(row.get("name") or row.get("item"))
        key = slug(name)
        if not name or key in seen:
            continue
        seen.add(key)
        items.append(name)
    items.sort(key=lambda value: value.lower())
    return items


async def load_raid_item_rows(raid):
    try:
        result = await asyncio.to_thread(api_get, {"action": "getLootItems", "raid": loot_raid(raid), "t": int(time.time())})
    except Exception as error:
        print(f"Lootitems konnten nicht geladen werden ({raid}): {error}")
        return []
    seen = set()
    rows = []
    for row in result.get("items") or []:
        name = clean(row.get("name") or row.get("item"))
        item_id = clean(row.get("itemId") or row.get("ItemID") or row.get("item_id"))
        slot = clean(row.get("slot") or row.get("Slot"))
        boss = clean(row.get("boss") or row.get("Boss"))
        key = f"{slug(name)}|{item_id}|{slug(slot)}|{slug(boss)}"
        if not name or key in seen:
            continue
        seen.add(key)
        rows.append({
            "name": name,
            "icon": clean(row.get("icon") or row.get("iconName") or row.get("IconName") or row.get("icon_url")),
            "itemId": item_id,
            "slot": slot,
            "boss": boss,
        })
    rows.sort(key=lambda value: (value["name"].lower(), value.get("slot", "").lower(), value.get("itemId", "")))
    return rows


def po_item_name_value(item):
    if isinstance(item, dict):
        return clean(item.get("name") or item.get("item") or item.get("itemName"))
    return clean(item)


def po_item_id_value(item):
    if isinstance(item, dict):
        return clean(item.get("itemId") or item.get("ItemID") or item.get("item_id"))
    return ""


def po_item_option_description(item):
    if not isinstance(item, dict):
        return ""
    parts = [
        clean(item.get("slot") or item.get("Slot")),
        clean(item.get("boss") or item.get("Boss")),
        f"ID {po_item_id_value(item)}" if po_item_id_value(item) else "",
    ]
    return " · ".join(part for part in parts if part)[:100]


def po_item_display_text(item):
    name = po_item_name_value(item)
    description = po_item_option_description(item)
    return f"{name} ({description})" if description else name


def po_entry_item_name(entry):
    return clean(entry.get("item") or entry.get("itemName")) or "Ohne Item"


def po_entry_item_id(entry):
    return clean(entry.get("itemId") or entry.get("item_id") or entry.get("poItemId") or entry.get("po_item_id"))


def po_entry_item_slot(entry):
    return clean(entry.get("itemSlot") or entry.get("item_slot") or entry.get("slot"))


def po_entry_item_boss(entry):
    return clean(entry.get("itemBoss") or entry.get("item_boss") or entry.get("boss"))


def po_entry_item_group_key(entry):
    item_id = po_entry_item_id(entry)
    if item_id:
        return f"id:{item_id}"
    return "|".join([
        slug(po_entry_item_name(entry)),
        slug(po_entry_item_slot(entry)),
        slug(po_entry_item_boss(entry)),
    ])


def is_hakkari_blade_variant(entry):
    item_id = po_entry_item_id(entry)
    if item_id in {"19865", "19866"}:
        return True
    return slug(po_entry_item_name(entry)) == "kriegsklinge-der-hakkari" and (
        po_entry_item_slot(entry) or po_entry_item_boss(entry)
    )


def po_entry_item_display(entry):
    name = po_entry_item_name(entry)
    if not is_hakkari_blade_variant(entry):
        return name
    parts = [
        po_entry_item_slot(entry),
        po_entry_item_boss(entry),
        f"ID {po_entry_item_id(entry)}" if po_entry_item_id(entry) else "",
    ]
    suffix = " · ".join(part for part in parts if part)
    return f"{name} ({suffix})" if suffix else name


def po_item_option_label(item):
    return po_item_name_value(item)[:100]


def po_item_option_key(item, index=0):
    if isinstance(item, dict):
        item_id = po_item_id_value(item)
        if item_id:
            return f"id:{item_id}"[:100]
        return f"idx:{index}:{slug(po_item_name_value(item))}"[:100]
    return po_item_name_value(item)[:100]


def resolve_po_item_selection(items, selected_value):
    selected = clean(selected_value)
    for index, item in enumerate(items or []):
        if po_item_option_key(item, index) == selected:
            return item
    for item in items or []:
        if po_item_name_value(item)[:100] == selected:
            return item
    return {"name": selected}


def download_item_icon(icon_name):
    icon = normalize_emoji_name(icon_name)
    if not icon:
        return b""
    url = f"https://wow.zamimg.com/images/wow/icons/large/{icon}.jpg"
    with urllib.request.urlopen(url, timeout=20) as response:
        data = response.read()
    if len(data) > 256 * 1024:
        raise ValueError("Icon ist größer als 256 KiB.")
    return data


async def search_raid_items(raid, query, limit=25):
    words = [word for word in slug(query).split("-") if word]
    if not words:
        return []
    matches = []
    for item in await load_raid_item_rows(raid):
        item_key = slug(" ".join([
            po_item_name_value(item),
            clean(item.get("slot") or "") if isinstance(item, dict) else "",
            clean(item.get("boss") or "") if isinstance(item, dict) else "",
            po_item_id_value(item),
        ]))
        if all(word in item_key for word in words):
            matches.append(item)
            if len(matches) >= limit:
                break
    return matches


def format_points(value):
    try:
        number = float(str(value).replace(",", "."))
        if number.is_integer():
            return str(int(number))
        return f"{number:.2f}".rstrip("0").rstrip(".")
    except Exception:
        return clean(value)


async def load_p0plus_labels(raid):
    raid_key = normalize_raid(raid)
    cached = p0plus_cache.get(raid_key)
    now = time.time()
    if cached and now - cached[0] < P0PLUS_CACHE_SECONDS:
        return cached[1]
    try:
        result = await asyncio.to_thread(api_get, {"action": "getP0Plus", "raid": raid_key, "t": int(now)})
    except Exception as error:
        print(f"P0/P0+ Punkte konnten nicht geladen werden ({raid_key}): {error}")
        return {}

    grouped = {}
    for row in result.get("entries") or []:
        item = clean(row.get("item") or row.get("itemName"))
        player = clean(row.get("player") or row.get("character") or row.get("name"))
        points = format_points(row.get("count") if row.get("count") is not None else row.get("points"))
        if not item or not player or not points or points == "0":
            continue
        item_key = slug(item)
        player_key = slug(player)
        grouped.setdefault(item_key, {})
        grouped[item_key][player_key] = f"{player} {points}"

    labels = {
        item_key: ", ".join(players[key] for key in sorted(players.keys()))
        for item_key, players in grouped.items()
        if players
    }
    p0plus_cache[raid_key] = (now, labels)
    return labels


def payload_source_channel_id(payload):
    return clean(payload.get("sourceChannelId") or payload.get("channelId"))


def payload_target_channel_id(payload):
    return clean(payload.get("targetChannelId") or payload.get("discordChannelId") or payload.get("channelId"))


async def fetch_accessible_channel(client, channel_id):
    channel_id = clean(channel_id)
    if not channel_id:
        return None
    try:
        return client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    except Exception:
        return None


def po_channel_rank(channel, payload):
    name = clean(channel.get("name") or channel.get("channelName")).lower()
    category = clean(channel.get("category") or channel.get("categoryName")).lower()
    combined = f"{category} {name}".strip()
    if "backup" in combined or "sicherung" in combined:
        return 99
    raid = normalize_raid((payload or {}).get("raid") or "")
    has_po = "po" in combined or "p0" in combined
    has_signup = "anmeld" in combined or "signup" in combined
    has_raid = bool(raid and raid.lower() in combined)

    if has_raid and has_po and has_signup:
        return 0
    if has_po and has_signup:
        return 1
    if has_raid and has_po:
        return 2
    if has_po:
        return 3
    if has_raid:
        return 4
    return 99


async def resolve_po_target_channel_id(client, payload):
    configured_channel_id = payload_target_channel_id(payload)
    if configured_channel_id and await fetch_accessible_channel(client, configured_channel_id):
        return configured_channel_id

    if configured_channel_id:
        print(f"PO-Anmelder Ziel-Channel nicht erreichbar ({payload.get('postKey')}): {configured_channel_id}")

    try:
        result = await asyncio.to_thread(api_get, {
            "action": "guildGetDiscordBotChannels",
            "queueToken": QUEUE_TOKEN,
            "t": int(time.time()),
        })
    except Exception as error:
        print(f"PO-Anmelder Channel-Fallback konnte Channel-Liste nicht laden ({payload.get('postKey')}): {error}")
        return configured_channel_id

    channels = result.get("channels") or []
    ranked = sorted(
        [channel for channel in channels if clean(channel.get("id") or channel.get("channelId"))],
        key=lambda channel: (
            po_channel_rank(channel, payload),
            clean(channel.get("category") or channel.get("categoryName")).lower(),
            clean(channel.get("name") or channel.get("channelName")).lower(),
        )
    )
    for channel in ranked:
        if po_channel_rank(channel, payload) >= 99:
            break
        channel_id = clean(channel.get("id") or channel.get("channelId"))
        if await fetch_accessible_channel(client, channel_id):
            print(
                "PO-Anmelder Channel-Fallback: "
                f"{payload.get('postKey')} nutzt #{clean(channel.get('name') or channel.get('channelName'))} ({channel_id})"
            )
            return channel_id

    return configured_channel_id


def parse_item_options(text):
    seen = set()
    items = []
    for raw in re.split(r"[\n;,]+", clean(text)):
        item = clean(raw)
        key = slug(item)
        if not item or key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


async def items_for_payload(payload):
    options = parse_item_options(payload.get("itemOptions") or payload.get("items") or payload.get("itemList"))
    if options:
        return options
    return await load_raid_item_rows(payload.get("raid") or "")


def po_entry_key(entry):
    message_id = clean((entry or {}).get("messageId") or (entry or {}).get("poMessageId"))
    if message_id:
        return f"msg:{message_id}"
    player = slug((entry or {}).get("player") or (entry or {}).get("playerName"))
    item = slug((entry or {}).get("item") or (entry or {}).get("itemName"))
    if player and item:
        return f"{player}|{item}"
    return ""


def merge_po_entries(saved_entries, fresh_entries):
    merged = {}
    for entry in fresh_entries or []:
        key = po_entry_key(entry)
        if key:
            merged[key] = dict(entry)
    for entry in saved_entries or []:
        key = po_entry_key(entry)
        if key:
            merged[key] = {**merged.get(key, {}), **dict(entry)}
    return list(merged.values())


async def load_entries(payload):
    is_repost = clean(payload.get("restoreArchived") or payload.get("repost")).lower() in {"1", "true", "yes", "ja"}
    guild_slug = payload_guild_slug(payload)
    result = await asyncio.to_thread(api_get, {
        "action": "lichtbotGetPoPostEntries",
        "queueToken": QUEUE_TOKEN,
        "guild": guild_slug,
        "guildSlug": guild_slug,
        "postKey": payload["postKey"],
        "sourceChannelId": "" if is_repost else payload_source_channel_id(payload),
        "targetChannelId": "" if is_repost else payload_target_channel_id(payload),
        "includeArchived": "true" if is_repost else "false",
        # Nach einem neuen Eintrag niemals eine zuvor zwischengespeicherte
        # leere Antwort verwenden.
        "t": int(time.time() * 1000),
    })
    entries = [
        entry for entry in (result.get("entries") or [])
        if not entry.get("configOnly")
        and (clean(entry.get("player")) or clean(entry.get("item") or entry.get("itemName")))
    ]
    # Sobald die Datenbank erfolgreich geantwortet hat, ist ihre Liste
    # vollständig und verbindlich. Insbesondere darf ein dort gelöschter
    # Eintrag nicht aus dem alten Discord-Snapshot wieder ergänzt werden.
    return apply_po_item_variants(payload, entries)


def payload_po_post_entries(payload):
    raw = (payload or {}).get("postedEntries") or (payload or {}).get("poEntries") or (payload or {}).get("entries")
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            entries = json.loads(raw)
        except Exception as error:
            print(f"Mitgesendete PO-Eintraege konnten nicht gelesen werden: {error}")
            entries = []
    else:
        entries = []
    return [
        entry for entry in entries
        if isinstance(entry, dict)
        and (clean(entry.get("player")) or clean(entry.get("item") or entry.get("itemName")))
    ]


def message_matches_post_key(message, post_key):
    if not post_key:
        return False
    if post_key in clean(getattr(message, "content", "")):
        return True
    for embed in getattr(message, "embeds", []) or []:
        if post_key in clean(getattr(embed, "title", "")) or post_key in clean(getattr(embed, "description", "")):
            return True
        for field in getattr(embed, "fields", []) or []:
            if post_key in clean(getattr(field, "name", "")) or post_key in clean(getattr(field, "value", "")):
                return True
        footer = getattr(embed, "footer", None)
        if footer and post_key in clean(getattr(footer, "text", "")):
            return True
    return False


async def find_existing_message_id(client, payload):
    try:
        entries = await load_entries(payload)
    except Exception as error:
        print(f"PO-Anmelder bestehende Nachricht konnte nicht gesucht werden ({payload.get('postKey')}): {error}")
        entries = []
    for entry in entries:
        message_id = clean(entry.get("discordMessageId") or entry.get("mainMessageId"))
        if message_id:
            return message_id
    target_channel_id = payload_target_channel_id(payload)
    post_key = clean(payload.get("postKey"))
    if not target_channel_id or not post_key:
        return ""
    try:
        channel = await fetch_accessible_channel(client, target_channel_id)
        if channel is None:
            raise RuntimeError(f"Channel nicht erreichbar: {target_channel_id}")
        async for message in channel.history(limit=100):
            if message_matches_post_key(message, post_key):
                print(f"PO-Anmelder bestehende Discord-Nachricht gefunden: {post_key} -> {message.id}")
                return str(message.id)
    except Exception as error:
        print(f"PO-Anmelder Channel-Suche fehlgeschlagen ({post_key}): {error}")
    return ""


async def deduplicate_po_messages(client, channel, payload, preferred_message=None):
    """Keep exactly one PO signup message for a post key, even after concurrent creates."""
    post_key = clean((payload or {}).get("postKey") or (payload or {}).get("poPostKey"))
    if not post_key:
        return preferred_message
    await asyncio.sleep(1.0)
    matches = []
    try:
        async for candidate in channel.history(limit=250):
            if getattr(getattr(candidate, "author", None), "id", None) != getattr(client.user, "id", None):
                continue
            if message_matches_post_key(candidate, post_key):
                matches.append(candidate)
    except Exception as error:
        print(f"PO-Anmelder Dublettenprüfung fehlgeschlagen ({post_key}): {error}")
        return preferred_message
    if not matches:
        return preferred_message
    keep = max(matches, key=lambda candidate: int(candidate.id))
    for duplicate in matches:
        if duplicate.id == keep.id:
            continue
        try:
            await duplicate.delete()
            print(f"Doppelten PO-Anmelder entfernt: {post_key} -> {duplicate.id}")
        except discord.NotFound:
            pass
        except Exception as error:
            print(f"Doppelter PO-Anmelder konnte nicht entfernt werden ({post_key}/{duplicate.id}): {error}")
    return keep


async def remember_po_message(payload):
    message_id = clean(payload.get("messageId"))
    if not message_id:
        return
    try:
        await asyncio.to_thread(api_post, {
            "action": "lichtbotSetPoPostMessage",
            "queueToken": QUEUE_TOKEN,
            "postKey": payload["postKey"],
            "sourceChannelId": payload_source_channel_id(payload),
            "targetChannelId": payload_target_channel_id(payload),
            "discordMessageId": message_id,
            "raid": payload.get("raid") or "",
            "title": payload.get("title") or "PO-Anmelder",
            "raidDate": payload.get("raidDate") or payload.get("date") or "",
            "raidTime": payload.get("raidTime") or payload.get("time") or "",
            "mode": payload.get("mode") or "signup",
            "raidPin": payload_lichtloot_raid_pin(payload),
        })
    except Exception as error:
        print(f"PO-Anmelder Nachricht-ID konnte nicht in LichtLoot gespeichert werden ({payload.get('postKey')}): {error}")


async def load_payloads_from_api_entries():
    try:
        result = await asyncio.to_thread(api_get, {
            "action": "lichtbotGetPoPostEntries",
            "queueToken": QUEUE_TOKEN,
            "includeArchived": "false",
            "t": int(time.time()),
        })
    except Exception as error:
        print(f"PO-Anmelder konnten nicht aus LichtLoot geladen werden: {error}")
        return []

    payloads = {}
    for entry in result.get("entries") or []:
        post_key = clean(entry.get("postKey"))
        message_id = clean(entry.get("discordMessageId") or entry.get("mainMessageId"))
        target_channel_id = clean(entry.get("targetChannelId"))
        source_channel_id = clean(entry.get("sourceChannelId") or target_channel_id)
        if not post_key or not message_id or not target_channel_id:
            continue
        payloads[post_key] = {
            "guildSlug": payload_guild_slug(entry),
            "postKey": post_key,
            "raid": normalize_raid(entry.get("raid")),
            "title": clean(entry.get("title")) or "PO-Anmelder",
            "sourceChannelId": source_channel_id,
            "targetChannelId": target_channel_id,
            "channelId": target_channel_id,
            "messageId": message_id,
            "date": clean(entry.get("raidDate") or entry.get("date")),
            "time": clean(entry.get("raidTime") or entry.get("time")),
            "mode": clean(entry.get("mode")) or "signup",
            "raidPin": clean(entry.get("raidPin") or entry.get("prioPin") or entry.get("lichtlootPlayerPin") or entry.get("lichtlootRaidId")),
            "prioPin": clean(entry.get("prioPin") or entry.get("raidPin") or entry.get("lichtlootPlayerPin") or entry.get("lichtlootRaidId")),
            "lichtlootRaidId": clean(entry.get("lichtlootRaidId") or entry.get("raidPin") or entry.get("prioPin") or entry.get("lichtlootPlayerPin")),
            "lichtlootPlayerPin": clean(entry.get("lichtlootPlayerPin") or entry.get("raidPin") or entry.get("prioPin") or entry.get("lichtlootRaidId")),
            "source": "lichtloot_restore",
        }
    return list(payloads.values())


async def refresh_po_view_only(client, payload):
    payload = payload_with_saved_lichtloot_id(payload)
    target_channel_id = payload_target_channel_id(payload)
    channel = client.get_channel(int(target_channel_id)) or await client.fetch_channel(int(target_channel_id))
    message = await channel.fetch_message(int(payload["messageId"]))
    items = await items_for_payload(payload)
    entries = await load_entries(payload)
    raid = combined_raid_snapshot(payload)
    view = CombinedRaidPoView(raid, payload, items, entries) if raid else PoView(payload, items, entries)
    await message.edit(view=view)
    client.add_view(view, message_id=message.id)
    return items, entries


def quick_items_for_payload(payload):
    return parse_item_options(payload.get("itemOptions") or payload.get("items") or payload.get("itemList"))


def register_po_view(client, payload, items=None, entries=None):
    payload = payload_with_saved_lichtloot_id(payload)
    message_id = clean(payload.get("messageId"))
    if not message_id:
        return False
    try:
        raid = combined_raid_snapshot(payload)
        view = (
            CombinedRaidPoView(raid, payload, items or [], entries or [])
            if raid else PoView(payload, items or [], entries or [])
        )
        client.add_view(view, message_id=int(message_id))
        return True
    except Exception as error:
        print(f"PO View konnte nicht registriert werden ({payload.get('postKey')}): {error}")
        return False


async def restore_po_view_fast(client, payload):
    register_po_view(client, payload, quick_items_for_payload(payload), [])
    try:
        items = await items_for_payload(payload)
    except Exception as error:
        print(f"PO Items konnten beim Wiederherstellen nicht geladen werden ({payload.get('postKey')}): {error}")
        items = quick_items_for_payload(payload)
    try:
        entries = await load_entries(payload)
    except Exception as error:
        print(f"PO Einträge konnten beim Wiederherstellen nicht geladen werden ({payload.get('postKey')}): {error}")
        entries = []
    register_po_view(client, payload, items, entries)
    return items, entries


def po_review_entry_options(entries):
    result = []
    seen = set()
    for idx, entry in enumerate(entries or []):
        status = clean(entry.get("approvalStatus")).lower()
        if entry.get("approved") or status in {"approved", "rejected"}:
            continue
        player = clean(entry.get("player"))
        item = clean(entry.get("item") or entry.get("itemName"))
        if not player or not item:
            continue
        key = f"{slug(player)}|{slug(item)}"
        if key in seen:
            continue
        seen.add(key)
        entry_id = clean(entry.get("id") or entry.get("entryId"))
        result.append((f"id:{entry_id}" if entry_id else str(idx), f"{player} · {item}"[:100]))
        if len(result) >= 25:
            break
    return result


def po_reject_entry_options(entries):
    return po_review_entry_options(entries)


def po_entry_options(entries, *, only_unlucked=False):
    result = []
    seen = set()
    for idx, entry in enumerate(entries or []):
        if only_unlucked and entry.get("luckBy"):
            continue
        player = clean(entry.get("player"))
        item = clean(entry.get("item") or entry.get("itemName"))
        if not player or not item:
            continue
        key = f"{slug(player)}|{slug(item)}"
        if key in seen:
            continue
        seen.add(key)
        result.append((str(idx), f"{player} · {item}"[:100]))
        if len(result) >= 25:
            break
    return result


async def reviewer_allowed(user):
    roles = list(getattr(user, "roles", []) or [])
    role_ids = {str(getattr(role, "id", "")) for role in roles}
    role_names = {normalize_role_name(getattr(role, "name", "")) for role in roles}
    member_names = {
        normalized_prio_player_name(getattr(user, "name", "")),
        normalized_prio_player_name(getattr(user, "display_name", "")),
        normalized_prio_player_name(getattr(user, "global_name", "")),
    }
    guild_slug = guild_slug_for_discord_server(getattr(user, "guild", None), current_guild_slug())
    try:
        result = await asyncio.to_thread(api_get, {
            "action": "guildGetNotificationSettings",
            "queueToken": QUEUE_TOKEN,
            "guild": guild_slug,
            "guildSlug": guild_slug,
            "t": int(time.time()),
        })
        targets = ((result or {}).get("settings") or {}).get("po_reviewers") or []
        configured_role_ids = {
            clean(target.get("value") or target.get("id"))
            for target in targets
            if clean(target.get("type")).lower() == "role"
        }
        configured_names = {
            normalized_prio_player_name(target.get("value") or target.get("name"))
            for target in targets
            if clean(target.get("type") or "name").lower() == "name"
        }
        if configured_role_ids.intersection(role_ids):
            return True
        if configured_discord_name_matches(configured_names, member_names):
            return True
        # Once this guild has an explicit selection it is authoritative. This
        # keeps Lichtbringer and Nachtloot permissions strictly separated.
        if targets:
            return False
    except Exception as error:
        print(f"PO-Freigeber-Konfiguration fuer {guild_slug} konnte nicht geladen werden: {error}")

    # Backward-compatible fallback for guilds that have not configured the new
    # setting yet.
    return bool(role_names.intersection(PO_REVIEW_ROLE_NAMES))


def has_expression_admin_permission(user):
    permissions = getattr(user, "guild_permissions", None)
    if not permissions:
        return False
    for name in [
        "administrator",
        "manage_guild",
        "manage_emojis_and_stickers",
        "manage_expressions",
        "create_expressions",
    ]:
        if bool(getattr(permissions, name, False)):
            return True
    return False


async def can_sync_item_emojis(user):
    if has_expression_admin_permission(user):
        return True
    try:
        return await reviewer_allowed(user)
    except Exception:
        return False


async def fresh_entries_for_payload(payload):
    try:
        return await load_entries(payload)
    except Exception:
        return []


async def review_entry(payload, entry, user):
    payload = payload_with_saved_lichtloot_id(payload)
    guild_slug = payload_guild_slug(payload)
    raid_pin = payload_lichtloot_raid_pin(payload)
    print(
        "PO-Freigabe suche:",
        f"guild={guild_slug}",
        f"postKey={clean(payload.get('postKey'))}",
        f"raidPin={raid_pin}",
        f"player={clean(entry.get('player'))}",
        f"item={clean(entry.get('item') or entry.get('itemName'))}",
    )
    result = await asyncio.to_thread(api_post, {
        "action": "reviewPoPostEntry",
        "queueToken": QUEUE_TOKEN,
        "guild": guild_slug,
        "guildSlug": guild_slug,
        "entryId": entry.get("id") or entry.get("entryId") or "",
        "postKey": payload["postKey"],
        "sourceChannelId": payload_source_channel_id(payload),
        "targetChannelId": payload_target_channel_id(payload),
        "messageId": entry.get("messageId") or "",
        "poMessageId": entry.get("messageId") or "",
        "discordMessageId": payload.get("messageId") or entry.get("discordMessageId") or "",
        "raidPin": raid_pin,
        "prioPin": raid_pin,
        "lichtlootRaidId": raid_pin,
        "lichtlootPlayerPin": raid_pin,
        "player": entry.get("player") or "",
        "item": entry.get("item") or entry.get("itemName") or "",
        "status": "approved",
        "approvalNoticeHandled": "true",
        "reviewer": getattr(user, "display_name", None) or getattr(user, "name", None) or str(user),
    })
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "PO-Eintrag konnte nicht freigegeben werden.")
    return result


async def reject_entry(payload, entry, user, reason=""):
    payload = payload_with_saved_lichtloot_id(payload)
    guild_slug = payload_guild_slug(payload)
    raid_pin = payload_lichtloot_raid_pin(payload)
    result = await asyncio.to_thread(api_post, {
        "action": "reviewPoPostEntry",
        "queueToken": QUEUE_TOKEN,
        "guild": guild_slug,
        "guildSlug": guild_slug,
        "entryId": entry.get("id") or entry.get("entryId") or "",
        "postKey": payload["postKey"],
        "sourceChannelId": payload_source_channel_id(payload),
        "targetChannelId": payload_target_channel_id(payload),
        "messageId": entry.get("messageId") or "",
        "poMessageId": entry.get("messageId") or "",
        "discordMessageId": payload.get("messageId") or entry.get("discordMessageId") or "",
        "raidPin": raid_pin,
        "prioPin": raid_pin,
        "lichtlootRaidId": raid_pin,
        "lichtlootPlayerPin": raid_pin,
        "player": entry.get("player") or "",
        "item": entry.get("item") or entry.get("itemName") or "",
        "status": "rejected",
        "reason": reason,
        "rejectionNoticeHandled": "true",
        "reviewer": getattr(user, "display_name", None) or getattr(user, "name", None) or str(user),
    })
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "PO-Eintrag konnte nicht abgelehnt werden.")
    return result


async def send_po_rejection_message(client, entry, reason):
    user_id = clean(entry.get("discordUserId") or entry.get("discord_user_id"))
    if not user_id:
        return False
    try:
        user = client.get_user(int(user_id)) or await client.fetch_user(int(user_id))
        player = clean(entry.get("player")) or "dein Charakter"
        item = clean(entry.get("item") or entry.get("itemName")) or "deine PO"
        text = f"❌ Deine PO für **{player}** auf **{item}** wurde abgelehnt."
        if clean(reason):
            text += f"\n\nNachricht der PO-Freigabe: {clean(reason)}"
        await user.send(text)
        return True
    except Exception as error:
        print(f"PO-Ablehnung: DM konnte nicht gesendet werden: {error}")
        return False


async def send_po_approval_message(client, entry):
    user_id = clean(entry.get("discordUserId") or entry.get("discord_user_id"))
    if not user_id:
        print(
            "PO-Freigabe: Discord-User-ID fehlt "
            f"({clean(entry.get('player')) or '?'}, {clean(entry.get('item') or entry.get('itemName')) or '?'})"
        )
        return False
    player = clean(entry.get("player")) or "dein Charakter"
    item = clean(entry.get("item") or entry.get("itemName")) or "deine PO"
    raid = display_raid(entry.get("raid") or entry.get("raidName") or "") or "Raid"
    guild_name = guild_display_name(payload=entry)
    fallback_text = (
        "✅ **Deine Item-PO wurde freigegeben**\n\n"
        f"🏰 **Gilde:** {guild_name}\n"
        f"⚔️ **Raid:** {raid}\n"
        f"👤 **Charakter:** {player}\n"
        f"🎁 **Item:** {item}\n\n"
        "Deine freigegebene PO ist jetzt für den Raid hinterlegt."
    )
    try:
        user = client.get_user(int(user_id)) or await client.fetch_user(int(user_id))
        icon = item_icon(item)
        embed = discord.Embed(
            title="✅ Deine Item-PO wurde freigegeben",
            description=f"Deine Priorität für **{item}** wurde bestätigt.",
            color=0x22C55E,
        )
        embed.add_field(name="🏰 Gilde", value=guild_name, inline=True)
        embed.add_field(name="⚔️ Raid", value=raid, inline=True)
        embed.add_field(name="👤 Charakter", value=player, inline=False)
        embed.add_field(name="🎁 Item", value=f"{icon} **{item}**", inline=False)
        emoji_match = re.match(r"<a?:[^:]+:(\d+)>", icon)
        if emoji_match:
            embed.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_match.group(1)}.png?size=128&quality=lossless")
        embed.set_footer(text="Deine freigegebene PO ist jetzt für den Raid hinterlegt.")
        await user.send(embed=embed)
        return True
    except Exception as error:
        print(
            "PO-Freigabe: Embed-DM fehlgeschlagen, Text-Fallback wird versucht: "
            f"{type(error).__name__}: {error!r}"
        )
        try:
            user = client.get_user(int(user_id)) or await client.fetch_user(int(user_id))
            await user.send(fallback_text)
            return True
        except Exception as fallback_error:
            print(
                "PO-Freigabe: Auch Text-DM fehlgeschlagen: "
                f"{type(fallback_error).__name__}: {fallback_error!r}"
            )
            return False


async def send_raid_signup_confirmation(interaction, raid, char_name, class_name, spec):
    try:
        raid_name = clean((raid or {}).get("raidName") or (raid or {}).get("raid")) or "Raid"
        raid_date = format_raid_announcement_date((raid or {}).get("raidDate") or "")
        raid_time = format_raid_announcement_time((raid or {}).get("raidTime") or "")
        raid_key = clean((raid or {}).get("raidId") or (raid or {}).get("id") or raid_name)
        cache_key = f"{interaction.user.id}:{raid_key}:{clean(char_name).lower()}"
        now = time.time()
        if now - RAID_SIGNUP_DM_CACHE.get(cache_key, 0) < 120:
            return False
        RAID_SIGNUP_DM_CACHE[cache_key] = now
        embed = discord.Embed(
            title="✅ Raidanmeldung gespeichert",
            description=f"Du bist erfolgreich für **{raid_name}** angemeldet.",
            color=0x22C55E,
        )
        embed.add_field(name="🏰 Gilde", value=guild_display_name(payload=raid), inline=True)
        embed.add_field(name="⚔️ Raid", value=raid_name, inline=True)
        embed.add_field(name="👤 Charakter", value=clean(char_name) or "-", inline=True)
        embed.add_field(name="🛡️ Klasse", value=f"{class_icon(class_name)} {class_display_name(class_name) or '-'}", inline=True)
        embed.add_field(name="✨ Skillung", value=clean(spec) or "-", inline=True)
        if raid_date != "noch offen" or raid_time != "noch offen":
            embed.add_field(name="📅 Termin", value=f"{raid_date} · {raid_time}", inline=False)
        embed.set_footer(text="Änderungen kannst du jederzeit über den Raidanmelder vornehmen.")
        await interaction.user.send(embed=embed)
        return True
    except Exception as error:
        print(f"Raid-Anmelder-DM nach Anmeldung konnte nicht gesendet werden: {error}")
        return False


def raid_signup_action_label(action):
    return {
        "signed": "angemeldet",
        "active": "aktiv angemeldet",
        "bench": "auf die Bank gesetzt",
        "late": "als verspätet markiert",
        "tentative": "als vorläufig markiert",
        "absent": "als abwesend markiert",
        "deleted": "abgemeldet",
        "removed": "aus der Anmeldung entfernt",
    }.get(clean(action).lower(), "aktualisiert")


def raid_notice_targets(raid):
    raw = (raid or {}).get("statusNotifyTargets") or (raid or {}).get("status_notify_targets") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    targets = list(raw) if isinstance(raw, list) else []
    for name in (
        (raid or {}).get("createdBy"),
        (raid or {}).get("erstelltVon"),
        (raid or {}).get("lootMaster"),
        (raid or {}).get("pluendermeister"),
    ):
        if clean(name):
            targets.append({"type": "name", "value": clean(name)})
    return targets


async def send_raid_player_status_confirmation(interaction, raid, char_name, action, note=""):
    try:
        raid_name = clean((raid or {}).get("raidName") or (raid or {}).get("raid")) or "Raid"
        raid_date = format_raid_announcement_date((raid or {}).get("raidDate") or "")
        raid_time = format_raid_announcement_time((raid or {}).get("raidTime") or "")
        embed = discord.Embed(
            title="Dein Raidstatus wurde geändert",
            description=f"**{char_name}** wurde für **{raid_name}** **{raid_signup_action_label(action)}**.",
            color=0xF59E0B,
        )
        embed.add_field(name="Raid", value=raid_name, inline=True)
        embed.add_field(name="Datum", value=raid_date, inline=True)
        embed.add_field(name="Uhrzeit", value=raid_time, inline=True)
        if clean(note):
            embed.add_field(name="Deine Notiz", value=clean(note)[:1024], inline=False)
        await interaction.user.send(embed=embed)
        return True
    except Exception as error:
        print(f"Eigene Raidstatus-DM fehlgeschlagen: {error}")
        return False


async def send_raid_staff_action_notice(interaction, raid, char_name, action, note=""):
    targets = raid_notice_targets(raid)
    wanted_names = {
        normalized_prio_player_name(target.get("value") or target.get("name"))
        for target in targets
        if clean(target.get("type") or "name").lower() == "name"
    }
    wanted_roles = {
        clean(target.get("value") or target.get("id"))
        for target in targets
        if clean(target.get("type")).lower() == "role"
    }
    wanted_roles.discard("")
    raid_name = clean((raid or {}).get("raidName") or (raid or {}).get("raid")) or "Raid"
    raid_date = format_raid_announcement_date((raid or {}).get("raidDate") or "")
    raid_time = format_raid_announcement_time((raid or {}).get("raidTime") or "")
    embed = discord.Embed(
        title="Änderung im Raidanmelder",
        description=f"**{char_name}** wurde für **{raid_name}** **{raid_signup_action_label(action)}**.",
        color=0x7C3AED,
    )
    embed.add_field(name="Raid", value=raid_name, inline=True)
    embed.add_field(name="Datum", value=raid_date, inline=True)
    embed.add_field(name="Uhrzeit", value=raid_time, inline=True)
    embed.add_field(name="Ausgeführt von", value=str(interaction.user.display_name), inline=True)
    if clean(note):
        embed.add_field(name="Hinweis", value=clean(note)[:1024], inline=False)
    guild = getattr(interaction, "guild", None)
    if not guild:
        return 0
    sent = set()
    for member in guild.members:
        if member.bot or member.id == interaction.user.id or member.id in sent:
            continue
        member_names = {
            normalized_prio_player_name(getattr(member, "name", "")),
            normalized_prio_player_name(getattr(member, "display_name", "")),
            normalized_prio_player_name(getattr(member, "global_name", "")),
        }
        member_roles = {str(role.id) for role in getattr(member, "roles", [])}
        if not (wanted_names.intersection(member_names) or wanted_roles.intersection(member_roles)):
            continue
        try:
            await member.send(embed=embed)
            sent.add(member.id)
        except Exception as error:
            print(f"Raidstatus-DM an {member} fehlgeschlagen: {error}")
    print(f"Raidstatus-DM an {len(sent)} Empfänger gesendet: {raid_name}/{char_name}/{action}")
    return len(sent)


async def send_queue_targeted_embed(payload, embed, image_path=None, show_recipients=False):
    targets = list(payload.get("targets") or payload.get("roleTargets") or [])
    wanted_names = {
        normalized_prio_player_name(target.get("value") or target.get("name"))
        for target in targets
        if clean(target.get("type") or "name").lower() == "name"
    }
    wanted_roles = {
        clean(target.get("value") or target.get("id"))
        for target in targets
        if clean(target.get("type")).lower() == "role"
    }
    wanted_roles.discard("")
    guild_slug = payload_guild_slug(payload)
    registry_entry = GUILD_REGISTRY.get(guild_slug) or {}
    discord_guild_id = clean(
        registry_entry.get("discordGuildId")
        or ({
            "lichtloot": LICHTLOOT_DISCORD_GUILD_ID,
            "nachtloot": NACHTLOOT_DISCORD_GUILD_ID,
        }.get(guild_slug) or "")
    )
    target_guild = client.get_guild(int(discord_guild_id)) if discord_guild_id.isdigit() else None
    if target_guild is None:
        guild_name = clean(payload.get("guildName") or registry_entry.get("name") or guild_slug)
        guild_name_aliases = {
            "lichtloot": {"lichtloot", "lichtbringer"},
            "nachtloot": {"nachtloot", "nachtwachter", "nachtwaechter", "nachtwächter"},
        }
        expected_names = {
            normalized_prio_player_name(value)
            for value in ({guild_slug, guild_name} | guild_name_aliases.get(guild_slug, set()))
            if clean(value)
        }
        target_guild = next(
            (
                guild for guild in client.guilds
                if any(name and name in normalized_prio_player_name(guild.name) for name in expected_names)
            ),
            None,
        )
    if target_guild is None:
        raise RuntimeError(f"Discord-Server fuer {guild_slug} wurde nicht gefunden.")
    recipients = []
    for guild in [target_guild]:
        guild_role_ids = {str(role.id) for role in guild.roles}
        if wanted_roles and not wanted_roles.intersection(guild_role_ids) and not wanted_names:
            continue
        for member in guild.members:
            if member.bot or any(existing.id == member.id for existing in recipients):
                continue
            member_names = {
                normalized_prio_player_name(getattr(member, "name", "")),
                normalized_prio_player_name(getattr(member, "display_name", "")),
                normalized_prio_player_name(getattr(member, "global_name", "")),
            }
            member_roles = {str(role.id) for role in getattr(member, "roles", [])}
            if not (configured_discord_name_matches(wanted_names, member_names) or wanted_roles.intersection(member_roles)):
                continue
            recipients.append(member)

    if show_recipients and recipients:
        recipient_names = sorted(
            {clean(getattr(member, "display_name", "")) or clean(getattr(member, "name", "")) for member in recipients},
            key=str.lower,
        )
        recipient_text = ", ".join(f"**{name}**" for name in recipient_names if name)
        if len(recipient_text) > 1024:
            recipient_text = recipient_text[:1018].rstrip(", ") + " …"
        embed.add_field(
            name=f"👥 Empfänger dieses Raids ({len(recipients)})",
            value=recipient_text or "Keine Empfänger gefunden.",
            inline=False,
        )

    sent = set()
    for member in recipients:
        try:
            if image_path and Path(image_path).is_file():
                image_file = discord.File(str(image_path), filename=Path(image_path).name)
                await member.send(embed=embed, file=image_file)
            else:
                await member.send(embed=embed)
            sent.add(member.id)
        except Exception as error:
            print(f"Raid-DM an {member} fehlgeschlagen: {error}")
    return len(sent)


async def send_player_login_approval_notice_from_queue(payload):
    guild_slug = payload_guild_slug(payload)
    registry_entry = GUILD_REGISTRY.get(guild_slug) or {}
    guild_name = guild_display_name(
        payload.get("guildName") or registry_entry.get("name") or guild_slug,
        payload,
    )
    discord_guild_id = clean(
        registry_entry.get("discordGuildId")
        or ({
            "lichtloot": LICHTLOOT_DISCORD_GUILD_ID,
            "nachtloot": NACHTLOOT_DISCORD_GUILD_ID,
        }.get(guild_slug) or "")
    )
    discord_guild = client.get_guild(int(discord_guild_id)) if discord_guild_id.isdigit() else None
    if discord_guild is None:
        guild_name_aliases = {
            "lichtloot": {"lichtloot", "lichtbringer"},
            "nachtloot": {"nachtloot", "nachtwachter", "nachtwaechter", "nachtwächter"},
        }
        expected_names = {
            normalized_prio_player_name(value)
            for value in ({guild_slug, guild_name} | guild_name_aliases.get(guild_slug, set()))
            if clean(value)
        }
        discord_guild = next(
            (
                guild for guild in client.guilds
                if any(name and name in normalized_prio_player_name(guild.name) for name in expected_names)
            ),
            None,
        )
    if discord_guild is None:
        raise RuntimeError(f"Discord-Server fuer {guild_slug} wurde nicht gefunden.")

    wanted_role_ids = {str(value) for value in (payload.get("notificationRoleIds") or []) if str(value).isdigit()}
    wanted_names = {
        normalized_prio_player_name(value)
        for value in (payload.get("notificationNames") or [])
        if clean(value)
    }
    character = clean(payload.get("character")) or "Unbekannt"
    server = clean(payload.get("server"))
    class_name = clean(payload.get("className"))
    approval_url = f"{LICHTLOOT_URL.rstrip('/')}/gildenleitung.html?" + urllib.parse.urlencode({
        "guild": guild_slug,
        "panel": "spielerlogins",
        "player": character,
    })
    character_label = f"{character}-{server}" if server else character
    default_message = "\n".join(filter(None, [
        "🔐 **Neuer SpielerLogin wartet auf Freigabe**",
        f"**Gilde:** {guild_name}",
        f"**Charakter:** {character_label}",
        f"**Klasse:** {class_name}" if class_name else "",
        "",
        "Bitte den neuen SpielerLogin in der Gildenleitung prüfen und freigeben.",
        f"🔗 **[Direkt zur Spielerfreigabe]({approval_url})**",
    ]))
    message = clean(payload.get("messageTemplate"))
    for token, value in {
        "{gilde}": guild_name,
        "{charakter}": character,
        "{server}": server,
        "{klasse}": class_name,
        "{link}": approval_url,
    }.items():
        message = message.replace(token, value)
    message = message or default_message

    members = list(getattr(discord_guild, "members", []))
    if not members:
        members = [member async for member in discord_guild.fetch_members(limit=None)]
    recipients = {}
    for member in members:
        if member.bot:
            continue
        member_names = {
            normalized_prio_player_name(getattr(member, "name", "")),
            normalized_prio_player_name(getattr(member, "display_name", "")),
            normalized_prio_player_name(getattr(member, "global_name", "")),
        }
        member_roles = {str(role.id) for role in getattr(member, "roles", [])}
        if configured_discord_name_matches(wanted_names, member_names) or wanted_role_ids.intersection(member_roles):
            recipients[member.id] = member
    if not recipients:
        raise RuntimeError(f"Keine konfigurierten Discord-Empfaenger auf {discord_guild.name} gefunden.")
    delivered = 0
    for member in recipients.values():
        try:
            await member.send(message)
            delivered += 1
        except Exception as error:
            print(f"SpielerLogin-DM an {member} fehlgeschlagen: {error}")
    if not delivered:
        raise RuntimeError("Die SpielerLogin-DM konnte keinem Empfaenger zugestellt werden.")
    print(f"SpielerLogin-Freigabehinweis fuer {guild_slug} per PO-Bot an {delivered} Empfaenger gesendet.")
    return delivered


async def send_player_login_granted_notice_from_queue(payload):
    discord_user_id = clean(payload.get("discordUserId") or payload.get("discord_user_id"))
    if not discord_user_id.isdigit():
        raise RuntimeError("SpielerLogin-Freigabe: Discord-User-ID fehlt.")

    user = client.get_user(int(discord_user_id))
    if user is None:
        user = await client.fetch_user(int(discord_user_id))

    guild_slug = payload_guild_slug(payload)
    registry_entry = GUILD_REGISTRY.get(guild_slug) or {}
    guild_name = guild_display_name(
        payload.get("guildName") or registry_entry.get("name") or guild_slug,
        payload,
    )
    character = clean(payload.get("character"))
    server = clean(payload.get("server"))
    character_label = f"{character}-{server}" if character and server else character
    start_url = f"{LICHTLOOT_URL.rstrip('/')}/start.html?" + urllib.parse.urlencode({"guild": guild_slug})

    embed = discord.Embed(
        title="✅ Dein SpielerLogin wurde freigeschaltet",
        description=(
            f"Dein SpielerLogin für **{guild_name}** wurde von der Gildenleitung freigegeben.\n\n"
            "Du kannst dich jetzt bei LichtLoot anmelden und deine Charaktere, Prios und Raidtermine verwenden."
        ),
        color=0x22C55E,
    )
    if character_label:
        embed.add_field(name="Charakter", value=character_label, inline=False)
    embed.add_field(name="LichtLoot öffnen", value=f"[Jetzt zum SpielerLogin]({start_url})", inline=False)
    embed.set_footer(text="Diese Nachricht wurde automatisch nach der Freigabe verschickt.")
    await user.send(embed=embed)
    print(f"SpielerLogin-Freigabe-DM an {user} gesendet: {guild_slug}:{character_label or discord_user_id}")
    return 1


async def send_raid_announcement_notice_from_queue(payload):
    raid_name = clean(payload.get("raidName")) or "Raid"
    raid_date = format_raid_announcement_date(payload.get("raidDate") or "")
    raid_time = format_raid_announcement_time(payload.get("raidTime") or "")
    channel_id = clean(payload.get("channelId"))
    channel_label = f"<#{channel_id}>" if channel_id else "dem vorgesehenen Raid-Channel"
    guild_icon = guild_prio_link_icon(payload)
    embed = discord.Embed(
        title=f"{guild_icon} Neuer Raidanmelder",
        description="📣 Bitte meldet euch rechtzeitig an und tragt eure Prios ein.",
        color=0x7C3AED,
    )
    embed.add_field(name="⚔️ Raid", value=raid_name, inline=True)
    embed.add_field(name="🗓️ Datum", value=raid_date, inline=True)
    embed.add_field(name="⏰ Uhrzeit", value=raid_time, inline=True)
    embed.add_field(name="Hier geht’s zu den Raidanmeldungen", value=channel_label, inline=False)
    additional_message = clean(payload.get("announcementMessage") or payload.get("notificationMessage"))
    if additional_message:
        embed.add_field(
            name="📌 Zusätzliche Informationen",
            value=additional_message[:1024],
            inline=False,
        )
    prio_url = lichtloot_prio_url(payload)
    embed.add_field(
        name="P1–P3 auf LichtLoot",
        value=f"**[{guild_icon} Hier kannst du deine P1–P3 eintragen.]({prio_url})**",
        inline=False,
    )
    guide_path = RAID_ANNOUNCEMENT_GUIDE_IMAGE_PATH
    if guide_path.is_file():
        embed.add_field(
            name="PO- & Prio-Anleitung",
            value="Die vollständige Schritt-für-Schritt-Anleitung findest du direkt unter dieser Nachricht.",
            inline=False,
        )
        embed.set_image(url=f"attachment://{guide_path.name}")
    else:
        print(f"PO- & Prio-Anleitung nicht gefunden: {guide_path}")
        guide_path = None
    count = await send_queue_targeted_embed(payload, embed, guide_path)
    print(f"Raidankündigungs-DM an {count} Empfänger gesendet: {raid_name}")
    return count


async def send_raid_status_notice_from_queue(payload):
    raid_name = clean(payload.get("raidName")) or "Raid"
    action = clean(payload.get("action"))
    custom_description = clean(payload.get("messageTemplate"))
    replacements = {"{spieler}": clean(payload.get("player")) or "Ein Spieler", "{raid}": raid_name, "{status}": raid_signup_action_label(action), "{datum}": format_raid_announcement_date(payload.get("raidDate") or ""), "{uhrzeit}": format_raid_announcement_time(payload.get("raidTime") or ""), "{hinweis}": clean(payload.get("message"))}
    for token,value in replacements.items(): custom_description = custom_description.replace(token,value)
    custom_description = re.sub(
        r"^\s*(?:📋\s*)?\*\*Änderung im Raidanmelder\*\*\s*",
        "",
        custom_description,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    embed = discord.Embed(
        title="Änderung im Raidanmelder",
        description=custom_description or f"**{clean(payload.get('player')) or 'Ein Spieler'}** wurde für **{raid_name}** **{raid_signup_action_label(action)}**.",
        color=0x7C3AED,
    )
    embed.add_field(name="Raid", value=raid_name, inline=True)
    embed.add_field(name="Datum", value=format_raid_announcement_date(payload.get("raidDate") or ""), inline=True)
    embed.add_field(name="Uhrzeit", value=format_raid_announcement_time(payload.get("raidTime") or ""), inline=True)
    if clean(payload.get("changedBy")):
        embed.add_field(name="Geändert von", value=clean(payload.get("changedBy")), inline=True)
    if clean(payload.get("message")):
        embed.add_field(name="Hinweis", value=clean(payload.get("message"))[:1024], inline=False)
    count = await send_queue_targeted_embed(payload, embed)
    print(f"Raidstatus-Queue-DM an {count} Empfänger gesendet: {raid_name}")
    return count


async def send_po_release_request_notice_from_queue(payload):
    guild_slug = payload_guild_slug(payload)
    guild_name = guild_display_name(payload=payload)
    character = clean(payload.get("character")) or "Unbekannt"
    server = clean(payload.get("server"))
    class_name = clean(payload.get("className"))
    raid = clean(payload.get("raid")).upper() or "-"
    request_type = clean(payload.get("requestType"))
    request_label = {"recruit":"Rekrutenstatus aufheben","p1p3":"P1–P3 Freigabe","p0":"P0 Freigabe","po":"PO-Freigabe"}.get(request_type,request_type or "PO-Freigabe")
    registry_entry = GUILD_REGISTRY.get(guild_slug) or {}
    discord_guild_id = clean(
        payload.get("discordGuildId")
        or registry_entry.get("discordGuildId")
        or ({
            "lichtloot": LICHTLOOT_DISCORD_GUILD_ID,
            "nachtloot": NACHTLOOT_DISCORD_GUILD_ID,
        }.get(guild_slug) or "")
    )
    discord_guild = client.get_guild(int(discord_guild_id)) if discord_guild_id.isdigit() else None
    discord_channel_id = clean(
        payload.get("targetChannelId")
        or payload.get("sourceChannelId")
        or payload.get("channelId")
        or payload.get("discordChannelId")
    )
    if discord_guild and not discord_channel_id:
        preferred_names = {"pofreigabe", "pofreigaben", "pofreigabeantraege", "pofreigabeanträge"}
        matching_channel = next(
            (
                channel for channel in getattr(discord_guild, "text_channels", [])
                if normalize_emoji_name(getattr(channel, "name", "")) in preferred_names
            ),
            None,
        )
        if matching_channel:
            discord_channel_id = str(matching_channel.id)
    discord_link = (
        f"https://discord.com/channels/{discord_guild_id}/{discord_channel_id}"
        if discord_guild_id.isdigit() and discord_channel_id.isdigit()
        else ""
    )
    text = clean(payload.get("messageTemplate"))
    replacements = {"{gilde}":guild_name,"{charakter}":character,"{server}":server,"{klasse}":class_name,"{raid}":raid,"{antrag}":request_label,"{link}":discord_link}
    for token,value in replacements.items(): text = text.replace(token,value)
    text = re.sub(
        r"^\s*(?:🔎\s*)?\*\*Neue PO-Freigabe wartet\*\*\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    embed = discord.Embed(
        title="🔎 Neue PO-Freigabe wartet",
        description=text or f"Für **{character}** wurde eine **{request_label}** eingereicht und wartet auf Prüfung.",
        color=0xFACC15,
    )
    embed.add_field(name="🏰 Gilde", value=guild_name, inline=True)
    embed.add_field(name="⚔️ Raid", value=display_raid(raid) or raid, inline=True)
    embed.add_field(
        name="👤 Charakter",
        value=f"{character}{f'-{server}' if server else ''}",
        inline=False,
    )
    if class_name:
        embed.add_field(
            name="🛡️ Klasse",
            value=f"{class_icon(class_name)} {class_display_name(class_name)}",
            inline=True,
        )
    embed.add_field(name="📋 Antrag", value=request_label, inline=True)
    if discord_link:
        embed.add_field(name="💬 Zum Discord-Channel", value=f"[PO-Freigabe-Channel öffnen]({discord_link})", inline=False)
    class_emoji = class_icon(class_name)
    emoji_match = re.match(r"<a?:[^:]+:(\d+)>", class_emoji)
    if emoji_match:
        embed.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_match.group(1)}.png?size=128&quality=lossless")
    embed.set_footer(text="Der Antrag wartet auf Freigabe durch die Gildenleitung.")
    count = await send_queue_targeted_embed(payload,embed)
    print(f"PO-Freigabehinweis an {count} Empfänger gesendet: {character}")
    return count


async def send_po_release_granted_notice_from_queue(payload):
    user_id = clean(payload.get("discordUserId") or payload.get("discord_user_id"))
    if not user_id:
        return 0
    guild_name = guild_display_name(payload=payload)
    raid_name = clean(payload.get("raidLabel") or payload.get("raidName")) or display_raid(payload.get("raid") or "") or "Raid"
    character = clean(payload.get("character") or payload.get("player")) or "Unbekannt"
    server = clean(payload.get("server"))
    class_name = clean(payload.get("className") or payload.get("class"))
    embed = discord.Embed(
        title="✅ PO-Freigabe erteilt",
        description=f"Deine PO-Freigabe für **{raid_name}** wurde erfolgreich bestätigt.",
        color=0x22C55E,
    )
    embed.add_field(name="🏰 Gilde", value=guild_name, inline=True)
    embed.add_field(name="⚔️ Raid", value=raid_name, inline=True)
    embed.add_field(name="👤 Charakter", value=f"{character}{f'-{server}' if server else ''}", inline=True)
    if class_name:
        embed.add_field(name="🛡️ Klasse", value=f"{class_icon(class_name)} {class_display_name(class_name)}", inline=True)
    embed.set_footer(text="Du kannst deine Prios jetzt auf der entsprechenden Lootseite eintragen.")
    try:
        user = client.get_user(int(user_id)) or await client.fetch_user(int(user_id))
        await user.send(embed=embed)
        return 1
    except Exception as error:
        print(f"PO-Freigabe-DM an {character} konnte nicht gesendet werden: {error}")
        return 0


async def send_loot_master_leadpin_notice_from_queue(payload):
    raid_name = clean(payload.get("raidName")) or "Raid"
    guild_slug = normalize_guild_slug(payload.get("guildSlug") or payload.get("guild") or "")
    guild_name = clean(payload.get("guildName") or payload.get("guild") or guild_slug)
    guild_display_names = {
        "lichtloot": "Lichtbringer",
        "nachtloot": "Die Nachtwächter",
        "panemloot": "Panem et Circenses",
    }
    if guild_slug in guild_display_names or guild_name.lower() in {"lichtloot", "nachtloot", "panemloot"}:
        guild_name = guild_display_names.get(guild_slug, guild_display_names.get(guild_name.lower(), guild_name))
    guild_name = guild_name or "Unbekannte Gilde"
    raid_id = clean(payload.get("raidId") or payload.get("id"))
    lead_pin = clean(payload.get("leadPin"))
    loot_master_pin = clean(payload.get("lootMasterPin") or payload.get("lootMasterPassword"))
    if not lead_pin:
        return 0
    custom_description = clean(payload.get("messageTemplate")).replace("{raid}", raid_name)
    embed = discord.Embed(
        title="LeadPIN für deinen Raid",
        description=custom_description or f"Du bist für **{raid_name}** als Plündermeister eingetragen.",
        color=0xFACC15,
    )
    embed.add_field(name="🏰 Gilde", value=f"**{guild_name}**", inline=True)
    embed.add_field(name="⚔️ Raid", value=f"**{raid_name}**", inline=True)
    embed.add_field(name="🔑 LeadPIN", value=f"`{lead_pin}`", inline=False)
    if loot_master_pin:
        embed.add_field(name="🪙 Plündermeister-PIN", value=f"`{loot_master_pin}`", inline=False)
    embed.add_field(
        name="🔐 Zugang",
        value="Alternativ kannst du den **Mastercode der Gildenleitung** als Plündermeister-Passwort verwenden.",
        inline=False,
    )
    embed.add_field(name="📅 Datum", value=format_raid_announcement_date(payload.get("raidDate") or ""), inline=True)
    embed.add_field(name="🕒 Uhrzeit", value=format_raid_announcement_time(payload.get("raidTime") or ""), inline=True)
    raidlead_url = (
        f"{LICHTLOOT_URL.rstrip('/')}/raidlead-panel.html?"
        + urllib.parse.urlencode({
            "guild": payload_guild_slug(payload),
            "raidId": raid_id,
            "leadPin": lead_pin,
        })
    )
    embed.add_field(
        name="➡️ Direkt zum Plündermeisterpanel",
        value=f"**[Plündermeisterseite für {raid_name} öffnen]({raidlead_url})**",
        inline=False,
    )
    embed.add_field(
        name="✅ Erinnerung für nach dem Raid",
        value="• **Erhaltene Items markieren** und die zugehörigen Punkte entfernen\n• Danach **PO+ Punkte übertragen**",
        inline=False,
    )
    embed.set_footer(text="PM-PIN: nur PO+ übertragen und Item erhalten/Punkte entfernen. Der Mastercode bleibt voll gültig.")
    guide_path = Path(__file__).resolve().parent / "assets" / "pluendermeister-anleitung-ariee.png"
    if guide_path.is_file():
        embed.add_field(
            name="📘 Schritt-für-Schritt-Anleitung",
            value="Die vollständige Anleitung findest du direkt unter dieser Nachricht.",
            inline=False,
        )
        embed.set_image(url=f"attachment://{guide_path.name}")
    else:
        print(f"Plündermeister-Anleitung nicht gefunden: {guide_path}")
    count = await send_queue_targeted_embed(payload, embed, guide_path, show_recipients=True)
    print(f"LeadPIN-DM an {count} Plündermeister gesendet: {raid_name}")
    return count


async def delete_entry(payload, entry, user):
    raid_pin = payload_lichtloot_raid_pin(payload)
    result = await asyncio.to_thread(api_post, {
        "action": "lichtbotDeletePoPostEntry",
        "queueToken": QUEUE_TOKEN,
        "postKey": payload["postKey"],
        "sourceChannelId": payload_source_channel_id(payload),
        "targetChannelId": payload_target_channel_id(payload),
        "raidPin": raid_pin,
        "prioPin": raid_pin,
        "lichtlootRaidId": raid_pin,
        "discordMessageId": payload.get("messageId") or entry.get("discordMessageId") or "",
        "player": entry.get("player") or "",
        "item": entry.get("item") or entry.get("itemName") or "",
        "discordUserId": str(getattr(user, "id", "") or ""),
        "discordName": getattr(user, "display_name", None) or getattr(user, "name", None) or str(user),
    })
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "PO-Eintrag konnte nicht gelöscht werden.")
    return result


async def luck_entry(payload, entry, user):
    result = await asyncio.to_thread(api_post, {
        "action": "lichtbotSetPoPostLuck",
        "queueToken": QUEUE_TOKEN,
        "postKey": payload["postKey"],
        "sourceChannelId": payload_source_channel_id(payload),
        "targetChannelId": payload_target_channel_id(payload),
        "discordMessageId": payload.get("messageId") or entry.get("discordMessageId") or "",
        "player": entry.get("player") or "",
        "item": entry.get("item") or entry.get("itemName") or "",
        "luckBy": getattr(user, "display_name", None) or getattr(user, "name", None) or str(user),
        "discordUserId": str(getattr(user, "id", "") or ""),
    })
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Kleeblatt konnte nicht gespeichert werden.")
    return result


def make_embed(payload, entries, p0plus_labels=None):
    payload = payload_with_saved_lichtloot_id(payload)
    embed = discord.Embed(
        title=f"📋 {display_raid(payload.get('raid') or '')} PO-Anmelder",
        color=discord.Color.gold(),
    )
    if clean(payload.get("postKey")):
        embed.set_footer(text=f"Post-ID: {payload.get('postKey')}")

    note = po_post_note(payload)
    header_lines = build_fixed_po_header(payload)
    if note:
        header_lines = note.splitlines() + [""] + header_lines
        header_lines.append("")

    grouped = {}
    for entry in entries:
        grouped.setdefault(po_entry_item_group_key(entry), []).append(entry)

    if not grouped:
        embed.description = "\n".join(header_lines + ["**Anmeldungen (0)**", "Noch keine PO-Anmeldung vorhanden."])[:3900]
        return embed

    lines = header_lines + [f"**Anmeldungen ({len(entries)})**"]
    p0plus_labels = p0plus_labels or {}
    for item_key in sorted(grouped.keys(), key=lambda value: po_entry_item_display(grouped[value][0]).lower()):
        rows = grouped[item_key]
        item_name = po_entry_item_name(rows[0])
        item_label_base = po_entry_item_display(rows[0])
        p0_label = p0plus_labels.get(slug(item_name))
        item_label = f"{item_label_base} ({p0_label})" if p0_label else item_label_base
        lines.append("")
        lines.append(f"{item_icon(item_name)} **{item_label}**")
        players = []
        for row in sorted(rows, key=lambda entry: clean(entry.get("player")).lower()):
            class_name = class_display_name(row.get("className") or row.get("Klasse"))
            icon = class_icon(class_name)
            approval_status = clean(row.get("approvalStatus")).lower()
            status_icon = (
                f" {custom_emoji('Beutegrun', '🟢')}"
                if row.get("approved") or approval_status == "approved"
                else " ❌"
                if approval_status == "rejected"
                else f" {custom_emoji('beuteorange', '🟠')}"
            )
            players.append(f"{icon} {clean(row.get('player'))}{status_icon}")
        lines.append(", ".join(players) or "-")

    embed.description = "\n".join(lines)[:3900]
    return embed


def po_help_image_file():
    if not PO_HELP_IMAGE_PATH.exists():
        return None
    return discord.File(str(PO_HELP_IMAGE_PATH), filename=PO_HELP_IMAGE_FILENAME)


def po_message_has_help_image(message):
    return any(
        str(getattr(attachment, "filename", "") or "") == PO_HELP_IMAGE_FILENAME
        for attachment in getattr(message, "attachments", []) or []
    )


async def send_po_message(channel, embed, view):
    return await channel.send(embed=embed, view=view, silent=True)


async def edit_po_message(message, embed, view):
    await message.edit(embed=embed, view=view)


def class_options():
    return [
        discord.SelectOption(label=name, value=name, emoji=class_select_emoji(name))
        for name in ["Krieger", "Druide", "Paladin", "Schurke", "Jäger", "Priester", "Magier", "Hexenmeister", "Schamane"]
    ]


def selected_class(post_key, user_id):
    return user_classes.get(f"{post_key}:{user_id}", "")


def po_signup_error_message(error, char_name=""):
    message = str(error or "unbekannt")
    folded = message.casefold()
    if "passt nicht zu diesem charakter" in folded or "spielerlogin" in folded or "spielerlogin/pin" in folded:
        wanted = clean(char_name)
        suffix = f" für **{wanted}**" if wanted else ""
        return f"SpielerLogin/PIN oder Charaktername falsch{suffix}. Bitte prüfe deinen SpielerLogin/PIN und den Charakternamen."
    return message


async def submit_po_entry(interaction, payload, item_name, class_name, char_name, player_login, server=""):
    payload = payload_for_interaction(payload, interaction)
    payload = payload_with_saved_lichtloot_id(payload)
    raid_pin = payload_lichtloot_raid_pin(payload)
    char_name = clean(char_name)
    player_login = clean(player_login)
    item_id = po_item_id_value(item_name)
    item_slot = clean(item_name.get("slot") or item_name.get("Slot")) if isinstance(item_name, dict) else ""
    item_boss = clean(item_name.get("boss") or item_name.get("Boss")) if isinstance(item_name, dict) else ""
    item_name = po_item_name_value(item_name)
    class_name = class_display_name(class_name)
    server = clean(server)

    if not class_name:
        await interaction.followup.send("⚠️ Bitte zuerst eine Klasse wählen.", ephemeral=True)
        return
    if not player_login:
        await interaction.followup.send("⚠️ Bitte deinen SpielerLogin/PIN eintragen.", ephemeral=True)
        return
    if not char_name:
        await interaction.followup.send("⚠️ Bitte deinen Charakternamen eintragen.", ephemeral=True)
        return

    try:
        result = await asyncio.to_thread(api_post, {
            "action": "lichtbotSavePoPostEntry",
            "queueToken": QUEUE_TOKEN,
            "guildSlug": payload_guild_slug(payload),
            "postKey": payload["postKey"],
            "sourceChannelId": payload_source_channel_id(payload),
            "targetChannelId": payload_target_channel_id(payload),
            "raid": payload["raid"],
            "title": payload.get("title") or "PO-Anmelder",
            "discordMessageId": payload.get("messageId") or "",
            "messageId": payload.get("messageId") or "",
            "raidPin": raid_pin,
            "prioPin": raid_pin,
            "lichtlootRaidId": raid_pin,
            "player": char_name,
            "server": server,
            "className": class_name,
            "item": item_name,
            "itemId": item_id,
            "itemSlot": item_slot,
            "itemBoss": item_boss,
            "playerPin": player_login,
            "spielerLogin": player_login,
            "discordUserId": str(interaction.user.id),
            "discordName": interaction.user.display_name,
        })
    except Exception as error:
        detail = po_signup_error_message(error, char_name)
        await interaction.followup.send(f"⚠️ PO konnte nicht gespeichert werden: {detail}", ephemeral=True)
        return

    if not result.get("success"):
        detail = po_signup_error_message(result.get("error") or "unbekannt", char_name)
        await interaction.followup.send(f"⚠️ PO konnte nicht gespeichert werden: {detail}", ephemeral=True)
        return

    saved_entry = result.get("entry") or {}
    saved_player = clean(saved_entry.get("player")) or char_name
    saved_item = clean(saved_entry.get("item")) or item_name
    remember_po_item_variant(payload, saved_player, {
        "name": saved_item,
        "itemId": item_id,
        "slot": item_slot,
        "boss": item_boss,
    })
    prio_result = None
    try:
        prio_result = await asyncio.to_thread(save_po_signup_prio, {**payload, "server": server}, saved_player, class_name, saved_item, player_login, item_id)
    except Exception as error:
        prio_result = {"success": False, "error": str(error)}
    if prio_result and not prio_result.get("success"):
        detail = po_signup_error_message(prio_result.get("error") or "unbekannt", saved_player)
        await interaction.followup.send(
            f"⚠️ Discord-Eintrag ist gespeichert, aber PO+ konnte nicht gespeichert werden: {detail}",
            ephemeral=True,
        )
        return
    # Erst nachdem sowohl der PO-Post-Eintrag als auch die zugehörige
    # LichtLoot-Prio dauerhaft gespeichert wurden, den Discord-Post neu
    # aufbauen. Zuvor konnten zwei fast gleichzeitige Aktualisierungen eine
    # ältere Momentaufnahme anzeigen und den neuen Eintrag wieder verdrängen.
    asyncio.create_task(refresh_po_message_safely(interaction.client, payload))
    await interaction.followup.send(
        f"✅ Deine PO wurde gespeichert: **{saved_player}** → **{saved_item}**.\n"
        "Der PO-Post wird gleich aktualisiert.",
        ephemeral=True,
    )


class PoEntryModal(discord.ui.Modal):
    def __init__(self, payload, item_name, class_name, default_char=""):
        super().__init__(title="PO eintragen")
        self.payload = payload
        self.item_name = item_name
        self.class_name = class_name
        self.char_name = discord.ui.TextInput(
            label="Charaktername",
            placeholder="z. B. Rune",
            default=default_char[:50],
            required=True,
            max_length=50,
        )
        self.player_login = discord.ui.TextInput(
            label="SpielerLogin/PIN",
            placeholder="dein SpielerLogin/PIN",
            required=True,
            max_length=80,
        )
        self.add_item(self.char_name)
        self.add_item(self.player_login)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        char_name = clean(self.char_name.value)
        player_login = clean(self.player_login.value)
        class_name = class_display_name(self.class_name)
        await submit_po_entry(interaction, self.payload, self.item_name, class_name, char_name, player_login)


class PoKnownCharacterSelect(discord.ui.Select):
    def __init__(self, payload, item_name, class_name, characters):
        self.payload = payload
        self.item_name = item_name
        self.class_name = class_name
        self.characters = list(characters or [])[:25]
        options = []
        for index, char in enumerate(self.characters):
            label = clean(char.get("name"))[:100]
            description = " · ".join(
                part for part in [clean(char.get("className")), clean(char.get("server"))] if part
            )[:100]
            options.append(discord.SelectOption(label=label, value=str(index), description=description or None))
        super().__init__(
            custom_id=f"po-known-char:{payload['postKey'][:55]}",
            placeholder="Bekannten Charakter wählen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            char = self.characters[int(self.values[0])]
        except Exception:
            await interaction.followup.send("⚠️ Charakterauswahl konnte nicht gelesen werden.", ephemeral=True)
            return
        class_name = class_display_name(char.get("className") or self.class_name)
        await submit_po_entry(
            interaction,
            self.payload,
            self.item_name,
            class_name,
            char.get("name"),
            char.get("playerPin"),
            char.get("server"),
        )


class PoPlayerLoginCharacterSelect(discord.ui.Select):
    def __init__(self, payload, item_name, class_name, characters, player_login):
        self.payload = payload
        self.item_name = item_name
        self.class_name = class_name
        self.characters = list(characters or [])[:25]
        self.player_login = clean(player_login)
        options = []
        for index, char in enumerate(self.characters):
            label = clean(char.get("name"))[:100]
            description = " · ".join(
                part for part in [clean(char.get("className")), clean(char.get("server"))] if part
            )[:100]
            options.append(discord.SelectOption(label=label, value=str(index), description=description or None))
        super().__init__(
            custom_id=f"po-pin-char:{payload['postKey'][:55]}",
            placeholder="Gespeicherten Charakter wählen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            char = self.characters[int(self.values[0])]
        except Exception:
            await interaction.followup.send("⚠️ Charakterauswahl konnte nicht gelesen werden.", ephemeral=True)
            return
        class_name = class_display_name(char.get("className") or self.class_name)
        await submit_po_entry(
            interaction,
            self.payload,
            self.item_name,
            class_name,
            char.get("name"),
            self.player_login,
            char.get("server"),
        )


class PoPlayerLoginCharacterView(discord.ui.View):
    def __init__(self, payload, item_name, class_name, characters, player_login):
        super().__init__(timeout=180)
        self.add_item(PoPlayerLoginCharacterSelect(payload, item_name, class_name, characters, player_login))


class PoPlayerLoginModal(discord.ui.Modal):
    def __init__(self, payload, item_name, class_name):
        super().__init__(title="SpielerLogin eingeben")
        self.payload = payload
        self.item_name = item_name
        self.class_name = class_name
        self.player_login = discord.ui.TextInput(
            label="SpielerLogin/PIN",
            placeholder="dein SpielerLogin/PIN",
            required=True,
            max_length=80,
        )
        self.add_item(self.player_login)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        player_login = clean(self.player_login.value)
        characters, error = await load_po_characters_by_pin(player_login, payload_for_interaction(self.payload, interaction))
        item_display = po_item_display_text(self.item_name)
        if error:
            await interaction.followup.send(
                f"⚠️ SpielerLogin konnte nicht geprüft werden: {error}",
                ephemeral=True,
            )
            return
        if not characters:
            await interaction.followup.send(
                f"Item gewählt: **{item_display}**.\n"
                "⚠️ Für diesen SpielerLogin wurden in dieser Gilde keine freigegebenen Charaktere gefunden.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"Item gewählt: **{item_display}**.\nWähle jetzt deinen gespeicherten Charakter.",
            view=PoPlayerLoginCharacterView(
                payload_for_interaction(self.payload, interaction),
                self.item_name,
                self.class_name,
                characters,
                player_login,
            ),
            ephemeral=True,
        )


class PoOtherCharacterButton(discord.ui.Button):
    def __init__(self, payload, item_name, class_name, default_char=""):
        super().__init__(
            custom_id=f"po-other-char:{payload['postKey'][:55]}",
            label="Anderen Charakter eingeben",
            style=discord.ButtonStyle.secondary,
        )
        self.payload = payload
        self.item_name = item_name
        self.class_name = class_name
        self.default_char = default_char

    async def callback(self, interaction):
        await interaction.response.send_modal(
            PoEntryModal(self.payload, self.item_name, self.class_name, self.default_char)
        )


class PoUseOtherLoginButton(discord.ui.Button):
    def __init__(self, payload, item_name, class_name=""):
        super().__init__(
            custom_id=f"po-other-login:{payload['postKey'][:55]}",
            label="Spielerlogin",
            style=discord.ButtonStyle.secondary,
        )
        self.payload = payload
        self.item_name = item_name
        self.class_name = class_name

    async def callback(self, interaction):
        await interaction.response.send_modal(
            PoPlayerLoginModal(self.payload, self.item_name, self.class_name)
        )


class PoKnownCharacterView(discord.ui.View):
    def __init__(self, payload, item_name, class_name, characters, default_char=""):
        super().__init__(timeout=180)
        self.add_item(PoKnownCharacterSelect(payload, item_name, class_name, characters))
        self.add_item(PoUseOtherLoginButton(payload, item_name, class_name))


class PoFirstLoginView(discord.ui.View):
    def __init__(self, payload, item_name, class_name=""):
        super().__init__(timeout=180)
        self.add_item(PoUseOtherLoginButton(payload, item_name, class_name))


class PoOtherCharacterView(discord.ui.View):
    def __init__(self, payload, item_name, class_name, default_char=""):
        super().__init__(timeout=180)
        self.add_item(PoOtherCharacterButton(payload, item_name, class_name, default_char))


async def open_po_entry_flow(interaction, payload, item_name, class_name, default_char=""):
    payload = payload_for_interaction(payload, interaction)
    await interaction.response.defer(ephemeral=True)
    characters = await load_po_linked_characters(interaction.user.id, payload)
    item_display = po_item_display_text(item_name)
    if characters:
        await interaction.followup.send(
            f"Item gewählt: **{item_display}**.\nWähle deinen Charakter – die Klasse wird automatisch übernommen.",
            view=PoKnownCharacterView(payload, item_name, "", characters),
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        f"Item gewählt: **{item_display}**.\nVerbinde einmalig deinen SpielerLogin; danach kennt der Bot deine Charaktere.",
        view=PoFirstLoginView(payload, item_name),
        ephemeral=True,
    )


class PoClassSelect(discord.ui.Select):
    def __init__(self, payload):
        self.payload = payload
        super().__init__(
            custom_id=f"po-class:{payload['postKey']}",
            placeholder="1. Klasse wählen",
            min_values=1,
            max_values=1,
            options=class_options(),
            row=0,
        )

    async def callback(self, interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            class_name = class_display_name(self.values[0])
            user_classes[f"{self.payload['postKey']}:{interaction.user.id}"] = class_name
            await interaction.followup.send(
                f"{class_icon(class_name)} Klasse gespeichert: **{class_name}**. Jetzt Item auswählen.",
                ephemeral=True,
            )
        except Exception as error:
            print(f"PO Klasse konnte nicht gespeichert werden ({self.payload.get('postKey')}): {error}")


class PoItemSelect(discord.ui.Select):
    def __init__(self, payload, items):
        self.payload = payload
        self.items = list(items or [])[:25]
        options = [
            discord.SelectOption(
                label=po_item_option_label(item),
                value=po_item_option_key(item, index),
                description=po_item_option_description(item) or None,
                emoji=item_select_emoji(po_item_name_value(item))
            )
            for index, item in enumerate(self.items)
        ]
        super().__init__(
            custom_id=f"po-item:{payload['postKey']}",
            placeholder="Item auswählen und PO eintragen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction):
        class_name = selected_class(self.payload["postKey"], interaction.user.id)
        default_char = clean(interaction.user.display_name).split("/")[0].strip()
        await open_po_entry_flow(interaction, self.payload, resolve_po_item_selection(self.items, self.values[0]), class_name, default_char)


class PoItemSearchResultSelect(discord.ui.Select):
    def __init__(self, payload, items, class_name, default_char=""):
        self.payload = payload
        self.class_name = class_name
        self.default_char = default_char
        self.items = list(items or [])[:25]
        options = [
            discord.SelectOption(
                label=po_item_option_label(item),
                value=po_item_option_key(item, index),
                description=po_item_option_description(item) or None,
                emoji=item_select_emoji(po_item_name_value(item))
            )
            for index, item in enumerate(self.items)
        ]
        super().__init__(
            custom_id=f"po-search-result:{payload['postKey'][:55]}",
            placeholder="Gefundenes Item auswählen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction):
        class_name = selected_class(self.payload["postKey"], interaction.user.id) or self.class_name
        await open_po_entry_flow(interaction, self.payload, resolve_po_item_selection(self.items, self.values[0]), class_name, self.default_char)


class PoItemSearchResultView(discord.ui.View):
    def __init__(self, payload, items, class_name, default_char=""):
        super().__init__(timeout=180)
        self.add_item(PoItemSearchResultSelect(payload, items, class_name, default_char))


class PoItemSearchModal(discord.ui.Modal):
    def __init__(self, payload, class_name, default_char=""):
        super().__init__(title="PO-Item suchen")
        self.payload = payload
        self.class_name = class_name
        self.default_char = default_char
        self.query = discord.ui.TextInput(
            label="Item suchen",
            placeholder="z. B. Vek'nilash, Gebundene Essenz, Raptor ...",
            required=True,
            max_length=80,
        )
        self.add_item(self.query)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        query = clean(self.query.value)
        matches = await search_raid_items(self.payload.get("raid"), query)
        if not matches:
            await interaction.followup.send(f"Keine Items für **{query}** gefunden.", ephemeral=True)
            return
        await interaction.followup.send(
            f"Gefundene Items für **{query}**. Wähle dein Item:",
            view=PoItemSearchResultView(self.payload, matches, self.class_name, self.default_char),
            ephemeral=True,
        )


class PoSearchButton(discord.ui.Button):
    def __init__(self, payload):
        super().__init__(
            custom_id=f"po-search:{payload['postKey'][:70]}",
            label="PO eintragen",
            style=discord.ButtonStyle.success,
            row=1,
        )
        self.payload = payload

    async def callback(self, interaction):
        class_name = selected_class(self.payload["postKey"], interaction.user.id)
        default_char = clean(interaction.user.display_name).split("/")[0].strip()
        await interaction.response.send_modal(PoItemSearchModal(self.payload, class_name, default_char))


class PoReviewSelect(discord.ui.Select):
    def __init__(self, payload, entries):
        self.payload = payload
        self.entries = list(entries or [])
        review_options = po_review_entry_options(self.entries)
        options = [
            discord.SelectOption(label=label, value=value, emoji="✅")
            for value, label in review_options
        ]
        if not options:
            options = [discord.SelectOption(label="Keine offenen Einträge", value="none", emoji="✅")]
        super().__init__(
            custom_id=f"po-review:{payload['postKey'][:70]}",
            placeholder="Item freigeben",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not bool(review_options),
            row=2,
        )

    async def callback(self, interaction):
        try:
            if not self.values or self.values[0] == "none":
                await interaction.response.send_message("Es gibt gerade keinen offenen PO-Eintrag zum Freigeben.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            if not await reviewer_allowed(interaction.user):
                await interaction.followup.send(
                    "⚠️ Nur PO-Freigeber können PO-Einträge freigeben.",
                    ephemeral=True,
                )
                return
            action_payload = payload_for_interaction(self.payload, interaction)
            selected_value = clean(self.values[0])
            current_entries = await fresh_entries_for_payload(action_payload)
            entry = None
            if selected_value.startswith("id:"):
                selected_id = selected_value[3:]
                entry = next(
                    (row for row in current_entries if clean(row.get("id") or row.get("entryId")) == selected_id),
                    None,
                )
            else:
                try:
                    old_index = int(selected_value)
                    old_entry = self.entries[old_index] if 0 <= old_index < len(self.entries) else None
                except (TypeError, ValueError):
                    old_entry = None
                if old_entry:
                    old_id = clean(old_entry.get("id") or old_entry.get("entryId"))
                    old_key = (slug(old_entry.get("player")), slug(old_entry.get("item") or old_entry.get("itemName")))
                    entry = next(
                        (
                            row for row in current_entries
                            if (old_id and clean(row.get("id") or row.get("entryId")) == old_id)
                            or (slug(row.get("player")), slug(row.get("item") or row.get("itemName"))) == old_key
                        ),
                        None,
                    )
                if entry is None:
                    pending_entries = [
                        row for row in current_entries
                        if not row.get("approved")
                        and clean(row.get("approvalStatus")).lower() not in {"approved", "rejected"}
                    ]
                    if len(pending_entries) == 1:
                        entry = pending_entries[0]
            if entry is None:
                await refresh_po_message(interaction.client, action_payload)
                await interaction.followup.send(
                    "⚠️ Diese Auswahl war nicht mehr aktuell. Der PO-Anmelder wurde aktualisiert – bitte die Freigabe erneut auswählen.",
                    ephemeral=True,
                )
                return
            result = await review_entry(action_payload, entry, interaction.user)
            saved = result.get("entry") or entry
            await refresh_po_message(interaction.client, action_payload)
            dm_sent = await send_po_approval_message(interaction.client, saved)
            await interaction.followup.send(
                f"✅ Freigegeben: **{saved.get('player') or entry.get('player')}** → **{saved.get('item') or entry.get('item')}**."
                + (" Nachricht wurde gesendet." if dm_sent else " Nachricht konnte nicht per DM gesendet werden."),
                ephemeral=True,
            )
        except Exception as error:
            if interaction.response.is_done():
                await interaction.followup.send(f"⚠️ Freigabe konnte nicht geöffnet werden: `{error}`", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ Freigabe konnte nicht geöffnet werden: `{error}`", ephemeral=True)


class PoRejectModal(discord.ui.Modal):
    def __init__(self, payload, entry):
        self.payload = payload
        self.entry = dict(entry or {})
        player = clean(self.entry.get("player")) or "Spieler"
        super().__init__(title=f"PO ablehnen: {player}"[:45])
        self.message = discord.ui.TextInput(
            label="Nachricht an den Spieler",
            placeholder="z. B. Bitte anderes Item wählen / passt nicht zur Lootregel.",
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=500,
        )
        self.add_item(self.message)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            reason = clean(self.message.value)
            result = await reject_entry(self.payload, self.entry, interaction.user, reason)
            saved = result.get("entry") or self.entry
            await refresh_po_message(interaction.client, self.payload)
            dm_sent = await send_po_rejection_message(interaction.client, saved, reason)
            await interaction.followup.send(
                f"❌ Abgelehnt: **{saved.get('player') or self.entry.get('player')}** → **{saved.get('item') or self.entry.get('item')}**."
                + (" Nachricht wurde gesendet." if dm_sent else " Nachricht konnte nicht per DM gesendet werden."),
                ephemeral=True,
            )
        except Exception as error:
            await interaction.followup.send(f"⚠️ Ablehnung konnte nicht gespeichert werden: `{error}`", ephemeral=True)


class PoRejectSelect(discord.ui.Select):
    def __init__(self, payload, entries):
        self.payload = payload
        self.entries = list(entries or [])
        options = [
            discord.SelectOption(label=label, value=value, emoji="❌")
            for value, label in po_reject_entry_options(self.entries)
        ]
        super().__init__(
            custom_id=f"po-reject-select:{payload['postKey'][:60]}",
            placeholder="PO zum Ablehnen auswählen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction):
        try:
            if not await reviewer_allowed(interaction.user):
                await interaction.response.send_message(
                    "⚠️ Nur PO-Freigeber können PO-Einträge ablehnen.",
                    ephemeral=True,
                )
                return
            action_payload = payload_for_interaction(self.payload, interaction)
            selected_value = clean(self.values[0])
            current_entries = await fresh_entries_for_payload(action_payload)
            entry = None
            if selected_value.startswith("id:"):
                selected_id = selected_value[3:]
                entry = next((row for row in current_entries if clean(row.get("id") or row.get("entryId")) == selected_id), None)
            else:
                try:
                    old_index = int(selected_value)
                    old_entry = self.entries[old_index] if 0 <= old_index < len(self.entries) else None
                except (TypeError, ValueError):
                    old_entry = None
                if old_entry:
                    old_key = (slug(old_entry.get("player")), slug(old_entry.get("item") or old_entry.get("itemName")))
                    entry = next(
                        (row for row in current_entries if (slug(row.get("player")), slug(row.get("item") or row.get("itemName"))) == old_key),
                        None,
                    )
            if entry is None:
                await interaction.response.send_message(
                    "⚠️ Diese Auswahl ist nicht mehr aktuell. Bitte den PO-Anmelder neu laden und erneut auswählen.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_modal(PoRejectModal(action_payload, entry))
        except Exception as error:
            if interaction.response.is_done():
                await interaction.followup.send(f"⚠️ Ablehnen konnte nicht geöffnet werden: `{error}`", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ Ablehnen konnte nicht geöffnet werden: `{error}`", ephemeral=True)


class PoRejectEntryView(discord.ui.View):
    def __init__(self, payload, entries):
        super().__init__(timeout=180)
        self.add_item(PoRejectSelect(payload, entries))


class PoRejectButton(discord.ui.Button):
    def __init__(self, payload):
        super().__init__(
            custom_id=f"po-reject:{payload['postKey'][:70]}",
            label="PO ablehnen",
            style=discord.ButtonStyle.danger,
            row=1,
        )
        self.payload = payload

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        if not await reviewer_allowed(interaction.user):
            await interaction.followup.send("⚠️ Nur PO-Freigeber können PO-Einträge ablehnen.", ephemeral=True)
            return
        action_payload = payload_for_interaction(self.payload, interaction)
        entries = await fresh_entries_for_payload(action_payload)
        if not po_reject_entry_options(entries):
            await interaction.followup.send("Es gibt gerade keinen offenen PO-Eintrag zum Ablehnen.", ephemeral=True)
            return
        await interaction.followup.send(
            "Wähle den PO-Eintrag aus, den du ablehnen möchtest.",
            view=PoRejectEntryView(action_payload, entries),
            ephemeral=True,
        )


class PoDeleteEntrySelect(discord.ui.Select):
    def __init__(self, payload, entries):
        self.payload = payload
        self.entries = list(entries or [])
        options = [
            discord.SelectOption(label=label, value=value, emoji="🗑️")
            for value, label in po_entry_options(self.entries)
        ]
        super().__init__(
            custom_id=f"po-delete-select:{payload['postKey'][:60]}",
            placeholder="PO-Eintrag zum Löschen auswählen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = self.entries[int(self.values[0])]
            can_delete_all = await reviewer_allowed(interaction.user)
            is_own_entry = str(entry.get("discordUserId") or entry.get("discord_user_id") or "").strip() == str(interaction.user.id)
            if not can_delete_all and not is_own_entry:
                await interaction.followup.send("⚠️ Du kannst nur deinen eigenen PO-Eintrag löschen.", ephemeral=True)
                return
            action_payload = payload_for_interaction(self.payload, interaction)
            await delete_entry(action_payload, entry, interaction.user)
            await refresh_po_message(interaction.client, action_payload)
            await interaction.followup.send(
                f"🗑️ Gelöscht: **{entry.get('player')}** → **{entry.get('item') or entry.get('itemName')}**.",
                ephemeral=True,
            )
        except Exception as error:
            await interaction.followup.send(f"⚠️ Löschen ging nicht: `{error}`", ephemeral=True)


class PoDeleteEntryView(discord.ui.View):
    def __init__(self, payload, entries):
        super().__init__(timeout=180)
        self.add_item(PoDeleteEntrySelect(payload, entries))


class PoDeleteButton(discord.ui.Button):
    def __init__(self, payload):
        super().__init__(
            custom_id=f"po-delete:{payload['postKey'][:70]}",
            label="PO-Eintrag löschen",
            style=discord.ButtonStyle.danger,
            row=1,
        )
        self.payload = payload

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        all_entries = await fresh_entries_for_payload(self.payload)
        can_delete_all = await reviewer_allowed(interaction.user)
        entries = all_entries if can_delete_all else [
            entry for entry in all_entries
            if str(entry.get("discordUserId") or entry.get("discord_user_id") or "").strip() == user_id
        ]
        if not po_entry_options(entries):
            await interaction.followup.send(
                "Es gibt gerade keinen PO-Eintrag zum Löschen." if can_delete_all else "Es gibt gerade keinen eigenen PO-Eintrag zum Löschen.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            "Wähle den PO-Eintrag aus, den du löschen möchtest." if can_delete_all else "Wähle deinen PO-Eintrag aus, den du löschen möchtest.",
            view=PoDeleteEntryView(self.payload, entries),
            ephemeral=True,
        )


class PoLuckSelect(discord.ui.Select):
    def __init__(self, payload, entries):
        self.payload = payload
        self.entries = list(entries or [])
        options = [
            discord.SelectOption(label=label, value=value, emoji="🍀")
            for value, label in po_entry_options(self.entries, only_unlucked=True)
        ]
        super().__init__(
            custom_id=f"po-luck:{payload['postKey'][:70]}",
            placeholder="Spieler Glück wünschen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = self.entries[int(self.values[0])]
            await luck_entry(self.payload, entry, interaction.user)
            await refresh_po_message(interaction.client, self.payload)
            await interaction.followup.send(
                f"🍀 Glück gewünscht: **{entry.get('player')}**.",
                ephemeral=True,
            )
        except Exception as error:
            await interaction.followup.send(f"⚠️ Kleeblatt ging nicht: `{error}`", ephemeral=True)


class PoView(discord.ui.View):
    def __init__(self, payload, items, entries=None):
        super().__init__(timeout=None)
        self.add_item(PoSearchButton(payload))
        self.add_item(PoDeleteButton(payload))
        self.add_item(PoRejectButton(payload))
        self.add_item(PoReviewSelect(payload, entries or []))


class CombinedRaidPoView(discord.ui.View):
    def __init__(self, raid, payload, items, entries=None):
        super().__init__(timeout=None)
        raid_select = RaidSignupClassSelect(raid)
        raid_select.row = 0
        self.add_item(raid_select)

        for component in [
            PoSearchButton(payload),
            PoDeleteButton(payload),
            PoRejectButton(payload),
        ]:
            component.row = 3
            self.add_item(component)
        review = PoReviewSelect(payload, entries or [])
        review.row = 4
        self.add_item(review)

    @discord.ui.button(label="Bank", emoji="🪑", style=discord.ButtonStyle.secondary, custom_id="combined_raid_signup_bench", row=1)
    async def bench_signup(self, interaction, button):
        await interaction.response.send_modal(RaidSignupStatusModal(self.raid, "bench", "Auf die Bank setzen"))

    @discord.ui.button(label="Spät", emoji="🕒", style=discord.ButtonStyle.secondary, custom_id="combined_raid_signup_late", row=1)
    async def late_signup(self, interaction, button):
        await interaction.response.send_modal(RaidSignupStatusModal(self.raid, "late", "Verspätung eintragen"))

    @discord.ui.button(label="Vorläufig", emoji="⚖️", style=discord.ButtonStyle.secondary, custom_id="combined_raid_signup_tentative", row=1)
    async def tentative_signup(self, interaction, button):
        await interaction.response.send_modal(RaidSignupStatusModal(self.raid, "tentative", "Vorläufig anmelden"))

    @discord.ui.button(label="Abwesenheit", emoji="🚫", style=discord.ButtonStyle.secondary, custom_id="combined_raid_signup_absent", row=1)
    async def absent_signup(self, interaction, button):
        await interaction.response.send_modal(RaidSignupStatusModal(self.raid, "absent", "Als abwesend markieren"))

    @discord.ui.button(label="Ändern", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id="combined_raid_signup_change", row=1)
    async def change_signup(self, interaction, button):
        await interaction.response.send_message(
            "Wähle deine Klasse, um Charakter oder Skillung zu ändern:",
            view=RaidSignupChangeView(self.raid),
            ephemeral=True,
        )

    @property
    def raid(self):
        raid_select = next((item for item in self.children if isinstance(item, RaidSignupClassSelect)), None)
        return getattr(raid_select, "raid", {})


def combined_raid_snapshot(payload):
    raid = payload.get("combinedRaidSnapshot")
    return raid if isinstance(raid, dict) and raid else None


def po_message_parts(payload, entries, p0plus_labels, items):
    po_embed = make_embed(payload, entries, p0plus_labels)
    raid = combined_raid_snapshot(payload)
    if not raid:
        return [po_embed], PoView(payload, items, entries)
    raid_embed = build_raid_announcement_embed(raid)
    helper = {
        "raid": raid,
        "signups": payload.get("combinedRaidSignups") or [],
        "externalSignups": payload.get("combinedRaidExternalSignups") or [],
    }
    add_raid_signup_roster_fields(raid_embed, helper)
    return [raid_embed, po_embed], CombinedRaidPoView(raid, payload, items, entries)


async def refresh_po_message(client, payload):
    payload = payload_with_saved_lichtloot_id(payload)
    target_channel_id = await resolve_po_target_channel_id(client, payload)
    if not target_channel_id:
        raise RuntimeError("PO-Anmelder ohne Ziel-Channel.")
    payload = {**payload, "targetChannelId": str(target_channel_id), "channelId": str(target_channel_id)}
    channel = await fetch_accessible_channel(client, target_channel_id)
    if channel is None:
        raise RuntimeError(f"PO-Anmelder Ziel-Channel nicht erreichbar: {target_channel_id}")
    message = await channel.fetch_message(int(payload["messageId"]))
    items = await items_for_payload(payload)
    entries = await load_entries(payload)
    p0plus_labels = await load_p0plus_labels(payload.get("raid") or "")
    if combined_raid_snapshot(payload):
        helper = await get_raid_helper_for_refresh(payload)
        if helper and helper.get("success"):
            payload = {
                **payload,
                "combinedRaidSnapshot": helper.get("raid") or combined_raid_snapshot(payload),
                "combinedRaidSignups": helper.get("signups") or [],
                "combinedRaidExternalSignups": helper.get("externalSignups") or [],
            }
    embeds, view = po_message_parts(payload, entries, p0plus_labels, items)
    banner, _ = raid_banner_file(combined_raid_snapshot(payload) or {})
    if banner:
        await message.edit(embeds=embeds, attachments=[banner], view=view)
    else:
        await message.edit(embeds=embeds, attachments=[], view=view)
    register_po_view(client, payload, items, entries)


async def refresh_po_message_safely(client, payload):
    try:
        await refresh_po_message(client, payload)
    except Exception as error:
        print(f"PO-Anmelder konnte nach Eintrag nicht aktualisiert werden ({payload.get('postKey')}): {error}")


async def post_or_update_from_queue(client, payload):
    payload = dict(payload or {})
    payload["guildSlug"] = payload_guild_slug(payload)
    post_key = clean(payload.get("postKey") or payload.get("poPostKey") or payload.get("postId"))
    if not post_key and clean(payload.get("source")).lower() == "p0_review":
        raid_key = normalize_raid(payload.get("raid") or payload.get("raidName"))
        raid_id = clean(payload.get("raidId") or payload.get("id") or payload.get("raidPin") or payload.get("prioPin"))
        post_key = clean(f"{raid_key}-po-anmelder-{raid_id}".strip("-"))
        payload["mode"] = "po-anmelder"
        payload["postKey"] = post_key
        payload["poPostKey"] = post_key
        payload["targetChannelId"] = clean(payload.get("targetChannelId") or payload.get("discordChannelId") or payload.get("channelId"))
        payload["sourceChannelId"] = clean(payload.get("sourceChannelId") or payload.get("targetChannelId") or payload.get("discordChannelId") or payload.get("channelId"))
    if not post_key:
        raise RuntimeError("PO-Anmelder ohne Post-ID.")
    original_target_channel_id = payload_target_channel_id(payload)
    target_channel_id = await resolve_po_target_channel_id(client, payload)
    source_channel_id = payload_source_channel_id(payload) or target_channel_id
    if source_channel_id == original_target_channel_id and target_channel_id != original_target_channel_id:
        source_channel_id = target_channel_id
    if not target_channel_id:
        raise RuntimeError("PO-Anmelder ohne Ziel-Channel.")

    state = load_state()
    state_key = po_post_state_key(payload)
    stored = state.get(state_key) or state.get(post_key) or {}
    force_new_message = clean(
        payload.get("forceNewMessage") or payload.get("forceRepost")
    ).lower() in {"1", "true", "yes", "ja"}
    previous_message_id = clean(
        stored.get("messageId") or payload.get("messageId") or payload.get("discordMessageId")
    )
    raid_date, raid_time = payload_raid_schedule(payload, stored)
    normalized = {
        **stored,
        **payload,
        "guildSlug": payload_guild_slug(payload),
        "postKey": post_key,
        "raid": normalize_raid(payload.get("raid") or stored.get("raid")),
        "date": raid_date,
        "raidDate": raid_date,
        "time": raid_time,
        "raidTime": raid_time,
        "title": clean(payload.get("title") or stored.get("title")) or "PO-Anmelder",
        "sourceChannelId": str(source_channel_id),
        "targetChannelId": str(target_channel_id),
        "channelId": str(target_channel_id),
        "messageId": "" if force_new_message else previous_message_id,
    }
    normalized = payload_with_lichtloot_id_from_sources(normalized, stored)
    normalized = await asyncio.to_thread(ensure_payload_lichtloot_raid, normalized)
    if force_new_message and not previous_message_id:
        previous_message_id = await find_existing_message_id(client, normalized)
    elif not normalized.get("messageId"):
        normalized["messageId"] = await find_existing_message_id(client, normalized)

    channel = await fetch_accessible_channel(client, target_channel_id)
    if channel is None:
        raise RuntimeError(f"PO-Anmelder Ziel-Channel nicht erreichbar: {target_channel_id}")
    items = await items_for_payload(normalized)
    entries = await load_entries(normalized)
    p0plus_labels = await load_p0plus_labels(normalized.get("raid") or "")
    embeds, view = po_message_parts(normalized, entries, p0plus_labels, items)
    banner, _ = raid_banner_file(combined_raid_snapshot(normalized) or {})
    message = None
    if normalized.get("messageId"):
        try:
            message = await channel.fetch_message(int(normalized["messageId"]))
            if banner:
                await message.edit(embeds=embeds, attachments=[banner], view=view)
            else:
                await message.edit(embeds=embeds, attachments=[], view=view)
        except Exception as error:
            print(f"PO-Anmelder wird neu gepostet, alte Nachricht nicht nutzbar ({post_key}): {error}")
            message = None
    if message is None:
        if banner:
            message = await channel.send(embeds=embeds, file=banner, view=view, silent=True)
        else:
            message = await channel.send(embeds=embeds, view=view, silent=True)
        normalized["messageId"] = str(message.id)
        if force_new_message and previous_message_id and previous_message_id != normalized["messageId"]:
            try:
                previous_message = await channel.fetch_message(int(previous_message_id))
                await previous_message.delete()
            except Exception as error:
                print(
                    f"Alter PO-Anmelder konnte nach dem Neuposten nicht entfernt werden "
                    f"({post_key}/{previous_message_id}): {error}"
                )
    message = await deduplicate_po_messages(client, channel, normalized, message)
    normalized["messageId"] = str(message.id)
    state[state_key] = normalized
    if post_key in state and post_key != state_key:
        state.pop(post_key, None)
    save_state(state)
    await remember_po_message(normalized)
    register_po_view(client, normalized, items, entries)
    return normalized


async def resolve_queue_item(row_number):
    if not row_number:
        return
    await asyncio.to_thread(api_post, {
        "action": "lichtbotResolveQueue",
        "queueToken": QUEUE_TOKEN,
        "rowNumber": row_number,
    })


async def claim_queue_item(row_number):
    if not row_number:
        return False
    result = await asyncio.to_thread(api_post, {
        "action": "lichtbotClaimQueue",
        "queueToken": QUEUE_TOKEN,
        "rowNumber": row_number,
    })
    return bool(result.get("success") and result.get("claimed"))


def queue_item_created_timestamp(item):
    value = clean((item or {}).get("createdAt"))
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


async def po_queue_loop():
    global empty_queue_log_at
    await client.wait_until_ready()
    if not QUEUE_TOKEN:
        print("PO-Bot Queue deaktiviert: LICHTBOT_QUEUE_TOKEN fehlt.")
        return
    print(f"PO-Bot Queue aktiv: guild={GUILD_SLUG}, api={API_URL}, pruefe alle {QUEUE_CHECK_SECONDS} Sekunden.")
    while not client.is_closed():
        try:
            # on_ready lädt zuerst die App-Emojis. Ohne diese Sperre kann ein
            # Queue-Refresh die Nachricht vorher mit Ersatzsymbolen ersetzen.
            await emoji_cache_ready.wait()
            await refresh_guild_registry()
            result = await asyncio.to_thread(api_get, {
                "action": "lichtbotGetQueueAllGuilds",
                "queueToken": QUEUE_TOKEN,
                "limit": "50",
                "types": "player_login_approval_notice,player_login_granted_notice,po_post,p0_post_refresh,raid_announcement,raid_announcement_refresh,raid_announcement_role_notice,raid_status_staff_notice,loot_master_leadpin_notice,po_release_request_notice,po_release_granted_notice,po_rejection_notice,po_approval_notice,po_post_delete,free_discord_embed",
                "t": int(time.time()),
            })
            if result.get("success"):
                items = result.get("items") or []
                po_items = [
                    item for item in items
                    if clean(item.get("type")) in {"player_login_approval_notice", "player_login_granted_notice", "po_post", "p0_post_refresh"}
                    or clean(item.get("type")) in {
                        "raid_announcement",
                        "raid_announcement_refresh",
                        "raid_announcement_role_notice",
                        "raid_status_staff_notice",
                        "loot_master_leadpin_notice",
                        "po_release_request_notice",
                        "po_release_granted_notice",
                        "po_rejection_notice",
                        "po_approval_notice",
                        "free_discord_embed",
                    }
                ]
                stale_delete_items = [item for item in items if clean(item.get("type")) == "po_post_delete"]
                for item in stale_delete_items:
                    queue_guild_slug = normalize_guild_slug(item.get("guild") or item.get("guildSlug"))
                    token = CURRENT_GUILD_SLUG.set(queue_guild_slug)
                    try:
                        await resolve_queue_item(item.get("rowNumber"))
                    finally:
                        CURRENT_GUILD_SLUG.reset(token)
                if stale_delete_items:
                    print(f"PO-Bot Queue: {len(stale_delete_items)} alte po_post_delete-Auftraege erledigt markiert.")
                if not po_items:
                    now = time.time()
                    if now - empty_queue_log_at >= 60:
                        queue_types = ", ".join(clean(item.get("type")) or "?" for item in items) or "leer"
                        print(f"PO-Bot Queue: kein po_post gefunden. Antwort-Typen: {queue_types}")
                        empty_queue_log_at = now
                for item in po_items:
                    queue_guild_slug = normalize_guild_slug(item.get("guild") or item.get("guildSlug"))
                    token = CURRENT_GUILD_SLUG.set(queue_guild_slug)
                    payload = item.get("payload") or {}
                    payload["guildSlug"] = queue_guild_slug
                    mode = clean(payload.get("mode")).lower() or "signup"
                    try:
                        item_type = clean(item.get("type"))
                        if not await claim_queue_item(item.get("rowNumber")):
                            print(
                                "Queue-Auftrag bereits von einer anderen Bot-Instanz übernommen: "
                                f"{queue_guild_slug}:{item_type}:{item.get('rowNumber')}"
                            )
                            continue
                        if item_type == "player_login_approval_notice":
                            await send_player_login_approval_notice_from_queue(payload)
                            await resolve_queue_item(item.get("rowNumber"))
                            continue
                        if item_type == "player_login_granted_notice":
                            await send_player_login_granted_notice_from_queue(payload)
                            await resolve_queue_item(item.get("rowNumber"))
                            continue
                        if item_type == "free_discord_embed":
                            sent = await post_free_discord_embed_from_queue(payload)
                            await resolve_queue_item(item.get("rowNumber"))
                            print(
                                "Freies Discord-Embed "
                                + ("gesendet" if sent else "konnte nicht gesendet werden")
                                + f": {current_guild_slug()}:{payload.get('title') or payload.get('embedType') or '?'}"
                            )
                            continue
                        if (
                            item_type == "raid_announcement_role_notice"
                            and queue_item_created_timestamp(item) < BOT_STARTED_AT
                        ):
                            await resolve_queue_item(item.get("rowNumber"))
                            print(
                                "Alte Raidankündigungs-DM beim Neustart verworfen: "
                                f"{queue_guild_slug}:{payload.get('raidId') or item.get('rowNumber')}"
                            )
                            continue
                        if item_type == "po_rejection_notice":
                            sent = await send_po_rejection_message(
                                client,
                                payload,
                                clean(payload.get("reason") or payload.get("rejectionReason"))
                            )
                            await resolve_queue_item(item.get("rowNumber"))
                            print(
                                "PO-Ablehnungsnachricht "
                                + ("gesendet" if sent else "konnte nicht gesendet werden")
                                + f": {current_guild_slug()}:{payload.get('player') or '?'}"
                            )
                            continue
                        if item_type == "po_approval_notice":
                            sent = await send_po_approval_message(client, payload)
                            await resolve_queue_item(item.get("rowNumber"))
                            print(
                                "PO-Freigabenachricht "
                                + ("gesendet" if sent else "konnte nicht gesendet werden")
                                + f": {current_guild_slug()}:{payload.get('player') or '?'}"
                            )
                            continue
                        if item_type == "raid_announcement":
                            helper = await get_raid_helper_for_refresh(payload)
                            fallback_helper = raid_helper_snapshot_from_payload(payload)
                            if not helper or not helper.get("success"):
                                helper = fallback_helper
                            raid = helper.get("raid") or fallback_helper.get("raid") or {}
                            followup = dict(payload.get("followupPoPost") or {})
                            channel_id = clean(
                                payload.get("channelId")
                                or payload.get("discordChannelId")
                                or raid.get("discordChannelId")
                            )
                            if not followup:
                                posted = await post_raid_announcement_by_id(
                                    payload.get("raidId") or payload.get("id"),
                                    channel_id,
                                    payload,
                                    force_new=clean(
                                        payload.get("forceNewMessage") or payload.get("forceRepost")
                                    ).lower() in {"1", "true", "yes", "ja"},
                                )
                                if posted or posted == "stale":
                                    await resolve_queue_item(item.get("rowNumber"))
                                    print(
                                        f"Raidanmelder allein vom PO-Bot gepostet: "
                                        f"{current_guild_slug()}:{payload.get('raidId') or payload.get('id')}"
                                    )
                                continue
                            combined_payload = {
                                **followup,
                                "guildSlug": queue_guild_slug,
                                "sourceChannelId": clean(followup.get("sourceChannelId") or channel_id),
                                "targetChannelId": channel_id,
                                "channelId": channel_id,
                                "restoreArchived": "true",
                                "forceNewMessage": "false",
                                "lichtlootRaidId": clean(
                                    followup.get("lichtlootRaidId")
                                    or raid.get("raidId")
                                    or payload.get("raidId")
                                ),
                                "combinedRaidSnapshot": raid,
                                "combinedRaidSignups": helper.get("signups") or [],
                                "combinedRaidExternalSignups": helper.get("externalSignups") or [],
                            }
                            normalized = await post_or_update_from_queue(client, combined_payload)
                            await asyncio.to_thread(api_post, {
                                "action": "lichtbotSetRaidDiscordMessage",
                                "queueToken": QUEUE_TOKEN,
                                "raidId": clean(raid.get("raidId") or payload.get("raidId")),
                                "discordChannelId": channel_id,
                                "discordMessageId": clean(normalized.get("messageId")),
                            })
                            await resolve_queue_item(item.get("rowNumber"))
                            print(
                                f"Kombinierter Raid-/PO-Anmelder vom PO-Bot gepostet: "
                                f"{current_guild_slug()}:{payload.get('raidId') or payload.get('id')}"
                            )
                            continue
                        if item_type == "raid_announcement_refresh":
                            refreshed = await refresh_raid_signup_message_by_id(
                                payload.get("raidId") or payload.get("id"),
                                payload.get("channelId") or payload.get("discordChannelId"),
                                payload.get("messageId") or payload.get("discordMessageId") or payload.get("raidHelperMessageId"),
                                payload
                            )
                            if refreshed:
                                await resolve_queue_item(item.get("rowNumber"))
                                if refreshed == "foreign_message":
                                    print(
                                        "Veralteter Raidanmelder-Refresh erledigt markiert; "
                                        "die Nachricht gehört einem anderen Bot: "
                                        f"{current_guild_slug()}:{payload.get('raidId') or payload.get('id')}"
                                    )
                                else:
                                    print(f"Raidanmelder vom PO-Bot aktualisiert: {current_guild_slug()}:{payload.get('raidId') or payload.get('id')}")
                            continue
                        if item_type == "raid_announcement_role_notice":
                            await send_raid_announcement_notice_from_queue(payload)
                            await resolve_queue_item(item.get("rowNumber"))
                            continue
                        if item_type == "raid_status_staff_notice":
                            await send_raid_status_notice_from_queue(payload)
                            await resolve_queue_item(item.get("rowNumber"))
                            continue
                        if item_type == "loot_master_leadpin_notice":
                            await send_loot_master_leadpin_notice_from_queue(payload)
                            await resolve_queue_item(item.get("rowNumber"))
                            continue
                        if item_type == "po_release_request_notice":
                            await send_po_release_request_notice_from_queue(payload)
                            await resolve_queue_item(item.get("rowNumber"))
                            continue
                        if item_type == "po_release_granted_notice":
                            await send_po_release_granted_notice_from_queue(payload)
                            await resolve_queue_item(item.get("rowNumber"))
                            continue
                        if item_type == "raid_signup_notice":
                            print(f"Spieler-DM bleibt für den Hauptbot offen: {current_guild_slug()}:{item.get('rowNumber')}")
                            continue
                        if item_type == "p0_post_refresh":
                            payload["source"] = payload.get("source") or "p0_review"
                            payload["mode"] = payload.get("mode") or "po-anmelder"
                        if mode not in {"signup", "anmelder", "po_signup", "po-anmelder"} and item_type != "p0_post_refresh":
                            await resolve_queue_item(item.get("rowNumber"))
                            print(f"Alter PO-Post-Auftrag uebersprungen und erledigt markiert: {payload.get('postKey') or item.get('rowNumber')}")
                            continue
                        normalized = await post_or_update_from_queue(client, payload)
                        await resolve_queue_item(item.get("rowNumber"))
                        print(f"PO-Anmelder aus Gildenleitung gepostet: {current_guild_slug()}:{normalized.get('postKey')}")
                    except Exception as error:
                        print(f"PO-Anmelder-Queue konnte nicht verarbeitet werden: {error}")
                    finally:
                        CURRENT_GUILD_SLUG.reset(token)
            else:
                print(f"PO-Bot Queue Antwort: {result}")
        except Exception as error:
            print(f"Fehler im PO-Bot Queue-Loop: {error}")
        await asyncio.sleep(QUEUE_CHECK_SECONDS)


NACHTLOOT_HELP_TOPICS = {
    "login": (
        "SpielerLogin & Freigabe",
        "Erstelle deinen SpielerLogin auf LichtLoot. Neue Logins müssen zuerst von der "
        "Gildenleitung freigegeben werden. Wenn die Freigabe fehlt, melde dich hier mit deinem Charakternamen."
    ),
    "prio": (
        "P1, P2 und P3",
        "Öffne Mein LichtLoot, wähle deinen Charakter und anschließend den Raid. Dort kannst du deine "
        "P1, P2 und P3 eintragen oder ändern."
    ),
    "po": (
        "PO-Anmeldung",
        "Für MC, BWL, AQ40 und Naxx benötigst du die passende PO-Freigabe für Nachtloot. "
        "Fehlt sie, wende dich bitte an einen PO-Freigeber oder die Gildenleitung."
    ),
    "raid": (
        "Raid-Anmeldung",
        "Wähle im Discord-Raidanmelder Klasse, Skillung und anschließend deinen LichtLoot-SpielerLogin. "
        "Danach wählst du deinen Charakter aus."
    ),
    "fehler": (
        "Fehler melden",
        "Bitte nenne deinen Charakter, den Raid, den genauen Wortlaut der Fehlermeldung und sende möglichst "
        "einen Screenshot. So kann die Gildenleitung schneller helfen."
    ),
}


def nachtloot_help_answer(question):
    text = clean(question).casefold()
    topic_keys = []
    if any(word in text for word in ("login", "pin", "freigabe", "account", "konto")):
        topic_keys.append("login")
    if any(word in text for word in ("prio", "p1", "p2", "p3")):
        topic_keys.append("prio")
    if any(word in text for word in (" po ", "po-", "po+", "item", "freigegeben")):
        topic_keys.append("po")
    if any(word in text for word in ("raid", "anmeld", "bank", "spät", "abwes")):
        topic_keys.append("raid")
    if not topic_keys:
        topic_keys.append("fehler")
    parts = [NACHTLOOT_HELP_TOPICS[key][1] for key in dict.fromkeys(topic_keys)]
    return "\n\n".join(parts)


class NachtlootHelpQuestionModal(discord.ui.Modal, title="KI-Frage an die Nachtloot-Hilfe"):
    question = discord.ui.TextInput(
        label="Wobei brauchst du Hilfe?",
        placeholder="Beschreibe deine Frage möglichst genau …",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    async def on_submit(self, interaction):
        embed = discord.Embed(
            title="✨ Antwort der Nachtloot-Hilfe",
            description=nachtloot_help_answer(self.question.value),
            color=discord.Color.from_rgb(88, 101, 242),
        )
        embed.add_field(name="Deine Frage", value=clean(self.question.value)[:1024], inline=False)
        embed.set_footer(text="Die Antwort ist nur für dich sichtbar. Bei ungelösten Problemen hilft die Gildenleitung.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class NachtlootHelpTopicSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Wobei brauchst du Hilfe?",
            min_values=1,
            max_values=1,
            custom_id="nachtloot_help_topic",
            options=[
                discord.SelectOption(label=label, value=key)
                for key, (label, _answer) in NACHTLOOT_HELP_TOPICS.items()
            ],
        )

    async def callback(self, interaction):
        label, answer = NACHTLOOT_HELP_TOPICS.get(self.values[0], NACHTLOOT_HELP_TOPICS["fehler"])
        embed = discord.Embed(title=f"💡 {label}", description=answer, color=discord.Color.from_rgb(250, 204, 21))
        await interaction.response.send_message(embed=embed, ephemeral=True)


class NachtlootHelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(NachtlootHelpTopicSelect())
        self.add_item(discord.ui.Button(
            label="Nachtloot öffnen",
            emoji="🔗",
            style=discord.ButtonStyle.link,
            url="https://lichtloot.de/start.html?guild=nachtloot",
        ))

    @discord.ui.button(
        label="KI-Frage stellen",
        emoji="✨",
        style=discord.ButtonStyle.primary,
        custom_id="nachtloot_help_ai_question",
        row=1,
    )
    async def ask_ai(self, interaction, _button):
        await interaction.response.send_modal(NachtlootHelpQuestionModal())


class PoBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(NachtlootHelpView())
        self.bg_task = asyncio.create_task(po_queue_loop())
        if TEST_GUILD_ID:
            guild = discord.Object(id=int(TEST_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Slash-Commands fuer Testserver {TEST_GUILD_ID} synchronisiert.")
        else:
            await self.tree.sync()


client = PoBot()


async def sync_po_commands_for_connected_guilds():
    global slash_commands_synced_for_guilds
    if slash_commands_synced_for_guilds:
        return
    slash_commands_synced_for_guilds = True
    # In Produktion sind die Befehle global registriert. Alte, zusaetzlich auf
    # einzelnen Servern registrierte Kopien werden entfernt, sonst zeigt
    # Discord denselben Befehl doppelt an.
    if TEST_GUILD_ID:
        return
    for guild in getattr(client, "guilds", []) or []:
        try:
            guild_object = discord.Object(id=int(guild.id))
            client.tree.clear_commands(guild=guild_object)
            synced = await client.tree.sync(guild=guild_object)
            print(f"Alte lokale PO Slash-Commands fuer {guild.name} ({guild.id}) entfernt: {len(synced)} verbleiben")
        except Exception as error:
            print(f"PO Slash-Commands fuer Discord-Server {getattr(guild, 'id', '?')} konnten nicht synchronisiert werden: {error}")


@client.event
async def on_ready():
    print(f"PO Bot online als {client.user}")
    await refresh_guild_registry()
    await sync_po_commands_for_connected_guilds()
    if not hasattr(client, "discord_channel_sync_started"):
        client.discord_channel_sync_started = True
        client.loop.create_task(discord_channel_sync_loop())
    emoji_cache_ready.clear()
    found_classes, found_specs, found_items = {}, {}, {}
    try:
        found_classes, found_specs, found_items = await refresh_emoji_cache()
    # Der PO-Anmelder und der Raidanmelder verwenden denselben Emoji-Cache.
    # Fehlen in der PO-Bot-App noch Klassen-/Skillungsbilder, werden sie beim
    # Start einmalig wie die Itemicons ergänzt und anschließend neu geladen.
        if len(found_classes) < len(CLASS_EMOJI_NAME_ALIASES) or len(found_specs) < len(SPEC_EMOJI_NAME_ALIASES):
            try:
                emoji_sync = await sync_raid_application_emojis()
                found_classes, found_specs, found_items = await refresh_emoji_cache()
                print(
                    "PO Raid-Emojis automatisch synchronisiert: "
                    f"{len(emoji_sync['created'])} neu, {len(emoji_sync['skipped'])} vorhanden, "
                    f"{len(emoji_sync['failed'])} Fehler."
                )
            except Exception as error:
                print(f"PO Raid-Emoji-Autosync übersprungen: {error}")
    finally:
        # Auch bei einem vorübergehenden Discord-Fehler darf der Bot nicht
        # blockieren; dann greifen weiterhin die vorhandenen Ersatzsymbole.
        emoji_cache_ready.set()
    print(f"PO Klassenemojis gefunden: {', '.join(sorted(found_classes.keys())) or 'keine'}")
    print(f"PO Skill-Emojis gefunden: {', '.join(sorted(found_specs.keys())) or 'keine'}")
    print(f"PO Item-Emojis gefunden: {len(found_items)}")
    # Erst nach dem Laden/Synchronisieren der Application-Emojis werden die
    # persistenten Raidanmelder registriert und neu gerendert. Andernfalls
    # bleiben nach einem Neustart die Unicode-Ersatzsymbole im alten Embed.
    if not hasattr(client, "raid_signup_views_restored"):
        client.raid_signup_views_restored = True
        await restore_active_raid_signup_views()
    state = load_state()
    for payload in state.values():
        if not isinstance(payload, dict) or not payload.get("postKey"):
            continue
        token = CURRENT_GUILD_SLUG.set(normalize_guild_slug(payload.get("guildSlug") or payload.get("guild")))
        try:
            await restore_po_view_fast(client, payload)
        except Exception as error:
            print(f"PO View konnte nicht wiederhergestellt werden ({payload.get('postKey')}): {error}")
        finally:
            CURRENT_GUILD_SLUG.reset(token)
    restored = 0
    known_posts = set(state.keys())
    restore_slugs = list(GUILD_REGISTRY.keys()) or [current_guild_slug()]
    for guild_slug in restore_slugs:
        token = CURRENT_GUILD_SLUG.set(normalize_guild_slug(guild_slug))
        try:
            for payload in await load_payloads_from_api_entries():
                state_key = po_post_state_key(payload)
                if state_key in known_posts:
                    continue
                try:
                    items, entries = await restore_po_view_fast(client, payload)
                    state[state_key] = payload
                    known_posts.add(state_key)
                    restored += 1
                except Exception as error:
                    print(f"PO View konnte nicht aus LichtLoot wiederhergestellt werden ({payload.get('postKey')}): {error}")
        finally:
            CURRENT_GUILD_SLUG.reset(token)
    if restored:
        save_state(state)
        print(f"PO Views aus LichtLoot wiederhergestellt: {restored}")


async def refresh_signup_posts_in_channel(interaction, refresh_kind="alle"):
    """Aktualisiert vorhandene Raid-/PO-Anmelder im aktuellen Discord-Channel."""
    await refresh_guild_registry()
    guild_slug = guild_slug_for_discord_server(getattr(interaction, "guild", None), GUILD_SLUG)
    channel_id = clean(getattr(interaction, "channel_id", ""))
    kind = clean(refresh_kind).lower() or "alle"
    raid_refreshed = 0
    raid_replaced = 0
    po_refreshed = 0
    skipped = 0
    errors = []

    token = CURRENT_GUILD_SLUG.set(guild_slug)
    try:
        if kind in {"alle", "raid"}:
            try:
                result = await asyncio.to_thread(api_get, {
                    "action": "getActiveRaids",
                    "guild": guild_slug,
                    "guildSlug": guild_slug,
                    "t": int(time.time()),
                })
                active_raids = list(result.get("allRaids") or result.get("raids") or [])
                # Zuerst die real vorhandenen eigenen Raidposts dieses
                # Channels über Raidtyp + Datum zuordnen. Das repariert auch
                # historisch falsche gespeicherte Channel-/Message-IDs.
                discovered_messages = {}
                try:
                    channel = client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
                    async for candidate in channel.history(limit=100):
                        if not client.user or candidate.author.id != client.user.id or not candidate.embeds:
                            continue
                        embed = candidate.embeds[0]
                        field_names = {clean(field.name).lower() for field in embed.fields}
                        if not ({"slots", "gesamt angemeldet", "rollenverteilung"} & field_names):
                            continue
                        candidate_raid = normalize_raid(clean(embed.title)).lower()
                        field_text = " ".join(clean(field.value) for field in embed.fields)
                        for raid in active_raids:
                            raid_key = normalize_raid(raid.get("raid") or raid.get("raidName") or "").lower()
                            raid_date = clean(raid.get("raidDate") or raid.get("date"))
                            if raid_key != candidate_raid:
                                continue
                            if raid_date and raid_date not in field_text and format_raid_announcement_date(raid_date) not in field_text:
                                continue
                            raid_id = clean(raid.get("raidId") or raid.get("id"))
                            discovered_messages[raid_id] = candidate
                            raid["discordChannelId"] = channel_id
                            raid["discordMessageId"] = str(candidate.id)
                            await asyncio.to_thread(api_post, {
                                "action": "lichtbotSetRaidDiscordMessage",
                                "queueToken": QUEUE_TOKEN,
                                "guild": guild_slug,
                                "guildSlug": guild_slug,
                                "raidId": raid_id,
                                "discordChannelId": channel_id,
                                "discordMessageId": str(candidate.id),
                            })
                            break
                except Exception as error:
                    print(f"Raidanmelder im aktuellen Channel konnten nicht vorab zugeordnet werden: {error}")

                for raid in active_raids:
                    raid_channel_id = clean(raid.get("discordChannelId") or raid.get("discord_channel_id"))
                    message_id = clean(raid.get("discordMessageId") or raid.get("discord_message_id"))
                    if raid_channel_id != channel_id or not message_id:
                        continue
                    try:
                        refreshed = await refresh_raid_signup_message_by_id(
                            clean(raid.get("raidId") or raid.get("id")),
                            raid_channel_id,
                            message_id,
                            raid,
                        )
                        if refreshed is True:
                            raid_refreshed += 1
                        elif refreshed in {"foreign_message", "missing_message"}:
                            old_message = None
                            try:
                                channel = client.get_channel(int(raid_channel_id)) or await client.fetch_channel(int(raid_channel_id))
                                old_message = await channel.fetch_message(int(message_id))
                            except Exception:
                                old_message = None
                            own_message = None
                            try:
                                wanted_raid = normalize_raid(raid.get("raid") or raid.get("raidName") or "").lower()
                                wanted_date = clean(raid.get("raidDate") or raid.get("date"))
                                channel = client.get_channel(int(raid_channel_id)) or await client.fetch_channel(int(raid_channel_id))
                                async for candidate in channel.history(limit=100):
                                    if not client.user or candidate.author.id != client.user.id or not candidate.embeds:
                                        continue
                                    embed = candidate.embeds[0]
                                    title_key = normalize_raid(clean(embed.title)).lower()
                                    field_text = " ".join(clean(field.value) for field in embed.fields)
                                    date_matches = not wanted_date or wanted_date in field_text or format_raid_announcement_date(wanted_date) in field_text
                                    if wanted_raid and wanted_raid in title_key and date_matches:
                                        own_message = candidate
                                        break
                            except Exception as error:
                                print(f"Eigener bestehender Raidanmelder konnte nicht gesucht werden: {error}")
                            if own_message is not None:
                                await asyncio.to_thread(api_post, {
                                    "action": "lichtbotSetRaidDiscordMessage",
                                    "queueToken": QUEUE_TOKEN,
                                    "guild": guild_slug,
                                    "guildSlug": guild_slug,
                                    "raidId": clean(raid.get("raidId") or raid.get("id")),
                                    "discordChannelId": raid_channel_id,
                                    "discordMessageId": str(own_message.id),
                                })
                                refreshed = await refresh_raid_signup_message_by_id(
                                    clean(raid.get("raidId") or raid.get("id")),
                                    raid_channel_id,
                                    str(own_message.id),
                                    {**raid, "discordMessageId": str(own_message.id)},
                                )
                                if refreshed is True:
                                    raid_refreshed += 1
                                    continue
                            # Fehlt nur eine alte Nachricht, aber es gibt in
                            # diesem Channel keinen passenden eigenen Post,
                            # wird hier kein fremder Raid (z. B. NAXX im
                            # AQ20-Channel) neu gepostet.
                            if refreshed == "missing_message":
                                skipped += 1
                                continue
                            posted = await post_raid_announcement_by_id(
                                clean(raid.get("raidId") or raid.get("id")),
                                raid_channel_id,
                                raid,
                                force_new=True,
                            )
                            if posted is True:
                                raid_replaced += 1
                                if old_message is not None:
                                    try:
                                        await old_message.delete()
                                    except (discord.Forbidden, discord.NotFound):
                                        errors.append(
                                            f"Alter Post für {clean(raid.get('raidName') or raid.get('raid'))} konnte nicht entfernt werden."
                                        )
                            else:
                                skipped += 1
                        else:
                            skipped += 1
                    except Exception as error:
                        errors.append(f"Raid {clean(raid.get('raidName') or raid.get('raid') or raid.get('raidId'))}: {error}")
            except Exception as error:
                errors.append(f"Raidanmelder konnten nicht geladen werden: {error}")

        if kind in {"alle", "po"}:
            state = load_state()
            payloads = []
            payloads.extend(payload for payload in state.values() if isinstance(payload, dict))
            try:
                payloads.extend(await load_payloads_from_api_entries())
            except Exception as error:
                errors.append(f"PO-Anmelder konnten nicht vollständig geladen werden: {error}")

            seen_messages = set()
            for raw_payload in payloads:
                payload = dict(raw_payload or {})
                payload_channel_id = clean(
                    payload.get("targetChannelId")
                    or payload.get("channelId")
                    or payload.get("sourceChannelId")
                )
                message_id = clean(payload.get("messageId") or payload.get("discordMessageId"))
                if payload_channel_id != channel_id or not message_id or message_id in seen_messages:
                    continue
                if payload_guild_slug(payload) != guild_slug:
                    continue
                seen_messages.add(message_id)
                try:
                    await refresh_po_message(client, payload)
                    po_refreshed += 1
                except discord.NotFound:
                    # Gelöschte historische PO-Posts sind kein Refresh-Fehler.
                    skipped += 1
                except Exception as error:
                    errors.append(f"PO {clean(payload.get('title') or payload.get('postKey'))}: {error}")

        return {
            "raid": raid_refreshed,
            "replaced": raid_replaced,
            "po": po_refreshed,
            "skipped": skipped,
            "errors": errors,
        }
    finally:
        CURRENT_GUILD_SLUG.reset(token)


@client.tree.command(name="anmelder_refresh", description="Aktualisiert Raid- und PO-Anmelder im aktuellen Channel.")
@app_commands.describe(was="Welche Anmelder sollen aktualisiert werden?")
@app_commands.choices(was=[
    app_commands.Choice(name="Alle Anmelder", value="alle"),
    app_commands.Choice(name="Nur Raidanmelder", value="raid"),
    app_commands.Choice(name="Nur PO-Anmelder", value="po"),
])
async def anmelder_refresh(interaction, was: str = "alle"):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await emoji_cache_ready.wait()
    result = await refresh_signup_posts_in_channel(interaction, was)
    raid_count = int(result.get("raid") or 0)
    replaced = int(result.get("replaced") or 0)
    po_count = int(result.get("po") or 0)
    skipped = int(result.get("skipped") or 0)
    errors = result.get("errors") or []
    total = raid_count + replaced + po_count
    if total:
        text = f"✅ Aktualisiert: **{raid_count} Raidanmelder** und **{po_count} PO-Anmelder**."
        if replaced:
            text += f" **{replaced} alter Raidanmelder** wurde durch die aktuelle Bot-Version ersetzt."
    else:
        text = "ℹ️ In diesem Channel wurden keine passenden Anmelder gefunden."
    if skipped:
        text += f" Übersprungen: {skipped}."
    if errors:
        preview = "\n".join(f"• {clean(error)[:220]}" for error in errors[:3])
        text += f"\n⚠️ {len(errors)} Fehler:\n{preview}"
    await interaction.followup.send(text, ephemeral=True)


def slash_embed_points(value):
    return [clean(entry) for entry in re.split(r"[\n|]+", clean(value)) if clean(entry)]


@client.tree.command(name="raid_anmelder", description="Erstellt einen Raidanmelder und speichert ihn in LichtLoot.")
@app_commands.describe(
    raid="Raid, z. B. MC, BWL, AQ20, AQ40, ZG oder NAXX",
    datum="Raid-Datum, z. B. 23.08.2026",
    uhrzeit="Startzeit, z. B. 19:45",
    titel="Optionaler eigener Titel",
    gesamt="Maximale Spielerzahl",
    tanks="Anzahl Tankplaetze",
    heiler="Anzahl Heilerplaetze",
    beschreibung="Optionaler Text im Anmelder",
)
async def raid_anmelder(
    interaction: discord.Interaction,
    raid: str,
    datum: str,
    uhrzeit: str,
    titel: str = "",
    gesamt: int = 20,
    tanks: int = 2,
    heiler: int = 4,
    beschreibung: str = "",
):
    await refresh_guild_registry()
    token = CURRENT_GUILD_SLUG.set(guild_slug_for_discord_server(interaction.guild, GUILD_SLUG))
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
        raid_key = normalize_raid(raid)
        post_key = f"{slug(raid_key)}-raid-{datetime.now().strftime('%Y%m%d-%H%M')}-{str(int(time.time()))[-4:]}"
        guild_info = GUILD_REGISTRY.get(current_guild_slug()) or {}
        total = max(1, int(gesamt))
        tank_slots = max(0, int(tanks))
        heal_slots = max(0, int(heiler))
        payload = {
            "guildSlug": current_guild_slug(), "postKey": post_key, "raidId": post_key,
            "raid": raid_key, "raidName": display_raid(raid_key),
            "date": clean(datum), "raidDate": clean(datum),
            "time": clean(uhrzeit), "raidTime": clean(uhrzeit),
            "title": clean(titel) or display_raid(raid_key),
            "description": clean(beschreibung),
            "channelId": str(interaction.channel_id), "sourceChannelId": str(interaction.channel_id),
            "targetChannelId": str(interaction.channel_id), "messageId": "",
            "server": clean(guild_info.get("server")) or "Everlook",
            "guildName": clean(guild_info.get("name")) or current_guild_slug(),
            "createdBy": clean(getattr(interaction.user, "display_name", "")) or "Gildenleitung",
            "status": "offen", "maxPlayers": total, "tankSlots": tank_slots,
            "healSlots": heal_slots, "ddSlots": max(0, total - tank_slots - heal_slots),
        }
        payload = await asyncio.to_thread(ensure_payload_lichtloot_raid, payload)
        raid_id = clean(payload.get("raidId") or payload.get("lichtlootCanonicalRaidId") or post_key)
        posted = await post_raid_announcement_by_id(raid_id, interaction.channel_id, payload, force_new=True)
        if not posted:
            raise RuntimeError("Der Raidanmelder konnte nicht in Discord gepostet werden.")
        await interaction.followup.send(
            f"✅ Raidanmelder erstellt und in LichtLoot gespeichert.\n"
            f"Prio-PIN: `{payload_lichtloot_raid_pin(payload)}` · Lead-PIN: `{clean(payload.get('leadPin'))}`",
            ephemeral=True,
        )
    except Exception as error:
        await interaction.followup.send(f"❌ Raidanmelder konnte nicht erstellt werden: {error}", ephemeral=True)
    finally:
        CURRENT_GUILD_SLUG.reset(token)


async def post_slash_embed(interaction, payload, success_text):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        posted = await post_free_discord_embed_from_queue({**payload, "channelId": str(interaction.channel_id)})
        await interaction.followup.send(success_text if posted else "❌ Das Embed konnte nicht gepostet werden.", ephemeral=True)
    except Exception as error:
        await interaction.followup.send(f"❌ Das Embed konnte nicht gepostet werden: {error}", ephemeral=True)


@client.tree.command(name="abstimmung_erstellen", description="Erstellt eine Abstimmung mit anklickbaren Reaktionen.")
async def abstimmung_erstellen(interaction: discord.Interaction, thema: str, antworten: str, beschreibung: str = "", farbe: str = "purple"):
    points = slash_embed_points(antworten)
    if len(points) < 2:
        await interaction.response.send_message("Bitte mindestens zwei Antworten mit | trennen.", ephemeral=True)
        return
    await post_slash_embed(interaction, {"embedType": "poll", "title": thema, "description": beschreibung, "points": points, "color": farbe}, "✅ Abstimmung erstellt.")


@client.tree.command(name="offimeeting_erstellen", description="Erstellt eine strukturierte Einladung zum Offimeeting.")
async def offimeeting_erstellen(interaction: discord.Interaction, titel: str, datum: str, uhrzeit: str, tagesordnung: str, ort: str = "Discord", beschreibung: str = "", farbe: str = "gold"):
    await post_slash_embed(interaction, {"embedType": "meeting", "title": titel, "description": beschreibung, "meetingDate": datum, "meetingTime": uhrzeit, "meetingLocation": ort, "points": slash_embed_points(tagesordnung), "color": farbe}, "✅ Offimeeting erstellt.")


@client.tree.command(name="ankuendigung_erstellen", description="Erstellt eine gegliederte Ankündigung.")
async def ankuendigung_erstellen(interaction: discord.Interaction, titel: str, text: str, punkte: str = "", farbe: str = "sky"):
    await post_slash_embed(interaction, {"embedType": "custom", "title": titel, "description": text, "points": slash_embed_points(punkte), "color": farbe}, "✅ Ankündigung erstellt.")


@client.tree.command(name="embed_erstellen", description="Erstellt ein frei gestaltbares Discord-Embed.")
async def embed_erstellen(interaction: discord.Interaction, titel: str, text: str = "", felder: str = "", farbe: str = "sky", fusszeile: str = ""):
    await post_slash_embed(interaction, {"embedType": "custom", "title": titel, "description": text, "points": slash_embed_points(felder), "color": farbe, "footer": fusszeile}, "✅ Freies Embed erstellt.")


@client.tree.command(name="po_anmelder", description="Erstellt einen PO-Anmelder im aktuellen Channel.")
@app_commands.describe(
    raid="Raid, z. B. MC, BWL, AQ20, AQ40, ZG, NAXX",
    datum="Datum, z. B. 23.07.2026",
    uhrzeit="Uhrzeit, z. B. 19:45",
    titel="Optionaler Titel",
)
async def po_anmelder(interaction, raid: str, datum: str, uhrzeit: str, titel: str = ""):
    await refresh_guild_registry()
    token = CURRENT_GUILD_SLUG.set(
        guild_slug_for_discord_server(getattr(interaction, "guild", None), GUILD_SLUG)
    )
    try:
        await interaction.response.defer(ephemeral=True)
        raid_key = normalize_raid(raid)
        post_key = f"{slug(raid_key)}-po-{datetime.now().strftime('%Y%m%d-%H%M')}-{str(int(time.time()))[-4:]}"
        guild_info = GUILD_REGISTRY.get(current_guild_slug()) or {}
        payload = {
            "guildSlug": current_guild_slug(),
            "postKey": post_key,
            "raid": raid_key,
            "raidName": display_raid(raid_key),
            "date": clean(datum), "raidDate": clean(datum),
            "time": clean(uhrzeit), "raidTime": clean(uhrzeit),
            "title": clean(titel) or f"{display_raid(raid_key)} PO-Anmelder",
            "channelId": str(interaction.channel_id),
            "sourceChannelId": str(interaction.channel_id),
            "targetChannelId": str(interaction.channel_id),
            "messageId": "",
            "server": clean(guild_info.get("server")) or "Everlook",
            "guildName": clean(guild_info.get("name")) or current_guild_slug(),
            "createdBy": clean(getattr(interaction.user, "display_name", "")) or "Gildenleitung",
        }
        payload = await asyncio.to_thread(ensure_payload_lichtloot_raid, payload)
        items = await items_for_payload(payload)
        embed = make_embed(payload, [])
        message = await send_po_message(interaction.channel, embed, PoView(payload, items, []))
        payload["messageId"] = str(message.id)
        await remember_po_message(payload)
        state = load_state()
        state[po_post_state_key(payload)] = payload
        save_state(state)
        client.add_view(PoView(payload, items, []), message_id=message.id)
        await edit_po_message(message, make_embed(payload, []), PoView(payload, items, []))
        await interaction.followup.send(
            f"✅ PO-Anmelder erstellt und in LichtLoot gespeichert.\n"
            f"Prio-PIN: `{payload_lichtloot_raid_pin(payload)}` · Lead-PIN: `{clean(payload.get('leadPin'))}`",
            ephemeral=True,
        )
    finally:
        CURRENT_GUILD_SLUG.reset(token)


@client.tree.command(name="po_emojis_sync", description="Lädt fehlende Item-Emojis für einen Raid automatisch hoch.")
@app_commands.describe(
    raid="Raid, z. B. MC, BWL, AQ20, AQ40, ZG, NAXX",
    limit="Maximal neu anzulegende Emojis. Standard: 25",
)
@app_commands.choices(raid=[
    app_commands.Choice(name="MC", value="MC"),
    app_commands.Choice(name="BWL", value="BWL"),
    app_commands.Choice(name="AQ20", value="AQ20"),
    app_commands.Choice(name="AQ40", value="AQ40"),
    app_commands.Choice(name="ZG", value="ZG"),
    app_commands.Choice(name="Naxxramas", value="NAXX"),
])
async def po_emojis_sync(interaction, raid: str, limit: int = 25):
    await run_po_emoji_sync(interaction, raid, limit)


@client.tree.command(name="poemoji", description="Kurzform: Lädt fehlende Item-Emojis für einen Raid hoch.")
@app_commands.describe(
    raid="Raid, z. B. MC, BWL, AQ20, AQ40, ZG, NAXX",
    limit="Maximal neu anzulegende Emojis. Standard: 25",
)
@app_commands.choices(raid=[
    app_commands.Choice(name="MC", value="MC"),
    app_commands.Choice(name="BWL", value="BWL"),
    app_commands.Choice(name="AQ20", value="AQ20"),
    app_commands.Choice(name="AQ40", value="AQ40"),
    app_commands.Choice(name="ZG", value="ZG"),
    app_commands.Choice(name="Naxxramas", value="NAXX"),
])
async def poemoji(interaction, raid: str, limit: int = 25):
    await run_po_emoji_sync(interaction, raid, limit)


async def sync_raid_application_emojis():
    create_emoji = getattr(client, "create_application_emoji", None)
    if not callable(create_emoji):
        raise RuntimeError("Die installierte discord.py-Version unterstützt Application Emojis noch nicht.")
    try:
        application_emojis = await client.fetch_application_emojis()
    except Exception as error:
        raise RuntimeError(f"Application Emojis konnten nicht geladen werden: {error}") from error
    existing = {normalize_emoji_name(emoji.name): emoji for emoji in application_emojis}
    created = []
    skipped = []
    failed = []
    for configured_name, icon_name in RAID_APPLICATION_EMOJI_ICONS.items():
        emoji_name = normalize_emoji_name(configured_name)
        if emoji_name in existing:
            skipped.append(emoji_name)
            continue
        try:
            image = await asyncio.to_thread(download_item_icon, icon_name)
            emoji = await create_emoji(name=emoji_name, image=image)
            existing[emoji_name] = emoji
            created.append(str(emoji))
            await asyncio.sleep(1.0)
        except Exception as error:
            failed.append(f"{emoji_name}: {error}")
    await refresh_emoji_cache()
    return {"created": created, "skipped": skipped, "failed": failed}


@client.tree.command(name="raid_emojis_sync", description="Lädt Klassen-, Skillungs-, Rollen- und Lootbag-Emojis in die Discord-App.")
async def raid_emojis_sync(interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    if not await can_sync_item_emojis(interaction.user):
        await interaction.followup.send("⚠️ Dafür brauchst du Gildenleitungs- oder Emoji-Rechte.", ephemeral=True)
        return
    try:
        result = await sync_raid_application_emojis()
    except Exception as error:
        await interaction.followup.send(f"⚠️ Raid-Emojis konnten nicht synchronisiert werden: {error}", ephemeral=True)
        return
    created = result["created"]
    skipped = result["skipped"]
    failed = result["failed"]
    lines = [
        "✅ Raid-Application-Emoji-Sync abgeschlossen.",
        f"Neu im Developer Portal: **{len(created)}**",
        f"Bereits vorhanden: **{len(skipped)}**",
        f"Fehler: **{len(failed)}**",
    ]
    if created:
        lines.append("Neu: " + " ".join(created[:20]))
    if failed:
        lines.append("Erste Fehler: " + " | ".join(failed[:5]))
    await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)


async def run_po_emoji_sync(interaction, raid: str, limit: int = 25):
    await interaction.response.defer(ephemeral=True, thinking=True)
    if not interaction.guild:
        await interaction.followup.send("⚠️ Dieser Befehl geht nur auf einem Discord-Server.", ephemeral=True)
        return
    if not await can_sync_item_emojis(interaction.user):
        await interaction.followup.send("⚠️ Dafür brauchst du Gildenleitungs- oder Emoji-Rechte.", ephemeral=True)
        return

    raid_key = normalize_raid(raid)
    max_create = max(1, min(int(limit or 25), 50))
    rows = await load_raid_item_rows(raid_key)
    if not rows:
        await interaction.followup.send(f"⚠️ Keine Lootitems für {display_raid(raid_key)} gefunden.", ephemeral=True)
        return

    existing = {normalize_emoji_name(emoji.name): emoji for emoji in getattr(interaction.guild, "emojis", []) or []}
    created = []
    skipped_existing = 0
    skipped_no_icon = 0
    failed = []

    for row in rows:
        name = row["name"]
        candidates = item_emoji_candidates(name)
        if any(candidate in existing for candidate in candidates):
            skipped_existing += 1
            continue
        emoji_name = primary_item_emoji_name(name)
        icon_name = row.get("icon") or ""
        if not emoji_name or not icon_name:
            skipped_no_icon += 1
            continue
        if len(created) >= max_create:
            break
        try:
            image = await asyncio.to_thread(download_item_icon, icon_name)
            emoji = await interaction.guild.create_custom_emoji(
                name=emoji_name,
                image=image,
                reason=f"LichtLoot PO Item-Emoji Sync {display_raid(raid_key)}",
            )
            existing[normalize_emoji_name(emoji.name)] = emoji
            created.append(f"{emoji} {name}")
            await asyncio.sleep(1.5)
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ Der Bot hat keine Rechte, Emojis anzulegen. Bitte dem Bot `Emojis und Sticker verwalten` bzw. `Ausdrücke erstellen` geben.",
                ephemeral=True,
            )
            return
        except Exception as error:
            failed.append(f"{name}: {error}")
            if len(failed) >= 5:
                break

    await refresh_emoji_cache()
    lines = [
        f"✅ Emoji-Sync für **{display_raid(raid_key)}** fertig.",
        f"Neu erstellt: **{len(created)}**",
        f"Schon vorhanden: **{skipped_existing}**",
        f"Ohne Icon übersprungen: **{skipped_no_icon}**",
    ]
    if created:
        lines.append("Beispiele: " + ", ".join(created[:8]))
    if failed:
        lines.append("Fehler: " + " | ".join(failed[:3]))
    if len(created) >= max_create:
        lines.append(f"Limit erreicht ({max_create}). Du kannst den Befehl noch einmal ausführen.")
    await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)


async def send_po_emoji_sync_text(message, text):
    await message.channel.send(text[:1900], silent=True)


async def run_po_emoji_sync_for_message(message, raid: str, limit: int = 25):
    if not message.guild:
        await send_po_emoji_sync_text(message, "⚠️ Dieser Befehl geht nur auf einem Discord-Server.")
        return
    if not await can_sync_item_emojis(message.author):
        await send_po_emoji_sync_text(message, "⚠️ Dafür brauchst du Gildenleitungs- oder Emoji-Rechte.")
        return

    raid_key = normalize_raid(raid)
    max_create = max(1, min(int(limit or 25), 50))
    await send_po_emoji_sync_text(message, f"⏳ Emoji-Sync für **{display_raid(raid_key)}** startet, Limit {max_create} ...")
    rows = await load_raid_item_rows(raid_key)
    if not rows:
        await send_po_emoji_sync_text(message, f"⚠️ Keine Lootitems für {display_raid(raid_key)} gefunden.")
        return

    existing = {normalize_emoji_name(emoji.name): emoji for emoji in getattr(message.guild, "emojis", []) or []}
    created = []
    skipped_existing = 0
    skipped_no_icon = 0
    failed = []

    for row in rows:
        name = row["name"]
        candidates = item_emoji_candidates(name)
        if any(candidate in existing for candidate in candidates):
            skipped_existing += 1
            continue
        emoji_name = primary_item_emoji_name(name)
        icon_name = row.get("icon") or ""
        if not emoji_name or not icon_name:
            skipped_no_icon += 1
            continue
        if len(created) >= max_create:
            break
        try:
            image = await asyncio.to_thread(download_item_icon, icon_name)
            emoji = await message.guild.create_custom_emoji(
                name=emoji_name,
                image=image,
                reason=f"LichtLoot PO Item-Emoji Sync {display_raid(raid_key)}",
            )
            existing[normalize_emoji_name(emoji.name)] = emoji
            created.append(f"{emoji} {name}")
            await asyncio.sleep(1.5)
        except discord.Forbidden:
            await send_po_emoji_sync_text(
                message,
                "⚠️ Der Bot hat keine Rechte, Emojis anzulegen. Bitte dem Bot `Emojis und Sticker verwalten` bzw. `Ausdrücke erstellen` geben.",
            )
            return
        except Exception as error:
            failed.append(f"{name}: {error}")
            if len(failed) >= 5:
                break

    await refresh_emoji_cache()
    lines = [
        f"✅ Emoji-Sync für **{display_raid(raid_key)}** fertig.",
        f"Neu erstellt: **{len(created)}**",
        f"Schon vorhanden: **{skipped_existing}**",
        f"Ohne Icon übersprungen: **{skipped_no_icon}**",
    ]
    if created:
        lines.append("Beispiele: " + ", ".join(created[:8]))
    if failed:
        lines.append("Fehler: " + " | ".join(failed[:3]))
    if len(created) >= max_create:
        lines.append(f"Limit erreicht ({max_create}). Du kannst den Befehl noch einmal ausführen.")
    await send_po_emoji_sync_text(message, "\n".join(lines))


def raid_helper_role_from_heading(value):
    heading = clean(value).lower()
    if any(word in heading for word in ("tank", "main tank", "off tank")):
        return "tank"
    if any(word in heading for word in ("heal", "heiler", "healing")):
        return "heal"
    if any(word in heading for word in ("melee", "nahkampf")):
        return "melee"
    if any(word in heading for word in ("range", "ranged", "fernkampf")):
        return "range"
    return "dd"


def raid_helper_class_from_text(value):
    normalized = clean(value).lower()
    aliases = {
        "warrior": "Warrior", "krieger": "Warrior", "druid": "Druid", "druide": "Druid",
        "paladin": "Paladin", "pala": "Paladin", "rogue": "Rogue", "schurke": "Rogue",
        "hunter": "Hunter", "jäger": "Hunter", "jaeger": "Hunter", "priest": "Priest",
        "priester": "Priest", "mage": "Mage", "magier": "Mage", "warlock": "Warlock",
        "hexenmeister": "Warlock", "shaman": "Shaman", "schamane": "Shaman",
    }
    for alias, class_name in aliases.items():
        if alias in normalized:
            return class_name
    return ""


def raid_helper_signup_rows_from_message(message):
    rows = []
    seen = set()
    guild = getattr(message, "guild", None)

    def append_section(heading, section_value):
        heading = clean(heading)
        heading_lower = heading.lower()
        heading_class = raid_helper_class_from_text(heading)
        if not heading_class and not any(word in heading_lower for word in ("tank", "heal", "heiler", "melee", "nahkampf", "range", "ranged", "fernkampf", "dd", "signup", "anmeld")):
            return
        role = raid_helper_role_from_heading(heading)
        field_value = clean(section_value)
        field_value = re.sub(
            r"\s+(?=<a?:[^:>]+:\d+>\s*(?:`\d+`|\*\*\d+\*\*|\d+\b))",
            "\n",
            field_value,
        )
        for raw_line in field_value.splitlines():
            line = clean(raw_line)
            if not line or line in {"-", "—"}:
                continue
            mention = re.search(r"<@!?(\d+)>", line)
            member = guild.get_member(int(mention.group(1))) if mention and guild else None
            without_markup = re.sub(r"<a?:[^:>]+:\d+>", " ", line)
            without_markup = re.sub(r"<@!?\d+>", " ", without_markup)
            without_markup = re.sub(r"[*_`~>|•✅❌🪑🕒⚖️🚫]+", " ", without_markup)
            without_markup = re.sub(r"^\s*\d+[.)-]?\s*", "", without_markup).strip(" -–—")
            player = clean(getattr(member, "display_name", "")) or clean(without_markup.split(" - ")[0].split(" | ")[0])
            if not player:
                continue
            key = normalized_prio_player_name(player)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append({
                "char": player,
                "spieler": player,
                "klasse": heading_class or raid_helper_class_from_text(line),
                "role": role,
                "status": "signed",
                "discordUserId": str(getattr(member, "id", "") or (mention.group(1) if mention else "")),
                "discordName": clean(getattr(member, "display_name", "")),
                "discordChannelId": str(getattr(message.channel, "id", "") or ""),
                "discordMessageId": str(getattr(message, "id", "") or ""),
                "source": f"Raid-Helper:{getattr(message, 'id', '')}",
            })

    class_header_pattern = re.compile(
        r"(?i)(tank|warrior|krieger|druid|druide|paladin|pala|rogue|schurke|hunter|jäger|jaeger|priest|priester|mage|magier|warlock|hexenmeister|shaman|schamane)[*_~`\s]*\(\s*\d+\s*\)"
    )
    for embed in getattr(message, "embeds", []) or []:
        sources = [("", clean(getattr(embed, "description", "")))]
        sources.extend(
            (clean(getattr(field, "name", "")), clean(getattr(field, "value", "")))
            for field in getattr(embed, "fields", []) or []
        )
        for heading, value in sources:
            matches = list(class_header_pattern.finditer(value))
            if matches:
                for index, match in enumerate(matches):
                    end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
                    append_section(match.group(1), value[match.end():end])
                continue
            append_section(heading, value)
    return rows


def is_raid_helper_message(message):
    author = getattr(message, "author", None)
    author_name = clean(getattr(author, "name", "")).lower().replace("_", "-").replace(" ", "-")
    display_name = clean(getattr(author, "display_name", "")).lower().replace("_", "-").replace(" ", "-")
    return any(
        marker in value
        for value in (author_name, display_name)
        for marker in ("raid-helper", "raidhelper")
    )


def raid_helper_message_metadata(message):
    parts = []
    for embed in getattr(message, "embeds", []) or []:
        parts.extend([clean(getattr(embed, "title", "")), clean(getattr(embed, "description", ""))])
        for field in getattr(embed, "fields", []) or []:
            parts.extend([clean(getattr(field, "name", "")), clean(getattr(field, "value", ""))])
    text = "\n".join(part for part in parts if part)
    lowered = text.lower()
    raid = ""
    for aliases, raid_key in (
        (("naxxramas", "naxx"), "naxx"), (("blackwing lair", "bwl"), "bwl"),
        (("molten core", " mc "), "mc"), (("ahn'qiraj 40", "aq40"), "aq40"),
        (("ahn'qiraj 20", "aq20"), "aq20"), (("zul'gurub", "zul gurub", " zg "), "zg"),
        (("onyxia", "ony"), "ony"),
    ):
        if any(alias in f" {lowered} " for alias in aliases):
            raid = raid_key
            break
    date_match = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text)
    iso_match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    raid_date = ""
    if date_match:
        raid_date = f"{date_match.group(3)}-{int(date_match.group(2)):02d}-{int(date_match.group(1)):02d}"
    elif iso_match:
        raid_date = iso_match.group(0)
    else:
        discord_date_match = re.search(r"<t:(\d{9,12}):D>", text)
        if discord_date_match:
            raid_date = datetime.fromtimestamp(int(discord_date_match.group(1))).strftime("%Y-%m-%d")
    time_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    return {"raid": raid, "raidDate": raid_date, "raidTime": time_match.group(0) if time_match else ""}


async def sync_foreign_raid_helper_message(message):
    if not is_raid_helper_message(message):
        return False
    if not getattr(message, "embeds", None):
        return False
    rows = raid_helper_signup_rows_from_message(message)
    metadata = raid_helper_message_metadata(message)
    try:
        result = await asyncio.to_thread(api_post, {
            "action": "saveDiscordSignupRows",
            "queueToken": QUEUE_TOKEN,
            "guild": guild_slug_for_discord_server(message.guild, GUILD_SLUG),
            "discordChannelId": str(message.channel.id),
            "raidHelperMessageId": str(message.id),
            "discordMessageId": str(message.id),
            "raid": metadata.get("raid") or "",
            "raidDate": metadata.get("raidDate") or "",
            "raidTime": metadata.get("raidTime") or "",
            "replaceSnapshot": "true",
            "rows": rows,
        })
        if result.get("success"):
            print(f"Raid-Helper-Spiegel aktualisiert: {result.get('guild') or current_guild_slug()}:{message.id} ({len(rows)} Anmeldungen)")
            return True
    except Exception as error:
        # Nur bereits mit einem LichtLoot-Raid verknüpfte Nachrichten werden übernommen.
        if "nicht gefunden" not in str(error).lower() and "404" not in str(error):
            print(f"Raid-Helper-Spiegel konnte nicht aktualisiert werden ({message.id}): {error}")
    return False


async def po_signup_channel_sync_payloads():
    payloads = []
    seen = set()

    def add_payload(payload):
        if not isinstance(payload, dict):
            return
        raid_snapshot = payload.get("combinedRaidSnapshot") or payload.get("raidSnapshot") or {}
        merged = {**raid_snapshot, **payload} if isinstance(raid_snapshot, dict) else dict(payload)
        raid = normalize_raid(
            payload.get("raid") or payload.get("raidName")
            or raid_snapshot.get("raid") or raid_snapshot.get("raidName") or ""
        )
        raid_date = clean(
            payload.get("raidDate") or payload.get("date")
            or raid_snapshot.get("raidDate") or raid_snapshot.get("date")
        )
        channel_id = payload_target_channel_id(merged) or payload_source_channel_id(merged)
        if not raid or not raid_date or not channel_id:
            return
        merged["raid"] = raid
        merged["raidDate"] = raid_date
        merged["targetChannelId"] = channel_id
        key = (payload_guild_slug(merged), raid, raid_date, channel_id)
        if key in seen:
            return
        seen.add(key)
        payloads.append(merged)

    for payload in load_state().values():
        add_payload(payload)

    guild_slugs = {normalize_guild_slug(GUILD_SLUG), *GUILD_REGISTRY.keys()}
    for guild_slug in sorted(guild_slugs):
        try:
            result = await asyncio.to_thread(api_get, {
                "action": "lichtbotGetPoPostChannels",
                "queueToken": QUEUE_TOKEN,
                "guild": guild_slug,
                "guildSlug": guild_slug,
                "includeArchived": "false",
                "t": int(time.time()),
            })
            for entry in result.get("posts") or []:
                entry = dict(entry)
                entry["guildSlug"] = guild_slug
                add_payload(entry)
        except Exception as error:
            print(f"PO-Channel-Liste konnte für {guild_slug} nicht geladen werden: {error}")
    return payloads[-30:]


async def sync_latest_raid_signup_from_po_channel(payload):
    channel_id = payload_target_channel_id(payload) or payload_source_channel_id(payload)
    channel = await fetch_accessible_channel(client, channel_id)
    if channel is None or not hasattr(channel, "history"):
        return False
    expected_guild_slug = payload_guild_slug(payload)
    discord_guild = getattr(channel, "guild", None)
    actual_guild_slug = guild_slug_for_discord_server(discord_guild, "")
    if actual_guild_slug and actual_guild_slug != expected_guild_slug:
        print(
            "PO-Channel Raidanmelder-Sync übersprungen: "
            f"Channel {channel_id} gehört zu {actual_guild_slug}, "
            f"der Datenbankeintrag aber zu {expected_guild_slug}."
        )
        return False
    wanted_raid = normalize_raid(payload.get("raid") or payload.get("raidName") or "")
    wanted_date = clean(payload.get("raidDate") or payload.get("date"))
    newest_match = None
    newest_rows = []
    newest_metadata = {}
    inspected_embeds = 0
    inspected_raid_helper = 0
    candidate_summaries = []
    async for message in channel.history(limit=500):
        if not getattr(message, "embeds", None):
            continue
        inspected_embeds += 1
        if not is_raid_helper_message(message):
            continue
        inspected_raid_helper += 1
        metadata = raid_helper_message_metadata(message)
        message_raid = normalize_raid(metadata.get("raid") or "")
        message_date = clean(metadata.get("raidDate"))
        if len(candidate_summaries) < 5:
            candidate_summaries.append(
                f"{getattr(message, 'id', '')}:{message_raid or '-'}:{message_date or '-'}"
            )
        if wanted_raid and message_raid != wanted_raid:
            continue
        if not message_date:
            continue
        # Ein Channel kann mehrere Anmelder desselben Raidtyps enthalten.
        # Ohne Datumsabgleich wurde z. B. für einen BWL am 07.08. der neueste
        # BWL-Anmelder vom 11.08. übernommen. Der Server konnte diesen nicht
        # dem erstellten Raid zuordnen und legte früher einen Discord-Import
        # als zweiten Raid an.
        if wanted_date and message_date != wanted_date:
            continue
        rows = raid_helper_signup_rows_from_message(message)
        if not rows:
            continue
        newest_match = message
        newest_rows = rows
        newest_metadata = metadata
        break
    if newest_match is None:
        if wanted_raid == "BWL":
            print(
                "PO-Channel BWL-Diagnose: "
                f"Channel {channel_id}, PO-Datum {wanted_date or '-'}, "
                f"{inspected_embeds} Embed(s), {inspected_raid_helper} Raid-Helper-Beitrag/Beiträge, "
                f"Kandidaten {candidate_summaries or ['keine']}."
            )
        return False
    matched_date = clean(newest_metadata.get("raidDate")) or wanted_date
    matched_time = clean(newest_metadata.get("raidTime")) or clean(payload.get("raidTime") or payload.get("time"))
    result = await asyncio.to_thread(api_post, {
        "action": "saveDiscordSignupRows",
        "queueToken": QUEUE_TOKEN,
        "guild": expected_guild_slug,
        "raidId": clean(payload.get("raidId") or payload.get("id")),
        "raid": wanted_raid,
        "raidDate": matched_date,
        "raidTime": matched_time,
        "discordChannelId": str(channel.id),
        "raidHelperMessageId": str(newest_match.id),
        "discordMessageId": str(newest_match.id),
        "replaceSnapshot": "true",
        "rows": newest_rows,
    })
    if result.get("success"):
        print(
            "PO-Channel Raidanmelder-Sync: "
            f"{wanted_raid.upper()} {matched_date} aus Channel {channel.id}, "
            f"Nachricht {newest_match.id}: {len(newest_rows)} Anmeldung(en)."
        )
        return True
    return False


async def po_channel_signup_sync_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        payloads = await po_signup_channel_sync_payloads()
        print(f"PO-Channel Raidanmelder-Sync prüft {len(payloads)} Raid-Channel(s).")
        for payload in payloads:
            try:
                await sync_latest_raid_signup_from_po_channel(payload)
            except Exception as error:
                print(
                    "PO-Channel Raidanmelder-Sync fehlgeschlagen "
                    f"({payload.get('postKey') or payload.get('raid')}): {error}"
                )
        await asyncio.sleep(60)


@client.event
async def on_message(message):
    if message.author.bot:
        return
    text = clean(getattr(message, "content", ""))
    lower = text.lower()
    if lower == "!clearchannel" or lower == "!clearchannel bestätigen":
        permissions = getattr(message.author, "guild_permissions", None)
        clear_channel_names = {
            normalized_prio_player_name(value)
            for value in [
                getattr(message.author, "name", ""),
                getattr(message.author, "display_name", ""),
                getattr(message.author, "global_name", ""),
            ]
            if normalized_prio_player_name(value)
        }
        personally_allowed = any(
            name in clear_channel_names
            for name in {
                normalized_prio_player_name("Ariee"),
                normalized_prio_player_name("Juksi"),
                normalized_prio_player_name("Ariee / Juksi"),
            }
        )
        may_clear_channel = bool(
            permissions
            and (permissions.administrator or permissions.manage_messages)
        ) or personally_allowed
        if not may_clear_channel:
            await message.channel.send(
                "⚠️ Nur Administratoren oder Mitglieder mit „Nachrichten verwalten“ dürfen diesen Channel leeren.",
                delete_after=20,
            )
            return
        if lower != "!clearchannel bestätigen":
            await message.channel.send(
                "⚠️ Dadurch werden alle nicht angehefteten Nachrichten in diesem Channel gelöscht. "
                "Zum Bestätigen bitte `!clearchannel bestätigen` senden.",
                delete_after=30,
            )
            return
        try:
            deleted = await message.channel.purge(
                limit=None,
                check=lambda old_message: not old_message.pinned,
                bulk=True,
                reason=f"!clearchannel von {message.author} ({message.author.id})",
            )
            await message.channel.send(
                f"✅ Channel geleert: **{len(deleted)}** nicht angeheftete Nachrichten gelöscht.",
                delete_after=15,
            )
        except discord.Forbidden:
            await message.channel.send(
                "⚠️ Der Bot hat in diesem Channel nicht die Berechtigung „Nachrichten verwalten“.",
                delete_after=20,
            )
        except Exception as error:
            await message.channel.send(
                f"⚠️ Channel konnte nicht vollständig geleert werden: `{error}`",
                delete_after=30,
            )
        return
    if lower in {"!hilfe-start", "!hilfe-aktualisieren", "!hilfe-stop"}:
        if int(message.channel.id) != NACHTLOOT_HELP_CHANNEL_ID:
            await message.channel.send(
                f"⚠️ Diese Befehle funktionieren nur in <#{NACHTLOOT_HELP_CHANNEL_ID}>.",
                delete_after=20,
            )
            return
        permissions = getattr(message.author, "guild_permissions", None)
        member_roles = {
            normalize_role_name(getattr(role, "name", ""))
            for role in getattr(message.author, "roles", []) or []
        }
        may_manage_help = bool(
            permissions
            and (permissions.administrator or permissions.manage_messages)
        ) or bool(member_roles & NACHTLOOT_HELP_ROLE_NAMES)
        if not may_manage_help:
            await message.channel.send(
                "⚠️ Nur Gildenleitung, Offiziere, Raidoffiziere oder PO-Freigeber dürfen die Hilfe aktivieren.",
                delete_after=20,
            )
            return
        removed = 0
        async for old_message in message.channel.history(limit=100):
            if old_message.author != client.user:
                continue
            if any(
                clean(getattr(getattr(embed, "footer", None), "text", "")) == NACHTLOOT_HELP_MARKER
                for embed in old_message.embeds
            ):
                await old_message.delete()
                removed += 1
        if lower != "!hilfe-stop":
            embed = discord.Embed(
                title="💡 Nachtloot-Hilfe",
                description=(
                    "Hier bekommst du Hilfe zu **Nachtloot**, **PO-Items**, **Worldbuffs**, "
                    "**Hordenbuffs** und **Raid-Anmeldungen**.\n\n"
                    "Wähle unten ein Thema aus oder klicke auf **KI-Frage stellen**. "
                    "Die Antwort ist nur für dich sichtbar.\n\n"
                    "**So funktioniert es**\n"
                    "1. Thema auswählen\n"
                    "2. Antwort lesen\n"
                    "3. Bei Bedarf eine eigene Frage stellen\n\n"
                    "**Noch keine Lösung?**\n"
                    "Halte die genaue Fehlermeldung und deinen Charakternamen bereit und "
                    "wende dich an die Nachtloot-Gildenleitung."
                ),
                color=discord.Color.from_rgb(250, 204, 21),
            )
            embed.set_footer(text=NACHTLOOT_HELP_MARKER)
            await message.channel.send(embed=embed, view=NachtlootHelpView(), silent=True)
            # Falls versehentlich zwei PO-Bot-Instanzen laufen, empfangen beide
            # denselben Befehl. Nach einer kurzen Wartezeit bleibt trotzdem nur
            # genau ein Hilfepost im Kanal stehen.
            await asyncio.sleep(2)
            help_posts = []
            async for old_message in message.channel.history(limit=30):
                if old_message.author != client.user:
                    continue
                if any(
                    clean(getattr(getattr(old_embed, "footer", None), "text", "")) == NACHTLOOT_HELP_MARKER
                    for old_embed in old_message.embeds
                ):
                    help_posts.append(old_message)
            help_posts.sort(key=lambda entry: entry.id)
            for duplicate in help_posts[1:]:
                try:
                    await duplicate.delete()
                except Exception:
                    pass
        try:
            await message.delete()
        except Exception:
            pass
        print(
            f"Nachtloot-Hilfe {'gestoppt' if lower == '!hilfe-stop' else 'aktiviert'} "
            f"durch PO-Bot in {message.channel.id}; alte Posts entfernt: {removed}."
        )
        return
    match = re.match(r"^!(?:poemoji|po_emojis_sync)\s+([a-zA-Z0-9]+)(?:\s+(\d+))?\s*$", text)
    if not match:
        return
    raid = match.group(1)
    limit = int(match.group(2) or 25)
    await run_po_emoji_sync_for_message(message, raid, limit)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args):
        return


def start_health_server():
    port = int(os.getenv("PORT", "8080"))
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    except OSError as error:
        if getattr(error, "errno", None) == 98:
            print(f"PO-Bot nutzt vorhandenen Healthserver auf Port {port}.")
            return
        raise
    threading.Thread(target=server.serve_forever, daemon=True).start()


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("PO_BOT_TOKEN fehlt.")
    # Im gemeinsamen Railway-Container bekommt der Hauptbot zuerst die Chance,
    # den öffentlichen API-/Health-Port zu öffnen.
    time.sleep(2)
    start_health_server()
    client.run(TOKEN)
