"""LichtLoot Raid-/P0-Bot V2 (produktive Fassung).

Der Neubau verwendet ausschließlich stabile Identitäten:

* ``guild_id``: interne LichtLoot-Gilden-ID
* ``guild_slug``: lesbarer API-Routingwert
* ``discord_guild_id``: Discord-Server-ID
* ``raid_id``: kanonische LichtLoot-Raid-ID

Raidname, Datum, PIN und Discord-Message-ID dürfen niemals zur Identifikation
einer Gilde oder eines Raids verwendet werden.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands


API_DEFAULT = "https://lichtloot-production.up.railway.app/api/apps-script"
SITE_DEFAULT = "https://lichtloot.de"
EMOJI_CACHE: dict[str, str] = {}


def _emoji_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean(value)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9_]+", "", normalized)


def _emoji(name: str, fallback: str) -> str:
    return EMOJI_CACHE.get(_emoji_key(name), fallback)


ITEM_EMOJI_ALIASES = {
    "berührung des chaos": ["beruhrung_des_chaos", "beruehrung_des_chaos"],
    "jin'dos verhexer": ["jindos_verhexer"],
    "urzeitlicher hakkarigötze": ["urzeitlicher_hakkarigtze", "urzeitlicher_hakkarigoetze"],
    "kriegsklinge der hakkari": ["kriegsklinge_der_hakkari"],
    "schneller razzashiraptor": ["schneller_razzashiraptor"],
    "schneller zulianischer tiger": ["schneller_zulianischer_tiger", "schneller_zullianischer_tiger"],
}


def _item_icon(item_name: str) -> str:
    raw = clean(item_name)
    candidates = ITEM_EMOJI_ALIASES.get(raw.casefold(), [])
    underscored = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode().lower())).strip("_")
    candidates.extend((underscored, f"item_{underscored}", f"loot_{underscored}", f"po_{underscored}"))
    for candidate in candidates:
        icon = EMOJI_CACHE.get(_emoji_key(candidate))
        if icon:
            return icon
    return "🎒"


def _class_icon(class_key: str, fallback: str) -> str:
    english = {
        "krieger": "warrior", "druide": "druid", "schurke": "rogue", "jäger": "hunter",
        "priester": "priest", "magier": "mage", "hexenmeister": "warlock", "schamane": "shaman",
    }.get(class_key, class_key)
    return _emoji(f"classicon_{english}", fallback)


def _spec_icon(spec: str, fallback: str = "◆") -> str:
    aliases = {
        "waffen": "waffen", "furor": "fury", "heilung": "heilung", "heilig": "holy_pala",
        "vergeltung": "retri", "feuer": "feuer", "frost": "frost", "arkan": "arkan",
        "schatten": "schatten", "tank": "tank", "combat": "combat", "kampf": "combat",
        "survival": "survival", "marksman": "marksman", "beastmaster": "beastmaster",
    }
    return _emoji(aliases.get(clean(spec).casefold(), clean(spec)), fallback)


def clean(value: Any) -> str:
    return str(value or "").strip()


def required(value: Any, field: str) -> str:
    result = clean(value)
    if not result:
        raise ValueError(f"Pflichtfeld fehlt: {field}")
    return result


@dataclass(frozen=True, slots=True)
class GuildIdentity:
    guild_id: str
    guild_slug: str
    discord_guild_id: str

    @classmethod
    def from_api(cls, row: dict[str, Any]) -> "GuildIdentity":
        return cls(
            guild_id=required(row.get("id") or row.get("guildId"), "guild_id"),
            guild_slug=required(row.get("slug") or row.get("guildSlug"), "guild_slug").lower(),
            discord_guild_id=required(row.get("discordGuildId"), "discord_guild_id"),
        )


@dataclass(frozen=True, slots=True)
class RaidIdentity:
    guild_id: str
    raid_id: str
    internal_raid_id: str

    def __post_init__(self) -> None:
        required(self.guild_id, "guild_id")
        required(self.raid_id, "raid_id")
        required(self.internal_raid_id, "internal_raid_id")

    @classmethod
    def from_api(cls, guild: GuildIdentity, raid: dict[str, Any]) -> "RaidIdentity":
        returned_guild_id = required(raid.get("guildId"), "raid.guild_id")
        if returned_guild_id != guild.guild_id:
            raise RuntimeError(
                f"Raid gehört zur falschen Gilde: {returned_guild_id} statt {guild.guild_id}"
            )
        return cls(
            guild_id=guild.guild_id,
            raid_id=required(raid.get("raidId"), "raid_id"),
            internal_raid_id=required(raid.get("internalRaidId") or raid.get("id"), "internal_raid_id"),
        )


@dataclass(frozen=True, slots=True)
class DiscordPostIdentity:
    guild_id: str
    raid_id: str
    discord_guild_id: str
    discord_channel_id: str
    discord_message_id: str

    def __post_init__(self) -> None:
        for field in (
            "guild_id",
            "raid_id",
            "discord_guild_id",
            "discord_channel_id",
            "discord_message_id",
        ):
            required(getattr(self, field), field)


class LichtLootApi:
    def __init__(self, base_url: str, queue_token: str) -> None:
        self.base_url = required(base_url, "api_url").rstrip("/")
        self.queue_token = required(queue_token, "queue_token")

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        body = {
            **params,
            "queueToken": self.queue_token,
        }
        if method == "GET":
            url = f"{self.base_url}?{urllib.parse.urlencode(body)}"
            request = urllib.request.Request(url, method="GET")
        else:
            encoded = json.dumps(body).encode("utf-8")
            request = urllib.request.Request(
                self.base_url,
                data=encoded,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LichtLoot API {error.code}: {detail[:500]}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RuntimeError(f"LichtLoot API nicht erreichbar: {error}") from error
        if not isinstance(result, dict) or result.get("success") is False:
            message = result.get("error") if isinstance(result, dict) else "Ungültige Antwort"
            raise RuntimeError(f"LichtLoot API: {message}")
        return result

    async def get(self, action: str, **params: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, "GET", {"action": action, **params})

    async def post(self, action: str, **params: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, "POST", {"action": action, **params})

    async def list_guilds(self) -> list[GuildIdentity]:
        result = await self.get("lichtbotListGuilds")
        guilds = []
        for row in result.get("guilds") or []:
            try:
                guilds.append(GuildIdentity.from_api(row))
            except ValueError as error:
                print(f"V2 ignoriert unvollständige Gilde: {error}")
        return guilds

    @staticmethod
    def require_guild_response(result: dict[str, Any], guild: GuildIdentity) -> None:
        returned_id = required(result.get("guildId"), "response.guild_id")
        returned_slug = required(result.get("guild"), "response.guild_slug").lower()
        if returned_id != guild.guild_id or returned_slug != guild.guild_slug:
            raise RuntimeError(
                "Gildenidentität der API-Antwort stimmt nicht überein: "
                f"erwartet {guild.guild_id}/{guild.guild_slug}, "
                f"erhalten {returned_id}/{returned_slug}"
            )

    async def get_active_raids(self, guild: GuildIdentity) -> list[dict[str, Any]]:
        result = await self.get(
            "getActiveRaids",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
        )
        self.require_guild_response(result, guild)
        raids = list(result.get("allRaids") or result.get("raids") or [])
        verified = []
        for raid in raids:
            try:
                identity = RaidIdentity.from_api(guild, raid)
            except (ValueError, RuntimeError) as error:
                print(f"V2 ignoriert ungültigen Raid in Gilde {guild.guild_id}: {error}")
                continue
            verified.append({**raid, "raidId": identity.raid_id})
        return verified

    async def get_raid(self, guild: GuildIdentity, raid_id: str) -> dict[str, Any]:
        raid_id = required(raid_id, "raid_id")
        result = await self.get(
            "getRaidHelper",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            raidId=raid_id,
        )
        self.require_guild_response(result, guild)
        raid = dict(result.get("raid") or {})
        identity = RaidIdentity.from_api(guild, raid)
        returned_id = identity.raid_id
        if returned_id != raid_id:
            raise RuntimeError(
                f"Raid-ID stimmt nicht überein: erwartet {raid_id}, erhalten {returned_id or '-'}"
            )
        return result

    async def get_p0_context(self, guild: GuildIdentity, raid_id: str) -> dict[str, Any]:
        result = await self.get(
            "lichtbotGetP0SignupContext",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            raidId=required(raid_id, "raid_id"),
        )
        self.require_guild_response(result, guild)
        RaidIdentity.from_api(guild, dict(result.get("raid") or {}))
        return result

    async def get_p0_entries(self, guild: GuildIdentity, raid_id: str) -> list[dict[str, Any]]:
        result = await self.get(
            "lichtbotGetPoPostEntries",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            raidId=required(raid_id, "raid_id"),
        )
        self.require_guild_response(result, guild)
        return [dict(row) for row in list(result.get("entries") or []) if not row.get("configOnly")]

    async def get_linked_characters(
        self, guild: GuildIdentity, discord_user_id: int | str
    ) -> list[dict[str, Any]]:
        result = await self.get(
            "lichtbotGetPoLinkedCharacters",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            discordUserId=required(discord_user_id, "discord_user_id"),
        )
        self.require_guild_response(result, guild)
        return list(result.get("characters") or [])

    async def get_p0_points(self, guild: GuildIdentity) -> list[dict[str, Any]]:
        result = await self.get(
            "getP0Plus",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
        )
        return list(result.get("entries") or [])

    async def save_discord_post(
        self,
        guild: GuildIdentity,
        raid_id: str,
        channel_id: int | str,
        message_id: int | str,
    ) -> None:
        result = await self.post(
            "lichtbotSetRaidDiscordMessage",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            raidId=required(raid_id, "raid_id"),
            discordChannelId=required(channel_id, "discord_channel_id"),
            discordMessageId=required(message_id, "discord_message_id"),
            claimOnly="true",
        )
        self.require_guild_response(result, guild)
        saved_raid = dict(result.get("raid") or {})
        identity = RaidIdentity.from_api(guild, saved_raid)
        if result.get("claimed") is not True:
            raise RuntimeError("Ein anderer Vorgang hat bereits einen Post für diesen Raid erstellt.")
        if identity.raid_id != raid_id:
            raise RuntimeError("API hat den Discord-Post an einen anderen Raid gebunden.")

    async def save_raid_signup(
        self,
        guild: GuildIdentity,
        raid_id: str,
        *,
        player_pin: str,
        character: str,
        role: str,
        status: str,
        note: str,
        discord_user_id: int | str,
        discord_name: str,
        channel_id: int | str,
        message_id: int | str,
    ) -> None:
        result = await self.post(
            "saveRaidSignup",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            raidId=required(raid_id, "raid_id"),
            playerPin=clean(player_pin),
            char=required(character, "character"),
            signupRole=required(role, "role").lower(),
            signupStatus=required(status, "status").lower(),
            note=clean(note),
            discordUserId=required(discord_user_id, "discord_user_id"),
            discordName=required(discord_name, "discord_name"),
            discordChannelId=required(channel_id, "discord_channel_id"),
            discordMessageId=required(message_id, "discord_message_id"),
            source=f"discordSignup:{required(message_id, 'discord_message_id')}",
        )
        self.require_guild_response(result, guild)
        identity = RaidIdentity.from_api(guild, dict(result.get("raid") or {}))
        if identity.raid_id != raid_id:
            raise RuntimeError("Raid-Anmeldung wurde für einen anderen Raid beantwortet.")

    async def save_p0_signup(
        self,
        guild: GuildIdentity,
        raid_id: str,
        *,
        player_pin: str,
        character: str,
        item: str,
        discord_user_id: int | str,
        discord_name: str,
        channel_id: int | str,
        message_id: int | str,
    ) -> None:
        result = await self.post(
            "lichtbotSaveP0Signup",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            raidId=required(raid_id, "raid_id"),
            playerPin=clean(player_pin),
            char=required(character, "character"),
            item=required(item, "item"),
            discordUserId=required(discord_user_id, "discord_user_id"),
            discordName=required(discord_name, "discord_name"),
            discordChannelId=required(channel_id, "discord_channel_id"),
            discordMessageId=required(message_id, "discord_message_id"),
        )
        self.require_guild_response(result, guild)
        identity = RaidIdentity.from_api(guild, dict(result.get("raid") or {}))
        if identity.raid_id != raid_id:
            raise RuntimeError("P0-Anmeldung wurde für einen anderen Raid beantwortet.")

    async def delete_p0_signup(
        self,
        guild: GuildIdentity,
        raid_id: str,
        *,
        player_pin: str,
        character: str,
        discord_user_id: int | str,
    ) -> None:
        result = await self.post(
            "lichtbotDeleteP0Signup",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            raidId=required(raid_id, "raid_id"),
            playerPin=clean(player_pin),
            char=required(character, "character"),
            discordUserId=required(discord_user_id, "discord_user_id"),
        )
        self.require_guild_response(result, guild)
        identity = RaidIdentity.from_api(guild, dict(result.get("raid") or {}))
        if identity.raid_id != raid_id:
            raise RuntimeError("P0-Löschung wurde für einen anderen Raid beantwortet.")

    async def review_p0_signup(
        self,
        guild: GuildIdentity,
        raid_id: str,
        *,
        signup_id: str,
        status: str,
        reviewer_discord_id: int | str,
        reviewer_discord_name: str,
    ) -> None:
        result = await self.post(
            "lichtbotReviewP0Signup",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            raidId=required(raid_id, "raid_id"),
            signupId=required(signup_id, "signup_id"),
            status=required(status, "approval_status"),
            reviewerDiscordId=required(reviewer_discord_id, "reviewer_discord_id"),
            reviewerDiscordName=required(reviewer_discord_name, "reviewer_discord_name"),
        )
        self.require_guild_response(result, guild)


class IdentityRegistry:
    def __init__(self, api: LichtLootApi) -> None:
        self.api = api
        self.by_discord_guild_id: dict[str, GuildIdentity] = {}

    async def refresh(self) -> None:
        guilds = await self.api.list_guilds()
        registry: dict[str, GuildIdentity] = {}
        for guild in guilds:
            existing = registry.get(guild.discord_guild_id)
            if existing is not None and existing.guild_id != guild.guild_id:
                raise RuntimeError(
                    "Discord-Server ist mehreren LichtLoot-Gilden zugeordnet: "
                    f"{guild.discord_guild_id}"
                )
            registry[guild.discord_guild_id] = guild
        self.by_discord_guild_id = registry

    def for_discord_guild(self, discord_guild_id: int | str | None) -> GuildIdentity:
        key = required(discord_guild_id, "discord_guild_id")
        guild = self.by_discord_guild_id.get(key)
        if guild is None:
            raise RuntimeError(f"Discord-Server {key} ist keiner LichtLoot-Gilden-ID zugeordnet.")
        return guild


class PoBotV2(discord.Client):
    def __init__(self, api: LichtLootApi) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.api = api
        self.identities = IdentityRegistry(api)
        self._refresh_task: asyncio.Task[None] | None = None
        self._register_commands()

    def _register_commands(self) -> None:
        @self.tree.command(name="p0_post_erstellen", description="Erstellt den kombinierten Raid-/P0-Post explizit.")
        @app_commands.default_permissions(manage_guild=True)
        async def create_post(interaction: discord.Interaction, raid_id: str) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                guild = self.identities.for_discord_guild(interaction.guild_id)
                helper = await self.api.get_raid(guild, raid_id)
                raid = dict(helper.get("raid") or {})
                existing_message_id = clean(raid.get("discordMessageId"))
                if existing_message_id:
                    raise RuntimeError(
                        "Für diesen Raid ist bereits ein Discord-Post gespeichert. "
                        "Nutze /p0_post_aktualisieren."
                    )
                p0_context, p0_entries = await asyncio.gather(
                    self.api.get_p0_context(guild, raid_id),
                    self.api.get_p0_entries(guild, raid_id),
                )
                embed = build_combined_embed(guild, helper, p0_context, p0_entries)
                configured_channel_id = required(
                    raid.get("discordChannelId"), "raid.discord_channel_id"
                )
                target_channel = self.get_channel(int(configured_channel_id))
                if target_channel is None:
                    target_channel = await self.fetch_channel(int(configured_channel_id))
                if (
                    not hasattr(target_channel, "send")
                    or clean(getattr(getattr(target_channel, "guild", None), "id", ""))
                    != guild.discord_guild_id
                ):
                    raise RuntimeError(
                        "Der in der Gildenleitung konfigurierte Discord-Kanal ist ungültig."
                    )
                message = await target_channel.send(embed=embed)
                try:
                    await self.api.save_discord_post(guild, raid_id, message.channel.id, message.id)
                except Exception:
                    await message.delete()
                    raise
                try:
                    await message.edit(
                        view=CombinedSignupView(self, guild, raid_id, message.id)
                    )
                except Exception as error:
                    print(f"V2-Post wurde gespeichert, aber Buttons fehlen vorübergehend: {error}")
                await interaction.followup.send(
                    f"✅ Post für Raid-ID `{raid_id}` wurde im konfigurierten Kanal "
                    f"<#{configured_channel_id}> erstellt und eindeutig gespeichert.",
                    ephemeral=True,
                )
            except Exception as error:
                await interaction.followup.send(f"⚠️ Post wurde nicht erstellt: {error}", ephemeral=True)

        @self.tree.command(name="p0_post_aktualisieren", description="Aktualisiert ausschließlich einen vorhandenen Raid-/P0-Post.")
        @app_commands.default_permissions(manage_guild=True)
        async def refresh_post(interaction: discord.Interaction, raid_id: str) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                guild = self.identities.for_discord_guild(interaction.guild_id)
                state = await self.refresh_existing_post(guild, raid_id)
                await interaction.followup.send(f"✅ Vorhandener Post aktualisiert: `{state.discord_message_id}`.", ephemeral=True)
            except Exception as error:
                await interaction.followup.send(f"⚠️ Kein Post wurde erstellt oder ersetzt: {error}", ephemeral=True)

        @self.tree.command(
            name="refresh",
            description="Aktualisiert vorhandene Raid-/P0-Posts, ohne neue Posts zu erstellen.",
        )
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.describe(raid_id="Optional: nur diese Raid-ID aktualisieren")
        async def refresh(interaction: discord.Interaction, raid_id: str | None = None) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                guild = self.identities.for_discord_guild(interaction.guild_id)
                if clean(raid_id):
                    state = await self.refresh_existing_post(guild, required(raid_id, "raid_id"))
                    await interaction.followup.send(
                        f"✅ Raid-/P0-Post `{state.discord_message_id}` wurde aktualisiert.",
                        ephemeral=True,
                    )
                    return
                raids = await self.api.get_active_raids(guild)
                updated = 0
                skipped = 0
                errors = []
                for raid in raids:
                    if not clean(raid.get("discordMessageId")):
                        skipped += 1
                        continue
                    current_raid_id = required(raid.get("raidId"), "raid_id")
                    try:
                        await self.refresh_existing_post(guild, current_raid_id)
                        updated += 1
                    except Exception as error:
                        errors.append(f"{current_raid_id}: {error}")
                summary = (
                    f"✅ **{updated}** vorhandene Raid-/P0-Posts aktualisiert; "
                    f"**{skipped}** Raids ohne Post übersprungen."
                )
                if errors:
                    summary += "\n⚠️ " + "\n⚠️ ".join(errors[:5])
                await interaction.followup.send(summary[:1900], ephemeral=True)
            except Exception as error:
                await interaction.followup.send(
                    f"⚠️ Refresh fehlgeschlagen; es wurde kein Post erstellt: {error}",
                    ephemeral=True,
                )

    async def refresh_existing_post(
        self, guild: GuildIdentity, raid_id: str
    ) -> DiscordPostIdentity:
        helper = await self.api.get_raid(guild, raid_id)
        raid = dict(helper.get("raid") or {})
        identity = RaidIdentity.from_api(guild, raid)
        channel_id = required(raid.get("discordChannelId"), "discord_channel_id")
        message_id = required(raid.get("discordMessageId"), "discord_message_id")
        post = DiscordPostIdentity(
            guild_id=guild.guild_id,
            raid_id=identity.raid_id,
            discord_guild_id=guild.discord_guild_id,
            discord_channel_id=channel_id,
            discord_message_id=message_id,
        )
        discord_guild = self.get_guild(int(guild.discord_guild_id))
        if discord_guild is None:
            raise RuntimeError("Der konfigurierte Discord-Server ist nicht erreichbar.")
        channel = discord_guild.get_channel(int(channel_id))
        if channel is None or not hasattr(channel, "fetch_message"):
            raise RuntimeError("Der gespeicherte Discord-Kanal existiert nicht.")
        try:
            message = await channel.fetch_message(int(message_id))
        except discord.NotFound as error:
            raise RuntimeError(
                "Der gespeicherte Discord-Post fehlt. Refresh erstellt absichtlich keinen neuen Post."
            ) from error
        if message.author.id != self.user.id:
            raise RuntimeError("Der gespeicherte Post gehört nicht zu diesem Bot.")
        p0_context, p0_entries = await asyncio.gather(
            self.api.get_p0_context(guild, raid_id),
            self.api.get_p0_entries(guild, raid_id),
        )
        await message.edit(
            embed=build_combined_embed(guild, helper, p0_context, p0_entries),
            view=CombinedSignupView(self, guild, raid_id, message_id),
        )
        return post

    async def setup_hook(self) -> None:
        await self.identities.refresh()
        await self.refresh_emoji_cache()
        for guild in self.identities.by_discord_guild_id.values():
            try:
                raids = await self.api.get_active_raids(guild)
            except Exception as error:
                print(f"V2-Views für Gilde {guild.guild_id} konnten nicht geladen werden: {error}")
                continue
            for raid in raids:
                message_id = clean(raid.get("discordMessageId"))
                if message_id:
                    self.add_view(
                        CombinedSignupView(
                            self,
                            guild,
                            required(raid.get("raidId"), "raid_id"),
                            message_id,
                        ),
                        message_id=int(message_id),
                    )
        await self.tree.sync()
        self._refresh_task = asyncio.create_task(self.refresh_loop(), name="p0-v2-refresh")

    async def refresh_emoji_cache(self) -> None:
        emojis = []
        try:
            emojis.extend(list(await self.fetch_application_emojis()))
        except Exception as error:
            print(f"V2 Application-Emojis konnten nicht geladen werden: {error}")
        for discord_guild in self.guilds:
            try:
                emojis.extend(list(await discord_guild.fetch_emojis()))
            except Exception:
                emojis.extend(list(discord_guild.emojis))
        EMOJI_CACHE.clear()
        EMOJI_CACHE.update({_emoji_key(emoji.name): str(emoji) for emoji in emojis})
        print(f"P0-Bot V2 Emoji-Cache: {len(EMOJI_CACHE)} Emojis geladen.")

    async def refresh_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.identities.refresh()
            except Exception as error:
                print(f"V2 behält die letzte gültige Gildenkonfiguration: {error}")
            for guild in list(self.identities.by_discord_guild_id.values()):
                try:
                    raids = await self.api.get_active_raids(guild)
                except Exception as error:
                    print(f"V2 konnte Raids für Gilde {guild.guild_id} nicht laden: {error}")
                    continue
                for raid in raids:
                    if not clean(raid.get("discordMessageId")):
                        continue
                    try:
                        await self.refresh_existing_post(guild, required(raid.get("raidId"), "raid_id"))
                    except Exception as error:
                        print(
                            f"V2-Refresh übersprungen für {guild.guild_id}/"
                            f"{clean(raid.get('raidId'))}: {error}"
                        )
            await asyncio.sleep(60)

    async def on_ready(self) -> None:
        try:
            await self.identities.refresh()
        except Exception as error:
            print(f"V2 konnte die Gildenkonfiguration beim Reconnect nicht laden: {error}")
        print(
            f"P0-Bot V2 online als {self.user}; "
            f"{len(self.identities.by_discord_guild_id)} Gilden-ID(s) geladen."
        )

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        command = clean(message.content).casefold()
        if command not in {"!clearchannel", "!clearchannel bestätigen"}:
            return
        try:
            guild = self.identities.for_discord_guild(message.guild.id)
        except Exception as error:
            await message.channel.send(f"⚠️ {error}", delete_after=20)
            return
        permissions = getattr(message.author, "guild_permissions", None)
        if not permissions or not (
            permissions.administrator or permissions.manage_messages
        ):
            await message.channel.send(
                "⚠️ Dafür wird die Discord-Berechtigung „Nachrichten verwalten“ benötigt.",
                delete_after=20,
            )
            return
        if command != "!clearchannel bestätigen":
            await message.channel.send(
                "⚠️ Dadurch werden alle nicht angehefteten Nachrichten außer aktiven "
                "Raid-/P0-Posts in diesem Kanal gelöscht. Bestätige mit "
                "`!clearchannel bestätigen`.",
                delete_after=30,
            )
            return
        if not hasattr(message.channel, "purge"):
            await message.channel.send("⚠️ Dieser Kanal kann nicht geleert werden.", delete_after=20)
            return
        try:
            raids = await self.api.get_active_raids(guild)
            protected_message_ids = {
                int(required(raid.get("discordMessageId"), "discord_message_id"))
                for raid in raids
                if clean(raid.get("discordChannelId")) == clean(message.channel.id)
                and clean(raid.get("discordMessageId"))
            }
            deleted = await message.channel.purge(
                limit=None,
                check=lambda old_message: (
                    not old_message.pinned and old_message.id not in protected_message_ids
                ),
                bulk=True,
                reason=f"!clearchannel von {message.author} ({message.author.id})",
            )
            await message.channel.send(
                f"✅ Kanal geleert: **{len(deleted)}** Nachrichten gelöscht; "
                f"**{len(protected_message_ids)}** aktive Raid-/P0-Posts geschützt.",
                delete_after=15,
            )
        except discord.Forbidden:
            await message.channel.send(
                "⚠️ Dem Bot fehlt die Discord-Berechtigung „Nachrichten verwalten“.",
                delete_after=20,
            )
        except Exception as error:
            await message.channel.send(
                f"⚠️ Kanal wurde nicht geleert: {error}", delete_after=30
            )


class RaidSignupModal(discord.ui.Modal, title="Raid anmelden"):
    player_pin = discord.ui.TextInput(label="SpielerLogin/PIN (nur beim ersten Mal)", required=False, max_length=40)
    character = discord.ui.TextInput(label="Charakter", max_length=40)
    role = discord.ui.TextInput(label="Rolle: tank, heal, dd oder flex", default="dd", max_length=10)
    status = discord.ui.TextInput(label="Status: signed, bench, late, tentative, absent", default="signed", max_length=12)
    note = discord.ui.TextInput(label="Notiz (optional)", required=False, max_length=100)

    def __init__(
        self,
        bot: "PoBotV2",
        guild: GuildIdentity,
        raid_id: str,
        channel_id: int | str,
        message_id: int | str,
        preset_status: str = "signed",
        default_character: str = "",
    ) -> None:
        super().__init__()
        self.bot = bot
        self.guild_identity = guild
        self.raid_id = required(raid_id, "raid_id")
        self.channel_id = required(channel_id, "discord_channel_id")
        self.message_id = required(message_id, "discord_message_id")
        self.preset_status = required(preset_status, "signup_status").lower()
        self.remove_item(self.status)
        if clean(default_character):
            self.character.default = clean(default_character)
            self.player_pin.placeholder = "LichtLoot-Account bereits verknüpft"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            role = clean(str(self.role)).lower()
            status = self.preset_status
            if role not in {"tank", "heal", "dd", "flex"}:
                raise ValueError("Rolle muss tank, heal, dd oder flex sein.")
            if status not in {"signed", "bench", "late", "tentative", "absent"}:
                raise ValueError("Status muss signed, bench, late, tentative oder absent sein.")
            await self.bot.api.save_raid_signup(
                self.guild_identity,
                self.raid_id,
                player_pin=str(self.player_pin),
                character=str(self.character),
                role=role,
                status=status,
                note=str(self.note),
                discord_user_id=interaction.user.id,
                discord_name=interaction.user.display_name,
                channel_id=self.channel_id,
                message_id=self.message_id,
            )
            await self.bot.refresh_existing_post(self.guild_identity, self.raid_id)
            await interaction.followup.send("✅ Raidanmeldung gespeichert.", ephemeral=True)
        except Exception as error:
            await interaction.followup.send(f"⚠️ Raidanmeldung fehlgeschlagen: {error}", ephemeral=True)


class P0SignupModal(discord.ui.Modal, title="P0 eintragen"):
    player_pin = discord.ui.TextInput(label="SpielerLogin/PIN (nur beim ersten Mal)", required=False, max_length=40)
    character = discord.ui.TextInput(label="Charakter", max_length=40)
    item = discord.ui.TextInput(label="P0-Item (exakter Name)", max_length=120)

    def __init__(
        self,
        bot: "PoBotV2",
        guild: GuildIdentity,
        raid_id: str,
        channel_id: int | str,
        message_id: int | str,
        default_character: str = "",
    ) -> None:
        super().__init__()
        self.bot = bot
        self.guild_identity = guild
        self.raid_id = required(raid_id, "raid_id")
        self.channel_id = required(channel_id, "discord_channel_id")
        self.message_id = required(message_id, "discord_message_id")
        if clean(default_character):
            self.character.default = clean(default_character)
            self.player_pin.placeholder = "LichtLoot-Account bereits verknüpft"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.api.save_p0_signup(
                self.guild_identity,
                self.raid_id,
                player_pin=str(self.player_pin),
                character=str(self.character),
                item=str(self.item),
                discord_user_id=interaction.user.id,
                discord_name=interaction.user.display_name,
                channel_id=self.channel_id,
                message_id=self.message_id,
            )
            await self.bot.refresh_existing_post(self.guild_identity, self.raid_id)
            await interaction.followup.send("✅ P0-Anmeldung gespeichert.", ephemeral=True)
        except Exception as error:
            await interaction.followup.send(f"⚠️ P0-Anmeldung fehlgeschlagen: {error}", ephemeral=True)


class P0DeleteModal(discord.ui.Modal, title="Eigene P0-Anmeldung löschen"):
    player_pin = discord.ui.TextInput(label="SpielerLogin/PIN (nur beim ersten Mal)", required=False, max_length=40)
    character = discord.ui.TextInput(label="Charakter", max_length=40)

    def __init__(self, bot: "PoBotV2", guild: GuildIdentity, raid_id: str, default_character: str = "") -> None:
        super().__init__()
        self.bot = bot
        self.guild_identity = guild
        self.raid_id = required(raid_id, "raid_id")
        if clean(default_character):
            self.character.default = clean(default_character)
            self.player_pin.placeholder = "LichtLoot-Account bereits verknüpft"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.api.delete_p0_signup(
                self.guild_identity,
                self.raid_id,
                player_pin=str(self.player_pin),
                character=str(self.character),
                discord_user_id=interaction.user.id,
            )
            await self.bot.refresh_existing_post(self.guild_identity, self.raid_id)
            await interaction.followup.send("✅ Deine P0-Anmeldung wurde gelöscht.", ephemeral=True)
        except Exception as error:
            await interaction.followup.send(f"⚠️ P0-Löschung fehlgeschlagen: {error}", ephemeral=True)


class P0ReviewSelect(discord.ui.Select):
    def __init__(
        self,
        bot: "PoBotV2",
        guild: GuildIdentity,
        raid_id: str,
        entries: list[dict[str, Any]],
        status: str,
    ) -> None:
        self.bot = bot
        self.guild_identity = guild
        self.raid_id = raid_id
        self.review_status = status
        options = [
            discord.SelectOption(
                label=(clean(row.get("player") or row.get("char")) or "Unbekannt")[:100],
                description=(clean(row.get("item") or row.get("itemName")) or "P0-Item")[:100],
                value=required(row.get("id") or row.get("signupId"), "signup_id"),
                emoji="✅" if status == "approved" else "❌",
            )
            for row in entries[:25]
            if clean(row.get("id") or row.get("signupId"))
        ]
        super().__init__(
            placeholder="P0-Eintrag auswählen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.api.review_p0_signup(
                self.guild_identity,
                self.raid_id,
                signup_id=self.values[0],
                status=self.review_status,
                reviewer_discord_id=interaction.user.id,
                reviewer_discord_name=interaction.user.display_name,
            )
            await self.bot.refresh_existing_post(self.guild_identity, self.raid_id)
            label = "freigegeben" if self.review_status == "approved" else "abgelehnt"
            await interaction.followup.send(f"✅ P0-Eintrag wurde {label}.", ephemeral=True)
        except Exception as error:
            await interaction.followup.send(f"⚠️ Prüfung fehlgeschlagen: {error}", ephemeral=True)


class P0ReviewView(discord.ui.View):
    def __init__(self, select: P0ReviewSelect) -> None:
        super().__init__(timeout=120)
        self.add_item(select)


class CombinedSignupView(discord.ui.View):
    def __init__(
        self,
        bot: "PoBotV2",
        guild: GuildIdentity,
        raid_id: str,
        message_id: int | str,
    ) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_identity = guild
        self.raid_id = required(raid_id, "raid_id")
        self.message_id = required(message_id, "discord_message_id")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            actual = self.bot.identities.for_discord_guild(interaction.guild_id)
            if actual.guild_id != self.guild_identity.guild_id:
                raise RuntimeError("Dieser Post gehört zu einer anderen Gilde.")
            if clean(getattr(interaction.message, "id", "")) != self.message_id:
                raise RuntimeError("Dieser Discord-Post ist nicht mehr der aktive Post dieses Raids.")
            return True
        except Exception as error:
            if interaction.response.is_done():
                await interaction.followup.send(f"⚠️ {error}", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ {error}", ephemeral=True)
            return False

    async def open_raid_modal(self, interaction: discord.Interaction, status: str) -> None:
        linked = await self.bot.api.get_linked_characters(self.guild_identity, interaction.user.id)
        await interaction.response.send_modal(
            RaidSignupModal(
                self.bot,
                self.guild_identity,
                self.raid_id,
                interaction.channel_id,
                interaction.message.id,
                preset_status=status,
                default_character=clean(linked[0].get("name")) if linked else "",
            )
        )

    @discord.ui.button(label="Klasse / Charakter anmelden", style=discord.ButtonStyle.primary, custom_id="p0v2:raid_signup", row=0)
    async def raid_signup(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.open_raid_modal(interaction, "signed")

    @discord.ui.button(label="🪑 Bank", style=discord.ButtonStyle.secondary, custom_id="p0v2:raid_bench", row=1)
    async def raid_bench(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.open_raid_modal(interaction, "bench")

    @discord.ui.button(label="🕒 Spät", style=discord.ButtonStyle.secondary, custom_id="p0v2:raid_late", row=1)
    async def raid_late(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.open_raid_modal(interaction, "late")

    @discord.ui.button(label="⚖️ Vorläufig", style=discord.ButtonStyle.secondary, custom_id="p0v2:raid_tentative", row=1)
    async def raid_tentative(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.open_raid_modal(interaction, "tentative")

    @discord.ui.button(label="🚫 Abwesenheit", style=discord.ButtonStyle.secondary, custom_id="p0v2:raid_absent", row=1)
    async def raid_absent(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.open_raid_modal(interaction, "absent")

    @discord.ui.button(label="⚙️ Ändern", style=discord.ButtonStyle.secondary, custom_id="p0v2:raid_change", row=1)
    async def raid_change(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.open_raid_modal(interaction, "signed")

    @discord.ui.button(label="P0 eintragen", style=discord.ButtonStyle.success, custom_id="p0v2:p0_signup", row=2)
    async def p0_signup(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        linked = await self.bot.api.get_linked_characters(self.guild_identity, interaction.user.id)
        await interaction.response.send_modal(
            P0SignupModal(
                self.bot,
                self.guild_identity,
                self.raid_id,
                interaction.channel_id,
                interaction.message.id,
                default_character=clean(linked[0].get("name")) if linked else "",
            )
        )

    @discord.ui.button(label="P0-Eintrag löschen", style=discord.ButtonStyle.danger, custom_id="p0v2:p0_delete", row=2)
    async def p0_delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        linked = await self.bot.api.get_linked_characters(self.guild_identity, interaction.user.id)
        await interaction.response.send_modal(
            P0DeleteModal(
                self.bot,
                self.guild_identity,
                self.raid_id,
                default_character=clean(linked[0].get("name")) if linked else "",
            )
        )

    async def open_p0_review(self, interaction: discord.Interaction, status: str) -> None:
        permissions = getattr(interaction.user, "guild_permissions", None)
        if not permissions or not (permissions.administrator or permissions.manage_guild):
            await interaction.response.send_message(
                "⚠️ Dafür wird die Discord-Berechtigung „Server verwalten“ benötigt.",
                ephemeral=True,
            )
            return
        context = await self.bot.api.get_p0_context(self.guild_identity, self.raid_id)
        entries = [
            row for row in list(context.get("signups") or [])
            if clean(row.get("approvalStatus")).lower() != status
            and clean(row.get("id") or row.get("signupId"))
        ]
        if not entries:
            await interaction.response.send_message("ℹ️ Kein passender P0-Eintrag vorhanden.", ephemeral=True)
            return
        await interaction.response.send_message(
            "P0-Eintrag auswählen:",
            view=P0ReviewView(P0ReviewSelect(self.bot, self.guild_identity, self.raid_id, entries, status)),
            ephemeral=True,
        )

    @discord.ui.button(label="P0 freigeben", style=discord.ButtonStyle.success, custom_id="p0v2:p0_approve", row=2)
    async def p0_approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.open_p0_review(interaction, "approved")

    @discord.ui.button(label="P0 ablehnen", style=discord.ButtonStyle.danger, custom_id="p0v2:p0_reject", row=2)
    async def p0_reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.open_p0_review(interaction, "rejected")

    @discord.ui.button(label="🏆 Alle P0+-Punkte", style=discord.ButtonStyle.secondary, custom_id="p0v2:p0_points", row=2)
    async def p0_points(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        linked, all_points = await asyncio.gather(
            self.bot.api.get_linked_characters(self.guild_identity, interaction.user.id),
            self.bot.api.get_p0_points(self.guild_identity),
        )
        names = {clean(row.get("name")).casefold() for row in linked}
        own_points = [row for row in all_points if clean(row.get("player")).casefold() in names]
        if not linked:
            text = "⚠️ Dein Discord-Nutzer ist noch nicht mit einem LichtLoot-Account verknüpft. Gib bei einer Anmeldung einmalig deinen SpielerLogin/PIN ein."
        elif not own_points:
            text = "🏆 Für deine verknüpften Charaktere sind aktuell keine P0+-Punkte gespeichert."
        else:
            lines = [
                f"{_item_icon(clean(row.get('item')))} **{clean(row.get('item'))}** · {float(row.get('points') or row.get('count') or 0):g} Punkte · {clean(row.get('player'))}"
                for row in own_points
            ]
            text = "🏆 **Deine P0+-Punkte**\n" + "\n".join(lines)
        await interaction.followup.send(text[:1900], ephemeral=True)


CLASS_LABELS = {
    "warrior": ("⚔️", "Krieger"), "krieger": ("⚔️", "Krieger"),
    "paladin": ("✨", "Paladin"), "druid": ("🐾", "Druide"),
    "druide": ("🐾", "Druide"), "rogue": ("🗡️", "Schurke"),
    "schurke": ("🗡️", "Schurke"), "hunter": ("🏹", "Jäger"),
    "jäger": ("🏹", "Jäger"), "priest": ("💠", "Priester"),
    "priester": ("💠", "Priester"), "mage": ("🔮", "Magier"),
    "magier": ("🔮", "Magier"), "warlock": ("🟣", "Hexenmeister"),
    "hexenmeister": ("🟣", "Hexenmeister"), "shaman": ("🌩️", "Schamane"),
    "schamane": ("🌩️", "Schamane"),
}


def _truthy(value: Any) -> bool:
    return value is True or clean(value).lower() in {"1", "true", "yes", "ja", "freigegeben"}


def _prio_marker(row: dict[str, Any], p0_players: dict[str, str]) -> str:
    player_key = clean(row.get("player") or row.get("char")).casefold()
    po_status = clean(row.get("poApprovalStatus") or p0_players.get(player_key)).lower()
    if po_status in {"approved", "freigegeben"}:
        return f" {_emoji('Beutegrun', '🟢')}"
    if po_status in {"pending", "offen", "wartet"}:
        return f" {_emoji('beuteorange', '🟠')}"
    if _truthy(row.get("hasPrio")):
        return f" {_emoji('beutelilia', '🟣')}"
    return ""


def _role_for(row: dict[str, Any]) -> str:
    role = clean(row.get("role")).lower()
    spec = clean(row.get("spec") or row.get("specialization") or row.get("skillung")).lower()
    if role in {"tank", "heal", "healer"}:
        return "heal" if role in {"heal", "healer"} else role
    if any(word in spec for word in ("heal", "heil", "resto")):
        return "heal"
    if "tank" in spec or "schutz" in spec or "guardian" in spec:
        return "tank"
    class_key = clean(row.get("className") or row.get("klasse")).lower()
    return "ranged" if class_key in {"mage", "magier", "warlock", "hexenmeister", "hunter", "jäger", "priest", "priester"} else "melee"


def _add_roster_fields(embed: discord.Embed, rows: list[dict[str, Any]], p0_rows: list[dict[str, Any]]) -> None:
    active_statuses = {"signed", "angemeldet", "confirmed", "fest", ""}
    active = [row for row in rows if clean(row.get("status")).lower() in active_statuses]
    p0_players = {
        clean(row.get("player") or row.get("char")).casefold(): clean(row.get("approvalStatus"))
        for row in p0_rows
    }
    counts = {"tank": 0, "melee": 0, "ranged": 0, "heal": 0}
    for row in active:
        counts[_role_for(row)] += 1
    embed.add_field(
        name="Rollenverteilung",
        value=(
            f"{_emoji('tank', '🛡️')} **Tanks {counts['tank']}** · "
            f"{_emoji('melee', '⚔️')} **Melee {counts['melee']}** · "
            f"{_emoji('range', '🏹')} **Ranged {counts['ranged']}** · "
            f"{_emoji('heilung', '✨')} **Heiler {counts['heal']}**"
        ),
        inline=False,
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in active:
        class_key = clean(row.get("className") or row.get("klasse")).lower()
        if _role_for(row) == "tank":
            class_key = "tank"
        grouped.setdefault(class_key or "ohne klasse", []).append(row)
    order = ["tank", "warrior", "krieger", "druid", "druide", "paladin", "rogue", "schurke", "hunter", "jäger", "priest", "priester", "mage", "magier", "warlock", "hexenmeister", "shaman", "schamane", "ohne klasse"]
    for class_key in sorted(grouped, key=lambda key: order.index(key) if key in order else 99):
        icon, label = ("🛡️", "Tank") if class_key == "tank" else CLASS_LABELS.get(class_key, ("👤", "Ohne Klasse"))
        icon = _emoji("tank", icon) if class_key == "tank" else _class_icon(class_key, icon)
        lines = []
        for position, row in enumerate(rows, 1):
            if row not in grouped[class_key]:
                continue
            player = clean(row.get("player") or row.get("char")) or "Unbekannt"
            spec = clean(row.get("spec") or row.get("specialization") or row.get("skillung") or row.get("role")) or "Flex"
            lines.append(f"{_spec_icon(spec)} `{position}` **{player}**{_prio_marker(row, p0_players)}")
        embed.add_field(name=f"{icon} __{label} ({len(lines)})__", value="\n".join(lines)[:1024], inline=True)
    status_groups = (
        ("🪑 Bank", {"bench", "bank"}), ("🕒 Spät", {"late", "spät", "spaet"}),
        ("⚖️ Vorläufig", {"tentative", "vorläufig", "vorlaeufig"}),
        ("🚫 Abwesenheit", {"absent", "abwesend"}),
    )
    for label, statuses in status_groups:
        status_rows = [row for row in rows if clean(row.get("status")).lower() in statuses]
        if status_rows:
            embed.add_field(
                name=f"{label} ({len(status_rows)})",
                value="\n".join(f"• **{clean(row.get('player') or row.get('char')) or 'Unbekannt'}**" for row in status_rows)[:1024],
                inline=True,
            )


def _add_p0_fields(embed: discord.Embed, rows: list[dict[str, Any]]) -> None:
    if not rows:
        embed.add_field(name="📋 P0-Anmeldungen (0)", value="Noch keine P0-Anmeldungen.", inline=False)
        return
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = clean(row.get("item") or row.get("itemName")) or "Unbekanntes Item"
        grouped.setdefault(item, []).append(row)
    embed.add_field(name=f"📋 P0-Anmeldungen ({len(rows)})", value="🟠 eingetragen · 🟢 freigegeben", inline=False)
    for item, item_rows in sorted(grouped.items(), key=lambda pair: pair[0].casefold()):
        if len(embed.fields) >= 25:
            break
        lines = []
        for row in sorted(item_rows, key=lambda value: clean(value.get("player") or value.get("char")).casefold()):
            player = clean(row.get("player") or row.get("char")) or "Unbekannt"
            approval = clean(row.get("approvalStatus")).lower()
            icon = _emoji("Beutegrun", "🟢") if approval in {"approved", "freigegeben"} else _emoji("beuteorange", "🟠")
            points = float(row.get("p0PlusPoints") or 0)
            suffix = f" · **{points:g} P0+**" if points else ""
            lines.append(f"{icon} `{player[:24]}`{suffix}")
        embed.add_field(name=f"{_item_icon(item)} {item}", value="\n".join(lines)[:1024], inline=True)


def build_combined_embed(
    guild: GuildIdentity,
    helper: dict[str, Any],
    p0_context: dict[str, Any],
    p0_entries: list[dict[str, Any]] | None = None,
) -> discord.Embed:
    raid = dict(helper.get("raid") or {})
    identity = RaidIdentity.from_api(guild, raid)
    title = (clean(raid.get("raidName") or raid.get("raid")) or "Raid").upper()
    raid_date = clean(raid.get("raidDate")) or "–"
    raid_time = clean(raid.get("raidTime")) or "–"
    configured_description = clean(raid.get("description"))
    embed = discord.Embed(
        title=title,
        description=(configured_description or "Raidanmeldung ist geöffnet.")[:4096],
        color=0x7C3AED,
    )
    embed.add_field(name="Raidlead", value=clean(raid.get("createdBy") or raid.get("raidLead")) or "Gildenleitung", inline=True)
    embed.add_field(name="Tag / Datum", value=f"**__{raid_date}__**", inline=True)
    embed.add_field(name="Uhrzeit", value=f"**__{raid_time} Uhr__**", inline=True)
    slot_parts = []
    for label, key in (
        ("Gesamt", "maxPlayers"),
        ("Tanks", "tankSlots"),
        ("Heiler", "healSlots"),
        ("DD", "ddSlots"),
    ):
        value = clean(raid.get(key))
        if value:
            slot_parts.append(f"{label} {value}")
    if slot_parts:
        embed.add_field(name="Raidplätze", value=" · ".join(slot_parts), inline=False)
    prio_pin = clean(raid.get("playerPin") or raid.get("prioPin"))
    if raid.get("prioEnabled") is not False and prio_pin:
        embed.add_field(name="Prio-PIN", value=f"`{prio_pin}`", inline=False)
    raid_rows = list(helper.get("signups") or []) + list(helper.get("externalSignups") or [])
    p0_by_player_item: dict[tuple[str, str], dict[str, Any]] = {}
    for row in list(p0_context.get("signups") or []) + list(p0_entries or []):
        key = (
            clean(row.get("player") or row.get("char")).casefold(),
            clean(row.get("item") or row.get("itemName")).casefold(),
        )
        current = p0_by_player_item.get(key, {})
        p0_by_player_item[key] = {**current, **row}
    p0_rows = list(p0_by_player_item.values())
    embed.add_field(
        name="\u200b",
        value=(
            f"{_emoji('beutelilia', '🟣')} **P1–P3 Lootbag** · "
            f"{_emoji('beuteorange', '🟠')} **P0 eingetragen** · "
            f"{_emoji('Beutegrun', '🟢')} **P0 freigegeben**"
        ),
        inline=False,
    )
    _add_roster_fields(embed, raid_rows, p0_rows)
    _add_p0_fields(embed, p0_rows)
    embed.set_footer(
        text=f"Gilden-ID: {guild.guild_id} · Raid-ID: {identity.raid_id}"
    )
    image_url = clean(raid.get("raidImageUrl") or raid.get("imageUrl"))
    if not image_url:
        raid_key = clean(raid.get("raid") or raid.get("raidName")).lower().replace("_", "-")
        if raid_key.startswith("zg"):
            raid_key = "zg"
        if raid_key in {"zg", "aq20", "aq40", "bwl", "mc", "naxx", "ony"}:
            image_url = f"https://lichtloot-production.up.railway.app/images/raid-banners/{raid_key}.jpg"
    if image_url.startswith(("https://", "http://")):
        embed.set_image(url=image_url)
    return embed


API_URL = clean(os.getenv("PO_BOT_API_URL") or os.getenv("LICHTLOOT_API_URL") or API_DEFAULT)
QUEUE_TOKEN = clean(os.getenv("LICHTBOT_QUEUE_TOKEN"))
BOT_TOKEN = clean(os.getenv("PO_BOT_TOKEN"))


def build_client() -> PoBotV2:
    return PoBotV2(LichtLootApi(API_URL, QUEUE_TOKEN))


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise SystemExit("PO_BOT_TOKEN fehlt.")
    build_client().run(BOT_TOKEN)
