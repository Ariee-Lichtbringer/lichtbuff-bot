import unittest
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
from queue_notices import deliver_queue_notice,render_notice,NOTICE_TYPES
class Embed:
    def __init__(self,**kw):self.footer=None
    def set_footer(self,text):self.footer=N(text=text)
class Forbidden(Exception):pass
class NoticeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.discord=N(Embed=Embed,AllowedMentions=N(none=lambda:None))
        self.guild=N(discord_guild_id='9',guild_slug='g',guild_id='internal')
    async def test_old_calendar_recovered_once_then_loaded_by_id(self):
        old=N(id=123456789012345678,author=N(id=7),embeds=[N(footer=N(text='GuildLoot-Kalender: internal'))],edit=AsyncMock())
        newer=[N(id=n,author=N(id=8),embeds=[]) for n in range(200)]
        async def history(limit,oldest_first=False):
            self.assertIsNone(limit)
            for m in ([old]+newer if oldest_first else newer+[old]):yield m
        channel=N(id=223456789012345678,guild=N(id=9),history=history,send=AsyncMock(),fetch_message=AsyncMock(return_value=old))
        state={'messageId':'','fail':True}
        async def post(action,**kw):
            if action=='lichtbotPrepareCalendarPost':return {'claimed':True,'leaseToken':'token','messageId':state['messageId']}
            if action=='lichtbotCompleteCalendarPost':
                state['messageId']=kw['messageId']
                if state['fail']:state['fail']=False;raise RuntimeError('ack lost after persistence')
            return {'success':True}
        bot=N(user=N(id=7),get_guild=lambda _:N(),get_channel=lambda _:channel,api=N(post=post))
        payload={'channelId':str(channel.id),'events':[]}
        with self.assertRaises(RuntimeError):await deliver_queue_notice(bot,self.guild,'raid_calendar',payload,'q',self.discord)
        result=await deliver_queue_notice(bot,self.guild,'raid_calendar',payload,'q',self.discord)
        self.assertEqual(result,str(old.id));channel.send.assert_not_awaited();channel.fetch_message.assert_awaited_once_with(old.id)
        with self.assertRaises(ValueError):await deliver_queue_notice(bot,N(discord_guild_id='10',guild_slug='g'),'raid_calendar',payload,'q',self.discord)
    async def test_blocked_recipient_does_not_stop_others_or_resend_success(self):
        async def history(**kw):
            if False:yield None
        good=N(id=88,history=history,send=AsyncMock(return_value=N(id=99)))
        bad=N(id=77,history=history,send=AsyncMock(side_effect=Forbidden('DM blocked')))
        first=N(id=11,bot=False,name='a',display_name='a',roles=[N(id=44)],create_dm=AsyncMock(return_value=bad))
        second=N(id=22,bot=False,name='b',display_name='b',roles=[N(id=44)],create_dm=AsyncMock(return_value=good))
        server=N(members=[first,second],chunked=True);receipts={};errors={}
        async def post(action,**kw):
            if kw.get('error'):errors[kw['targetId']]=kw['error']
            else:receipts[kw['targetId']]=kw['messageId']
            return {'success':True}
        bot=N(user=N(id=7),get_guild=lambda _:server,api=N(post=post));payload={'targets':[{'type':'role','value':'44'}]}
        with self.assertRaises(ValueError):await deliver_queue_notice(bot,self.guild,'po_release_request_notice',payload,'q',self.discord)
        self.assertEqual(receipts,{'22':'99'});self.assertIn('11',errors);good.send.assert_awaited_once()
        payload['deliveryReceipts']=receipts
        with self.assertRaises(ValueError):await deliver_queue_notice(bot,self.guild,'po_release_request_notice',payload,'q',self.discord)
        good.send.assert_awaited_once()
        first.create_dm.side_effect=Forbidden('cannot open DM')
        payload['deliveryReceipts']={}
        with self.assertRaises(ValueError):await deliver_queue_notice(bot,self.guild,'po_release_request_notice',payload,'q2',self.discord)
        self.assertEqual(good.send.await_count,2)
    def test_each_type_renders_without_account_secrets(self):
        for kind in NOTICE_TYPES:
            body=render_notice(kind,{'playerPin':'SECRET','character':'Tester','event':'raid_transfer'},N(guild_slug='g'))
            self.assertNotIn('SECRET',body);self.assertTrue(body)

    def test_points_notice_reports_committed_balance(self):
        p={'player':'Mála','raidName':'MC','raidDate':'2026-09-08','item':'Magierklinge','points':0.5,'oldPoints':2,'newPoints':2.5,'event':'raid_transfer'}
        body=render_notice('p0plus_points_notice',p,N(guild_slug='g'))
        self.assertIn('0,5 P0+-Punkte',body);self.assertIn('2,5 Punkte',body);self.assertIn('Magierklinge',body)
        p.update(event='item_received_clear',newPoints=0)
        body=render_notice('p0plus_points_notice',p,N(guild_slug='g'))
        self.assertIn('erhalten',body);self.assertIn('2 → 0',body)

    async def test_release_dm_uses_character_account_and_receipt(self):
        async def history(**kw):
            if False: yield None
        channel=N(id=88,history=history,send=AsyncMock(return_value=N(id=99)))
        member=N(create_dm=AsyncMock(return_value=channel))
        server=N(get_member=lambda uid:member if uid==123 else None)
        bot=N(user=N(id=7),get_guild=lambda _:server,api=N(post=AsyncMock()))
        payload={'discordUserId':'123','character':'Fixture','raidLabel':'Blackwing Lair'}
        self.assertIn('po_release_granted_notice',NOTICE_TYPES)
        self.assertEqual(await deliver_queue_notice(bot,self.guild,'po_release_granted_notice',payload,'q',self.discord),'99')
        self.assertEqual(bot.api.post.call_args.kwargs['targetId'],'123')
        payload['deliveryReceipts']={'123':'99'}
        await deliver_queue_notice(bot,self.guild,'po_release_granted_notice',payload,'q',self.discord)
        channel.send.assert_awaited_once()
        payload['discordUserId']=''
        with self.assertRaises(ValueError):await deliver_queue_notice(bot,self.guild,'po_release_granted_notice',payload,'q',self.discord)

    def test_release_decisions_render_truthfully(self):
        p={'character':'Fixture','raidLabel':'Blackwing Lair','decision':'revoked','reason':'Ausrüstung','customMessage':'Bitte prüfen'}
        text=render_notice('po_release_granted_notice',p,self.guild)
        for value in ('aufgehoben','Blackwing Lair','Ausrüstung','Bitte prüfen'):self.assertIn(value,text)
        self.assertNotIn('erteilt',text)
        self.assertIn('Freigabeantrag genehmigt',render_notice('po_approval_notice',{'requestId':'r'},self.guild))
        self.assertIn('Freigabeantrag abgelehnt',render_notice('po_rejection_notice',{'requestId':'r'},self.guild))
