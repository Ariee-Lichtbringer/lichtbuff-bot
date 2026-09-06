"""Explicitly requested DKP posts; delivery retries reuse the existing message."""
async def send_dkp_notice(bot, guild, payload, queue_id, discord):
    channel_id = str(payload.get('channelId') or '')
    if not channel_id.isdigit():
        raise ValueError('Ungültiger DKP-Zielkanal')
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        channel = await bot.fetch_channel(int(channel_id))
    if str(channel.guild.id) != str(guild.discord_guild_id):
        raise ValueError('DKP-Zielkanal gehört nicht zu dieser Gilde')
    marker = 'GuildLoot DKP · Auftrag ' + queue_id
    async for previous in channel.history(limit=None, oldest_first=True):
        if previous.author.id == bot.user.id and any(getattr(e.footer, 'text', '') == marker for e in previous.embeds):
            return str(previous.id)
    description = str(payload.get('description') or '').strip()
    if not description or len(description) > 3800:
        raise ValueError('Ungültiger DKP-Text')
    embed = discord.Embed(title='GuildLoot · DKP', description=description, color=0xFACC15)
    embed.set_footer(text=marker)
    message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    return str(message.id)
