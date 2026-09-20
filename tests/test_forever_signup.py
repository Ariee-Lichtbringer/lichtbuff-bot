import unittest
import copy
import json
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
import forever_signup as f

POST={'guild':{'slug':'forever','name':'Lichtbringer'},'channelId':'111111111111111111','discordGuildId':'222222222222222222','messageId':None,'hash':'','raid':{'id':'9ddfe6c0-ce6c-4d76-a7a0-090f359c32f3','kind':'hyjal','title':'TEST · Hyjal','starts_at':'2030-09-20T18:00:00Z','size':20,'tanks':2,'heals':4,'status':'open','description':'Test','signups':[]}}
class ForeverTest(unittest.IsolatedAsyncioTestCase):
    async def test_embed_limits_and_persistence(self):
        p=copy.deepcopy(POST);p['raid']['description']='A'*1500
        p['raid']['signups']=[{'name':'Sehrlangercharaktername Mitlangerfamilienbezeichnung'+str(i),'className':'priest','role':'heal','status':'signed' if i<40 else 'bench'} for i in range(200)]
        embed=f.build_embed(p,lambda c:'<:priest:123456789012345678>')
        self.assertLessEqual(len(embed),6000);self.assertLessEqual(len(embed.fields),25)
        for field in embed.fields:self.assertLessEqual(len(field.value),1024)
        view=f.SignupView(None,p);self.assertTrue(view.is_persistent());self.assertEqual(view.children[0].custom_id,'forever:signup')
        p['raid']['status']='cancelled';view=f.SignupView(None,p)
        self.assertTrue(all(c.disabled for c in view.children if getattr(c,'custom_id',None)))
        self.assertIn('guild=forever',f.raid_url(p))
    async def test_recover_after_ack_failure_without_duplicate_send(self):
        post=copy.deepcopy(POST);messages=[];counts={'send':0,'edit':0,'ack':0}
        class Message:
            id=333333333333333333
            author=SimpleNamespace(id=444444444444444444)
            def __init__(self,embed):self.embeds=[embed]
            async def edit(self,**kw):counts['edit']+=1;self.embeds=[kw['embed']]
        class Channel:
            guild=SimpleNamespace(id=int(post['discordGuildId']))
            async def history(self,limit):
                for m in messages:yield m
            async def send(self,**kw):
                counts['send']+=1;self.assert_mentions=kw['allowed_mentions'];m=Message(kw['embed']);messages.append(m);return m
        channel=Channel()
        class Api:
            async def call(self,action,**kw):
                if action=='claim':return {'leaseToken':'lease'}
                if action=='ack':
                    counts['ack']+=1
                    if counts['ack']==1:raise RuntimeError('temporary')
                return {'success':True}
        worker=object.__new__(f.ForeverWorker);worker.api=Api();worker.emoji=lambda c:'';worker.registered=set();worker.bot=SimpleNamespace(get_channel=lambda _:channel,add_view=lambda *a,**k:None,user=SimpleNamespace(id=444444444444444444))
        await worker.deliver(post);await worker.deliver(post)
        self.assertEqual(counts['send'],1);self.assertEqual(counts['edit'],1);self.assertEqual(counts['ack'],2)
        self.assertFalse(channel.assert_mentions.everyone)
    async def test_unchanged_posts_do_not_write(self):
        post=copy.deepcopy(POST);post['messageId']='333333333333333333'
        worker=object.__new__(f.ForeverWorker);worker.api=SimpleNamespace(call=AsyncMock());worker.emoji=lambda c:'';worker.registered=set();worker.bot=SimpleNamespace(add_view=lambda *a,**k:None)
        view=f.SignupView(worker,post);embed=f.build_embed(post,worker.emoji)
        post['hash']=hashlib.sha256(json.dumps({'embed':embed.to_dict(),'view':view.to_components()},sort_keys=True).encode()).hexdigest()
        await worker.deliver(post);worker.api.call.assert_not_called()
    async def test_wrong_channel_guild_never_sends(self):
        post=copy.deepcopy(POST);send=AsyncMock();call=AsyncMock(side_effect=[{'leaseToken':'lease'},{'success':True}]);worker=object.__new__(f.ForeverWorker);worker.api=SimpleNamespace(call=call);worker.emoji=lambda c:'';worker.registered=set();worker.bot=SimpleNamespace(get_channel=lambda _:SimpleNamespace(guild=SimpleNamespace(id=999),send=send),add_view=lambda *a,**k:None)
        await worker.deliver(post);send.assert_not_called();self.assertEqual(call.call_args.args[0],'failed')
if __name__=='__main__':unittest.main()
