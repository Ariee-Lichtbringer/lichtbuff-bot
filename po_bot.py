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
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import discord
from discord import app_commands

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


TOKEN = os.getenv("PO_BOT_TOKEN", "") or os.getenv("DISCORD_TOKEN", "")
TEST_GUILD_ID = str(os.getenv("PO_BOT_GUILD_ID", "") or "").strip()
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


def normalize_guild_slug(value):
    slug_value = str(value or "").strip().lower()
    if slug_value == "lichtbringer":
        return "lichtloot"
    return slug_value or GUILD_SLUG


def current_guild_slug():
    return normalize_guild_slug(CURRENT_GUILD_SLUG.get())


def guild_slug_for_discord_guild(discord_guild_id, fallback=""):
    return normalize_guild_slug(DISCORD_GUILD_SLUGS.get(str(discord_guild_id or "").strip()) or fallback)


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
        "PO-Freigabe,P0 Freigabe,P0-Freigabe,PO Freigabe,Gildenleitung,Gildenoffiziere,Raidoffiziere"
    ).split(",")
    if value.strip()
}
STATE_FILE = Path(os.getenv("PO_BOT_STATE_FILE", "po_bot_posts.json"))
QUEUE_CHECK_SECONDS = int(os.getenv("PO_BOT_QUEUE_CHECK_SECONDS", "10") or "10")
PRIO_SERVER = os.getenv("PO_BOT_PRIO_SERVER", "Lichtbringer")
PO_HELP_IMAGE_FILENAME = "po-anmelder-hinweis.png"
PO_HELP_IMAGE_PATH = Path(os.getenv("PO_BOT_HELP_IMAGE", str(Path(__file__).with_name(PO_HELP_IMAGE_FILENAME))))
LICHTLOOT_PRIO_URL = os.getenv("LICHTLOOT_PRIO_URL", "")

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
    "NAXX": "Naxxramas",
}

user_classes = {}
class_emoji_cache = {}
item_emoji_cache = {}
p0plus_cache = {}
P0PLUS_CACHE_SECONDS = int(os.getenv("PO_BOT_P0PLUS_CACHE_SECONDS", "60") or "60")
empty_queue_log_at = 0


def clean(value):
    return str(value or "").strip()


def normalize_raid(value):
    text = clean(value).upper().replace(" ", "").replace("-", "")
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
    found_items = {}
    all_emojis = []
    try:
        for guild in client.guilds:
            all_emojis.extend(getattr(guild, "emojis", []) or [])
    except Exception:
        return found_classes, found_items

    by_name = {normalize_emoji_name(emoji.name): emoji for emoji in all_emojis}
    for key, names in CLASS_EMOJI_NAME_ALIASES.items():
        for name in names:
            emoji = by_name.get(normalize_emoji_name(name))
            if emoji:
                found_classes[key] = str(emoji)
                break
    for emoji_name, emoji in by_name.items():
        found_items[emoji_name] = str(emoji)
    class_emoji_cache.clear()
    class_emoji_cache.update(found_classes)
    item_emoji_cache.clear()
    item_emoji_cache.update(found_items)
    return found_classes, found_items


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


def api_get(params):
    query = urllib.parse.urlencode({"guild": current_guild_slug(), **params})
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
    data = json.dumps({"guild": current_guild_slug(), **payload}).encode("utf-8")
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
        stored = load_state().get(post_key) or {}
    result = payload_with_lichtloot_id_from_sources(payload, stored)
    for key in ("raid", "date", "time", "title", "guildName", "guild", "createdBy", "created_by"):
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
        "raid": payload.get("raid") or "",
        "raidName": display_raid(payload.get("raid") or ""),
        "raidDate": payload.get("date") or payload.get("raidDate") or payload.get("datum") or "",
        "raidTime": payload.get("time") or payload.get("raidTime") or payload.get("uhrzeit") or "",
        "playerPin": prio_pin,
        "prioPin": prio_pin,
        "leadPin": lead_pin,
        "guildName": payload.get("guildName") or payload.get("guild") or payload.get("gilde") or "Lichtbringer",
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
    return api_post({
        "action": "lichtbotSavePoSignupPrio",
        "queueToken": QUEUE_TOKEN,
        "raidPin": raid_pin,
        "prioPin": raid_pin,
        "lichtlootRaidId": raid_pin,
        "playerPin": login,
        "spielerLogin": login,
        "player": player,
        "server": clean(payload.get("server")),
        "className": class_name,
        "item": item,
        "itemId": clean(item_id),
    })


