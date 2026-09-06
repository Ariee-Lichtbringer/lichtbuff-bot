"""Clean only history preceding a successfully saved weekly signup post."""


async def cleanup_scheduled_channel(bot, guild, posted, discord):
    if str(posted.guild_id) != str(guild.guild_id):
        raise ValueError("Kanalbereinigung gehört zu einer anderen Gilde.")
    channel = await bot.fetch_channel(int(posted.discord_channel_id))
    if str(getattr(getattr(channel, "guild", None), "id", "")) != str(guild.discord_guild_id):
        raise ValueError("Kanalbereinigung: Zielkanal gehört zu einer anderen Discord-Gilde.")
    # Verify the saved new post exists before deleting any older messages.
    current = await channel.fetch_message(int(posted.discord_message_id))
    if current.author.id != bot.user.id:
        raise ValueError("Kanalbereinigung: Der neue Anmelder gehört nicht zu diesem Bot.")
    removed = 0
    async for message in channel.history(limit=None, before=current, oldest_first=True):
        if message.pinned or int(message.id) >= int(current.id):
            continue
        try:
            # Individual deletes also work for messages older than 14 days.
            await message.delete()
            removed += 1
        except discord.NotFound:
            # Already deleted by a concurrent moderator; a retry remains safe.
            continue
    return removed
