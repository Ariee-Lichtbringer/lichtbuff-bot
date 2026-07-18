import asyncio
import json
import os
import re
import sys
import threading
import time
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
RAILWAY_API_URL = "https://lichtloot-production.up.railway.app/api/apps-script"
API_URL = os.getenv("PO_BOT_API_URL", "") or os.getenv("LICHTLOOT_RAILWAY_API_URL", "") or RAILWAY_API_URL
QUEUE_TOKEN = os.getenv("LICHTBOT_QUEUE_TOKEN", "")
STATE_FILE = Path(os.getenv("PO_BOT_STATE_FILE", "po_bot_posts.json"))
QUEUE_CHECK_SECONDS = int(os.getenv("PO_BOT_QUEUE_CHECK_SECONDS", "10") or "10")
PRIO_SERVER = os.getenv("PO_BOT_PRIO_SERVER", "Lichtbringer")

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
    return result


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
    query = urllib.parse.urlencode({"guild": GUILD_SLUG, **params})
    with urllib.request.urlopen(API_URL + "?" + query, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def api_post(payload):
    data = json.dumps({"guild": GUILD_SLUG, **payload}).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def payload_lichtloot_raid_pin(payload):
    return clean(
        payload.get("lichtlootPlayerPin")
        or payload.get("playerPin")
        or payload.get("lichtlootRaidId")
    )


def save_po_signup_prio(payload, player, class_name, item, player_login=""):
    raid_pin = payload_lichtloot_raid_pin(payload)
    if not raid_pin:
        return None

    login = clean(player_login)
    return api_post({
        "action": "lichtbotSavePoSignupPrio",
        "queueToken": QUEUE_TOKEN,
        "raidPin": raid_pin,
        "prioPin": raid_pin,
        "lichtlootRaidId": raid_pin,
        "playerPin": login,
        "spielerLogin": login,
        "player": player,
        "server": PRIO_SERVER,
        "className": class_name,
        "item": item,
    })


def load_state():
    try:
        return json.loads(STATE_FILE.read_text("utf-8"))
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


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
    return await load_raid_items(payload.get("raid") or "")


async def load_entries(payload):
    result = await asyncio.to_thread(api_get, {
        "action": "lichtbotGetPoPostEntries",
        "queueToken": QUEUE_TOKEN,
        "postKey": payload["postKey"],
        "sourceChannelId": payload_source_channel_id(payload),
        "targetChannelId": payload_target_channel_id(payload),
        "includeArchived": "false",
    })
    return result.get("entries") or []


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
            "postKey": post_key,
            "raid": normalize_raid(entry.get("raid")),
            "title": clean(entry.get("title")) or "PO-Anmelder",
            "sourceChannelId": source_channel_id,
            "targetChannelId": target_channel_id,
            "channelId": target_channel_id,
            "messageId": message_id,
            "source": "lichtloot_restore",
        }
    return list(payloads.values())


async def refresh_po_view_only(client, payload):
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
    result = await asyncio.to_thread(api_get, {
        "action": "lichtbotCanReviewPoPost",
        "queueToken": QUEUE_TOKEN,
        "discordUserId": str(getattr(user, "id", "") or ""),
        "discordName": getattr(user, "display_name", None) or getattr(user, "name", None) or str(user),
    })
    return bool(result.get("allowed"))


async def fresh_entries_for_payload(payload):
    try:
        return await load_entries(payload)
    except Exception:
        return []


