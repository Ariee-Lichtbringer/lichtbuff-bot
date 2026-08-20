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
import hashlib
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
    "drachenfangzahn-talisman": ["drachenfangzahntalisman", "drachenfangzahn_talisman", "_drachenfangzahntalisman"],
    "neltharions träne": ["neltharions_trane", "neltharions_traene", "neltharions_trne", "_neltharions_trne"],
    "halsschmuck des feuerlords": ["halsschmuck_des_feuerlords", "_halsschmuckdesfeuerlords"],
    "sulfuronblock": ["sulfuronblock", "_sulfuronblock"],
}


def _short_emoji_key(value: Any) -> str:
    """Discord begrenzt Emoji-Namen auf 32 Zeichen.

    Der bisherige P0-Bot hat lange Itemnamen beim Upload auf 25 Zeichen plus
    einen stabilen SHA-1-Suffix gekürzt. Diese Form muss beim Lesen erneut
    gebildet werden, sonst erscheinen lange Namen nur mit dem Ersatz-Rucksack.
    """
    key = _emoji_key(value)
    if len(key) <= 32:
        return key
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:6]
    return f"{key[:25]}_{digest}"[:32]


def _item_emoji_candidates(item_name: str) -> list[str]:
    raw = clean(item_name)
    # Derselbe Umlaut-Umschrieb wie beim ursprünglichen Emoji-Upload.
    ascii_name = raw.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    ascii_name = unicodedata.normalize("NFKD", ascii_name).encode("ascii", "ignore").decode()
    compact = re.sub(r"[^a-z0-9_]+", "", ascii_name)
    underscored = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", ascii_name)).strip("_")
    candidates = list(ITEM_EMOJI_ALIASES.get(raw.casefold(), []))
    for value in (compact, underscored):
        if value:
            candidates.extend((value, f"item_{value}", f"loot_{value}", f"po_{value}"))

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        for key in (_emoji_key(candidate), _short_emoji_key(candidate)):
            if key and key not in seen:
                seen.add(key)
                result.append(key)
    return result


def _item_icon(item_name: str) -> str:
    for candidate in _item_emoji_candidates(item_name):
        icon = EMOJI_CACHE.get(candidate)
        if icon:
            return icon
    return "🎒"


def _class_icon(class_key: str, fallback: str) -> str:
    english = {
        "krieger": "warrior", "druide": "druid", "schurke": "rogue", "jäger": "hunter",
        "priester": "priest", "magier": "mage", "hexenmeister": "warlock", "schamane": "shaman",
    }.get(class_key, class_key)
    return _emoji(f"classicon_{english}", fallback)


def _select_emoji(value: str) -> str | discord.PartialEmoji | None:
    value = clean(value)
    if value.startswith("<:") or value.startswith("<a:"):
        try:
            return discord.PartialEmoji.from_str(value)
        except ValueError:
            return None
    return value or None


def _class_select_emoji(class_name: str) -> str | discord.PartialEmoji | None:
    class_key = clean(class_name).casefold()
    fallbacks = {
        "krieger": "⚔️", "paladin": "🛡️", "jäger": "🏹", "schurke": "🗡️",
        "priester": "✨", "schamane": "⚡", "magier": "🔥", "hexenmeister": "👿", "druide": "🐾",
    }
    return _select_emoji(_class_icon(class_key, fallbacks.get(class_key, "🎮")))


def _spec_icon(spec: str, fallback: str = "◆") -> str:
    aliases = {
        "waffen": "waffen", "furor": "fury", "heilung": "heilung", "heilig": "holy_pala",
        "vergeltung": "retri", "feuer": "feuer", "frost": "frost", "arkan": "arkan",
        "schatten": "schatten", "tank": "tank", "combat": "combat", "kampf": "combat",
        "survival": "survival", "überleben": "survival", "marksman": "marksman",
        "treffsicherheit": "marksman", "beastmaster": "beastmaster", "tierherrschaft": "beastmaster",
        "disziplin": "disziplin", "gebrechen": "affliction", "dämonologie": "demonology",
        "damonologie": "demonology", "zerstörung": "destruction", "zerstorung": "destruction",
        "elementar": "elemental", "verstärkung": "enhancement", "verstarkung": "enhancement",
        "gleichgewicht": "balance", "wildheit": "feral", "meucheln": "assassination",
        "täuschung": "subtlety", "tauschung": "subtlety",
    }
    return _emoji(aliases.get(clean(spec).casefold(), clean(spec)), fallback)


