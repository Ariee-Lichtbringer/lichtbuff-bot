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


def current_guild_slug():
    return normalize_guild_slug(CURRENT_GUILD_SLUG.get())


def payload_guild_slug(payload):
    return normalize_guild_slug(
        (payload or {}).get("guildSlug")
        or (payload or {}).get("guild")
        or current_guild_slug()
    )


def guild_slug_for_discord_guild(discord_guild_id, fallback=""):
    return normalize_guild_slug(DISCORD_GUILD_SLUGS.get(str(discord_guild_id or "").strip()) or fallback)


def guild_slug_for_discord_server(guild, fallback=""):
    mapped = DISCORD_GUILD_SLUGS.get(str(getattr(guild, "id", "") or "").strip())
    if mapped:
        return normalize_guild_slug(mapped)
    guild_name = str(getattr(guild, "name", "") or "").strip().lower()
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
    return normalize_guild_slug(fallback)


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
RAID_SIGNUP_DM_CACHE = {}
p0plus_cache = {}
P0PLUS_CACHE_SECONDS = int(os.getenv("PO_BOT_P0PLUS_CACHE_SECONDS", "60") or "60")
empty_queue_log_at = 0
slash_commands_synced_for_guilds = False


def clean(value):
    return str(value or "").strip()


def normalize_raid(value):
    text = clean(value).upper().replace(" ", "").replace("-", "")
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
    if text in {"AQ20", "RUINSOFAHNQIRAJ"}:
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


def refresh_emoji_cache():
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
    for key, names in CLASS_EMOJI_NAME_ALIASES.items():
        for name in names:
            emoji = by_name.get(normalize_emoji_name(name))
            if emoji:
                found_classes[key] = str(emoji)
                break
    for key, names in SPEC_EMOJI_NAME_ALIASES.items():
        for name in names:
            emoji = by_name.get(normalize_emoji_name(name))
            if emoji:
                found_specs[key] = str(emoji)
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


def class_icon(class_name):
    key = class_key(class_name)
    env_name, emoji_name = CLASS_EMOJI_ENV.get(key, ("", ""))
    raw = clean(os.getenv(env_name, ""))
    if raw.startswith("<:") or raw.startswith("<a:"):
        return raw
    if raw.isdigit() and len(raw) >= 15:
        return f"<:{emoji_name}:{raw}>"
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


def format_raid_announcement_date(value):
    raw = clean(value)
    if not raw:
        return "noch offen"
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
    if guild_slug != "lichtloot" and guild_image:
        return urllib.parse.urljoin(LICHTLOOT_URL.rstrip("/") + "/", guild_image)
    explicit = clean((raid or {}).get("raidImageUrl") or (raid or {}).get("imageUrl"))
    if explicit.startswith(("http://", "https://")):
        return explicit
    if image_raid_key in {"zg", "aq20", "aq40", "bwl", "mc", "naxx", "ony"}:
        return f"https://lichtloot-production.up.railway.app/images/raid-banners/{image_raid_key}.jpg"
    return ""


