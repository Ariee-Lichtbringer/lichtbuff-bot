import unittest
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
from queue_notices import deliver_queue_notice,render_notice,NOTICE_TYPES
class NoticeTests(unittest.IsolatedAsyncioTestCase):
    async def test_receipt_failure_does_not_repeat_delivery(self):
        class Embed:
            def __init__(self,**kw):self.footer=None
            def set_footer(self,text):self.footer=N(text=text)
        messages=[]
        async def history(**kw):
            for m in messages:yield m
        async def send(**kw):
            m=N(id=123456789012345678,author=N(id=7),embeds=[kw['embed']],edit=AsyncMock());messages.append(m);return m
        channel=N(id=223456789012345678,guild=N(id=9),history=history,send=AsyncMock(side_effect=send))
        post=AsyncMock(side_effect=[RuntimeError('lost receipt'),{'success':True}]);bot=N(user=N(id=7),get_guild=lambda _:N(),get_channel=lambda _:channel,api=N(post=post))
        discord=N(Embed=Embed,AllowedMentions=N(none=lambda:None));guild=N(discord_guild_id='9',guild_slug='g',guild_id='internal');p={'channelId':str(channel.id),'events':[]}
        with self.assertRaises(RuntimeError):await deliver_queue_notice(bot,guild,'raid_calendar',p,'q',discord)
        await deliver_queue_notice(bot,guild,'raid_calendar',p,'q',discord)
        self.assertEqual(channel.send.await_count,1)
        with self.assertRaises(ValueError):await deliver_queue_notice(bot,N(discord_guild_id='10',guild_slug='g'),'raid_calendar',p,'other',discord)
    def test_each_type_renders_without_account_secrets(self):
        for kind in NOTICE_TYPES:
            body=render_notice(kind,{'playerPin':'SECRET','character':'Tester'},N(guild_slug='g'))
            self.assertNotIn('SECRET',body);self.assertTrue(body)
