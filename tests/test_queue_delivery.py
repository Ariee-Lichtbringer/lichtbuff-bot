import asyncio
import time
import unittest
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, patch

from bot_readiness import readiness
from po_bot import LichtLootApi, PoBotV2
from queue_delivery import QueueDelivery, queue_request_params


class Api(LichtLootApi):
    def __init__(self):
        super().__init__('https://invalid.example', 'test')
        self.calls=[]
        self.claimed=True
        self.renewed=True

    def _request(self, method, params):
        self.calls.append(params)
        if params['action']=='lichtbotClaimQueue':
            return {'success':True,'claimed':self.claimed,'leaseToken':'lease' if self.claimed else ''}
        if params['action']=='lichtbotRenewQueue':
            return {'success':True,'renewed':self.renewed}
        return {'success':True}


class LeaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_ack_injects_only_matching_queue_token_and_cleans_context(self):
        api=Api()
        async with QueueDelivery(api,'guild','row') as lease:
            await api.post('lichtbotResolveQueue',guild='guild',rowNumber='other')
            self.assertNotIn('leaseToken',api.calls[-1])
            self.assertFalse(lease.completed)
            with self.assertRaises(ValueError):
                await api.post('lichtbotResolveQueue',guild='foreign',rowNumber='row')
            await api.post('lichtbotResolveQueue',guild='guild',rowNumber='row')
            self.assertEqual(api.calls[-1]['leaseToken'],'lease')
            self.assertTrue(lease.completed)
        self.assertNotIn('leaseToken',queue_request_params('lichtbotResolveQueue',{'guild':'guild','rowNumber':'row'}))

    async def test_other_claimant_is_skipped(self):
        api=Api();api.claimed=False
        async with QueueDelivery(api,'guild','row') as lease:
            self.assertFalse(lease.acquired)
        self.assertEqual(len(api.calls),1)

    async def test_renewal_preserves_readiness_and_scope(self):
        api=Api();beat=asyncio.Event()
        async with QueueDelivery(api,'guild','row',interval=.001,heartbeat=beat.set):
            await asyncio.wait_for(beat.wait(),1)
            await api.post('lichtbotResolveQueue',guild='guild',rowNumber='row')
        self.assertTrue(any(c['action']=='lichtbotRenewQueue' and c['leaseToken']=='lease' for c in api.calls))

    async def test_lost_lease_cancels_work_but_does_not_kill_queue_task(self):
        api=Api();api.renewed=False
        with self.assertRaisesRegex(RuntimeError,'Lease-Verlust'):
            async with QueueDelivery(api,'guild','row',interval=.001):
                await asyncio.Event().wait()
        self.assertEqual(asyncio.current_task().cancelling(),0)
        await asyncio.sleep(0)

    async def test_external_cancellation_still_propagates(self):
        api=Api();entered=asyncio.Event()
        async def worker():
            async with QueueDelivery(api,'guild','row'):
                entered.set();await asyncio.Event().wait()
        task=asyncio.create_task(worker());await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def dispatch(self,kind,error=None):
        api=Api()
        guild=N(guild_slug='guild',guild_id='g')
        bot=N(api=api,identities=N(by_slug={'guild':guild}),wait_until_ready=AsyncMock(),
              is_closed=lambda:False,queue_heartbeat=lambda:None)
        async def get(*args,**kwargs):
            self.assertEqual(kwargs['claimMode'],'manual-v1')
            return {'success':True,'claimMode':'manual-v1','items':[
                {'guildSlug':'guild','type':kind,'rowNumber':'row','payload':{'channelId':'12'}}]}
        api.get=get
        real_sleep=asyncio.sleep
        async def sleep(delay):
            if delay==5:raise asyncio.CancelledError()
            await real_sleep(delay)
        handler=AsyncMock(return_value='123',side_effect=error)
        with patch('po_bot.asyncio.sleep',sleep), patch('po_bot.send_offline_notice',handler), patch('po_bot.deliver_queue_notice',handler):
            with self.assertRaises(asyncio.CancelledError):await PoBotV2.queue_loop(bot)
        return api.calls,handler

    async def test_offline_dispatch_ack_has_lease_and_message(self):
        calls,handler=await self.dispatch('po_offline_notice')
        handler.assert_awaited_once()
        result=next(c for c in calls if c['action']=='lichtbotResolveQueue')
        self.assertEqual((result['leaseToken'],result['messageId']),('lease','123'))

    async def test_transient_notice_error_retries_with_lease(self):
        calls,_=await self.dispatch('po_approval_notice',RuntimeError('temporary'))
        self.assertFalse(any(c['action']=='lichtbotResolveQueue' for c in calls))
        self.assertEqual(next(c for c in calls if c['action']=='lichtbotRetryQueue')['leaseToken'],'lease')

    async def test_permanent_notice_error_fails_with_lease(self):
        calls,_=await self.dispatch('po_approval_notice',ValueError('blocked'))
        self.assertEqual(next(c for c in calls if c['action']=='lichtbotFailQueue')['leaseToken'],'lease')


class ReadinessTests(unittest.TestCase):
    def test_disconnected_stale_or_stopped_queue_is_unready(self):
        bot=N(is_ready=lambda:True,is_closed=lambda:False,_queue_task=N(done=lambda:False),
              _refresh_task=N(done=lambda:False),_queue_last_success=time.monotonic())
        self.assertTrue(readiness(bot)[0])
        bot._queue_last_success-=181
        self.assertFalse(readiness(bot)[0])
        bot._queue_last_success=time.monotonic();bot._queue_task=N(done=lambda:True)
        self.assertFalse(readiness(bot)[0])
        bot._queue_task=N(done=lambda:False);bot.is_ready=lambda:False
        self.assertFalse(readiness(bot)[0])


if __name__=='__main__':unittest.main()