def custom_emoji(name, fallback):
    """Use the guild emoji uploaded in Discord and keep a portable fallback."""
    emoji = discord.utils.get(getattr(client, "emojis", []), name=name)
    return str(emoji) if emoji else fallback


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
    worldbuff_block = current_worldbuff_announcement_block(raid_guild_slug)
    if worldbuff_block:
        embed.add_field(name="Aktuelle Worldbuffs", value=worldbuff_block[:1024], inline=False)
    embed.add_field(
        name="\u200b",
        value=(
            f"{custom_emoji('Kofferlila', '🟪🧰')} **P1, P2, P3 auf LichtLoot:** P1, P2 oder P3 für diesen Raid eingetragen.\n"
            f"{custom_emoji('kofferorange', '🟧🧰')} **PO auf LichtLoot eingetragen:** Oranger Koffer = PO angemeldet, aber noch nicht freigegeben.\n"
            f"{custom_emoji('koffergrun', '🟩🧰')} **PO auf LichtLoot freigegeben:** Grüner Koffer = PO für diesen Raid eingetragen und freigegeben."
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


def current_worldbuff_announcement_block(guild_slug=None, max_lines=8):
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
    today = datetime.now().date()
    latest = today + timedelta(days=7)
    upcoming = []
    for row in rows:
        try:
            row_date = datetime.strptime(clean(row.get("datum") or row.get("date")), "%d.%m.%Y").date()
        except Exception:
            continue
        if today <= row_date <= latest:
            upcoming.append((row_date, clean(row.get("uhrzeit") or row.get("time")), row))
    upcoming.sort(key=lambda item: (item[0], item[1]))
    lines = []
    current_date = None
    for row_date, row_time, row in upcoming[:max_lines]:
        if row_date != current_date:
            weekday = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][row_date.weekday()]
            lines.append(f"**{weekday}, {row_date.strftime('%d.%m.%Y')}**")
            current_date = row_date
        buff = clean(row.get("buff") or row.get("type")) or "Buff"
        emoji = "🟢" if buff.lower() == "hakkar" else "🔴"
        guild = clean(row.get("gilde") or row.get("guild"))
        caster = clean(row.get("charakter") or row.get("character"))
        suffix = f" - {guild}" if guild else ""
        if caster:
            suffix += f" - ⚔️ {caster}"
        lines.append(f"{emoji} **{buff}** {row_time}{suffix}")
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


def infer_signup_role(spec_text):
    text = clean(spec_text).lower()
    if any(word in text for word in ["tank", "prot", "schutz", "def"]):
        return "tank"
    if any(word in text for word in ["heal", "heiler", "holy", "heilig", "resto", "diszi", "discipline"]):
        return "heal"
    return "dd"


def signup_spec_icon_key(spec_text, role="", class_name=""):
    text = clean(spec_text or role).lower()
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
        ("feral", ["feral"]),
        ("balance", ["balance", "eule", "moonkin"]),
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
        ("Schamane", "Shaman"),
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
    ]
    role_counts = {"tank": 0, "heal": 0, "dd": 0}
    for row in active_rows:
        role = clean(row.get("role")).lower()
        if role not in role_counts:
            role = infer_signup_role(signup_spec_from_note(row.get("note"), role))
        role_counts[role if role in role_counts else "dd"] += 1
    tank_max = clean(raid.get("tankSlots"))
    heal_max = clean(raid.get("healSlots"))
    dd_max = clean(raid.get("ddSlots"))
    tank_role_icon = signup_spec_icon("Tank", "tank", "Warrior")
    embed.add_field(
        name=f"{tank_role_icon} Tanks",
        value=f"**{role_counts['tank']}{('/' + tank_max) if tank_max else ''}**",
        inline=True,
    )
    embed.add_field(
        name="➕ Heals",
        value=f"**{role_counts['heal']}{('/' + heal_max) if heal_max else ''}**",
        inline=True,
    )
    embed.add_field(
        name="⚔️ DD",
        value=f"**{role_counts['dd']}{('/' + dd_max) if dd_max else ''}**",
        inline=True,
    )
    embed.add_field(name="\u200b", value="\u200b", inline=False)

    grouped = {}
    raid_key = normalize_raid(raid.get("raid") or "").lower()
    for row in active_rows:
        role = clean(row.get("role")).lower()
        resolved_role = role if role in role_counts else infer_signup_role(signup_spec_from_note(row.get("note"), role))
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
        for row in grouped[cls][:8]:
            player = clean(row.get("player") or row.get("char")) or "-"
            position = signup_positions.get(id(row), 0)
            po_status = clean(row.get("poApprovalStatus") or row.get("po_approval_status")).lower()
            if po_status in {"approved", "freigegeben"}:
                prio_icon = f" {custom_emoji('koffergrun', '🟩🧰')}"
            elif po_status in {"pending", "offen", "wartet"}:
                prio_icon = f" {custom_emoji('kofferorange', '🟧🧰')}"
            elif row.get("hasPrio") is True or clean(row.get("hasPrio")).lower() in {"1", "true", "yes", "ja"}:
                prio_icon = f" {custom_emoji('Kofferlila', '🟪🧰')}"
            else:
                prio_icon = ""
            spec = signup_spec_from_note(row.get("note"), row.get("role")) or "Flex"
            star = " ★" if any(
                row.get(key) is True or clean(row.get(key)).lower() in {"1", "true", "yes", "ja", "freigegeben"}
                for key in ("p0Released", "poReleased", "p0PlusReleased", "poPlusReleased")
            ) else ""
            lines.append(f"`{position}`{prio_icon} **{player}{star}** · {signup_spec_icon(spec, row.get('role'), cls)}")
        embed.add_field(
            name=f"{tank_role_icon if cls == 'Tank' else class_icon(cls)} {german_class_names.get(cls, cls)} ({len(grouped[cls])})",
            value=("\n".join(lines) or "\u200b")[:1024],
            inline=True,
        )
        if (class_index + 1) % 2 == 0 and class_index < len(sorted_classes) - 1:
            embed.add_field(name="\u200b", value="\u200b", inline=False)
    status_groups = [
        ("🪑 Bank", {"bench", "bank"}),
        ("🕒 Spät", {"late", "spät", "spaet"}),
        ("⚖️ Vorläufig", {"tentative", "vorläufig", "vorlaeufig"}),
        ("🚫 Abwesenheit", {"absent", "abwesend"}),
    ]
    if any(clean(row.get("status")).lower() in statuses for _, statuses in status_groups for row in rows):
        embed.add_field(name="\u200b", value="\u200b\n\u200b", inline=False)
    for label, statuses in status_groups:
        status_rows = [row for row in rows if clean(row.get("status")).lower() in statuses]
        if not status_rows:
            continue
        players = [
            f"{class_icon(canonical_signup_class(row.get('className') or row.get('klasse')))} "
            f"`{signup_positions.get(id(row), 0)}` {clean(row.get('player') or row.get('char'))}"
            for row in sorted(status_rows, key=lambda row: signup_positions.get(id(row), 0))
        ]
        embed.add_field(
            name=f"{label} ({len(players)})",
            value=", ".join(filter(None, players))[:1024],
            inline=False,
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
            row["hasPrio"] = bool(player_key and player_key in prio_players)
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
    state, state_key, po_payload = combined_po_payload_for_message(getattr(message, "id", ""))
    if not po_payload:
        embed = build_raid_announcement_embed(raid)
        add_raid_signup_roster_fields(embed, helper)
        banner, _ = raid_banner_file(raid)
        if banner:
            await message.edit(embed=embed, attachments=[banner], view=RaidSignupView(raid))
        else:
            await message.edit(embed=embed, view=RaidSignupView(raid))
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
        await message.edit(embeds=embeds, view=view)
    register_po_view(client, po_payload, items, entries)


async def refresh_raid_signup_message_by_id(raid_id, channel_id=None, message_id=None, payload=None):
    helper = await get_raid_helper_for_refresh(payload or clean(raid_id))
    fallback_helper = raid_helper_snapshot_from_payload(payload) if payload else {}
    if raid_signup_row_count(helper) == 0 and raid_signup_row_count(fallback_helper) > 0:
        helper = fallback_helper
    if not helper or not helper.get("success"):
        raise RuntimeError("Raid-Anmelder-Refresh: Raid wurde nicht gefunden.")
    raid = helper.get("raid") or (payload or {}).get("raidSnapshot") or {}
    channel_id = clean(channel_id or raid.get("discordChannelId") or raid.get("discord_channel_id"))
    message_id = clean(message_id or raid.get("discordMessageId") or raid.get("discord_message_id"))
    if not channel_id or not message_id:
        return "missing_message"
    channel = client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    message = await channel.fetch_message(int(message_id))
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
            all_rows = list(helper.get("signups") or []) + list(helper.get("externalSignups") or [])
            optimistic_char = clean(optimistic_signup.get("char") or optimistic_signup.get("player")).lower()
            if optimistic_char and not any(
                clean(row.get("char") or row.get("player")).lower() == optimistic_char
                for row in all_rows
            ):
                helper = dict(helper)
                helper["externalSignups"] = list(helper.get("externalSignups") or []) + [optimistic_signup]
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


async def post_raid_announcement_by_id(raid_id, channel_id=None, payload=None):
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
        "raid", "raidName", "raidDate", "raidTime", "createdBy", "guild", "guildName",
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
    existing_message_id = clean(
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
            "raidId": clean(raid.get("raidId") or raid.get("id") or raid_id),
            "discordChannelId": channel_id,
            "discordMessageId": str(message.id)
        })
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
            "status": "signed",
            "signupStatus": "signed",
            "note": f"Skillung: {self.spec_label}",
            "discordUserId": str(interaction.user.id),
            "discordName": str(interaction.user.display_name),
            "source": raid_signup_source(interaction, self.origin_channel_id, self.origin_message_id)
        })
        if not result.get("success"):
            await interaction.response.send_message(f"⚠️ Anmeldung fehlgeschlagen: {result.get('error') or 'unbekannter Fehler'}", ephemeral=True)
            return
        refresh_raid = dict(self.raid)
        if result.get("raid"):
            refresh_raid.update(result.get("raid") or {})
        if result.get("raidId"):
            refresh_raid["raidId"] = result.get("raidId")
        await interaction.response.edit_message(
            content=f"✅ Anmeldung gespeichert: **{char_name}** · {class_display_name(char_class)} · {self.spec_label}",
            view=None
        )
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
            "signed",
            f"{class_display_name(char_class)} · {self.spec_label}",
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
                    "role": infer_signup_role(self.spec_label),
                    "status": "signed",
                    "note": f"Skillung: {self.spec_label}",
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
            await asyncio.to_thread(api_post, {
                "action": "guildQueueRaidAnnouncementRefresh",
                "queueToken": QUEUE_TOKEN,
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
            if not existing:
                raise RuntimeError("Für diesen Charakter wurde keine Anmeldung gefunden.")
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
                    "role": clean(existing.get("role")),
                    "status": self.status,
                    "note": note or clean(existing.get("note")),
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
                "tentative": "als vorläufig markiert",
                "absent": "als abwesend markiert",
            }.get(self.status, "aktualisiert")
            await interaction.response.send_message(f"✅ **{char_name}** wurde {label}.", ephemeral=True)
            await send_raid_player_status_confirmation(interaction, fresh_raid, char_name, self.status, note)
            await send_raid_staff_action_notice(interaction, fresh_raid, char_name, self.status, note)
            await refresh_raid_signup_message(interaction, self.raid)
        except Exception as error:
            if interaction.response.is_done():
                await interaction.followup.send(f"⚠️ Status konnte nicht geändert werden: {error}", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ Status konnte nicht geändert werden: {error}", ephemeral=True)


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
    await asyncio.sleep(3)
    try:
        result = await asyncio.to_thread(api_get, {"action": "getActiveRaids", "t": int(time.time())})
        restored = 0
        for raid in result.get("allRaids") or result.get("raids") or []:
            channel_id = clean(raid.get("discordChannelId") or raid.get("discord_channel_id"))
            message_id = clean(raid.get("discordMessageId") or raid.get("discord_message_id"))
            if channel_id and message_id:
                client.add_view(RaidSignupView(raid), message_id=int(message_id))
                restored += 1
        print(f"Raid-Anmelder-Views im PO-Bot wiederhergestellt: {restored}.")
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


def lichtloot_prio_url():
    configured = clean(LICHTLOOT_PRIO_URL)
    if configured and "guild=" in configured:
        return configured
    return configured or f"https://lichtloot.de/index.html?guild={current_guild_slug()}"


def build_fixed_po_header(payload):
    raid_name = display_raid(payload.get("raid") or "")
    date = normalize_post_date(payload.get("date") or payload.get("raidDate") or payload.get("datum"))
    time_value = normalize_post_time(payload.get("time") or payload.get("raidTime") or payload.get("uhrzeit"))
    guild_name = clean(payload.get("guildName") or payload.get("guild") or payload.get("gilde")) or "Lichtbringer"
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
        f"➡️ Prios eintragen: {lichtloot_prio_url()}",
        "",
        "Bitte tragt eure Prios rechtzeitig ein.",
        "",
        "**LichtLoot**",
    ]
    if lichtloot_id:
        lines.append(f"ID: `{lichtloot_id}`")
    lines.append("PO wird mit LichtLoot synchronisiert.")
    lines.append(
        f"{custom_emoji('kofferorange', '🟧🧰')} **PO eingetragen:** wartet noch auf Freigabe."
    )
    lines.append(
        f"{custom_emoji('koffergrun', '🟩🧰')} **PO freigegeben:** wurde durch die Gildenleitung freigegeben."
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
    return payload_with_lichtloot_id_from_sources({
        **payload,
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
    return chars[:3]


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
    result = await asyncio.to_thread(api_get, {
        "action": "lichtbotGetPoPostEntries",
        "queueToken": QUEUE_TOKEN,
        "postKey": payload["postKey"],
        "sourceChannelId": "" if is_repost else payload_source_channel_id(payload),
        "targetChannelId": "" if is_repost else payload_target_channel_id(payload),
        "includeArchived": "true" if is_repost else "false",
    })
    entries = [
        entry for entry in (result.get("entries") or [])
        if not entry.get("configOnly")
        and (clean(entry.get("player")) or clean(entry.get("item") or entry.get("itemName")))
    ]
    # Im Discord-Post eingebettete Einträge dienen nur als Rückfall für alte
    # Posts. Der aktuelle Datenbankstatus muss immer Vorrang haben, damit eine
    # Freigabe beim anschließenden Refresh nicht wieder orange erscheint.
    return apply_po_item_variants(payload, merge_po_entries(entries, payload_po_post_entries(payload)))


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
        result.append((str(idx), f"{player} · {item}"[:100]))
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
    for role in getattr(user, "roles", []) or []:
        if normalize_role_name(getattr(role, "name", "")) in PO_REVIEW_ROLE_NAMES:
            return True
    return False


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
    raid_pin = payload_lichtloot_raid_pin(payload)
    result = await asyncio.to_thread(api_post, {
        "action": "reviewPoPostEntry",
        "queueToken": QUEUE_TOKEN,
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
    raid_pin = payload_lichtloot_raid_pin(payload)
    result = await asyncio.to_thread(api_post, {
        "action": "reviewPoPostEntry",
        "queueToken": QUEUE_TOKEN,
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
        return False
    try:
        user = client.get_user(int(user_id)) or await client.fetch_user(int(user_id))
        player = clean(entry.get("player")) or "dein Charakter"
        item = clean(entry.get("item") or entry.get("itemName")) or "deine PO"
        await user.send(f"✅ Deine PO für **{player}** auf **{item}** wurde freigegeben.")
        return True
    except Exception as error:
        print(f"PO-Freigabe: DM konnte nicht gesendet werden: {error}")
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
            title="Raidanmeldung gespeichert",
            description=f"Du bist für **{raid_name}** angemeldet.",
            color=0x22C55E,
        )
        embed.add_field(name="Charakter", value=clean(char_name) or "-", inline=True)
        embed.add_field(name="Klasse", value=class_display_name(class_name) or "-", inline=True)
        embed.add_field(name="Skillung", value=clean(spec) or "-", inline=True)
        if raid_date != "noch offen" or raid_time != "noch offen":
            embed.add_field(name="Termin", value=f"{raid_date} · {raid_time}", inline=False)
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


async def send_queue_targeted_embed(payload, embed):
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
    sent = set()
    for guild in [target_guild]:
        guild_role_ids = {str(role.id) for role in guild.roles}
        if wanted_roles and not wanted_roles.intersection(guild_role_ids) and not wanted_names:
            continue
        for member in guild.members:
            if member.bot or member.id in sent:
                continue
            member_names = {
                normalized_prio_player_name(getattr(member, "name", "")),
                normalized_prio_player_name(getattr(member, "display_name", "")),
                normalized_prio_player_name(getattr(member, "global_name", "")),
            }
            member_roles = {str(role.id) for role in getattr(member, "roles", [])}
            if not (configured_discord_name_matches(wanted_names, member_names) or wanted_roles.intersection(member_roles)):
                continue
            try:
                await member.send(embed=embed)
                sent.add(member.id)
            except Exception as error:
                print(f"Raid-DM an {member} fehlgeschlagen: {error}")
    return len(sent)


async def send_player_login_approval_notice_from_queue(payload):
    guild_slug = payload_guild_slug(payload)
    registry_entry = GUILD_REGISTRY.get(guild_slug) or {}
    guild_name = clean(payload.get("guildName") or registry_entry.get("name") or guild_slug)
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


async def send_raid_announcement_notice_from_queue(payload):
    raid_name = clean(payload.get("raidName")) or "Raid"
    raid_date = format_raid_announcement_date(payload.get("raidDate") or "")
    raid_time = format_raid_announcement_time(payload.get("raidTime") or "")
    channel_id = clean(payload.get("channelId"))
    channel_label = f"<#{channel_id}>" if channel_id else "dem vorgesehenen Raid-Channel"
    embed = discord.Embed(
        title="Neuer Raidanmelder",
        description=(
            f"Der neue Anmelder für **{raid_name}** wurde in {channel_label} "
            f"für den **{raid_date} um {raid_time}** erstellt.\n\n"
            "Bitte meldet euch rechtzeitig an und tragt eure Prios ein."
        ),
        color=0x7C3AED,
    )
    signup_url = clean(payload.get("signupUrl"))
    if signup_url:
        embed.add_field(name="Direkt zum Anmelder", value=f"[Raidanmelder öffnen]({signup_url})", inline=False)
    count = await send_queue_targeted_embed(payload, embed)
    print(f"Raidankündigungs-DM an {count} Empfänger gesendet: {raid_name}")
    return count


async def send_raid_status_notice_from_queue(payload):
    raid_name = clean(payload.get("raidName")) or "Raid"
    action = clean(payload.get("action"))
    custom_description = clean(payload.get("messageTemplate"))
    replacements = {"{spieler}": clean(payload.get("player")) or "Ein Spieler", "{raid}": raid_name, "{status}": raid_signup_action_label(action), "{datum}": format_raid_announcement_date(payload.get("raidDate") or ""), "{uhrzeit}": format_raid_announcement_time(payload.get("raidTime") or ""), "{hinweis}": clean(payload.get("message"))}
    for token,value in replacements.items(): custom_description = custom_description.replace(token,value)
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
    character = clean(payload.get("character")) or "Unbekannt"
    server = clean(payload.get("server"))
    class_name = clean(payload.get("className"))
    raid = clean(payload.get("raid")).upper() or "-"
    request_type = clean(payload.get("requestType"))
    request_label = {"recruit":"Rekrutenstatus aufheben","p1p3":"P1–P3 Freigabe","p0":"P0 Freigabe","po":"PO-Freigabe"}.get(request_type,request_type or "PO-Freigabe")
    link = f"{LICHTLOOT_URL.rstrip('/')}/gildenleitung.html?" + urllib.parse.urlencode({"guild":guild_slug,"panel":"po-freigaben"})
    text = clean(payload.get("messageTemplate"))
    replacements = {"{gilde}":guild_slug,"{charakter}":character,"{server}":server,"{klasse}":class_name,"{raid}":raid,"{antrag}":request_label,"{link}":link}
    for token,value in replacements.items(): text = text.replace(token,value)
    embed = discord.Embed(title="Neue PO-Freigabe wartet",description=text or f"**{character}** hat eine **{request_label}** für **{raid}** eingereicht.",color=0xFACC15)
    if not text: embed.add_field(name="Direkt zur PO-Freigabe",value=f"[Antrag prüfen]({link})",inline=False)
    count = await send_queue_targeted_embed(payload,embed)
    print(f"PO-Freigabehinweis an {count} Empfänger gesendet: {character}")
    return count


async def send_loot_master_leadpin_notice_from_queue(payload):
    raid_name = clean(payload.get("raidName")) or "Raid"
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
    embed.add_field(name="LeadPIN", value=f"`{lead_pin}`", inline=False)
    if loot_master_pin:
        embed.add_field(name="Plündermeister-PIN", value=f"`{loot_master_pin}`", inline=False)
    embed.add_field(
        name="Zugang",
        value="Alternativ wird auch der **Mastercode der Gildenleitung** als Plündermeister-Passwort akzeptiert.",
        inline=False,
    )
    embed.add_field(name="Datum", value=format_raid_announcement_date(payload.get("raidDate") or ""), inline=True)
    embed.add_field(name="Uhrzeit", value=format_raid_announcement_time(payload.get("raidTime") or ""), inline=True)
    raidlead_url = (
        f"{LICHTLOOT_URL.rstrip('/')}/raidlead-panel.html?"
        + urllib.parse.urlencode({
            "guild": payload_guild_slug(payload),
            "raidId": raid_id,
            "leadPin": lead_pin,
        })
    )
    embed.add_field(
        name="Direkt zum Plündermeisterpanel",
        value=f"[Plündermeisterseite für {raid_name} öffnen]({raidlead_url})",
        inline=False,
    )
    embed.add_field(
        name="Erinnerung für nach dem Raid",
        value="• **PO+ Punkte übertragen**\n• **Erhaltene Items markieren** und die zugehörigen Punkte entfernen",
        inline=False,
    )
    embed.set_footer(text="PM-PIN: nur PO+ übertragen und Item erhalten/Punkte entfernen. Der Mastercode bleibt voll gültig.")
    count = await send_queue_targeted_embed(payload, embed)
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
                f" {custom_emoji('koffergrun', '🟩🧰')}"
                if row.get("approved") or approval_status == "approved"
                else " ❌"
                if approval_status == "rejected"
                else f" {custom_emoji('kofferorange', '🟧🧰')}"
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
    asyncio.create_task(refresh_po_message_safely(interaction.client, payload))
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
        self.characters = list(characters or [])[:3]
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


class PoKnownCharacterView(discord.ui.View):
    def __init__(self, payload, item_name, class_name, characters, default_char=""):
        super().__init__(timeout=180)
        self.add_item(PoKnownCharacterSelect(payload, item_name, class_name, characters))
        self.add_item(PoOtherCharacterButton(payload, item_name, class_name, default_char))


class PoOtherCharacterView(discord.ui.View):
    def __init__(self, payload, item_name, class_name, default_char=""):
        super().__init__(timeout=180)
        self.add_item(PoOtherCharacterButton(payload, item_name, class_name, default_char))


async def open_po_entry_flow(interaction, payload, item_name, class_name, default_char=""):
    payload = payload_for_interaction(payload, interaction)
    await interaction.response.send_modal(PoPlayerLoginModal(payload, item_name, class_name))


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
        if not class_name:
            self.add_item(PoClassSelect(payload))
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
        hint = "\nBitte in dieser Trefferliste noch die Klasse wählen, falls sie noch nicht gesetzt ist." if not self.class_name else ""
        await interaction.followup.send(
            f"Gefundene Items für **{query}**:{hint}",
            view=PoItemSearchResultView(self.payload, matches, self.class_name, self.default_char),
            ephemeral=True,
        )


class PoSearchButton(discord.ui.Button):
    def __init__(self, payload):
        super().__init__(
            custom_id=f"po-search:{payload['postKey'][:70]}",
            label="2. Item suchen und PO eintragen",
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
            entry = self.entries[int(self.values[0])]
            result = await review_entry(self.payload, entry, interaction.user)
            saved = result.get("entry") or entry
            await refresh_po_message(interaction.client, self.payload)
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
            await interaction.response.send_modal(PoRejectModal(self.payload, self.entries[int(self.values[0])]))
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
        entries = await fresh_entries_for_payload(self.payload)
        if not po_reject_entry_options(entries):
            await interaction.followup.send("Es gibt gerade keinen offenen PO-Eintrag zum Ablehnen.", ephemeral=True)
            return
        await interaction.followup.send(
            "Wähle den PO-Eintrag aus, den du ablehnen möchtest.",
            view=PoRejectEntryView(self.payload, entries),
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
            await delete_entry(self.payload, entry, interaction.user)
            await refresh_po_message(interaction.client, self.payload)
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
        self.add_item(PoClassSelect(payload))
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

        po_class = PoClassSelect(payload)
        po_class.row = 2
        self.add_item(po_class)
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
    embeds, view = po_message_parts(payload, entries, p0plus_labels, items)
    banner, _ = raid_banner_file(combined_raid_snapshot(payload) or {})
    if banner:
        await message.edit(embeds=embeds, attachments=[banner], view=view)
    else:
        await message.edit(embeds=embeds, view=view)
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
    normalized = {
        **stored,
        **payload,
        "guildSlug": payload_guild_slug(payload),
        "postKey": post_key,
        "raid": normalize_raid(payload.get("raid") or stored.get("raid")),
        "date": clean(payload.get("raidDate") or payload.get("date") or stored.get("date")),
        "time": clean(payload.get("raidTime") or payload.get("time") or stored.get("time")),
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
                await message.edit(embeds=embeds, view=view)
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
            await refresh_guild_registry()
            result = await asyncio.to_thread(api_get, {
                "action": "lichtbotGetQueueAllGuilds",
                "queueToken": QUEUE_TOKEN,
                "limit": "50",
                "types": "player_login_approval_notice,po_post,p0_post_refresh,raid_announcement,raid_announcement_refresh,raid_announcement_role_notice,raid_status_staff_notice,loot_master_leadpin_notice,po_release_request_notice,po_rejection_notice,po_approval_notice,po_post_delete",
                "t": int(time.time()),
            })
            if result.get("success"):
                items = result.get("items") or []
                po_items = [
                    item for item in items
                    if clean(item.get("type")) in {"player_login_approval_notice", "po_post", "p0_post_refresh"}
                    or clean(item.get("type")) in {
                        "raid_announcement",
                        "raid_announcement_refresh",
                        "raid_announcement_role_notice",
                        "raid_status_staff_notice",
                        "loot_master_leadpin_notice",
                        "po_release_request_notice",
                        "po_rejection_notice",
                        "po_approval_notice",
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
        self.raid_signup_restore_task = asyncio.create_task(restore_active_raid_signup_views())
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
    for guild in getattr(client, "guilds", []) or []:
        try:
            guild_object = discord.Object(id=int(guild.id))
            client.tree.copy_global_to(guild=guild_object)
            synced = await client.tree.sync(guild=guild_object)
            print(f"PO Slash-Commands fuer Discord-Server {guild.name} ({guild.id}) synchronisiert: {len(synced)}")
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
    found_classes, found_specs, found_items = refresh_emoji_cache()
    print(f"PO Klassenemojis gefunden: {', '.join(sorted(found_classes.keys())) or 'keine'}")
    print(f"PO Skill-Emojis gefunden: {', '.join(sorted(found_specs.keys())) or 'keine'}")
    print(f"PO Item-Emojis gefunden: {len(found_items)}")
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
            "date": clean(datum),
            "time": clean(uhrzeit),
            "title": clean(titel) or f"{display_raid(raid_key)} PO-Anmelder",
            "channelId": str(interaction.channel_id),
            "sourceChannelId": str(interaction.channel_id),
            "targetChannelId": str(interaction.channel_id),
            "messageId": "",
            "server": clean(guild_info.get("server")) or "Everlook",
            "guildName": clean(guild_info.get("name")) or current_guild_slug(),
            "createdBy": "Gildenleitung",
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
        await interaction.followup.send(f"✅ PO-Anmelder erstellt: `{post_key}`", ephemeral=True)
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

    refresh_emoji_cache()
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

    refresh_emoji_cache()
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


@client.event
async def on_message(message):
    if message.author.bot:
        return
    text = clean(getattr(message, "content", ""))
    lower = text.lower()
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
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("PO_BOT_TOKEN fehlt.")
    start_health_server()
    client.run(TOKEN)
