import ast,asyncio,unittest
from pathlib import Path
from types import SimpleNamespace as N

class PostFailurePaths(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree=ast.parse((Path(__file__).parents[1]/'po_bot.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PoBotV2')
        self.env={'clean':lambda v:str(v or '').strip(),'without_copyright':lambda v:v.split('\n©')[0].strip(),'discord':N(Forbidden=LookupError,HTTPException=LookupError),'asyncio':asyncio,'_raid_is_inactive':lambda r:False,'_raid_signup_enabled':lambda r:True,'required':lambda v,k:v,'RaidIdentity':N(from_api=lambda *a:N(raid_id='r')),'DiscordPostIdentity':lambda **k:N(**k),'build_combined_embed':lambda *a:None,'CombinedSignupView':lambda *a:None}
        for name in ('remove_duplicate_raid_posts','_create_or_replace_post_unlocked'):
            f=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
            exec('from __future__ import annotations\n'+ast.unparse(f),self.env)
    async def test_exact_id_only(self):
        removed=[]
        def msg(mid,raid):
            async def delete():removed.append(mid)
            return N(id=mid,author=N(id=1),embeds=[N(footer=N(text='Gilden-ID: g · Raid-ID: '+raid+'\n© owner'))],delete=delete)
        async def history(**kw):
            for m in [msg(2,'schedule-rule-2026-09-13'),msg(3,'schedule-rule')]:yield m
        await self.env['remove_duplicate_raid_posts'](N(user=N(id=1)),N(history=history),'schedule-rule',1)
        self.assertEqual(removed,[3])
    async def run_create(self,wrong=False,recovery=False,save_error=False):
        state={'sent':0,'saved':0,'deleted':0}
        async def edit(**kw):raise RuntimeError('edit failed')
        async def delete():state['deleted']+=1
        message=N(id=123,channel=N(id=456),author=N(id=1),embeds=[N(footer=N(text='Gilden-ID: g · Raid-ID: r'))],edit=edit,delete=delete)
        async def send(**kw):state['sent']+=1;return message
        async def history(**kw):
            if recovery:yield message
        async def getraid(*a):return {'raid':{}}
        async def context(*a):return {}
        async def save(*a,**kw):
            state['saved']+=1
            if save_error:raise RuntimeError('save response lost')
        channel=N(guild=N(id=6 if wrong else 5),send=send,history=history)
        bot=N(user=N(id=1),api=N(get_raid=getraid,get_p0_context=context,save_discord_post=save),get_guild=lambda _:N(get_channel=lambda _:channel))
        with self.assertRaises(RuntimeError):await self.env['_create_or_replace_post_unlocked'](bot,N(guild_id='g',discord_guild_id='5'),'r',force_replace=False,channel_id_override='456')
        return state
    async def test_saved_post_survives_edit_failure(self):self.assertEqual(await self.run_create(),{'sent':1,'saved':1,'deleted':0})
    async def test_uncertain_save_survives(self):self.assertEqual((await self.run_create(save_error=True))['deleted'],0)
    async def test_wrong_guild_never_sends(self):self.assertEqual((await self.run_create(wrong=True))['sent'],0)
    async def test_retry_reuses_previous_send(self):self.assertEqual((await self.run_create(recovery=True))['sent'],0)

    async def test_force_retry_refreshes_already_saved_replacement(self):
        async def getraid(*a):return {"raid":{"discordMessageId":"new"}}
        async def refresh(*a,**kw):return "refreshed"
        bot=N(api=N(get_raid=getraid),_refresh_existing_post_unlocked=refresh)
        result=await self.env["_create_or_replace_post_unlocked"](bot,N(),"r",force_replace=True,force_origin_message_id="old")
        self.assertEqual(result,"refreshed")
