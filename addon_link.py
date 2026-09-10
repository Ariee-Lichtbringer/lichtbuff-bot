"""GuildLoot installation link for Discord raid signup posts."""
from pathlib import Path
from urllib.parse import urlencode

import discord

_curseforge_emoji = None


async def load_addon_emoji(client, application_emojis):
    """Reuse an application emoji, creating it once from the bundled icon."""
    global _curseforge_emoji
    _curseforge_emoji = next(
        (emoji for emoji in application_emojis if emoji.name == "curseforge"), None
    )
    if _curseforge_emoji is None:
        try:
            _curseforge_emoji = await client.create_application_emoji(
                name="curseforge",
                image=Path(__file__).with_name("assets").joinpath("curseforge.png").read_bytes(),
            )
            application_emojis.append(_curseforge_emoji)
        except (discord.HTTPException, OSError) as error:
            print(f"GuildLootAddon: CurseForge-Icon konnte nicht eingerichtet werden: {error}")


def addon_link_button(guild_slug):
    query = urlencode({"guild": guild_slug, "view": "addon"})
    return discord.ui.Button(
        label="GuildLootAddon",
        style=discord.ButtonStyle.link,
        url=f"https://lichtloot.de/start.html?{query}",
        emoji=_curseforge_emoji or "🔗",
        row=0,
    )