def _spec_for_row(row: dict[str, Any]) -> str:
    direct = clean(
        row.get("specialization")
        or row.get("specialisation")
        or row.get("spec")
        or row.get("skillung")
    )
    if direct:
        return direct
    match = re.search(r"skillung\s*:\s*([^|,;\n]+)", clean(row.get("note")), re.IGNORECASE)
    return clean(match.group(1)) if match else ""


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
            "lichtbotGetActiveRaids",
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
        return [
            {**dict(row), "entrySource": "po_post"}
            for row in list(result.get("entries") or [])
            if not row.get("configOnly")
        ]

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

    async def link_discord_account(
        self,
        guild: GuildIdentity,
        *,
        player_pin: str,
        character: str = "",
        discord_user_id: int | str,
        discord_name: str,
    ) -> list[dict[str, Any]]:
        result = await self.post(
            "lichtbotLinkDiscordAccount",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            playerPin=required(player_pin, "player_pin"),
            character=clean(character),
            discordUserId=required(discord_user_id, "discord_user_id"),
            discordName=clean(discord_name),
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

    async def can_review_p0(
        self,
        guild: GuildIdentity,
        discord_user_id: int | str,
        discord_name: str,
        discord_username: str,
        discord_role_ids: list[str],
        discord_role_names: list[str],
    ) -> bool:
        result = await self.get(
            "lichtbotCanReviewPoPost",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            discordUserId=required(discord_user_id, "discord_user_id"),
            discordName=clean(discord_name),
            discordUsername=clean(discord_username),
            discordRoleIds=json.dumps(discord_role_ids),
            discordRoleNames=json.dumps(discord_role_names),
        )
        return bool(result.get("allowed"))

    async def save_discord_post(
        self,
        guild: GuildIdentity,
        raid_id: str,
        channel_id: int | str,
        message_id: int | str,
        replace_existing: bool = False,
    ) -> None:
        result = await self.post(
            "lichtbotSetRaidDiscordMessage",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            raidId=required(raid_id, "raid_id"),
            discordChannelId=required(channel_id, "discord_channel_id"),
            discordMessageId=required(message_id, "discord_message_id"),
            claimOnly="false" if replace_existing else "true",
        )
        self.require_guild_response(result, guild)
        saved_raid = dict(result.get("raid") or {})
        identity = RaidIdentity.from_api(guild, saved_raid)
        if not replace_existing and result.get("claimed") is not True:
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

    async def review_po_post_entry(
        self,
        guild: GuildIdentity,
        *,
        entry_id: str,
        status: str,
        reviewer_discord_name: str,
    ) -> None:
        result = await self.post(
            "reviewPoPostEntry",
            guild=guild.guild_slug,
            guildId=guild.guild_id,
            guildSlug=guild.guild_slug,
            entryId=required(entry_id, "entry_id"),
            status=required(status, "approval_status"),
            reviewer=clean(reviewer_discord_name) or "Gildenleitung",
        )
        self.require_guild_response(result, guild)


class IdentityRegistry:
    def __init__(self, api: LichtLootApi) -> None:
        self.api = api
        self.by_discord_guild_id: dict[str, GuildIdentity] = {}
        self.by_slug: dict[str, GuildIdentity] = {}

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
        self.by_slug = {guild.guild_slug: guild for guild in guilds}

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
        self._queue_task: asyncio.Task[None] | None = None
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
                        view=CombinedSignupView(
                            self, guild, raid_id, message.id, _raid_signup_enabled(raid)
                        )
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

        @self.tree.command(
            name="anmelder_refresh",
            description="Aktualisiert die neuen kombinierten Raid-/P0-Posts.",
        )
        @app_commands.default_permissions(manage_guild=True)
        async def legacy_refresh_alias(interaction: discord.Interaction) -> None:
            await refresh.callback(interaction, None)

    async def refresh_existing_post(
        self,
        guild: GuildIdentity,
        raid_id: str,
        raid_signup_enabled_override: bool | None = None,
    ) -> DiscordPostIdentity:
        helper = await self.api.get_raid(guild, raid_id)
        raid = dict(helper.get("raid") or {})
        if raid_signup_enabled_override is not None:
            raid["raidHelperEnabled"] = raid_signup_enabled_override
            helper = {**helper, "raid": raid}
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
            view=CombinedSignupView(
                self, guild, raid_id, message_id, _raid_signup_enabled(raid)
            ),
        )
        await self.remove_duplicate_raid_posts(channel, raid_id, message_id)
        return post

    async def create_or_replace_post(
        self,
        guild: GuildIdentity,
        raid_id: str,
        *,
        force_replace: bool,
        channel_id_override: str = "",
        raid_signup_enabled_override: bool | None = None,
        legacy_post_key: str = "",
    ) -> DiscordPostIdentity:
        helper = await self.api.get_raid(guild, raid_id)
        raid = dict(helper.get("raid") or {})
        if raid_signup_enabled_override is not None:
            raid["raidHelperEnabled"] = raid_signup_enabled_override
            helper = {**helper, "raid": raid}
        identity = RaidIdentity.from_api(guild, raid)
        existing_message_id = clean(raid.get("discordMessageId"))
        if existing_message_id and not force_replace:
            return await self.refresh_existing_post(
                guild,
                raid_id,
                raid_signup_enabled_override=raid_signup_enabled_override,
            )
        p0_context, p0_entries = await asyncio.gather(
            self.api.get_p0_context(guild, raid_id),
            self.api.get_p0_entries(guild, raid_id),
        )
        channel_id = required(
            channel_id_override or raid.get("discordChannelId"),
            "raid.discord_channel_id",
        )
        discord_guild = self.get_guild(int(guild.discord_guild_id))
        if discord_guild is None:
            raise RuntimeError("Der konfigurierte Discord-Server ist nicht erreichbar.")
        channel = discord_guild.get_channel(int(channel_id))
        if channel is None:
            channel = await self.fetch_channel(int(channel_id))
        if not hasattr(channel, "send"):
            raise RuntimeError("Der konfigurierte Discord-Kanal kann keine Nachrichten empfangen.")
        message = await channel.send(
            embed=build_combined_embed(guild, helper, p0_context, p0_entries),
            view=CombinedSignupView(
                self, guild, raid_id, "pending", _raid_signup_enabled(raid)
            ),
        )
        try:
            await self.api.save_discord_post(
                guild,
                raid_id,
                message.channel.id,
                message.id,
                replace_existing=force_replace,
            )
            await message.edit(
                view=CombinedSignupView(
                    self, guild, raid_id, message.id, _raid_signup_enabled(raid)
                )
            )
        except Exception:
            await message.delete()
            raise
        if force_replace:
            await self.remove_duplicate_raid_posts(
                channel,
                raid_id,
                message.id,
                legacy_post_key=legacy_post_key,
            )
        return DiscordPostIdentity(
            guild_id=guild.guild_id,
            raid_id=identity.raid_id,
            discord_guild_id=guild.discord_guild_id,
            discord_channel_id=clean(message.channel.id),
            discord_message_id=clean(message.id),
        )

    async def remove_duplicate_raid_posts(
        self,
        channel: discord.abc.Messageable,
        raid_id: str,
        canonical_message_id: int | str,
        legacy_post_key: str = "",
    ) -> None:
        if not hasattr(channel, "history"):
            return
        marker = f"Raid-ID: {raid_id}"
        removed = 0
        try:
            async for candidate in channel.history(limit=100):
                if clean(candidate.id) == clean(canonical_message_id):
                    continue
                if not self.user or candidate.author.id != self.user.id:
                    continue
                footer_texts = [clean(embed.footer.text) for embed in candidate.embeds if embed.footer]
                is_same_v2_post = any(marker in footer for footer in footer_texts)
                legacy_marker = f"Post-ID: {clean(legacy_post_key)}"
                is_legacy_post = bool(legacy_post_key) and any(
                    footer == legacy_marker for footer in footer_texts
                )
                if not is_same_v2_post and not is_legacy_post:
                    continue
                await candidate.delete()
                removed += 1
            if removed:
                print(f"V2 entfernte {removed} doppelten Post für Raid-ID {raid_id}.")
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"V2 konnte doppelte Posts für Raid-ID {raid_id} nicht bereinigen: {error}")

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
                            _raid_signup_enabled(raid),
                        ),
                        message_id=int(message_id),
                    )
        await self.tree.sync()
        self._refresh_task = asyncio.create_task(self.refresh_loop(), name="p0-v2-refresh")
        self._queue_task = asyncio.create_task(self.queue_loop(), name="p0-v2-queue")

    async def queue_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                result = await self.api.get(
                    "lichtbotGetQueueAllGuilds",
                    types=(
                        "raid_announcement,po_post,p0_post_refresh,"
                        "raid_announcement_delete,po_post_delete"
                    ),
                    limit="20",
                )
                for item in list(result.get("items") or []):
                    queue_type = clean(item.get("type")).lower()
                    guild_slug = clean(item.get("guildSlug") or item.get("guild")).lower()
                    guild = self.identities.by_slug.get(guild_slug)
                    payload = dict(item.get("payload") or {})
                    row_number = clean(item.get("rowNumber"))
                    if guild is None:
                        print(f"V2 Queue übersprungen: unbekannte Gilde {guild_slug}.")
                        continue
                    try:
                        if queue_type in {"raid_announcement_delete", "po_post_delete"}:
                            await self.delete_queued_post(guild, payload)
                            await self.api.post(
                                "lichtbotResolveQueue",
                                guild=guild.guild_slug,
                                guildId=guild.guild_id,
                                guildSlug=guild.guild_slug,
                                rowNumber=row_number,
                            )
                            print(
                                f"V2 Queue-Löschung verarbeitet: "
                                f"{guild.guild_id}/{row_number}"
                            )
                            continue
                        raid_id = required(
                            payload.get("raidId") or payload.get("lichtlootRaidId"),
                            "raid_id",
                        )
                        force_new = (
                            queue_type == "po_post"
                            or clean(payload.get("forceNewMessage")).lower() in {"1", "true", "yes", "ja"}
                        )
                        raid_signup_override = _queue_raid_signup_override(payload)
                        await self.create_or_replace_post(
                            guild,
                            raid_id,
                            force_replace=force_new,
                            channel_id_override=clean(
                                payload.get("channelId")
                                or payload.get("discordChannelId")
                                or payload.get("targetChannelId")
                                or payload.get("sourceChannelId")
                            ),
                            raid_signup_enabled_override=raid_signup_override,
                            legacy_post_key=clean(
                                payload.get("postKey")
                                or payload.get("poPostKey")
                                or payload.get("postId")
                            ),
                        )
                        await self.api.post(
                            "lichtbotResolveQueue",
                            guild=guild.guild_slug,
                            guildId=guild.guild_id,
                            guildSlug=guild.guild_slug,
                            rowNumber=row_number,
                        )
                        print(f"V2 Queue verarbeitet: {guild.guild_id}/{raid_id} -> {row_number}")
                    except Exception as error:
                        print(f"V2 Queue fehlgeschlagen ({guild.guild_id}/{row_number}): {error}")
                        terminal_error = any(
                            marker in clean(error).casefold()
                            for marker in (
                                "raid wurde nicht gefunden",
                                "gespeicherte discord-post fehlt",
                                "pflichtfeld fehlt: raid_id",
                            )
                        )
                        if terminal_error:
                            await self.api.post(
                                "lichtbotResolveQueue",
                                guild=guild.guild_slug,
                                guildId=guild.guild_id,
                                guildSlug=guild.guild_slug,
                                rowNumber=row_number,
                            )
                            print(
                                f"V2 Queue verworfen (nicht mehr ausführbar): "
                                f"{guild.guild_id}/{row_number}"
                            )
            except Exception as error:
                print(f"V2 Queue konnte nicht geladen werden: {error}")
            await asyncio.sleep(5)

    async def delete_queued_post(
        self, guild: GuildIdentity, payload: dict[str, Any]
    ) -> None:
        channel_id = clean(
            payload.get("targetChannelId")
            or payload.get("discordChannelId")
            or payload.get("channelId")
            or payload.get("sourceChannelId")
        )
        message_id = clean(payload.get("discordMessageId") or payload.get("messageId"))
        if not channel_id or not message_id:
            # Es existiert kein gespeicherter Discord-Post mehr. Der
            # Löschauftrag ist damit bereits erfüllt und darf beendet werden.
            return
        discord_guild = self.get_guild(int(guild.discord_guild_id))
        if discord_guild is None:
            raise RuntimeError("Der konfigurierte Discord-Server ist nicht erreichbar.")
        channel = discord_guild.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await discord_guild.fetch_channel(int(channel_id))
            except discord.NotFound:
                return
        if not hasattr(channel, "fetch_message"):
            return
        try:
            message = await channel.fetch_message(int(message_id))
        except discord.NotFound:
            return
        if self.user is not None and message.author.id != self.user.id:
            raise RuntimeError("Der gespeicherte Post gehört nicht zu diesem Bot.")
        await message.delete()

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


