"""Deliver immutable player-analysis links through the P0 bot queue."""
import re
from urllib.parse import urlparse, parse_qs


async def deliver_player_analysis(bot, guild, payload, queue_id, discord, copyright_text):
    if str(payload.get('guildId')) != str(guild.guild_id) or payload.get('guildSlug') != guild.guild_slug:
        raise ValueError('Spielerbericht gehört nicht zur Queue-Gilde.')
    token = str(payload.get('reportToken') or '')
    params = dict(guild=guild.guild_slug, guildId=guild.guild_id,
                  guildSlug=guild.guild_slug, reportToken=token)
    state = await bot.api.get('lichtbotGetPlayerAnalysisDelivery', **params)
    if str(state.get('queueId')) != str(queue_id) or state.get('status') in ('sent', 'failed'):
        await bot.api.post('lichtbotResolveQueue', **params, rowNumber=queue_id)
        return
    if state.get('status') != 'queued':
        raise ValueError('Bericht ist nicht zum Versand freigegeben.')
    user_id = str(state.get('discordUserId') or '')
    url = str(state.get('reportUrl') or '')
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if (not re.fullmatch(r'\d{15,22}', user_id) or
            parsed.scheme != 'https' or parsed.netloc != 'lichtloot.de' or
            parsed.path != '/spieler-analyse.html' or
            query.get('guild') != [guild.guild_slug] or query.get('report') != [token]):
        raise ValueError('Ungültiger Empfänger oder Berichtslink.')
    params['queueId'] = str(queue_id)
    try:
        user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
        channel = user.dm_channel or await user.create_dm()
        # A lost API acknowledgement must not create a second DM after a restart.
        existing = None
        async for message in channel.history(limit=100):
            if message.author.id == bot.user.id and url in message.content:
                existing = message
                break
        if existing is None:
            escape = discord.utils.escape_markdown
            char = escape(str(payload.get('character') or 'Dein Charakter'))
            server = escape(str(payload.get('server') or ''))
            raid = escape(str(payload.get('raid') or 'Raid'))
            guild_name = escape(str(payload.get('guildName') or guild.guild_slug))
            content = (
                f'**GuildLoot · Spieleranalyse**\n\n'
                f'**Gilde:** {guild_name}\n**Charakter:** {char} – {server}\n'
                f'**Raid:** {raid} · {int(payload.get("count") or 1)} Teilnahme(n)\n'
                f'**Zeitraum:** {payload.get("fromDate", "")} bis {payload.get("toDate", "")}\n\n'
                f'[Ausführlichen Bericht öffnen]({url})\n\n'
                'Der Link zeigt den gespeicherten Bericht mit Bossvergleich, Vorbereitung und Prüfpunkten.'
            )
            existing = await channel.send(copyright_text(content), allowed_mentions=discord.AllowedMentions.none())
        await bot.api.post('lichtbotCompletePlayerAnalysisDm', **params,
                           status='sent', messageId=str(existing.id))
    except (discord.Forbidden, discord.NotFound):
        await bot.api.post('lichtbotCompletePlayerAnalysisDm', **params, status='failed',
                           error='Discord-DM nicht möglich. Der Spieler muss DMs erlauben und für den Bot erreichbar sein.')