async def review_entry(payload, entry, user):
    result = await asyncio.to_thread(api_post, {
        "action": "reviewPoPostEntry",
        "queueToken": QUEUE_TOKEN,
        "postKey": payload["postKey"],
        "sourceChannelId": payload_source_channel_id(payload),
        "targetChannelId": payload_target_channel_id(payload),
        "messageId": entry.get("messageId") or "",
        "poMessageId": entry.get("messageId") or "",
        "discordMessageId": payload.get("messageId") or entry.get("discordMessageId") or "",
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
    embed = discord.Embed(
        title=f"📋 {display_raid(payload['raid'])} PO-Anmelder",
        color=discord.Color.gold(),
    )
    embed.add_field(name="Post-ID", value=f"`{payload['postKey']}`", inline=False)
    embed.add_field(name="Raid", value=display_raid(payload["raid"]), inline=True)
    if payload.get("date") or payload.get("time"):
        embed.add_field(name="Termin", value=f"{payload.get('date') or '-'} · {payload.get('time') or '-'} Uhr", inline=True)

    note = clean(payload.get("note") or payload.get("message") or payload.get("description"))
    header_lines = []
    if note:
        header_lines.extend(note.splitlines())
        header_lines.append("")

    grouped = {}
    for entry in entries:
        item = clean(entry.get("item") or entry.get("itemName")) or "Ohne Item"
        grouped.setdefault(item, []).append(entry)

    if not grouped:
        embed.description = "\n".join(header_lines + ["**Anmeldungen (0)**", "Noch keine PO-Anmeldung vorhanden."])[:3900]
        return embed

    lines = header_lines + [f"**Anmeldungen ({len(entries)})**"]
    p0plus_labels = p0plus_labels or {}
    for item in sorted(grouped.keys(), key=lambda value: value.lower()):
        rows = grouped[item]
        p0_label = p0plus_labels.get(slug(item))
        item_label = f"{item} ({p0_label})" if p0_label else item
        lines.append("")
        lines.append(f"{item_icon(item)} **{item_label}**")
        players = []
        for row in sorted(rows, key=lambda entry: clean(entry.get("player")).lower()):
            class_name = clean(row.get("className") or row.get("Klasse"))
            icon = class_icon(class_name)
            approved = " ✅" if row.get("approved") or row.get("approvalStatus") == "approved" else ""
            luck = " 🍀" if row.get("luckBy") else ""
            players.append(f"{icon} {clean(row.get('player'))}{approved}{luck}")
        lines.append(", ".join(players) or "-")

    embed.description = "\n".join(lines)[:3900]
    return embed


def class_options():
    return [
        discord.SelectOption(label=name, value=name, emoji=class_select_emoji(name))
        for name in ["Warrior", "Druid", "Paladin", "Rogue", "Hunter", "Priest", "Mage", "Warlock", "Shaman"]
    ]


def selected_class(post_key, user_id):
    return user_classes.get(f"{post_key}:{user_id}", "")


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
        class_name = clean(self.class_name)
        if not class_name:
            await interaction.followup.send("⚠️ Bitte zuerst eine Klasse wählen.", ephemeral=True)
            return
        if not player_login:
            await interaction.followup.send("⚠️ Bitte deinen LichtLoot Spielerlogin eintragen.", ephemeral=True)
            return
        payload = self.payload
        raid_pin = payload_lichtloot_raid_pin(payload)
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
            "className": class_name,
            "item": self.item_name,
            "playerPin": player_login,
            "spielerLogin": player_login,
            "discordUserId": str(interaction.user.id),
            "discordName": interaction.user.display_name,
        })
        if not result.get("success"):
            await interaction.followup.send(f"⚠️ PO konnte nicht gespeichert werden: {result.get('error') or 'unbekannt'}", ephemeral=True)
            return
        prio_result = None
        try:
            prio_result = await asyncio.to_thread(save_po_signup_prio, payload, char_name, class_name, self.item_name, player_login)
        except Exception as error:
            prio_result = {"success": False, "error": str(error)}
        await refresh_po_message(interaction.client, payload)
        message = f"✅ Gespeichert: **{char_name}** → **{self.item_name}**"
        if prio_result:
            if prio_result.get("success"):
                message += "\n📌 Auch als PO+ in LichtLoot gespeichert."
            else:
                message += f"\n⚠️ LichtLoot-PO+ konnte nicht gespeichert werden: {prio_result.get('error') or 'unbekannt'}"
        await interaction.followup.send(message, ephemeral=True)