CLASS_SPECS = {
    "krieger": [("Waffen", "dd"), ("Furor", "dd"), ("Schutz", "tank")],
    "paladin": [("Heilig", "heal"), ("Schutz", "tank"), ("Vergeltung", "dd")],
    "jäger": [("Tierherrschaft", "dd"), ("Treffsicherheit", "dd"), ("Überleben", "dd")],
    "schurke": [("Meucheln", "dd"), ("Kampf", "dd"), ("Täuschung", "dd")],
    "priester": [("Disziplin", "heal"), ("Heilig", "heal"), ("Schatten", "dd")],
    "schamane": [("Elementar", "dd"), ("Verstärkung", "dd"), ("Wiederherstellung", "heal")],
    "magier": [("Arkan", "dd"), ("Feuer", "dd"), ("Frost", "dd")],
    "hexenmeister": [("Gebrechen", "dd"), ("Dämonologie", "dd"), ("Zerstörung", "dd")],
    "druide": [("Gleichgewicht", "dd"), ("Wildheit", "dd"), ("Wiederherstellung", "heal")],
}
CLASS_SPECS.update({
    english: CLASS_SPECS[german] for english, german in {
        "warrior": "krieger", "hunter": "jäger", "rogue": "schurke", "priest": "priester",
        "shaman": "schamane", "mage": "magier", "warlock": "hexenmeister", "druid": "druide",
    }.items()
})


