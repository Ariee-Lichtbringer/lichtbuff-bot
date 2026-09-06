"""Configured notifications with per-recipient delivery receipts and retry recovery."""
from datetime import datetime, timezone
from urllib.parse import urlencode
NOTICE_TYPES = {"p0plus_resolution_notice", "player_login_approval_notice", "po_approval_notice", "po_rejection_notice", "po_release_request_notice", "raid_calendar", "raid_signup_notice", "raid_status_staff_notice"}

def render_notice(kind, p, guild):
    titles={"po_approval_notice":"P0-Anmeldung freigegeben","po_rejection_notice":"P0-Anmeldung abgelehnt","p0plus_resolution_notice":"P0+-Meldung bearbeitet","player_login_approval_notice":"SpielerLogin wartet auf Freigabe","po_release_request_notice":"Neue P0-Freigabeanfrage","raid_signup_notice":"Raidanmeldung geändert","raid_status_staff_notice":"Raidstatus geändert","raid_calendar":"Raidkalender"}
    lines=[titles[kind],guild.guild_slug]
    for key in ("character","player","server","raidName","raid","raidDate","raidTime","item","requestType","reason","message"):
        if p.get(key):lines.append(str(p[key]))
    if "correctedPoints" in p:lines.append(f"Korrigierter Punktestand: {p['correctedPoints']}")
    link="https://lichtloot.de/gildenleitung.html?"+urlencode({"guild":guild.guild_slug})
    if kind in {"player_login_approval_notice","po_release_request_notice","raid_status_staff_notice"}:lines.append(link)
    if kind=="raid_calendar":
        today=datetime.now(timezone.utc).date().isoformat()
        lines += [f"{e.get('date','')} {e.get('time','')} · {e.get('name','Raid')}" for e in p.get("events",[]) if str(e.get("date",""))>=today]
    template=str(p.get("messageTemplate") or "")
    if template:
        values={**p,"gilde":guild.guild_slug,"charakter":p.get("character") or p.get("player",""),"klasse":p.get("className",""),"link":link}
        for k,v in values.items():template=template.replace("{"+k+"}",str(v))
        return template[:3900]
    return "\n".join(lines)[:3900]

async def deliver_queue_notice(bot, guild, kind, payload, queue_id, discord):
    server=bot.get_guild(int(guild.discord_guild_id))
    if server is None:raise RuntimeError("Discord-Server nicht erreichbar")
    channels={}
    if kind=="raid_calendar":
        channel=bot.get_channel(int(payload.get("channelId") or 0)) or await bot.fetch_channel(int(payload.get("channelId") or 0))
        if str(getattr(getattr(channel,"guild",None),"id",""))!=guild.discord_guild_id:raise ValueError("Ziel gehört zu einer anderen Discord-Gilde")
        channels[str(channel.id)]=channel
    else:
        uid=str(payload.get("discordUserId") or payload.get("userId") or "")
        if uid.isdigit():
            # Membership is checked before delivering guild-specific contents.
            member=server.get_member(int(uid)) or await server.fetch_member(int(uid))
            channel=await member.create_dm();channels[str(channel.id)]=channel
        else:
            targets=payload.get("targets") or []
            roles={str(x) for x in payload.get("notificationRoleIds",[])}|{str(t.get("value")) for t in targets if t.get("type")=="role"}
            names={str(x).strip().casefold() for x in payload.get("notificationNames",[])}|{str(t.get("value","")).strip().casefold() for t in targets if t.get("type")=="name"}
            if not roles and not names:raise ValueError("Keine Benachrichtigungsempfänger konfiguriert")
            members=list(server.members)
            if not getattr(server,"chunked",False):members=[m async for m in server.fetch_members(limit=None)]
            for member in members:
                if member.bot:continue
                member_names={str(getattr(member,k,"")).strip().casefold() for k in ("name","display_name","global_name")}
                if roles.intersection(str(r.id) for r in member.roles) or names.intersection(member_names):
                    channel=await member.create_dm();channels[str(channel.id)]=channel
    if not channels:raise ValueError("Kein konfigurierter Empfänger gefunden")
    receipts=payload.get("deliveryReceipts") or {};last=""
    marker=f"GuildLoot-Kalender: {guild.guild_id}" if kind=="raid_calendar" else f"GuildLoot-Auftrag: {queue_id}"
    for key,channel in channels.items():
        if receipts.get(key):last=str(receipts[key]);continue
        message=None
        async for candidate in channel.history(limit=100):
            if candidate.author.id==bot.user.id and any(getattr(e.footer,"text",None)==marker for e in candidate.embeds):message=candidate;break
        embed=discord.Embed(description=render_notice(kind,payload,guild));embed.set_footer(text=marker)
        if message is None:
            message=await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())
        elif kind=="raid_calendar":
            await message.edit(embed=embed,allowed_mentions=discord.AllowedMentions.none())
        last=str(message.id)
        await bot.api.post("lichtbotRecordNoticeDelivery",guild=guild.guild_slug,guildId=guild.guild_id,rowNumber=queue_id,targetId=key,messageId=last)
    return last
