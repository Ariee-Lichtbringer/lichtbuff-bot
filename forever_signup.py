"""Forever Discord signup: dedicated API/database, no Era identity or PIN reuse."""
import asyncio
import hashlib
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, urlencode
import discord
from discord import app_commands

ROLES = {'tank': '🛡️ Tank', 'heal': '💚 Heiler', 'dd': '⚔️ Schaden (offen)', 'melee':'⚔️ Nahkampf', 'ranged':'🏹 Fernkampf'}
STATES = {'signed': 'Zugesagt', 'bench': '🪑 Ersatzbank', 'late': '🕒 Später', 'tentative': 'Vielleicht', 'absent': 'Abgesagt'}
CLASSES = {'warrior':'Krieger','paladin':'Paladin','hunter':'Jäger','rogue':'Schurke','priest':'Priester','shaman':'Schamane','mage':'Magier','warlock':'Hexenmeister','druid':'Druide'}

class ApiError(RuntimeError):
    def __init__(self, message, status=500):
        super().__init__(message)
        self.status = status

class ForeverApi:
    def __init__(self, api):
        u = urlsplit(api.base_url)
        self.url = urlunsplit((u.scheme, u.netloc, '/api/forever/bot', '', ''))
        self.token = api.queue_token
    def request(self, action, **values):
        req = urllib.request.Request(self.url, data=json.dumps({'action':action, **values}).encode(), headers={'Content-Type':'application/json','X-Forever-Bot-Token':self.token}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            try: message = json.load(error).get('error', 'Forever-Anfrage fehlgeschlagen.')
            except Exception: message = 'Forever-Anfrage fehlgeschlagen.'
            raise ApiError(message, error.code) from None
        except (OSError, ValueError):
            raise ApiError('Forever ist gerade nicht erreichbar. Bitte erneut versuchen.') from None
    async def call(self, action, **values):
        return await asyncio.to_thread(self.request, action, **values)

def raid_url(post):
    return 'https://lichtloot.de/forever-raids.html?' + urlencode({'guild':post['guild']['slug'],'raid':post['raid']['id'],'loot':post['raid']['kind']}) + '#prioseiten'

def marker(post):
    return 'GuildLoot Forever · ' + post['raid']['id']

def build_embed(post, emoji=lambda c: ''):
    raid = post['raid']
    starts = datetime.fromisoformat(raid['starts_at'].replace('Z','+00:00'))
    from zoneinfo import ZoneInfo
    local = starts.astimezone(ZoneInfo('Europe/Berlin'))
    signed = [s for s in raid['signups'] if s['status']=='signed']
    status = {'open':'Raidanmeldung ist geöffnet.','closed':'Raidanmeldung ist geschlossen.','cancelled':'Dieser Raid wurde abgesagt.','completed':'Dieser Raid ist abgeschlossen.','running':'Dieser Raid läuft gerade.','archived':'Dieser Raid ist archiviert.'}[raid['status']]
    embed = discord.Embed(title=raid['title'].upper()[:256], url=raid_url(post), color=0x7C3AED,
        description=discord.utils.escape_markdown(raid.get('description') or status)[:1200])
    embed.set_footer(text=marker(post))
    image = {'hyjal':'forever/raids/hyjal-v1.jpg','barrow':'forever/raids/barrow-v1.jpg','onyxia':'forever/raids/onyxia-v1.jpg'}.get(raid['kind'],'forever/adventure.jpg')
    embed.set_image(url=raid.get('image_url') or 'https://lichtloot.de/images/'+image)
    embed.add_field(name='Raidlead',value='Gildenleitung',inline=True)
    embed.add_field(name='Termin',value=f"**__{local:%Y-%m-%d · %H:%M} Uhr__**",inline=True)
    embed.add_field(name='Gilde · Forever',value=discord.utils.escape_markdown(post['guild']['name'])[:200],inline=True)
    web = raid_url(post).split('#')[0]+'#termine'
    embed.add_field(name='Links',value=f'🌐 [Webansicht]({web}) · 🎒 [Lootseite]({raid_url(post)})',inline=False)
    counts = {state:sum(s['status']==state for s in raid['signups']) for state in STATES}
    embed.add_field(name='Anmeldestatus',value=f"👥 **{len(signed)} / {raid['size']} fest**\n🪑 Bank **{counts['bench']}** · 🕒 Spät **{counts['late']}** · ⚖️ Vorläufig **{counts['tentative']}** · 🚫 Abwesend **{counts['absent']}**",inline=True)
    role_counts = {role:sum(s['role']==role for s in signed) for role in ROLES}
    embed.add_field(name='Rollenverteilung',value=f"{emoji('tank') or '🛡️'} **Tanks {role_counts['tank']}** · {emoji('dd') or '⚔️'} **Nahkampf {role_counts['melee']}** · {emoji('ranged') or '🏹'} **Fernkampf {role_counts['ranged']}** · **Offen {role_counts['dd']}** · {emoji('heal') or '✨'} **Heiler {role_counts['heal']}**",inline=True)
    embed.add_field(name='\u200b',value='━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━',inline=False)
    embed.add_field(name='Kader',value='Klassen und aktuelle Belegung' if signed else 'Noch keine festen Anmeldungen.',inline=False)
    numbered = list(enumerate(raid['signups'],1))
    groups = []
    for cls in ['warrior','druid','paladin','rogue','hunter','priest','mage','warlock','shaman']:
        rows = [(n,s) for n,s in numbered if s['status']=='signed' and s['className']==cls]
        if rows: groups.append((f"{emoji(cls)} __{CLASSES[cls]} ({len(rows)})__",rows,True))
    for state,label in [('bench','🪑 Bank'),('late','🕒 Spät'),('tentative','⚖️ Vorläufig'),('absent','🚫 Abwesenheit')]:
        rows = [(n,s) for n,s in numbered if s['status']==state]
        if rows: groups.append((f'{label} ({len(rows)})',rows,False))
    for heading, rows, class_group in groups:
        chunks,chunk = [],''
        for n,s in rows:
            icon = (emoji(s['role']) or emoji(s['className'])) if class_group else ''
            line = f"{icon} `{n}` {discord.utils.escape_markdown(s['name'])}\n"
            if len(chunk)+len(line)>950:
                chunks.append(chunk);chunk=''
            chunk+=line
        if chunk: chunks.append(chunk)
        for index,chunk in enumerate(chunks):
            if len(embed)+len(heading)+len(chunk)>5500 or len(embed.fields)>=23:
                embed.add_field(name='Weitere Anmeldungen',value=f'Die vollständige Teilnehmerliste findest du in der [Webansicht]({web}).',inline=False)
                return embed
            embed.add_field(name=heading+(' · Fortsetzung' if index else ''),value=chunk,inline=True)
    return embed

async def reply_error(interaction, error):
    text = str(error)[:1000] if isinstance(error,ApiError) else 'Die Aktion konnte nicht gespeichert werden. Bitte erneut versuchen.'
    if interaction.response.is_done(): await interaction.followup.send(text,ephemeral=True)
    else: await interaction.response.send_message(text,ephemeral=True)

class PrivateView(discord.ui.View):
    def __init__(self, user_id, **kw):
        super().__init__(timeout=600, **kw);self.user_id=user_id
    async def interaction_check(self, interaction):
        if interaction.user.id!=self.user_id:
            await interaction.response.send_message('Diese Auswahl gehört einem anderen Spieler.',ephemeral=True);return False
        return True
    async def on_error(self, interaction, error, item): await reply_error(interaction,error)

class SaveModal(discord.ui.Modal, title='Forever-Anmeldung speichern'):
    def __init__(self, choice):
        super().__init__();self.choice=choice
        self.note=discord.ui.TextInput(label='Hinweis (optional)',required=False,max_length=240,default=choice.note)
        self.add_item(self.note)
    async def on_submit(self, interaction):
        if interaction.user.id!=self.choice.user_id:
            await interaction.response.send_message('Diese Auswahl gehört einem anderen Spieler.',ephemeral=True);return
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            c=self.choice
            result=await c.worker.api.call('signup',**c.identity,characterId=c.character_id,role=c.role,status=c.status,note=str(self.note))
            await interaction.followup.send('✅ Auf der Ersatzbank gespeichert.' if result.get('status')=='bench' else '✅ Deine Forever-Anmeldung wurde gespeichert.',ephemeral=True)
            c.worker.wake.set()
        except Exception as error: await reply_error(interaction,error)

class ChoiceView(PrivateView):
    def __init__(self, worker, identity, result, user_id):
        super().__init__(user_id);self.worker=worker;self.identity=identity
        characters=result['characters'];mine=next((s for s in result['raid']['signups'] if s['mine']),{})
        char=next((c for c in characters if c['id']==mine.get('characterId')),characters[0])
        self.character_id=char['id'];self.role=mine.get('role',char['role']);self.status=mine.get('status','signed');self.note=mine.get('note','')
        for name,label,options,current in [
            ('character_id','Dein Forever-Charakter',[(c['id'],c['name']+' · '+CLASSES.get(c['class_name'],c['class_name'])) for c in characters],self.character_id),
            ('role','Deine Rolle',list(ROLES.items()),self.role),('status','Deine Teilnahme',list(STATES.items()),self.status)]:
            select_options=[]
            for value,text in options:
                icon=None
                if name=='character_id':
                    character=next(c for c in characters if c['id']==value)
                    icon=worker.emoji(character['class_name']) or '👤'
                elif name=='role':
                    icon=worker.emoji(value) or {'tank':'🛡️','heal':'✨','dd':'⚔️','melee':'⚔️','ranged':'🏹'}[value]
                    text={'tank':'Tank','heal':'Heiler','dd':'Schaden (offen)','melee':'Nahkampf','ranged':'Fernkampf'}[value]
                select_options.append(discord.SelectOption(label=text[:100],value=value,default=value==current,emoji=icon))
            select=discord.ui.Select(placeholder=label,options=select_options)
            async def changed(interaction,field=name,control=select):
                setattr(self,field,control.values[0])
                for opt in control.options: opt.default=opt.value==control.values[0]
                await interaction.response.edit_message(view=self)
            select.callback=changed;self.add_item(select)
        save=discord.ui.Button(label='Anmeldung speichern',style=discord.ButtonStyle.success)
        async def submit(interaction): await interaction.response.send_modal(SaveModal(self))
        save.callback=submit;self.add_item(save)

async def send_choices(worker, interaction, identity, result):
    raid=result.get('raid')
    if not raid or raid['status']!='open' or datetime.fromisoformat(raid['starts_at'].replace('Z','+00:00'))<=datetime.now(timezone.utc):
        await interaction.followup.send('Die Anmeldung für diesen Termin ist geschlossen.',ephemeral=True);return
    if not result['characters']:
        await interaction.followup.send('Lege zuerst deinen Forever-Charakter auf lichtloot.de an.',ephemeral=True);return
    await interaction.followup.send('Wähle deinen Charakter, deine Rolle und Teilnahme:',view=ChoiceView(worker,identity,result,interaction.user.id),ephemeral=True)

class ConnectModal(discord.ui.Modal, title='Forever-SpielerLogin verbinden'):
    def __init__(self, worker, identity):
        super().__init__();self.worker=worker;self.identity=identity
        self.pin=discord.ui.TextInput(label='Dein Forever-SpielerLogin-Code',min_length=4,max_length=120)
        self.add_item(self.pin)
    async def on_submit(self, interaction):
        if str(interaction.user.id)!=self.identity['discordUserId']:
            await interaction.response.send_message('Diese Verbindung gehört einem anderen Spieler.',ephemeral=True);return
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            result=await self.worker.api.call('connect',**self.identity,playerPin=str(self.pin))
            await send_choices(self.worker,interaction,self.identity,result)
        except Exception as error: await reply_error(interaction,error)

class ConnectView(PrivateView):
    def __init__(self, worker, identity, user_id):
        super().__init__(user_id)
        b=discord.ui.Button(label='Forever-SpielerLogin verbinden',style=discord.ButtonStyle.primary)
        async def connect(interaction): await interaction.response.send_modal(ConnectModal(worker,identity))
        b.callback=connect;self.add_item(b)
        if identity.get("guild")=="lichtbringer-forever":
            self.add_item(discord.ui.Button(label="LichtLoot / Nachtloot übernehmen",url="https://lichtloot.de/forever-import.html"))

class SignupView(discord.ui.View):
    def __init__(self, worker, post):
        super().__init__(timeout=None);self.worker=worker;self.post=post
        self.add_item(discord.ui.Button(label='Loot & Raid auf der Webseite',url=raid_url(post)))
        if post['raid']['status']!='open' or datetime.fromisoformat(post['raid']['starts_at'].replace('Z','+00:00'))<=datetime.now(timezone.utc):
            for item in self.children:
                if getattr(item,'custom_id',None): item.disabled=True
    def identity(self, interaction):
        return {'guild':self.post['guild']['slug'],'raidId':self.post['raid']['id'],'messageId':str(interaction.message.id),'channelId':str(interaction.channel_id),'discordGuildId':str(interaction.guild_id),'discordUserId':str(interaction.user.id)}
    @discord.ui.button(label='Klasse / Charakter anmelden',style=discord.ButtonStyle.primary,custom_id='forever:signup')
    async def signup(self, interaction, button):
        await interaction.response.defer(ephemeral=True,thinking=True);identity=self.identity(interaction)
        try:
            result=await self.worker.api.call('context',**identity)
            await send_choices(self.worker,interaction,identity,result)
        except ApiError as error:
            if error.status==401: await interaction.followup.send('Verbinde deinen separaten Forever-SpielerLogin. Dein Code wird nicht im Kanal angezeigt.',view=ConnectView(self.worker,identity,interaction.user.id),ephemeral=True)
            else: await reply_error(interaction,error)
    @discord.ui.button(label='SpielerLogin trennen',style=discord.ButtonStyle.secondary,custom_id='forever:unlink')
    async def unlink(self, interaction, button):
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            await self.worker.api.call('unlink',**self.identity(interaction))
            await interaction.followup.send('Deine Discord-Verbindung ist getrennt. Bereits gespeicherte Raidanmeldungen bleiben bestehen.',ephemeral=True)
        except Exception as error: await reply_error(interaction,error)
    async def on_error(self, interaction, error, item): await reply_error(interaction,error)

class ConfigureModal(discord.ui.Modal, title='Forever-Gilde mit Discord verbinden'):
    def __init__(self, worker, slug):
        super().__init__();self.worker=worker;self.slug=slug
        self.code=discord.ui.TextInput(label='Forever-Leitungscode',max_length=120);self.add_item(self.code)
    async def on_submit(self, interaction):
        if not interaction.permissions.manage_guild:
            await interaction.response.send_message('Du brauchst die Berechtigung „Server verwalten“.',ephemeral=True);return
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            result=await self.worker.api.call('configure',guild=self.slug,masterCode=str(self.code),channelId=str(interaction.channel_id),discordGuildId=str(interaction.guild_id))
            await interaction.followup.send('✅ '+result['guild']+' ist mit diesem Kanal verbunden. Öffne einen Forever-Termin auf der Webseite und wähle „Discord-Anmelder veröffentlichen“.',ephemeral=True)
        except Exception as error: await reply_error(interaction,error)

class ForeverWorker:
    def __init__(self, bot, emoji=lambda c: ''):
        self.bot=bot;self.api=ForeverApi(bot.api);self.emoji=emoji;self.wake=asyncio.Event();self.registered=set();self.task=None
        @bot.tree.command(name='forever_verbinden',description='Verbindet diesen Kanal mit eurer separaten Forever-Gilde.')
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.guild_only()
        async def configure(interaction:discord.Interaction,gilde:str):
            if not interaction.permissions.manage_guild:
                await interaction.response.send_message('Du brauchst „Server verwalten“.',ephemeral=True);return
            await interaction.response.send_modal(ConfigureModal(self,gilde.strip()))
    def start(self): self.task=asyncio.create_task(self.loop(),name='forever-discord')
    async def deliver(self, post):
        view=SignupView(self,post)
        if post.get('messageId') and post['messageId'] not in self.registered:
            self.bot.add_view(view,message_id=int(post['messageId']));self.registered.add(post['messageId'])
        embed=build_embed(post,self.emoji)
        digest=hashlib.sha256(json.dumps({'embed':embed.to_dict(),'view':view.to_components()},sort_keys=True).encode()).hexdigest()
        if post.get('hash')==digest and post.get('messageId'): return
        ids={'guild':post['guild']['slug'],'raidId':post['raid']['id']}
        lease=(await self.api.call('claim',**ids)).get('leaseToken')
        if not lease:return
        try:
            channel=self.bot.get_channel(int(post['channelId'])) or await self.bot.fetch_channel(int(post['channelId']))
            if str(getattr(getattr(channel,'guild',None),'id',None))!=post['discordGuildId']: raise RuntimeError('Discord-Kanal gehört zu einem anderen Server.')
            message=None
            if post.get('messageId'):
                # Missing saved messages are not silently recreated; request publication explicitly.
                message=await channel.fetch_message(int(post['messageId']))
            else:
                async for candidate in channel.history(limit=100):
                    if candidate.author.id==self.bot.user.id and any(e.footer.text==marker(post) for e in candidate.embeds):
                        message=candidate;break
            if message: await message.edit(embed=embed,view=view,allowed_mentions=discord.AllowedMentions.none())
            else: message=await channel.send(embed=embed,view=view,allowed_mentions=discord.AllowedMentions.none())
            await self.api.call('ack',**ids,leaseToken=lease,messageId=str(message.id),hash=digest)
            self.bot.add_view(view,message_id=message.id);self.registered.add(str(message.id))
        except Exception as error:
            reason='Discord-Nachricht fehlt. Bitte erneut auf der Webseite veröffentlichen.' if isinstance(error,discord.NotFound) and post.get('messageId') else str(error) if isinstance(error,(discord.HTTPException,RuntimeError)) else 'Discord-Veröffentlichung fehlgeschlagen.'
            await self.api.call('failed',**ids,leaseToken=lease,error=reason[:300])
    async def sync_channels(self):
        targets=(await self.api.call('channelTargets')).get('targets',[])
        for target in targets:
            guild=self.bot.get_guild(int(target['discord_guild_id']))
            channels=[]
            if guild and guild.me:
                for channel in guild.text_channels:
                    p=channel.permissions_for(guild.me)
                    if p.view_channel and p.send_messages and p.embed_links and p.read_message_history:
                        channels.append({'id':str(channel.id),'name':channel.name,'category':channel.category.name if channel.category else '', 'position':channel.position})
                channels.sort(key=lambda c:(c['category'],c['position'],c['name']))
            await self.api.call('channelSync',guildId=target['guild_id'],discordGuildId=target['discord_guild_id'],channels=channels)

    async def diagnostics(self):
        response=await self.api.call('diagnosticsPoll')
        for job in response.get('jobs',[]):
            result={'bot':True,'server':False,'channel':False,'permissions':False,'testSent':False}
            try:
                guild=self.bot.get_guild(int(job['discord_guild_id']))
                if not guild: raise RuntimeError('Der PO Bot ist nicht mehr auf dem verbundenen Server. Bitte erneut einladen.')
                result['server']=True
                channel=self.bot.get_channel(int(job['channel_id'])) or await self.bot.fetch_channel(int(job['channel_id']))
                if str(getattr(getattr(channel,'guild',None),'id',None))!=job['discord_guild_id']: raise RuntimeError('Der Kanal gehört nicht zum verbundenen Server.')
                result['channel']=True
                permissions=channel.permissions_for(guild.me)
                missing=[name for name,ok in [('Kanal ansehen',permissions.view_channel),('Nachrichten senden',permissions.send_messages),('Links einbetten',permissions.embed_links),('Nachrichtenverlauf lesen',permissions.read_message_history)] if not ok]
                if missing: raise RuntimeError('Fehlende Kanalrechte: '+', '.join(missing))
                result['permissions']=True
                if job['kind']=='test':
                    marker='guildloot-forever-test:'+job['id']
                    message=None
                    async for candidate in channel.history(limit=100):
                        if candidate.author.id==self.bot.user.id and any(e.footer.text==marker for e in candidate.embeds):message=candidate;break
                    if not message:
                        embed=discord.Embed(title='GuildLoot · Forever-Verbindung erfolgreich',description='Diese Testnachricht wurde von eurer Gildenleitung angefordert. Der PO Bot kann in diesem Kanal Nachrichten und Raidanmelder veröffentlichen.',color=0xe6be63)
                        embed.set_footer(text=marker)
                        message=await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())
                    result['testSent']=True;result['messageId']=str(message.id)
            except Exception as error:
                result['error']=str(error)[:300] if isinstance(error,RuntimeError) else 'Discord-Kanal nicht erreichbar. Bitte Bot-Einladung und Kanalrechte prüfen.'
            await self.api.call('diagnosticsAck',id=job['id'],leaseToken=job['lease_token'],result=result)

    async def loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                try: await self.sync_channels()
                except Exception: print('Forever: Kanalliste derzeit nicht erreichbar.',flush=True)
                try: await self.diagnostics()
                except Exception: print('Forever: Verbindungsprüfung derzeit nicht erreichbar.',flush=True)
                cursor=None
                while True:
                    result=await self.api.call('poll',cursor=cursor)
                    for post in result['posts']:
                        try: await self.deliver(post)
                        except Exception: print('Forever: Ein Discord-Post konnte nicht aktualisiert werden.',flush=True)
                    cursor=result.get('cursor')
                    if not cursor: break
            except Exception: print('Forever: Datenabgleich derzeit nicht erreichbar.',flush=True)
            try: await asyncio.wait_for(self.wake.wait(),timeout=30)
            except asyncio.TimeoutError: pass
            self.wake.clear()
