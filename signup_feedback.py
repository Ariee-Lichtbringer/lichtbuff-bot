"""Report completed writes separately from refreshing their Discord post."""
import logging

logger = logging.getLogger("guildloot.signups")


async def confirm_saved_action(interaction, bot, guild, raid_id, success_text, **refresh_options):
    try:
        await bot.refresh_existing_post(guild, raid_id, **refresh_options)
    except Exception:
        logger.warning("Saved action: Discord refresh failed guild=%s raid=%s",
                       guild.guild_id, raid_id, exc_info=True)
        success_text += (
            "\n⚠️ Die Discord-Anzeige konnte noch nicht aktualisiert werden. "
            "Die Änderung ist gespeichert; bitte nicht erneut absenden."
        )
    await interaction.followup.send(success_text, ephemeral=True)
