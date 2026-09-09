"""Private prio confirmations reuse delivery tracking without creating mailbox messages."""
import unittest
from test_mailbox_dm import MailboxDmTests, Forbidden

class PrioSavedDmTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        MailboxDmTests.setUp(self)
        self.payload.update(prioSaveConfirmation=True, title='Prio erfolgreich gespeichert')

    def callback(self, payload):
        self.callbacks.append(payload)
        return {'success': True, 'status': 'queued'}

    async def test_private_confirmation_routes_and_style(self):
        await self.handler(self.payload, self.callback)
        self.assertEqual(self.callbacks[0]['action'], 'getPrioSaveDmStatus')
        self.assertEqual(self.callbacks[-1]['action'], 'completePrioSaveDm')
        self.assertEqual(self.callbacks[-1]['status'], 'delivered')
        self.assertEqual(self.sends[0]['embed'].values['color'], 0xE5BD60)
        self.assertNotIn('Postfach', self.sends[0]['embed'].footer['text'])
        self.assertEqual(self.sends[0]['allowed_mentions'], 'no-mentions')

    async def test_closed_dm_records_failure_without_resending(self):
        self.failure = Forbidden()
        await self.handler(self.payload, self.callback)
        self.assertEqual(self.callbacks[-1]['status'], 'failed')
        self.failure = None
        await self.handler(self.payload, self.callback)
        self.assertEqual(len(self.sends), 0)

    async def test_delivered_after_restart_is_not_resent(self):
        await self.handler(self.payload, lambda p: {'success': True, 'status': 'delivered'})
        self.assertEqual(len(self.sends), 0)

    async def test_callback_retry_does_not_resend(self):
        def fail(p):
            if p['action']=='completePrioSaveDm': raise RuntimeError('timeout')
            return {'success':True,'status':'queued'}
        with self.assertRaises(RuntimeError): await self.handler(self.payload, fail)
        await self.handler(self.payload, self.callback)
        self.assertEqual(len(self.sends), 1)
