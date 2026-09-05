import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from raid_workbook_post import message_data, post_raid_workbook

PAYLOAD = dict(analysisId='raid-id',guildSlug='nachtloot',guildName='NachtLoot',raidName='Naxxramas',channelId='123456789012345678',discordGuildId='234567890123456789',sheetUrl='https://api.example/api/guilds/nachtloot/log-analyses/raid-id/workbook.xlsx',analysisUrl='https://lichtloot.de/raid-analyse.html?id=raid-id&guild=nachtloot',reportUrl='https://vanilla.warcraftlogs.com/reports/AbCdEfGh12345678',startedAt='2026-09-04T18:00:00Z')
class Embed:
    def __init__(self,**kw):self.fields=[];self.__dict__.update(kw)
    def add_field(self,**kw):self.fields.append(kw)
    def set_footer(self,**kw):self.footer=SimpleNamespace(**kw)
class View:
    def __init__(self,**kw):self.children=[]
    def add_item(self,item):self.children.append(item)
D=SimpleNamespace(Embed=Embed,utils=SimpleNamespace(escape_markdown=lambda s:s),ui=SimpleNamespace(View=View,Button=lambda **kw:kw),ButtonStyle=SimpleNamespace(link='link'),AllowedMentions=SimpleNamespace(none=lambda:'none'))
class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_post_and_retry(self):
        history=[]
        async def items(**kw):
            for p in history:yield p
        channel=SimpleNamespace(guild=SimpleNamespace(id=int(PAYLOAD['discordGuildId'])),history=items,send=AsyncMock())
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
