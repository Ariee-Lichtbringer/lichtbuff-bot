"""Configured notifications with per-recipient delivery receipts and retry recovery."""
from datetime import datetime, timezone
from urllib.parse import urlencode
NOTICE_TYPES = {"p0plus_points_notice", "p0plus_resolution_notice", "player_login_approval_notice", "po_approval_notice", "po_rejection_notice", "po_release_request_notice", "raid_calendar", "raid_signup_notice", "raid_status_staff_notice"}

def render_notice(kind, p, guild):
    if kind == "p0plus_points_notice":
        raid = " · ".join(str(p[k]) for k in ("raidName", "raidDate", "raidTime") if p.get(k))
        number = lambda n: format(float(n or 0), "g").replace(".", ",")
        who = str(p.get("player") or "Spieler")
        item = str(p.get("item") or "Item")
        if p.get("event") == "item_received_clear":
            return (f"Hallo {who},\n\ndu hast im Raid {raid} das Item **{item}** erhalten.\n"
                    f"Deine P0+-Punkte für dieses Item wurden zurückgesetzt ({number(p.get('oldPoints'))} → 0).\n"
                    f"P0+-Stand für {item}: **{number(p.get('newPoints'))} Punkte**.")[:3900]
        if p.get("event") != "raid_transfer":
            raise ValueError("Unbekannter P0+-Vorgang")
        return (f"Hallo {who},\n\nfür den Raid {raid} wurden dir **{number(p.get('points'))} P0+-Punkte** übertragen.\n"
                f"Dein P0+-Stand für **{item}** ist jetzt **{number(p.get('newPoints'))} Punkte**.\n"
                "Stand direkt nach dieser Übertragung.")[:3900]
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

async def deliver_calendar(bot, guild, payload, queue_id, discord):
    channel_id=str(payload.get("channelId") or "")
    if not channel_id.isdigit():raise ValueError("Kalenderkanal fehlt")
    channel=bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
    if str(getattr(getattr(channel,"guild",None),"id",""))!=guild.discord_guild_id:
        raise ValueError("Ziel gehört zu einer anderen Discord-Gilde")
    prepared=await bot.api.post("lichtbotPrepareCalendarPost",guild=guild.guild_slug,guildId=guild.guild_id,channelId=channel_id)
    if not prepared.get("claimed"):raise RuntimeError("Kalender wird bereits verarbeitet; später erneut versuchen")
    token=prepared["leaseToken"]
    marker=f"GuildLoot-Kalender: {guild.guild_id}"
    try:
        message=None
        if prepared.get("messageId"):
            message=await channel.fetch_message(int(prepared["messageId"]))
            if message.author.id!=bot.user.id:raise ValueError("Gespeicherter Kalenderpost gehört nicht zu diesem Bot")
        else:
            # One-time recovery includes the complete history and keeps the
            # original (oldest) post, regardless of how far it has scrolled.
            async for candidate in channel.history(limit=None,oldest_first=True):
                if candidate.author.id==bot.user.id and any(getattr(e.footer,"text",None)==marker for e in candidate.embeds):
                    message=candidate;break
        embed=discord.Embed(description=render_notice("raid_calendar",payload,guild));embed.set_footer(text=marker)
        if message is None:message=await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())
        else:await message.edit(embed=embed,allowed_mentions=discord.AllowedMentions.none())
        mid=str(message.id)
        await bot.api.post("lichtbotCompleteCalendarPost",guild=guild.guild_slug,guildId=guild.guild_id,channelId=channel_id,leaseToken=token,messageId=mid)
        await bot.api.post("lichtbotRecordNoticeDelivery",guild=guild.guild_slug,guildId=guild.guild_id,rowNumber=queue_id,targetId=channel_id,messageId=mid)
        return mid
    finally:
        try:await bot.api.post("lichtbotReleaseCalendarPost",guild=guild.guild_slug,guildId=guild.guild_id,channelId=channel_id,leaseToken=token)
        except Exception:pass  # The persisted lease expires; never delete the post.

async def deliver_queue_notice(bot, guild, kind, payload, queue_id, discord):
    server=bot.get_guild(int(guild.discord_guild_id))
    if server is None:raise RuntimeError("Discord-Server nicht erreichbar")
    if kind=="raid_calendar":return await deliver_calendar(bot,guild,payload,queue_id,discord)
    recipients={}
    uid=str(payload.get("discordUserId") or payload.get("userId") or "")
    if kind == "p0plus_points_notice" and not uid.isdigit():
        raise ValueError("Kein verknüpftes Discord-Konto für diese persönliche P0+-Nachricht")
    if uid.isdigit():
        recipients[uid]=None  # Resolve membership inside this recipient's try block.
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
            if roles.intersection(str(r.id) for r in member.roles) or names.intersection(member_names):recipients[str(member.id)]=member
    if not recipients:raise ValueError("Kein konfigurierter Empfänger gefunden")
    receipts=payload.get("deliveryReceipts") or {};last="";failures=[];retryable=False
    marker=f"GuildLoot-Auftrag: {queue_id}"
    for uid,member in recipients.items():
        if receipts.get(uid):last=str(receipts[uid]);continue
        try:
            member=member or server.get_member(int(uid)) or await server.fetch_member(int(uid))
            channel=await member.create_dm()
            # Older receipts were keyed by DM-channel ID.
            if receipts.get(str(channel.id)):last=str(receipts[str(channel.id)]);continue
            message=None
            async for candidate in channel.history(limit=None):
                if candidate.author.id==bot.user.id and any(getattr(e.footer,"text",None)==marker for e in candidate.embeds):message=candidate;break
            if message is None:
                embed=discord.Embed(description=render_notice(kind,payload,guild));embed.set_footer(text=marker)
                message=await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())
            last=str(message.id)
            await bot.api.post("lichtbotRecordNoticeDelivery",guild=guild.guild_slug,guildId=guild.guild_id,rowNumber=queue_id,targetId=uid,messageId=last)
        except Exception as error:
            failures.append(f"{uid}: {type(error).__name__}: {error}")
            if type(error).__name__ not in {"Forbidden","NotFound","ValueError"}:retryable=True
            try:await bot.api.post("lichtbotRecordNoticeDelivery",guild=guild.guild_slug,guildId=guild.guild_id,rowNumber=queue_id,targetId=uid,error=str(error)[:500] or type(error).__name__)
            except Exception:retryable=True
            # A blocked DM never prevents delivery to the remaining recipients.
    if failures:
        message="Benachrichtigung teilweise fehlgeschlagen: "+"; ".join(failures)
        if retryable:raise RuntimeError(message)
        raise ValueError(message)
    return last
