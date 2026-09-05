"""Format and publish a guild-scoped raid workbook message without importing the bot."""
from copyright_notice import copyright_text, without_copyright
import re
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo


def text(value):
    return str(value or "").strip()


def message_data(payload):
    required = ("analysisId", "guildSlug", "guildName", "raidName", "channelId", "discordGuildId")
    if any(not text(payload.get(key)) for key in required):
        raise ValueError("Raid-Auswertung: Gilde, Raid oder Zielchannel fehlt.")
    links = {}
    for key in ("sheetUrl", "analysisUrl", "reportUrl"):
        value = text(payload.get(key))
        url = urllib.parse.urlparse(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Raid-Auswertung: Ungültiger Link.")
        links[key] = value
    page = urllib.parse.urlparse(links["analysisUrl"])
    query = urllib.parse.parse_qs(page.query)
    if query.get("guild") != [text(payload["guildSlug"])] or query.get("id") != [text(payload["analysisId"])]:
        raise ValueError("Analyse-Link gehört nicht zur Gilde und zum Raid.")
    sheet = urllib.parse.urlparse(links["sheetUrl"])
    expected_id = text(payload.get("googleSheetId"))
    if not re.fullmatch(r"[A-Za-z0-9_-]+",expected_id) or sheet.hostname != "docs.google.com" or sheet.path != "/spreadsheets/d/"+expected_id+"/edit":
        raise ValueError("Die Auswertung benötigt einen nativen Google-Sheet-Link.")
    report = urllib.parse.urlparse(links["reportUrl"])
    if not (report.hostname == "warcraftlogs.com" or report.hostname.endswith(".warcraftlogs.com")) or not report.path.startswith("/reports/"):
        raise ValueError("Ungültiger Warcraft-Logs-Report.")
    if not re.fullmatch(r"[0-9]{17,20}", text(payload["channelId"])) or not re.fullmatch(r"[0-9]{17,20}", text(payload["discordGuildId"])):
        raise ValueError("Ungültiger Discord-Zielchannel oder Server.")
    date = text(payload.get("raidDate")) or "Nicht im Log erfasst"
    time = text(payload.get("raidTime")) or "Nicht im Log erfasst"
    started = text(payload.get("startedAt"))
    if started:
        dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Raidbeginn ohne Zeitzone.")
        local = dt.astimezone(ZoneInfo("Europe/Berlin"))
        date, time = local.strftime("%d.%m.%Y"), local.strftime("%H:%M %Z")
    brand = {"nachtloot": "NachtLoot", "lichtloot": "LichtLoot"}.get(text(payload["guildSlug"]).lower(), "GuildLoot")
    return {"brand": brand, "title": text(payload["raidName"])[:240], "guild": text(payload["guildName"])[:200], "date": date, "time": time,
            "footer": "GuildLoot Raid-Auswertung " + text(payload["guildSlug"]) + "/" + text(payload["analysisId"]), **links}


def raid_thread_name(value):
    key = re.sub(r"[^a-z0-9]", "", text(value).lower())
    aliases = {"mc":"MC","moltencore":"MC","geschmolzenerkern":"MC","bwl":"BWL","blackwinglair":"BWL","pechschwingenhort":"BWL","aq40":"AQ40","templeofahnqiraj":"AQ40","tempelvonahnqiraj":"AQ40","naxx":"NAXX","naxxramas":"NAXX","zg":"ZG","zulgurub":"ZG","aq20":"AQ20","ruinsofahnqiraj":"AQ20","ony":"ONY","onyxia":"ONY","onyxiaslair":"ONY"}
    if key not in aliases: raise ValueError("Für diesen Raid muss ein Analyse-Thread eingestellt werden.")
    return aliases[key]

async def raid_destination(channel, payload, discord):
    if getattr(channel,"parent_id",None):
        target=channel
    else:
        name=raid_thread_name(payload.get("raid") or payload["raidName"])
        candidates=list(await channel.guild.active_threads())
        async for thread in channel.archived_threads(limit=100): candidates.append(thread)
        matches={t.id:t for t in candidates if t.parent_id==channel.id and text(t.name).upper()==name}
        if len(matches)>1:raise ValueError("Mehrere passende Raid-Threads gefunden. Bitte die Thread-ID einstellen.")
        target=next(iter(matches.values())) if matches else await channel.create_thread(name=name,type=discord.ChannelType.public_thread,auto_archive_duration=1440,reason="GuildLoot Raid-Auswertung")
    if getattr(target,"locked",False):raise ValueError("Der Analyse-Thread ist gesperrt.")
    if getattr(target,"archived",False):await target.edit(archived=False,reason="Neue GuildLoot Raid-Auswertung")
    return target

async def remove_previous_post(client,payload,data,message):
    old_id=text(payload.get("previousMessageId"));channel_id=text(payload.get("previousChannelId"))
    if not old_id or not channel_id or old_id==str(message.id):return
    if not re.fullmatch(r"[0-9]{17,20}",old_id) or not re.fullmatch(r"[0-9]{17,20}",channel_id):raise ValueError("Ungültiger vorheriger Bot-Post.")
    channel=client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
    if text(channel.guild.id)!=text(payload["discordGuildId"]):raise ValueError("Vorheriger Post gehört zu einer anderen Gilde.")
    try:previous=await channel.fetch_message(int(old_id))
    except Exception as error:
        if getattr(error,"status",None)==404:return
        raise
    if previous.author.id!=client.user.id or not any(without_copyright(e.footer.text)==data["footer"] for e in previous.embeds):raise ValueError("Vorheriger Post stimmt nicht mit dieser Auswertung überein.")
    await previous.delete()


async def post_raid_workbook(client, payload, registry, discord):
    data = message_data(payload)
    entry = registry.get(text(payload["guildSlug"])) or {}
    expected = text(entry.get("discordGuildId"))
    if not expected or expected != text(payload["discordGuildId"]):
        raise ValueError("Discord-Server stimmt nicht mit der registrierten Gilde überein.")
    channel_id = int(payload["channelId"])
    channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
    if text(getattr(getattr(channel, "guild", None), "id", "")) != expected:
        raise ValueError("Analyse-Zielchannel gehört zu einer anderen Gilde.")
    channel = await raid_destination(channel,payload,discord)
    embed = discord.Embed(title=data["title"], url=data["analysisUrl"], color=0x4F7EA7)
    embed.set_footer(text=copyright_text())
    embed.description = f"Dieses Sheet bietet eine kompakte Übersicht. Die ausführliche Analyse findest du auf [{data['brand']}]({data['analysisUrl']})."
    embed.add_field(name="Gilde", value=discord.utils.escape_markdown(data["guild"]), inline=False)
    embed.add_field(name="Datum", value=data["date"], inline=True)
    embed.add_field(name="Uhrzeit", value=data["time"], inline=True)
    embed.add_field(name="Auswertung", value=f"[Google Sheet öffnen]({data['sheetUrl']})\n[Ausführliche Analyse auf {data['brand']}]({data['analysisUrl']})\n[Warcraft Logs]({data['reportUrl']})", inline=False)
    embed.set_footer(text=copyright_text(data["footer"], limit=2048))
    view = discord.ui.View(timeout=None)
    for label, key in (("Google Sheet", "sheetUrl"), (data["brand"] + "-Analyse", "analysisUrl"), ("Warcraft Logs", "reportUrl")):
        view.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.link, url=data[key]))
    # A crash after sending but before resolving the queue must not duplicate the post.
    async for previous in channel.history(limit=100):
        if previous.author.id == client.user.id and any(without_copyright(e.footer.text) == data["footer"] for e in previous.embeds):
            await previous.edit(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            await remove_previous_post(client,payload,data,previous)
            return previous
    message=await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none(), silent=True)
    await remove_previous_post(client,payload,data,message)
    return message