class RaidSignupModal(discord.ui.Modal, title="LichtLoot-Account verknüpfen"):
    player_pin = discord.ui.TextInput(label="SpielerLogin/PIN (nur beim ersten Mal)", required=False, max_length=40)
    character = discord.ui.TextInput(label="Charakter", max_length=40)

    def __init__(
        self,
        bot: "PoBotV2",
        guild: GuildIdentity,
        raid_id: str,
        channel_id: int | str,
        message_id: int | str,
        preset_status: str = "signed",
    ) -> None:
        super().__init__()
        self.bot = bot
        self.guild_identity = guild
        self.raid_id = required(raid_id, "raid_id")
        self.channel_id = required(channel_id, "discord_channel_id")
        self.message_id = required(message_id, "discord_message_id")
        self.preset_status = required(preset_status, "signup_status").lower()

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            characters = await self.bot.api.link_discord_account(
                self.guild_identity,
                player_pin=str(self.player_pin),
                character=str(self.character),
                discord_user_id=interaction.user.id,
                discord_name=interaction.user.display_name,
            )
            await interaction.followup.send(
                "✅ Account verknüpft. Wähle jetzt den gespeicherten Charakter und seine Skillung:",
                view=RaidSignupSelectionView(
                    self.bot, self.guild_identity, self.raid_id, self.channel_id, self.message_id,
                    characters, self.preset_status, interaction.user.id, interaction.user.display_name,
                ), ephemeral=True,
            )
        except Exception as error:
            await interaction.followup.send(f"⚠️ Verknüpfung fehlgeschlagen: {error}", ephemeral=True)


