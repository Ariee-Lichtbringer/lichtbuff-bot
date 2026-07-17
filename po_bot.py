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


TOKEN = os.getenv("PO_BOT_TOKEN", "")
TEST_GUILD_ID = str(os.getenv("PO_BOT_GUILD_ID", "") or "").strip()
GUILD_SLUG = os.getenv("LICHTLOOT_GUILD", "lichtbringer")
API_URL = os.getenv("LICHTLOOT_API_URL", "https://lichtloot-production.up.railway.app/api/apps-script")
QUEUE_TOKEN = os.getenv("LICHTBOT_QUEUE_TOKEN", "")
STATE_FILE = Path(os.getenv("PO_BOT_STATE_FILE", "po_bot_posts.json"))
QUEUE_CHECK_SECONDS = int(os.getenv("PO_BOT_QUEUE_CHECK_SECONDS", "10") or "10")

CLASS_EMOJIS = {
    "Warrior": "⚔️",
    "Druid": "🌿",
    "Paladin": "✨",
    "Rogue": "🗡️",
    "Hunter": "🏹",
    "Priest": "💠",
    "Mage": "🔥",
    "Warlock": "💀",
    "Shaman": "⚡",
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


def make_embed(payload, entries):
    embed = discord.Embed(
        title=f"📋 {display_raid(payload['raid'])} PO-Anmelder",
        color=discord.Color.gold(),
    )
    embed.add_field(name="Post-ID", value=f"`{payload['postKey']}`", inline=False)
    embed.add_field(name="Raid", value=display_raid(payload["raid"]), inline=True)
    if payload.get("date") or payload.get("time"):
        embed.add_field(name="Termin", value=f"{payload.get('date') or '-'} · {payload.get('time') or '-'} Uhr", inline=True)

    grouped = {}
    for entry in entries:
        item = clean(entry.get("item") or entry.get("itemName")) or "Ohne Item"
        grouped.setdefault(item, []).append(entry)

    if not grouped:
        embed.description = "**Anmeldungen (0)**\nNoch keine PO-Anmeldung vorhanden."
        return embed

    lines = [f"**Anmeldungen ({len(entries)})**"]
    for item in sorted(grouped.keys(), key=lambda value: value.lower()):
        rows = grouped[item]
        lines.append("")
        lines.append(f"◇ **{item}**")
        players = []
        for row in sorted(rows, key=lambda entry: clean(entry.get("player")).lower()):
            class_name = clean(row.get("className") or row.get("Klasse"))
            icon = CLASS_EMOJIS.get(class_name, "◆")
            approved = " ✅" if row.get("approved") or row.get("approvalStatus") == "approved" else ""
            luck = " 🍀" if row.get("luckBy") else ""
            players.append(f"{icon} {clean(row.get('player'))}{approved}{luck}")
        lines.append(", ".join(players) or "-")

    embed.description = "\n".join(lines)[:3900]
    return embed


def class_options():
    return [
        discord.SelectOption(label=name, value=name, emoji=emoji)
        for name, emoji in CLASS_EMOJIS.items()
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
        self.add_item(self.char_name)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        char_name = clean(self.char_name.value)
        class_name = clean(self.class_name)
        if not class_name:
            await interaction.followup.send("⚠️ Bitte zuerst eine Klasse wählen.", ephemeral=True)
            return
        payload = self.payload
        result = await asyncio.to_thread(api_post, {
            "action": "lichtbotSavePoPostEntry",
            "queueToken": QUEUE_TOKEN,
            "postKey": payload["postKey"],
            "sourceChannelId": payload_source_channel_id(payload),
            "targetChannelId": payload_target_channel_id(payload),
            "raid": payload["raid"],
            "title": payload.get("title") or "PO-Anmelder",
            "player": char_name,
            "className": class_name,
            "item": self.item_name,
            "discordUserId": str(interaction.user.id),
            "discordName": interaction.user.display_name,
        })
        if not result.get("success"):
            await interaction.followup.send(f"⚠️ PO konnte nicht gespeichert werden: {result.get('error') or 'unbekannt'}", ephemeral=True)
            return
        await refresh_po_message(interaction.client, payload)
        await interaction.followup.send(f"✅ Gespeichert: **{char_name}** → **{self.item_name}**", ephemeral=True)


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
        class_name = self.values[0]
        user_classes[f"{self.payload['postKey']}:{interaction.user.id}"] = class_name
        await interaction.response.send_message(
            f"{CLASS_EMOJIS.get(class_name, '')} Klasse gespeichert: **{class_name}**. Jetzt Item auswählen.",
            ephemeral=True,
        )


class PoItemSelect(discord.ui.Select):
    def __init__(self, payload, items):
        self.payload = payload
        options = [discord.SelectOption(label=item[:100], value=item[:100]) for item in items[:25]]
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
        self.add_item(self.item_input)
        self.add_item(self.char_name)

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


class PoView(discord.ui.View):
    def __init__(self, payload, items):
        super().__init__(timeout=None)
        self.add_item(PoClassSelect(payload))
        if items:
            self.add_item(PoItemSelect(payload, items))
        self.add_item(PoManualButton(payload))


async def refresh_po_message(client, payload):
    target_channel_id = payload_target_channel_id(payload)
    channel = client.get_channel(int(target_channel_id)) or await client.fetch_channel(int(target_channel_id))
    message = await channel.fetch_message(int(payload["messageId"]))
    items = await items_for_payload(payload)
    entries = await load_entries(payload)
    await message.edit(embed=make_embed(payload, entries), view=PoView(payload, items))


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

    channel = client.get_channel(int(target_channel_id)) or await client.fetch_channel(int(target_channel_id))
    items = await items_for_payload(normalized)
    entries = await load_entries(normalized)
    view = PoView(normalized, items)
    embed = make_embed(normalized, entries)
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
    client.add_view(PoView(normalized, items), message_id=message.id)
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
    print(f"PO-Bot Queue aktiv: pruefe alle {QUEUE_CHECK_SECONDS} Sekunden.")
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
                    if clean(payload.get("mode")).lower() not in {"signup", "anmelder", "po_signup", "po-anmelder"}:
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
    state = load_state()
    for payload in state.values():
        try:
            items = await items_for_payload(payload)
            client.add_view(PoView(payload, items), message_id=int(payload["messageId"]))
        except Exception as error:
            print(f"PO View konnte nicht wiederhergestellt werden ({payload.get('postKey')}): {error}")


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
    message = await interaction.channel.send(embed=embed, view=PoView(payload, items), silent=True)
    payload["messageId"] = str(message.id)
    state = load_state()
    state[post_key] = payload
    save_state(state)
    client.add_view(PoView(payload, items), message_id=message.id)
    await message.edit(embed=make_embed(payload, []), view=PoView(payload, items))
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