class PoClassSelect(discord.ui.Select):
    def __init__(self, payload):
        self.payload = payload
        super().__init__(
            custom_id=f"po-class:{payload['postKey']}",
            placeholder="Klasse wählen",
            min_values=1,
            max_values=1,
            options=class_options(),
        )

    async def callback(self, interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            class_name = self.values[0]
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
        options = [
            discord.SelectOption(label=item[:100], value=item[:100], emoji=item_select_emoji(item))
            for item in items[:25]
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
        await interaction.response.send_modal(PoEntryModal(self.payload, self.values[0], class_name, default_char))


class ManualItemModal(PoEntryModal):
    def __init__(self, payload, class_name, default_char=""):
        discord.ui.Modal.__init__(self, title="Eigenes PO-Item")
        self.payload = payload
        self.class_name = class_name
        self.item_input = discord.ui.TextInput(label="Itemname", required=True, max_length=100)
        self.char_name = discord.ui.TextInput(label="Charaktername", default=default_char[:50], required=True, max_length=50)
        self.player_login = discord.ui.TextInput(
            label="LichtLoot Spielerlogin",
            placeholder="dein Spielerlogin/PIN aus LichtLoot",
            required=True,
            max_length=80,
        )
        self.add_item(self.item_input)
        self.add_item(self.char_name)
        self.add_item(self.player_login)

    async def on_submit(self, interaction):
        self.item_name = clean(self.item_input.value)
        await PoEntryModal.on_submit(self, interaction)


class PoManualButton(discord.ui.Button):
    def __init__(self, payload):
        super().__init__(
            custom_id=f"po-manual:{payload['postKey']}",
            label=f"Eigenes Item eintragen {display_raid(payload['raid'])}",
            style=discord.ButtonStyle.primary,
        )
        self.payload = payload

    async def callback(self, interaction):
        class_name = selected_class(self.payload["postKey"], interaction.user.id)
        default_char = clean(interaction.user.display_name).split("/")[0].strip()
        await interaction.response.send_modal(ManualItemModal(self.payload, class_name, default_char))


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
        await interaction.response.defer(ephemeral=True)
        try:
            if not self.values or self.values[0] == "none":
                await interaction.followup.send("Es gibt gerade keinen offenen PO-Eintrag zum Freigeben.", ephemeral=True)
                return
            if not await reviewer_allowed(interaction.user):
                await interaction.followup.send(
                    "⚠️ Nur Gildenleitung, Raidoffiziere oder Gildenoffiziere können PO-Einträge freigeben.",
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
            await interaction.followup.send(f"⚠️ Freigabe konnte nicht gespeichert werden: `{error}`", ephemeral=True)


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
        entries = await fresh_entries_for_payload(self.payload)
        if not po_entry_options(entries):
            await interaction.followup.send("Es gibt gerade keinen PO-Eintrag zum Löschen.", ephemeral=True)
            return
        await interaction.followup.send(
            "Wähle den PO-Eintrag aus, den du löschen möchtest.",
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
        if items:
            self.add_item(PoItemSelect(payload, items))
        self.add_item(PoManualButton(payload))
        self.add_item(PoDeleteButton(payload))
        self.add_item(PoReviewSelect(payload, entries or []))
        if po_entry_options(entries or [], only_unlucked=True):
            self.add_item(PoLuckSelect(payload, entries or []))


async def refresh_po_message(client, payload):
    target_channel_id = payload_target_channel_id(payload)
    channel = client.get_channel(int(target_channel_id)) or await client.fetch_channel(int(target_channel_id))
    message = await channel.fetch_message(int(payload["messageId"]))
    items = await items_for_payload(payload)
    entries = await load_entries(payload)
    p0plus_labels = await load_p0plus_labels(payload.get("raid") or "")
    view = PoView(payload, items, entries)
    await message.edit(embed=make_embed(payload, entries, p0plus_labels), view=view)
    register_po_view(client, payload, items, entries)


async def post_or_update_from_queue(client, payload):
    post_key = clean(payload.get("postKey") or payload.get("poPostKey") or payload.get("postId"))
    if not post_key:
        raise RuntimeError("PO-Anmelder ohne Post-ID.")
    target_channel_id = payload_target_channel_id(payload)
    source_channel_id = payload_source_channel_id(payload) or target_channel_id
    if not target_channel_id:
        raise RuntimeError("PO-Anmelder ohne Ziel-Channel.")

    state = load_state()
    stored = state.get(post_key) or {}
    normalized = {
        **stored,
        **payload,
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
            await message.edit(embed=embed, view=view)
        except Exception as error:
            print(f"PO-Anmelder wird neu gepostet, alte Nachricht nicht nutzbar ({post_key}): {error}")
            message = None
    if message is None:
        message = await channel.send(embed=embed, view=view, silent=True)
        normalized["messageId"] = str(message.id)
    state[post_key] = normalized
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
    await client.wait_until_ready()
    if not QUEUE_TOKEN:
        print("PO-Bot Queue deaktiviert: LICHTBOT_QUEUE_TOKEN fehlt.")
        return
    print(f"PO-Bot Queue aktiv: guild={GUILD_SLUG}, api={API_URL}, pruefe alle {QUEUE_CHECK_SECONDS} Sekunden.")
    while not client.is_closed():
        try:
            result = await asyncio.to_thread(api_get, {
                "action": "lichtbotGetQueue",
                "queueToken": QUEUE_TOKEN,
                "type": "po_post",
                "limit": "50",
                "t": int(time.time()),
            })
            if result.get("success"):
                for item in result.get("items") or []:
                    if clean(item.get("type")) != "po_post":
                        continue
                    payload = item.get("payload") or {}
                    mode = clean(payload.get("mode")).lower() or "signup"
                    if mode not in {"signup", "anmelder", "po_signup", "po-anmelder"}:
                        await resolve_queue_item(item.get("rowNumber"))
                        print(f"Alter PO-Post-Auftrag uebersprungen und erledigt markiert: {payload.get('postKey') or item.get('rowNumber')}")
                        continue
                    try:
                        normalized = await post_or_update_from_queue(client, payload)
                        await resolve_queue_item(item.get("rowNumber"))
                        print(f"PO-Anmelder aus Gildenleitung gepostet: {normalized.get('postKey')}")
                    except Exception as error:
                        print(f"PO-Anmelder-Queue konnte nicht verarbeitet werden: {error}")
            else:
                print(f"PO-Bot Queue Antwort: {result}")
        except Exception as error:
            print(f"Fehler im PO-Bot Queue-Loop: {error}")
        await asyncio.sleep(QUEUE_CHECK_SECONDS)


class PoBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = False
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
    found_classes, found_items = refresh_emoji_cache()
    print(f"PO Klassenemojis gefunden: {', '.join(sorted(found_classes.keys())) or 'keine'}")
    print(f"PO Item-Emojis gefunden: {len(found_items)}")
    state = load_state()
    for payload in state.values():
        try:
            await restore_po_view_fast(client, payload)
            await refresh_po_message(client, payload)
        except Exception as error:
            print(f"PO View konnte nicht wiederhergestellt werden ({payload.get('postKey')}): {error}")
    restored = 0
    known_posts = set(state.keys())
    for payload in await load_payloads_from_api_entries():
        if payload.get("postKey") in known_posts:
            continue
        try:
            items, entries = await restore_po_view_fast(client, payload)
            await refresh_po_view_only(client, payload)
            state[payload["postKey"]] = payload
            restored += 1
        except Exception as error:
            print(f"PO View konnte nicht aus LichtLoot wiederhergestellt werden ({payload.get('postKey')}): {error}")
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
    await interaction.response.defer(ephemeral=True)
    raid_key = normalize_raid(raid)
    post_key = f"{slug(raid_key)}-po-{datetime.now().strftime('%Y%m%d-%H%M')}-{str(int(time.time()))[-4:]}"
    payload = {
        "postKey": post_key,
        "raid": raid_key,
        "date": clean(datum),
        "time": clean(uhrzeit),
        "title": clean(titel) or f"{display_raid(raid_key)} PO-Anmelder",
        "channelId": str(interaction.channel_id),
        "sourceChannelId": str(interaction.channel_id),
        "targetChannelId": str(interaction.channel_id),
        "messageId": "",
    }
    items = await items_for_payload(payload)
    embed = make_embed(payload, [])
    message = await interaction.channel.send(embed=embed, view=PoView(payload, items, []), silent=True)
    payload["messageId"] = str(message.id)
    state = load_state()
    state[post_key] = payload
    save_state(state)
    client.add_view(PoView(payload, items, []), message_id=message.id)
    await message.edit(embed=make_embed(payload, []), view=PoView(payload, items, []))
    await interaction.followup.send(f"✅ PO-Anmelder erstellt: `{post_key}`", ephemeral=True)


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
