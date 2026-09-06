"""Shared offline notice delivery, with retry deduplication after a sent message."""
_sent = {}

async def send_offline_notice(bot, payload, queue_id, discord):
    channel_id = str(payload.get("channelId") or "")
    guild_id = str(payload.get("discordGuildId") or "")
    if not channel_id.isdigit() or not guild_id.isdigit() or not queue_id:
        raise ValueError("Offline-Hinweis ohne gültigen Channel/Gilde/Auftrag")
    key = (str(queue_id), channel_id)
    if key in _sent:
        return _sent[key]
    channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
    if str(getattr(getattr(channel, "guild", None), "id", "")) != guild_id:
        raise ValueError("Offline-Hinweis gehört zu einer anderen Discord-Gilde")
    content = "⚠️ **Bot vorübergehend offline**\n\nDer Bot ist für etwa **2 Stunden offline**.\n**P0-Eintragungen über LichtLoot oder NachtLoot sind weiterhin möglich.**"
    kind = payload.get("noticeKind", "bot")
    if kind == "update":
        content = "🛠️ **GuildLoot vorübergehend nicht erreichbar**\n\nGuildLoot ist gerade nicht erreichbar, da ein Update durchgeführt wird."
    elif kind != "bot":
        raise ValueError("Unbekannter Hinweis-Typ")
    if payload.get("editOnly") is True:
        message_id = str(payload.get("messageId") or "")
        if not message_id.isdigit():
            raise ValueError("Keine gespeicherte Nachricht zum Bearbeiten")
        message = await channel.fetch_message(int(message_id))
        if message.author.id != bot.user.id:
            raise ValueError("Hinweis wurde nicht von diesem Bot gesendet")
        if payload.get("noticeState", "online") == "online":
            content = "✅ **PO Bot ist wieder erreichbar.**" if kind == "bot" else "✅ **GuildLoot ist wieder erreichbar.**"
        elif payload.get("noticeState") != "offline":
            raise ValueError("Unbekannter Hinweis-Status")
        await message.edit(content=content, allowed_mentions=discord.AllowedMentions.none())
    else:
        message = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
    _sent[key] = str(message.id)
    if len(_sent) > 10000:
        del _sent[next(iter(_sent))]
    return str(message.id)