async def load_po_linked_characters(discord_user_id):
    if not discord_user_id:
        return []
    try:
        result = await asyncio.to_thread(api_get, {
            "action": "lichtbotGetPoLinkedCharacters",
            "queueToken": QUEUE_TOKEN,
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
        result = await asyncio.to_thread(api_get, {"action": "getLootItems", "raid": normalize_raid(raid)})
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
        result = await asyncio.to_thread(api_get, {"action": "getLootItems", "raid": normalize_raid(raid), "t": int(time.time())})
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


async def load_entries(payload):
    result = await asyncio.to_thread(api_get, {
        "action": "lichtbotGetPoPostEntries",
        "queueToken": QUEUE_TOKEN,
        "postKey": payload["postKey"],
        "sourceChannelId": payload_source_channel_id(payload),
        "targetChannelId": payload_target_channel_id(payload),
        "includeArchived": "false",
    })
    entries = [
        entry for entry in (result.get("entries") or [])
        if not entry.get("configOnly")
        and (clean(entry.get("player")) or clean(entry.get("item") or entry.get("itemName")))
    ]
    return apply_po_item_variants(payload, entries)


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
        channel = client.get_channel(int(target_channel_id)) or await client.fetch_channel(int(target_channel_id))
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
            "guildSlug": current_guild_slug(),
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
    view = PoView(payload, items, entries)
    await message.edit(view=view)
    client.add_view(PoView(payload, items, entries), message_id=message.id)
    return items, entries


def quick_items_for_payload(payload):
    return parse_item_options(payload.get("itemOptions") or payload.get("items") or payload.get("itemList"))


def register_po_view(client, payload, items=None, entries=None):
    payload = payload_with_saved_lichtloot_id(payload)
    message_id = clean(payload.get("messageId"))
    if not message_id:
        return False
    try:
        client.add_view(PoView(payload, items or [], entries or []), message_id=int(message_id))
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
        if entry.get("approved") or status == "approved":
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
    permissions = getattr(user, "guild_permissions", None)
    if permissions and (
        getattr(permissions, "administrator", False)
        or getattr(permissions, "manage_guild", False)
    ):
        return True
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
        "reviewer": getattr(user, "display_name", None) or getattr(user, "name", None) or str(user),
    })
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "PO-Eintrag konnte nicht freigegeben werden.")
    return result


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
            approved = " ✅" if row.get("approved") or row.get("approvalStatus") == "approved" else ""
            players.append(f"{icon} {clean(row.get('player'))}{approved}")
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
        return f"SpielerLogin/PIN oder Charaktername falsch{suffix}. Bitte prüfe genau deinen LichtLoot-Spielerlogin und den Charakternamen."
    return message


