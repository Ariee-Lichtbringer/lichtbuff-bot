import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
import discord
from forever_signup import ForeverWorker

class Diagnostics(unittest.IsolatedAsyncioTestCase):
    async def test_test_message_recovery_and_permissions(self):
        messages=[]
        class Channel:
            guild=SimpleNamespace(id=123)
            def permissions_for(self,member):return SimpleNamespace(view_channel=True,send_messages=True,embed_links=True,read_message_history=True)
            async def history(self,limit):
                for message in messages:yield message
            async def send(self,**kwargs):
                assert not kwargs['allowed_mentions'].everyone
                message=SimpleNamespace(id=789,author=SimpleNamespace(id=456),embeds=[kwargs['embed']]);messages.append(message);return message
        channel=Channel();job={'id':'job','lease_token':'lease','discord_guild_id':'123','channel_id':'321','kind':'test'}
        worker=object.__new__(ForeverWorker);worker.bot=SimpleNamespace(user=SimpleNamespace(id=456),get_guild=lambda _:SimpleNamespace(me=object()),get_channel=lambda _:channel)
        results=[]
        async def call(action,**body):
            if action=='diagnosticsPoll':return {'jobs':[job]}
            results.append(body['result']);return {'success':True}
        worker.api=SimpleNamespace(call=call)
        await worker.diagnostics();await worker.diagnostics();self.assertEqual(len(messages),1);self.assertTrue(results[-1]['testSent'])
        job['kind']='check';await worker.diagnostics();self.assertEqual(len(messages),1);self.assertFalse(results[-1]['testSent'])
        channel.guild=SimpleNamespace(id=999);await worker.diagnostics();self.assertFalse(results[-1]['channel']);self.assertEqual(len(messages),1)
        channel.guild=SimpleNamespace(id=123);channel.permissions_for=lambda _:SimpleNamespace(view_channel=True,send_messages=False,embed_links=True,read_message_history=True)
        job['kind']='test';await worker.diagnostics();self.assertIn('Nachrichten senden',results[-1]['error']);self.assertEqual(len(messages),1)

if __name__=='__main__':unittest.main()
