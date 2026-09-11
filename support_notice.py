import base64, io, re
"""Send only the fixed support announcement or the owner's ticket alert."""
async def deliver_support_notice(bot, payload, discord):
    kind = payload.get('kind')
    if kind == 'announcement':
        channel_id = str(payload.get('channelId') or '')
        guild_id = str(payload.get('discordGuildId') or '')
        proof_id = str(payload.get('proofMessageId') or '')
        if not all(v.isdigit() for v in [channel_id, guild_id, proof_id]):
            raise ValueError('Ungültiges Anmelder-Ziel')
        channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
        if str(getattr(getattr(channel, 'guild', None), 'id', '')) != guild_id:
            raise ValueError('Discord-Gilde stimmt nicht überein')
        found = False
        for candidate in (payload.get('proofMessageIds') or [proof_id])[:10]:
            if not str(candidate).isdigit():
                continue
            try:
                proof = await channel.fetch_message(int(candidate))
            except Exception as error:
                if type(error).__name__ == 'NotFound':
                    continue
                raise
            if proof.author.id == bot.user.id:
                found = True
                break
        if not found:
            raise ValueError('Kein eigener Anmelder im Channel gefunden')
        content = '🛟 **Fehler oder Probleme mit GuildLoot?**\n\nBitte nutzt den Button **„Support · Fehler melden“** unten auf der jeweiligen GuildLoot-Seite. Beschreibt kurz, was ihr tun wolltet und was passiert ist. Einen Screenshot könnt ihr direkt anhängen. Gebt eine E-Mail-Adresse oder euren Discord-Namen an, damit wir euch antworten können.\n\nSo landet eure Meldung direkt beim Support und geht nicht im Channel unter. Danke!\nhttps://lichtloot.de'
    elif kind == 'reply':
        user_id = str(payload.get('targetUserId') or '')
        subject = str(payload.get('subject') or '').strip()
        content = str(payload.get('message') or '').strip()
        if not user_id.isdigit() or not 15 <= len(user_id) <= 22 or not subject or len(subject) > 180 or not content or len(content) > 3500:
            raise ValueError('Ungültige Supportantwort')
        user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
        channel = await user.create_dm()
        embed = discord.Embed(title=subject, description=content)
        embed.set_footer(text='GuildLoot Support · Ticket ' + str(payload.get('ticketId') or ''))
        kwargs = {}
        screenshot = payload.get('screenshotData') or ''
        if screenshot:
            match = re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})', screenshot)
            if not match or len(screenshot) > 7 * 1024 * 1024:
                raise ValueError('Ungültiger Screenshot')
            data = base64.b64decode(match[2], validate=True)
            valid = data.startswith(b'\x89PNG\r\n\x1a\n') if match[1] == 'png' else data.startswith(b'\xff\xd8\xff') if match[1] == 'jpeg' else data[:4] == b'RIFF' and data[8:12] == b'WEBP'
            if not valid or not 12 <= len(data) <= 5 * 1024 * 1024:
                raise ValueError('Ungültiger Screenshot')
            filename = 'screenshot.' + ('jpg' if match[1] == 'jpeg' else match[1])
            kwargs['file'] = discord.File(io.BytesIO(data), filename=filename)
            embed.set_image(url='attachment://' + filename)
        try:
            message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none(), **kwargs)
        finally:
            if 'file' in kwargs:
                kwargs['file'].close()
        return str(message.id)
    elif kind == 'ticket':
        user_id = str(payload.get('targetUserId') or '')
        if not user_id.isdigit():
            raise ValueError('Discord-Empfänger fehlt')
        user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
        channel = await user.create_dm()
        content = '🛟 **Neues GuildLoot-Supportticket**\n\nEine neue Supportanfrage ist eingegangen. Du kannst sie in der Administration unter **Support** lesen und beantworten.\nhttps://lichtloot.de/admin.html'
    else:
        raise ValueError('Unbekannter Supporthinweis')
    message = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
    return str(message.id)