async def submit_po_entry(interaction, payload, item_name, class_name, char_name, player_login, server=""):
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
        await interaction.followup.send("⚠️ Bitte deinen LichtLoot Spielerlogin eintragen.", ephemeral=True)
        return
    if not char_name:
        await interaction.followup.send("⚠️ Bitte deinen Charakternamen eintragen.", ephemeral=True)
        return

    try:
        result = await asyncio.to_thread(api_post, {
            "action": "lichtbotSavePoPostEntry",
            "queueToken": QUEUE_TOKEN,
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
    await interaction.followup.send(
        f"✅ Deine PO wurde im Discord gespeichert: **{saved_player}** → **{saved_item}**.\n"
        "Der PO-Post wird gleich aktualisiert.",
        ephemeral=True,
    )
    asyncio.create_task(refresh_po_message_safely(interaction.client, payload))
    prio_result = None
    try:
        prio_result = await asyncio.to_thread(save_po_signup_prio, {**payload, "server": server}, saved_player, class_name, saved_item, player_login, item_id)
    except Exception as error:
        prio_result = {"success": False, "error": str(error)}
    if prio_result and not prio_result.get("success"):
        detail = po_signup_error_message(prio_result.get("error") or "unbekannt", saved_player)
        await interaction.followup.send(
            f"⚠️ Discord-Eintrag ist gespeichert, aber LichtLoot-PO+ konnte nicht gespeichert werden: {detail}",
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
            label="LichtLoot Spielerlogin",
            placeholder="dein Spielerlogin/PIN aus LichtLoot",
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
    await interaction.response.defer(ephemeral=True)
    characters = await load_po_linked_characters(interaction.user.id)
    item_display = po_item_display_text(item_name)
    if characters:
        await interaction.followup.send(
            f"Item gewählt: **{item_display}**.\nWähle deinen Charakter oder trage einen anderen ein.",
            view=PoKnownCharacterView(payload, item_name, class_name, characters, default_char),
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        f"Item gewählt: **{item_display}**.\nFür dich ist noch kein Charakter gespeichert.",
        view=PoOtherCharacterView(payload, item_name, class_name, default_char),
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
            await interaction.followup.send(
                f"✅ Freigegeben: **{saved.get('player') or entry.get('player')}** → **{saved.get('item') or entry.get('item')}**.",
                ephemeral=True,
            )
        except Exception as error:
            if interaction.response.is_done():
                await interaction.followup.send(f"⚠️ Freigabe konnte nicht geöffnet werden: `{error}`", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ Freigabe konnte nicht geöffnet werden: `{error}`", ephemeral=True)


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
        self.add_item(PoReviewSelect(payload, entries or []))


async def refresh_po_message(client, payload):
    payload = payload_with_saved_lichtloot_id(payload)
    target_channel_id = payload_target_channel_id(payload)
    channel = client.get_channel(int(target_channel_id)) or await client.fetch_channel(int(target_channel_id))
    message = await channel.fetch_message(int(payload["messageId"]))
    items = await items_for_payload(payload)
    entries = await load_entries(payload)
    p0plus_labels = await load_p0plus_labels(payload.get("raid") or "")
    view = PoView(payload, items, entries)
    await edit_po_message(message, make_embed(payload, entries, p0plus_labels), view)
    register_po_view(client, payload, items, entries)


async def refresh_po_message_safely(client, payload):
    try:
        await refresh_po_message(client, payload)
    except Exception as error:
        print(f"PO-Anmelder konnte nach Eintrag nicht aktualisiert werden ({payload.get('postKey')}): {error}")


async def post_or_update_from_queue(client, payload):
    payload = dict(payload or {})
    payload.setdefault("guildSlug", current_guild_slug())
    post_key = clean(payload.get("postKey") or payload.get("poPostKey") or payload.get("postId"))
    if not post_key:
        raise RuntimeError("PO-Anmelder ohne Post-ID.")
    target_channel_id = payload_target_channel_id(payload)
    source_channel_id = payload_source_channel_id(payload) or target_channel_id
    if not target_channel_id:
        raise RuntimeError("PO-Anmelder ohne Ziel-Channel.")

    state = load_state()
    state_key = po_post_state_key(payload)
    stored = state.get(state_key) or state.get(post_key) or {}
    normalized = {
        **stored,
        **payload,
        "guildSlug": current_guild_slug(),
        "postKey": post_key,
        "raid": normalize_raid(payload.get("raid") or stored.get("raid")),
        "date": clean(payload.get("raidDate") or payload.get("date") or stored.get("date")),
        "time": clean(payload.get("raidTime") or payload.get("time") or stored.get("time")),
        "title": clean(payload.get("title") or stored.get("title")) or "PO-Anmelder",
        "sourceChannelId": str(source_channel_id),
        "targetChannelId": str(target_channel_id),
        "channelId": str(target_channel_id),
        "messageId": clean(stored.get("messageId") or payload.get("messageId") or payload.get("discordMessageId")),
    }
    normalized = payload_with_lichtloot_id_from_sources(normalized, stored)
    normalized = await asyncio.to_thread(ensure_payload_lichtloot_raid, normalized)
    if not normalized.get("messageId"):
        normalized["messageId"] = await find_existing_message_id(client, normalized)

    channel = client.get_channel(int(target_channel_id)) or await client.fetch_channel(int(target_channel_id))
    items = await items_for_payload(normalized)
    entries = await load_entries(normalized)
    p0plus_labels = await load_p0plus_labels(normalized.get("raid") or "")
    view = PoView(normalized, items, entries)
    embed = make_embed(normalized, entries, p0plus_labels)
    message = None
    if normalized.get("messageId"):
        try:
            message = await channel.fetch_message(int(normalized["messageId"]))
            await edit_po_message(message, embed, view)
        except Exception as error:
            print(f"PO-Anmelder wird neu gepostet, alte Nachricht nicht nutzbar ({post_key}): {error}")
            message = None
    if message is None:
        message = await send_po_message(channel, embed, view)
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
                "type": "po_post",
                "limit": "50",
                "t": int(time.time()),
            })
            if result.get("success"):
                items = result.get("items") or []
                po_items = [item for item in items if clean(item.get("type")) == "po_post"]
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
                        if mode not in {"signup", "anmelder", "po_signup", "po-anmelder"}:
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


class PoBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.bg_task = asyncio.create_task(po_queue_loop())
        if TEST_GUILD_ID:
            guild = discord.Object(id=int(TEST_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Slash-Commands fuer Testserver {TEST_GUILD_ID} synchronisiert.")
        else:
            await self.tree.sync()


client = PoBot()


@client.event
async def on_ready():
    print(f"PO Bot online als {client.user}")
    await refresh_guild_registry()
    found_classes, found_items = refresh_emoji_cache()
    print(f"PO Klassenemojis gefunden: {', '.join(sorted(found_classes.keys())) or 'keine'}")
    print(f"PO Item-Emojis gefunden: {len(found_items)}")
    state = load_state()
    for payload in state.values():
        if not isinstance(payload, dict) or not payload.get("postKey"):
            continue
        token = CURRENT_GUILD_SLUG.set(normalize_guild_slug(payload.get("guildSlug") or payload.get("guild")))
        try:
            await restore_po_view_fast(client, payload)
            await remember_po_message(payload)
            await refresh_po_message(client, payload)
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
                    await refresh_po_view_only(client, payload)
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
        guild_slug_for_discord_guild(getattr(getattr(interaction, "guild", None), "id", ""), GUILD_SLUG)
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
