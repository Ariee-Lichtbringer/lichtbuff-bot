import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from raid_workbook_post import message_data, post_raid_workbook, raid_destination, raid_thread_name

PAYLOAD = dict(analysisId='raid-id',guildSlug='nachtloot',guildName='NachtLoot',raidName='Naxxramas',channelId='123456789012345678',discordGuildId='234567890123456789',sheetUrl='https://docs.google.com/spreadsheets/d/test_sheet_id/edit',googleSheetId='test_sheet_id',analysisUrl='https://lichtloot.de/raid-analyse.html?id=raid-id&guild=nachtloot',reportUrl='https://vanilla.warcraftlogs.com/reports/AbCdEfGh12345678',startedAt='2026-09-04T18:00:00Z')
class Embed:
    def __init__(self,**kw):self.fields=[];self.__dict__.update(kw)
    def add_field(self,**kw):self.fields.append(kw)
    def set_footer(self,**kw):self.footer=SimpleNamespace(**kw)
class View:
    def __init__(self,**kw):self.children=[]
    def add_item(self,item):self.children.append(item)
D=SimpleNamespace(ChannelType=SimpleNamespace(public_thread=11),Embed=Embed,utils=SimpleNamespace(escape_markdown=lambda s:s),ui=SimpleNamespace(View=View,Button=lambda **kw:kw),ButtonStyle=SimpleNamespace(link='link'),AllowedMentions=SimpleNamespace(none=lambda:'none'))
class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_post_and_retry(self):
        history=[]
        async def items(**kw):
            for p in history:yield p
        channel=SimpleNamespace(id=123456789012345678,parent_id=999,guild=SimpleNamespace(id=int(PAYLOAD['discordGuildId'])),history=items,send=AsyncMock(return_value=SimpleNamespace(id=321)))
        client=SimpleNamespace(get_channel=lambda i:channel,user=SimpleNamespace(id=1))
        registry={'nachtloot':{'discordGuildId':PAYLOAD['discordGuildId']}}
        await post_raid_workbook(client,PAYLOAD,registry,D)
        kw=channel.send.call_args.kwargs
        self.assertIn('kompakte Übersicht',kw['embed'].description)
        self.assertIn('[NachtLoot]',kw['embed'].description)
        self.assertEqual(len(kw['view'].children),3)
        self.assertEqual(kw['allowed_mentions'],'none')
        history.append(SimpleNamespace(author=client.user,embeds=[kw['embed']],edit=AsyncMock()))
        await post_raid_workbook(client,PAYLOAD,registry,D)
        channel.send.assert_awaited_once();history[0].edit.assert_awaited_once()
        channel.guild.id=999
        with self.assertRaises(ValueError):await post_raid_workbook(client,PAYLOAD,registry,D)
        channel.send.assert_awaited_once()
    def test_guild_and_dates(self):
        d=message_data(PAYLOAD);self.assertEqual(d['time'],'20:00 CEST');self.assertEqual(d['date'],'04.09.2026')
        with self.assertRaises(ValueError):message_data(dict(PAYLOAD,guildSlug='lichtloot'))
        with self.assertRaises(ValueError):message_data(dict(PAYLOAD,reportUrl='https://warcraftlogs.com.evil.example/reports/x'))
        with self.assertRaises(ValueError):message_data(dict(PAYLOAD,startedAt='2026-09-04T18:00:00'))
if __name__=='__main__':unittest.main()

class ThreadTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuse_archived_thread(self):
        t=SimpleNamespace(id=21,parent_id=10,name='NAXX',archived=True,locked=False,edit=AsyncMock())
        async def archived(**kw):yield t
        c=SimpleNamespace(id=10,guild=SimpleNamespace(active_threads=AsyncMock(return_value=[])),archived_threads=archived,create_thread=AsyncMock())
        self.assertIs(await raid_destination(c,PAYLOAD,D),t)
        t.edit.assert_awaited_once();c.create_thread.assert_not_called()
    async def test_create_missing_thread(self):
        async def archived(**kw):
            if False:yield None
        t=SimpleNamespace(id=22,archived=False,locked=False)
        c=SimpleNamespace(id=10,guild=SimpleNamespace(active_threads=AsyncMock(return_value=[])),archived_threads=archived,create_thread=AsyncMock(return_value=t))
        await raid_destination(c,dict(PAYLOAD,raidName="Zul'Gurub"),D)
        self.assertEqual(c.create_thread.call_args.kwargs['name'],'ZG')
    def test_no_xlsx_link(self):
        with self.assertRaises(ValueError):message_data(dict(PAYLOAD,sheetUrl='https://api.example/workbook.xlsx'))
        self.assertEqual(raid_thread_name("Temple of Ahn'Qiraj"),'AQ40')

class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_own_matching_previous_post_is_deleted(self):
        from raid_workbook_post import remove_previous_post
        payload=dict(PAYLOAD,previousMessageId='345678901234567890',previousChannelId=PAYLOAD['channelId'])
        data=message_data(payload)
        previous=SimpleNamespace(author=SimpleNamespace(id=1),embeds=[SimpleNamespace(footer=SimpleNamespace(text=data['footer']))],delete=AsyncMock())
        channel=SimpleNamespace(guild=SimpleNamespace(id=int(PAYLOAD['discordGuildId'])),fetch_message=AsyncMock(return_value=previous))
        client=SimpleNamespace(get_channel=lambda i:channel,user=SimpleNamespace(id=1))
        await remove_previous_post(client,payload,data,SimpleNamespace(id=456789012345678901))
        previous.delete.assert_awaited_once()
        previous.author.id=2
        with self.assertRaises(ValueError):await remove_previous_post(client,payload,data,SimpleNamespace(id=456789012345678901))
        previous.delete.assert_awaited_once()