class RaidCharacterSelect(discord.ui.Select):
    def __init__(self, parent: "RaidSignupSelectionView", characters: list[dict[str, Any]]) -> None:
        self.parent_view = parent
        options = [discord.SelectOption(
            label=clean(row.get("name"))[:100], value=str(index),
            description=" · ".join(filter(None, [clean(row.get("className")), clean(row.get("server"))]))[:100] or None,
            emoji=_class_select_emoji(clean(row.get("className"))), default=index == 0,
        ) for index, row in enumerate(characters[:25])]
        super().__init__(placeholder="Gespeicherten LichtLoot-Charakter auswählen", options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.set_character(int(self.values[0]))
        await interaction.response.edit_message(view=self.parent_view)


class RaidSpecSelect(discord.ui.Select):
    def __init__(self, parent: "RaidSignupSelectionView", specs: list[tuple[str, str]]) -> None:
        self.parent_view = parent
        options = [discord.SelectOption(label=name, value=f"{name}|{role}", emoji=_select_emoji(_spec_icon(name)), default=index == 0) for index, (name, role) in enumerate(specs)]
        super().__init__(placeholder="Skillung auswählen", options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.spec_name, self.parent_view.role = self.values[0].split("|", 1)
        await interaction.response.defer()


class RaidSignupSelectionView(discord.ui.View):
    def __init__(self, bot: "PoBotV2", guild: GuildIdentity, raid_id: str, channel_id: int | str,
                 message_id: int | str, characters: list[dict[str, Any]], status: str,
                 discord_user_id: int | str, discord_name: str) -> None:
        super().__init__(timeout=180)
        self.bot, self.guild_identity, self.raid_id = bot, guild, raid_id
        self.channel_id, self.message_id, self.characters = channel_id, message_id, characters
        self.status, self.discord_user_id, self.discord_name = status, discord_user_id, discord_name
        self.add_item(RaidCharacterSelect(self, characters))
        self.set_character(0)

    def set_character(self, index: int) -> None:
        self.character_row = self.characters[index]
        self.character = clean(self.character_row.get("name"))
        class_key = clean(self.character_row.get("className")).casefold()
        specs = CLASS_SPECS.get(class_key, [("DD", "dd")])
        self.spec_name, self.role = specs[0]
        for child in list(self.children):
            if isinstance(child, RaidSpecSelect): self.remove_item(child)
        self.add_item(RaidSpecSelect(self, specs))

    @discord.ui.button(label="Raidanmeldung speichern", style=discord.ButtonStyle.success, row=2)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.api.save_raid_signup(
                self.guild_identity, self.raid_id, player_pin="", character=self.character,
                role=self.role, status=self.status, note=f"Skillung: {self.spec_name}",
                discord_user_id=self.discord_user_id, discord_name=self.discord_name,
                channel_id=self.channel_id, message_id=self.message_id,
            )
            await self.bot.refresh_existing_post(self.guild_identity, self.raid_id)
            await interaction.followup.send("✅ Raidanmeldung gespeichert.", ephemeral=True)
            self.stop()
        except Exception as error:
            await interaction.followup.send(f"⚠️ Raidanmeldung fehlgeschlagen: {error}", ephemeral=True)


class P0SignupModal(discord.ui.Modal, title="SpielerLogin verknüpfen"):
    player_pin = discord.ui.TextInput(label="LichtLoot-/NachtLoot-SpielerLogin", required=True, max_length=40)

    def __init__(
        self,
        bot: "PoBotV2",
        guild: GuildIdentity,
        raid_id: str,
        channel_id: int | str,
        message_id: int | str,
    ) -> None:
        super().__init__()
        self.bot = bot
        self.guild_identity = guild
        self.raid_id = required(raid_id, "raid_id")
        self.channel_id = required(channel_id, "discord_channel_id")
        self.message_id = required(message_id, "discord_message_id")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            characters = await self.bot.api.link_discord_account(
                self.guild_identity,
                player_pin=str(self.player_pin),
                discord_user_id=interaction.user.id,
                discord_name=interaction.user.display_name,
            )
            context = await self.bot.api.get_p0_context(self.guild_identity, self.raid_id)
            items = list(context.get("items") or [])
            if not items:
                raise RuntimeError("Für diesen Raid ist keine P0-Lootliste konfiguriert.")
            await interaction.followup.send(
                "✅ SpielerLogin gefunden. **2. Wähle jetzt deinen Charakter:**",
                view=P0CharacterSelectionView(
                    self.bot, self.guild_identity, self.raid_id, self.channel_id, self.message_id,
                    characters, items, interaction.user.id, interaction.user.display_name,
                ),
                ephemeral=True,
            )
        except Exception as error:
            await interaction.followup.send(f"⚠️ Verknüpfung fehlgeschlagen: {error}", ephemeral=True)


class P0DeleteModal(discord.ui.Modal, title="Eigene P0-Anmeldung löschen"):
    player_pin = discord.ui.TextInput(label="LichtLoot-/NachtLoot-SpielerLogin", required=True, max_length=40)

    def __init__(self, bot: "PoBotV2", guild: GuildIdentity, raid_id: str, default_character: str = "") -> None:
        super().__init__()
        self.bot = bot
        self.guild_identity = guild
        self.raid_id = required(raid_id, "raid_id")
        self.default_character = clean(default_character)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            characters = await self.bot.api.link_discord_account(
                self.guild_identity,
                player_pin=str(self.player_pin),
                discord_user_id=interaction.user.id,
                discord_name=interaction.user.display_name,
            )
            await interaction.followup.send(
                "Wähle den gespeicherten Charakter, dessen P0-Anmeldung gelöscht werden soll:",
                view=P0DeleteCharacterView(
                    self.bot, self.guild_identity, self.raid_id, characters,
                    interaction.user.id, self.default_character,
                ),
                ephemeral=True,
            )
        except Exception as error:
            await interaction.followup.send(f"⚠️ P0-Löschung fehlgeschlagen: {error}", ephemeral=True)


class P0DeleteCharacterView(discord.ui.View):
    def __init__(self, bot: "PoBotV2", guild: GuildIdentity, raid_id: str,
                 characters: list[dict[str, Any]], discord_user_id: int | str,
                 default_character: str = "") -> None:
        super().__init__(timeout=180)
        self.bot, self.guild_identity, self.raid_id = bot, guild, raid_id
        self.characters, self.discord_user_id = characters, discord_user_id
        self.character = clean(default_character) or (clean(characters[0].get("name")) if characters else "")
        self.add_item(P0CharacterSelect(self, characters))

    @discord.ui.button(label="P0-Anmeldung löschen", style=discord.ButtonStyle.danger, row=1)
    async def delete_signup(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.api.delete_p0_signup(
                self.guild_identity, self.raid_id, player_pin="", character=self.character,
                discord_user_id=self.discord_user_id,
            )
            await self.bot.refresh_existing_post(self.guild_identity, self.raid_id)
            await interaction.followup.send("✅ Deine P0-Anmeldung wurde gelöscht.", ephemeral=True)
            self.stop()
        except Exception as error:
            await interaction.followup.send(f"⚠️ P0-Löschung fehlgeschlagen: {error}", ephemeral=True)


class P0CharacterSelect(discord.ui.Select):
    def __init__(self, parent: "P0SignupSelectionView", characters: list[dict[str, Any]]) -> None:
        self.parent_view = parent
        self.character_names: dict[str, str] = {}
        options = []
        for index, row in enumerate(characters[:25]):
            name = clean(row.get("name")) or "Unbekannt"
            option_value = str(index)
            self.character_names[option_value] = name
            options.append(discord.SelectOption(
                label=name[:100],
                description=" · ".join(filter(None, [clean(row.get("className")), clean(row.get("server"))]))[:100] or None,
                value=option_value,
                emoji=_class_select_emoji(clean(row.get("className"))),
                default=name.casefold() == clean(parent.character).casefold(),
            ))
        super().__init__(placeholder="Charakter suchen und auswählen", options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.character = self.character_names[self.values[0]]
        await interaction.response.defer()


class P0ItemSelect(discord.ui.Select):
    def __init__(self, parent: "P0SignupSelectionView", items: list[dict[str, Any]]) -> None:
        self.parent_view = parent
        self.item_names: dict[str, str] = {}
        options = []
        for index, row in enumerate(items[:25]):
            name = clean(row.get("name") or row.get("item") or row.get("itemName"))
            if not name:
                continue
            option_value = str(index)
            self.item_names[option_value] = name
            options.append(
                discord.SelectOption(
                    label=name[:100],
                    value=option_value,
                    description=(clean(row.get("slot") or row.get("category")) or "P0-Item")[:100],
                    emoji=_select_emoji(_item_icon(name)),
                    default=not options,
                )
            )
        super().__init__(placeholder="P0-Item suchen und auswählen", options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.item_name = self.item_names[self.values[0]]
        await interaction.response.defer()


class P0ItemSearchModal(discord.ui.Modal, title="P0-Item suchen"):
    search = discord.ui.TextInput(
        label="Itemname oder Teil des Namens",
        placeholder="z. B. Neltharion",
        min_length=2,
        max_length=100,
    )

    def __init__(self, parent: "P0SignupSelectionView") -> None:
        super().__init__()
        self.parent_view = parent

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        query = clean(str(self.search)).casefold()
        matches = [
            row for row in self.parent_view.all_items
            if query in clean(row.get("name") or row.get("item") or row.get("itemName")).casefold()
        ]
        if not matches:
            await interaction.followup.send(
                "⚠️ Kein gespeichertes LichtLoot-Item passt zu dieser Suche.", ephemeral=True
            )
            return
        result_view = P0SignupSelectionView(
            self.parent_view.bot,
            self.parent_view.guild_identity,
            self.parent_view.raid_id,
            self.parent_view.channel_id,
            self.parent_view.message_id,
            self.parent_view.characters,
            matches[:25],
            self.parent_view.discord_user_id,
            self.parent_view.discord_name,
            selected_character=self.parent_view.character,
            all_items=self.parent_view.all_items,
        )
        suffix = " (erste 25 Treffer)" if len(matches) > 25 else ""
        await interaction.followup.send(
            f"🔎 **4. {len(matches)} Item(s) gefunden{suffix}:** Wähle das richtige Item aus.",
            view=result_view,
            ephemeral=True,
        )


class P0CharacterSelectionView(discord.ui.View):
    def __init__(
        self, bot: "PoBotV2", guild: GuildIdentity, raid_id: str,
        channel_id: int | str, message_id: int | str,
        characters: list[dict[str, Any]], items: list[dict[str, Any]],
        discord_user_id: int | str, discord_name: str,
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_identity = guild
        self.raid_id = raid_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.discord_user_id = discord_user_id
        self.discord_name = discord_name
        self.characters = characters
        self.all_items = items
        self.character = clean(characters[0].get("name")) if characters else ""
        self.add_item(P0CharacterSelect(self, characters))

    @discord.ui.button(label="3. Item suchen", style=discord.ButtonStyle.primary, row=1)
    async def search_item(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(P0ItemSearchModal(self))


class P0SignupSelectionView(discord.ui.View):
    def __init__(
        self,
        bot: "PoBotV2",
        guild: GuildIdentity,
        raid_id: str,
        channel_id: int | str,
        message_id: int | str,
        characters: list[dict[str, Any]],
        items: list[dict[str, Any]],
        discord_user_id: int | str,
        discord_name: str,
        selected_character: str = "",
        all_items: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_identity = guild
        self.raid_id = raid_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.discord_user_id = discord_user_id
        self.discord_name = discord_name
        self.characters = characters
        self.all_items = list(all_items if all_items is not None else items)
        self.character = clean(selected_character) or (clean(characters[0].get("name")) if characters else "")
        first_item = items[0] if items else {}
        self.item_name = clean(first_item.get("name") or first_item.get("item") or first_item.get("itemName"))
        if not clean(selected_character):
            self.add_item(P0CharacterSelect(self, characters))
        self.add_item(P0ItemSelect(self, items))

    @discord.ui.button(label="🔎 Item suchen", style=discord.ButtonStyle.primary, row=2)
    async def search_item(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(P0ItemSearchModal(self))

    @discord.ui.button(label="P0 verbindlich eintragen", style=discord.ButtonStyle.success, row=2)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.api.save_p0_signup(
                self.guild_identity,
                self.raid_id,
                player_pin="",
                character=required(self.character, "character"),
                item=required(self.item_name, "item"),
                discord_user_id=self.discord_user_id,
                discord_name=self.discord_name,
                channel_id=self.channel_id,
                message_id=self.message_id,
            )
            await self.bot.refresh_existing_post(self.guild_identity, self.raid_id)
            await interaction.followup.send("✅ P0-Anmeldung gespeichert.", ephemeral=True)
            self.stop()
        except Exception as error:
            await interaction.followup.send(f"⚠️ P0-Anmeldung fehlgeschlagen: {error}", ephemeral=True)


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
        self.entries_by_value: dict[str, dict[str, Any]] = {}
        options = []
        for index, row in enumerate(entries[:25]):
            entry_id = clean(row.get("id") or row.get("signupId"))
            if not entry_id:
                continue
            source = "po_post" if clean(row.get("entrySource")) == "po_post" else "signup"
            value = f"{source}:{entry_id}"
            self.entries_by_value[value] = row
            options.append(
                discord.SelectOption(
                    label=(clean(row.get("player") or row.get("char")) or "Unbekannt")[:100],
                    description=(clean(row.get("item") or row.get("itemName")) or "P0-Item")[:100],
                    value=value[:100],
                    emoji="✅" if status == "approved" else "❌",
                )
            )
        super().__init__(
            placeholder="P0-Eintrag auswählen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            selected_value = self.values[0]
            selected = self.entries_by_value[selected_value]
            entry_id = required(selected.get("id") or selected.get("signupId"), "entry_id")
            if clean(selected.get("entrySource")) == "po_post":
                await self.bot.api.review_po_post_entry(
                    self.guild_identity,
                    entry_id=entry_id,
                    status=self.review_status,
                    reviewer_discord_name=interaction.user.display_name,
                )
            else:
                await self.bot.api.review_p0_signup(
                    self.guild_identity,
                    self.raid_id,
                    signup_id=entry_id,
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


class P0PointsSearchModal(discord.ui.Modal, title="P0+-Punkte suchen"):
    search = discord.ui.TextInput(
        label="Charakter oder Item",
        placeholder="z. B. Ariee oder Brust",
        min_length=2,
        max_length=100,
    )

    def __init__(self, bot: "PoBotV2", guild: GuildIdentity) -> None:
        super().__init__()
        self.bot = bot
        self.guild_identity = guild

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            query = clean(self.search.value)
            query_key = _emoji_key(query)
            all_points = await self.bot.api.get_p0_points(self.guild_identity)
            matches = [
                row for row in all_points
                if query_key in _emoji_key(row.get("player"))
                or query_key in _emoji_key(row.get("item"))
            ]
            if not matches:
                await interaction.followup.send(
                    f'🔎 Keine P0+-Punkte für „{query}“ gefunden.',
                    ephemeral=True,
                )
                return

            lines: list[str] = []
            hidden = 0
            current_length = len(query) + 40
            for row in matches:
                line = (
                    f"{_item_icon(clean(row.get('item')))} **{clean(row.get('item'))}** · "
                    f"**{float(row.get('points') or row.get('count') or 0):g} P0+** · "
                    f"{clean(row.get('player'))}"
                )
                if len(lines) >= 30 or current_length + len(line) + 1 > 1700:
                    hidden += 1
                    continue
                lines.append(line)
                current_length += len(line) + 1

            result = f'🏆 **P0+-Suche: „{query}“**\n' + "\n".join(lines)
            if hidden:
                result += f"\n… und {hidden} weitere Treffer. Bitte genauer suchen."
            await interaction.followup.send(result, ephemeral=True)
        except Exception as error:
            await interaction.followup.send(f"⚠️ P0+-Suche fehlgeschlagen: {error}", ephemeral=True)


class CombinedSignupView(discord.ui.View):
    def __init__(
        self,
        bot: "PoBotV2",
        guild: GuildIdentity,
        raid_id: str,
        message_id: int | str,
        raid_signup_enabled: bool = True,
    ) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_identity = guild
        self.raid_id = required(raid_id, "raid_id")
        self.message_id = required(message_id, "discord_message_id")
        if not raid_signup_enabled:
            for item in list(self.children):
                if clean(getattr(item, "custom_id", "")).startswith("p0v2:raid_"):
                    self.remove_item(item)

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
        if not linked:
            await interaction.response.send_modal(
                RaidSignupModal(
                    self.bot, self.guild_identity, self.raid_id, interaction.channel_id,
                    interaction.message.id, preset_status=status,
                )
            )
            return
        await interaction.response.send_message(
            "Wähle einen fest in LichtLoot gespeicherten Charakter und seine Skillung:",
            view=RaidSignupSelectionView(
                self.bot, self.guild_identity, self.raid_id, interaction.channel_id,
                interaction.message.id, linked, status, interaction.user.id,
                interaction.user.display_name,
            ),
            ephemeral=True,
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
        # Discord erwartet die erste Antwort innerhalb von drei Sekunden.
        # Das Modal wird deshalb sofort geöffnet; Verknüpfung, Charaktere und
        # Lootliste werden erst beim Absenden des Modals über die API geladen.
        await interaction.response.send_modal(
            P0SignupModal(
                self.bot,
                self.guild_identity,
                self.raid_id,
                interaction.channel_id,
                interaction.message.id,
            )
        )

    @discord.ui.button(label="P0-Eintrag löschen", style=discord.ButtonStyle.danger, custom_id="p0v2:p0_delete", row=2)
    async def p0_delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            P0DeleteModal(
                self.bot,
                self.guild_identity,
                self.raid_id,
            )
        )

    async def open_p0_review(self, interaction: discord.Interaction, status: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            allowed = await self.bot.api.can_review_p0(
                self.guild_identity,
                interaction.user.id,
                interaction.user.display_name,
                interaction.user.name,
                [clean(role.id) for role in getattr(interaction.user, "roles", [])],
                [clean(role.name) for role in getattr(interaction.user, "roles", [])],
            )
            if not allowed:
                await interaction.followup.send(
                    "⚠️ Deine Rolle ist auf der Gildenleitungsseite nicht für die P0-Prüfung freigegeben.",
                    ephemeral=True,
                )
                return
            context, legacy_entries = await asyncio.gather(
                self.bot.api.get_p0_context(self.guild_identity, self.raid_id),
                self.bot.api.get_p0_entries(self.guild_identity, self.raid_id),
            )
            combined = [
                {**dict(row), "entrySource": "signup"}
                for row in list(context.get("signups") or [])
            ] + list(legacy_entries)
            entries = []
            seen: set[tuple[str, str]] = set()
            for row in combined:
                entry_id = clean(row.get("id") or row.get("signupId"))
                source = clean(row.get("entrySource")) or "signup"
                key = (source, entry_id)
                if not entry_id or key in seen or clean(row.get("approvalStatus")).lower() == status:
                    continue
                seen.add(key)
                entries.append(row)
            if not entries:
                await interaction.followup.send("ℹ️ Kein passender P0-Eintrag vorhanden.", ephemeral=True)
                return
            await interaction.followup.send(
                "P0-Eintrag auswählen:",
                view=P0ReviewView(P0ReviewSelect(self.bot, self.guild_identity, self.raid_id, entries, status)),
                ephemeral=True,
            )
        except Exception as error:
            await interaction.followup.send(f"⚠️ P0-Prüfung fehlgeschlagen: {error}", ephemeral=True)

    @discord.ui.button(label="P0 freigeben", style=discord.ButtonStyle.success, custom_id="p0v2:p0_approve", row=2)
    async def p0_approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.open_p0_review(interaction, "approved")

    @discord.ui.button(label="P0 ablehnen", style=discord.ButtonStyle.danger, custom_id="p0v2:p0_reject", row=2)
    async def p0_reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.open_p0_review(interaction, "rejected")

    @discord.ui.button(label="🏆 P0+-Punkte suchen", style=discord.ButtonStyle.secondary, custom_id="p0v2:p0_points", row=2)
    async def p0_points(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(P0PointsSearchModal(self.bot, self.guild_identity))


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


def _queue_raid_signup_override(payload: dict[str, Any]) -> bool | None:
    """Liest den ausdrücklich von der API gesetzten Discord-Postmodus.

    Alte Queue-Einträge besitzen diese Angabe nicht und verwenden weiterhin
    den am Raid gespeicherten Wert. Neue Aufträge verlieren den gewählten
    Modus dadurch auch dann nicht, wenn parallel ein Raid gleichen Typs und
    Termins im jeweils anderen Modus existiert.
    """
    mode = clean(payload.get("postMode") or payload.get("discordPostMode")).lower()
    if mode in {"p0_only", "po_only", "p0-only", "po-only"}:
        return False
    if mode in {"raid_p0", "raid_po", "combined", "raid-p0", "raid-po"}:
        return True
    if "raidSignupEnabled" in payload:
        return _truthy(payload.get("raidSignupEnabled"))
    return None


def _raid_signup_enabled(raid: dict[str, Any]) -> bool:
    """Übernimmt exakt den Baustein „Raidanmelder im Discord erstellen“."""
    value = raid.get("raidHelperEnabled")
    if value is None:
        value = raid.get("raidhelperEnabled")
    if value is None:
        return True
    return value is True or clean(value).lower() in {"1", "true", "yes", "ja", "on"}


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
    spec = _spec_for_row(row).lower()
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
    status_sets = {
        "bank": {"bench", "bank"},
        "late": {"late", "spät", "spaet"},
        "tentative": {"tentative", "vorläufig", "vorlaeufig"},
        "absent": {"absent", "abwesend"},
    }
    status_counts = {
        key: sum(clean(row.get("status")).lower() in statuses for row in rows)
        for key, statuses in status_sets.items()
    }
    embed.add_field(
        name="Anmeldestatus",
        value=(
            f"👥 **Fest angemeldet {len(active)}** · "
            f"🪑 Bank **{status_counts['bank']}** · "
            f"🕒 Spät **{status_counts['late']}** · "
            f"⚖️ Vorläufig **{status_counts['tentative']}** · "
            f"🚫 Abwesend **{status_counts['absent']}**"
        ),
        inline=False,
    )
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
            spec = _spec_for_row(row) or clean(row.get("role")) or "Flex"
            lines.append(f"{_spec_icon(spec)} `{position}` {player}{_prio_marker(row, p0_players)}")
        embed.add_field(name=f"{icon} __{label} ({len(lines)})__", value="\n".join(lines)[:1024], inline=True)
    status_groups = (
        ("🪑 Bank", status_sets["bank"]), ("🕒 Spät", status_sets["late"]),
        ("⚖️ Vorläufig", status_sets["tentative"]),
        ("🚫 Abwesenheit", status_sets["absent"]),
    )
    for label, statuses in status_groups:
        status_rows = [row for row in rows if clean(row.get("status")).lower() in statuses]
        if status_rows:
            embed.add_field(
                name=f"{label} ({len(status_rows)})",
                value="\n".join(f"• {clean(row.get('player') or row.get('char')) or 'Unbekannt'}" for row in status_rows)[:1024],
                inline=True,
            )


def _add_p0_fields(
    embed: discord.Embed,
    rows: list[dict[str, Any]],
    *,
    separator: bool = True,
) -> None:
    if separator:
        embed.add_field(
            name="\u200b",
            value="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            inline=False,
        )
    if not rows:
        embed.add_field(name="📋 P0-Anmeldungen (0)", value="Noch keine P0-Anmeldungen.", inline=False)
        return
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = clean(row.get("item") or row.get("itemName")) or "Unbekanntes Item"
        grouped.setdefault(item, []).append(row)
    embed.add_field(
        name=f"📋 P0-Anmeldungen ({len(rows)})",
        value=(
            f"{_emoji('beuteorange', '🟠')} **eingetragen** · "
            f"{_emoji('Beutegrun', '🟢')} **freigegeben**"
        ),
        inline=False,
    )
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


def _fit_embed_to_discord_limit(embed: discord.Embed, maximum: int = 5900) -> discord.Embed:
    """Behält alle Bereiche, kürzt aber lange Feldlisten unter Discord 6000 Zeichen."""
    while len(embed) > maximum:
        candidates = [
            (index, field)
            for index, field in enumerate(embed.fields)
            if len(field.value) > 140
        ]
        if candidates:
            index, field = max(candidates, key=lambda pair: len(pair[1].value))
            excess = len(embed) - maximum
            keep = max(120, len(field.value) - excess - 40)
            value = field.value[:keep].rstrip() + "\n… weitere Einträge in der Webansicht"
            embed.set_field_at(index, name=field.name, value=value[:1024], inline=field.inline)
            continue
        if embed.description and len(embed.description) > 200:
            excess = len(embed) - maximum
            keep = max(180, len(embed.description) - excess - 10)
            embed.description = embed.description[:keep].rstrip() + "…"
            continue
        break
    return embed


def build_combined_embed(
    guild: GuildIdentity,
    helper: dict[str, Any],
    p0_context: dict[str, Any],
    p0_entries: list[dict[str, Any]] | None = None,
) -> discord.Embed:
    raid = dict(helper.get("raid") or {})
    raid_signup_enabled = _raid_signup_enabled(raid)
    identity = RaidIdentity.from_api(guild, raid)
    raid_title = (clean(raid.get("raidName") or raid.get("raid")) or "Raid").upper()
    title = raid_title if raid_signup_enabled else f"{raid_title} P0-ANMELDER"
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
    if raid_signup_enabled and slot_parts:
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
    if raid_signup_enabled:
        _add_roster_fields(embed, raid_rows, p0_rows)
    _add_p0_fields(embed, p0_rows, separator=raid_signup_enabled)
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
    return _fit_embed_to_discord_limit(embed)


API_URL = clean(os.getenv("PO_BOT_API_URL") or os.getenv("LICHTLOOT_API_URL") or API_DEFAULT)
QUEUE_TOKEN = clean(os.getenv("LICHTBOT_QUEUE_TOKEN"))
BOT_TOKEN = clean(os.getenv("PO_BOT_TOKEN"))


def build_client() -> PoBotV2:
    return PoBotV2(LichtLootApi(API_URL, QUEUE_TOKEN))


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise SystemExit("PO_BOT_TOKEN fehlt.")
    build_client().run(BOT_TOKEN)
