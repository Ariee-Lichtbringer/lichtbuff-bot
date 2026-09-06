import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from dkp_notice import send_dkp_notice
class DkpNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_then_retry_and_guild_guard(self):
        class Embed:
            def __init__(self,**kwargs):self.footer=None
            def set_footer(self,text):self.footer=SimpleNamespace(text=text)
        messages=[]
        async def history(**kwargs):
            for m in messages:yield m
        async def send(**kwargs):
            message=SimpleNamespace(id=50,author=SimpleNamespace(id=7),embeds=[kwargs['embed']]);messages.append(message);return message
        channel=SimpleNamespace(guild=SimpleNamespace(id=9),history=history,send=AsyncMock(side_effect=send))
        bot=SimpleNamespace(user=SimpleNamespace(id=7),get_channel=lambda _:channel)
        discord=SimpleNamespace(Embed=Embed,AllowedMentions=SimpleNamespace(none=lambda:None))
        guild=SimpleNamespace(discord_guild_id='9');payload=dict(channelId='123',description='Test DKP')
        self.assertEqual(await send_dkp_notice(bot,guild,payload,'request',discord),'50')
        self.assertEqual(await send_dkp_notice(bot,guild,payload,'request',discord),'50')
        self.assertEqual(channel.send.await_count,1)
        with self.assertRaises(ValueError):await send_dkp_notice(bot,SimpleNamespace(discord_guild_id='10'),payload,'other',discord)
