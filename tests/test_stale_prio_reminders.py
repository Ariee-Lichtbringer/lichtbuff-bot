import ast
import unittest
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pytz

ROOT=Path(__file__).resolve().parents[1]

class ReminderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree=ast.parse((ROOT/'po_bot.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PoBotV2')
        nodes=[next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='reminder_delivery_skip_reason'),next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='send_missing_prio_reminder')]
        class Missing(Exception):pass
        self.scope=dict(datetime=datetime,timezone=timezone,pytz=pytz,Any=Any,GuildIdentity=Any,
            clean=lambda v:str(v or '').strip(),required=lambda v,key:v,
            _guild_site_name=lambda g:'Nachtloot',_raid_loot_url=lambda g,p:'',copyright_text=lambda v:v,
            discord=types.SimpleNamespace(NotFound=Missing,Forbidden=Missing,utils=types.SimpleNamespace(escape_markdown=lambda s:s),AllowedMentions=types.SimpleNamespace(none=lambda:None)))
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'reminder-test','exec'),self.scope)
        self.sent=[];self.edits=[];self.missing=False;test=self
        class Message:
            id=456
            async def edit(self,**kwargs):test.edits.append(kwargs)
        class Channel:
            async def fetch_message(self,id):
                if test.missing:raise Missing()
                return Message()
            async def send(self,content,**kwargs):test.sent.append(content);return Message()
        self.channel=Channel();self.lookups=[]
        def get_guild(id):self.lookups.append(id);return types.SimpleNamespace(get_channel=lambda id:self.channel)
        self.bot=types.SimpleNamespace(get_guild=get_guild);self.guild=types.SimpleNamespace(discord_guild_id='123')
        self.payload=dict(raidId='raid',raidDate='2099-09-11',raidTime='22:00',channelId='123',prioPin='V4F',missingCharacters=['Player'],raidName='Naxxramas')
    async def send(self,payload):return await self.scope['send_missing_prio_reminder'](self.bot,self.guild,payload)
    async def test_old_or_invalid_never_touches_discord(self):
        for date in ['2020-09-04','', 'not-a-date']:
            result=await self.send({**self.payload,'raidDate':date})
            self.assertIn('skipped',result)
        self.assertFalse(self.lookups);self.assertFalse(self.sent)
    async def test_live_send_and_refresh(self):
        await self.send(self.payload);self.assertEqual(len(self.sent),1);self.assertIn('2099-09-11',self.sent[0])
        await self.send({**self.payload,'source':'prio_saved_refresh','messageId':'456'})
        self.assertEqual(len(self.edits),1);self.assertEqual(len(self.sent),1)
    async def test_deleted_refresh_is_not_reposted(self):
        self.missing=True
        result=await self.send({**self.payload,'source':'prio_saved_refresh','messageId':'456'})
        self.assertEqual(result['skipped'],'original_message_unavailable');self.assertFalse(self.sent)
        result=await self.send({**self.payload,'source':'prio_saved_refresh'})
        self.assertEqual(result['skipped'],'refresh_message_missing');self.assertFalse(self.sent)
    def test_berlin_summer_and_winter_cutoff(self):
        reason=self.scope['reminder_delivery_skip_reason']
        for date,utc_hour in [('2026-07-01',20),('2026-12-01',21)]:
            year,month,day=map(int,date.split('-'));p={**self.payload,'raidDate':date}
            self.assertEqual(reason(p,datetime(year,month,day,utc_hour-1,59,tzinfo=timezone.utc)),'')
            self.assertEqual(reason(p,datetime(year,month,day,utc_hour,0,tzinfo=timezone.utc)),'raid_already_started')
if __name__=='__main__':unittest.main()
