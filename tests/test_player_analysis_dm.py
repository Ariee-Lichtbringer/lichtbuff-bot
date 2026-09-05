import unittest
from types import SimpleNamespace
from player_analysis_dm import deliver_player_analysis

class Forbidden(Exception): pass
class NotFound(Exception): pass
DISCORD=SimpleNamespace(Forbidden=Forbidden,NotFound=NotFound,utils=SimpleNamespace(escape_markdown=lambda x:x),AllowedMentions=SimpleNamespace(none=lambda:None))
class FakeChannel:
    def __init__(self): self.messages=[];self.blocked=False
    async def history(self,limit):
        for msg in reversed(self.messages):yield msg
    async def send(self,content,**kwargs):
        if self.blocked:raise Forbidden()
        msg=SimpleNamespace(id=456,author=SimpleNamespace(id=111),content=content)
        self.messages.append(msg);return msg
class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.channel=FakeChannel();self.calls=[];self.fail_ack=False
        self.guild=SimpleNamespace(guild_id='guild-id',guild_slug='nachtloot')
        self.payload=dict(guildId='guild-id',guildSlug='nachtloot',reportToken='token',character='Sintha',server='Everlook',raid='Naxxramas',count=5,fromDate='2026-08-07',toDate='2026-09-04')
        self.state=dict(queueId='queue-id',status='queued',discordUserId='123456789123456789',reportUrl='https://lichtloot.de/spieler-analyse.html?guild=nachtloot&report=token')
        async def get(action,**params):return self.state
        async def post(action,**params):
            self.calls.append((action,params))
            if self.fail_ack:self.fail_ack=False;raise RuntimeError('lost acknowledgement')
            if action=='lichtbotCompletePlayerAnalysisDm':self.state['status']=params['status']
        self.bot=SimpleNamespace(api=SimpleNamespace(get=get,post=post),user=SimpleNamespace(id=111),get_user=lambda id:SimpleNamespace(dm_channel=self.channel))
    async def run_delivery(self):await deliver_player_analysis(self.bot,self.guild,self.payload,'queue-id',DISCORD,lambda text:text)
    async def test_link_only_and_idempotent(self):
        await self.run_delivery();await self.run_delivery()
        self.assertEqual(len(self.channel.messages),1)
        self.assertIn('[Ausführlichen Bericht öffnen](https://lichtloot.de/spieler-analyse.html?',self.channel.messages[0].content)
        self.assertEqual(self.state['status'],'sent')
    async def test_lost_ack_does_not_send_twice(self):
        self.fail_ack=True
        with self.assertRaises(RuntimeError):await self.run_delivery()
        await self.run_delivery();self.assertEqual(len(self.channel.messages),1)
    async def test_blocked_dm_is_failed(self):
        self.channel.blocked=True;await self.run_delivery();self.assertEqual(self.state['status'],'failed');self.assertEqual(len(self.channel.messages),0)
    async def test_wrong_guild_is_rejected(self):
        self.payload['guildId']='other'
        with self.assertRaises(ValueError):await self.run_delivery()
        self.assertEqual(len(self.channel.messages),0)
    async def test_untrusted_url_is_rejected(self):
        self.state['reportUrl']='https://example.com/report'
        with self.assertRaises(ValueError):await self.run_delivery()
    async def test_stale_queue_is_not_sent(self):
        self.state['queueId']='new-queue';await self.run_delivery();self.assertEqual(len(self.channel.messages),0)
if __name__=='__main__':unittest.main()
