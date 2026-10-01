import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import forever_signup as f
class BetaRoleTest(unittest.IsolatedAsyncioTestCase):
    async def test_dropdowns_and_submission_preserve_explicit_role(self):
        result={'characters':[{'role':'dd'}],'raid':{'signups':[{'mine':True,'role':'dd'}]}}
        call=AsyncMock(return_value=result)
        modal=f.BetaModal(SimpleNamespace(api=SimpleNamespace(call=call)),{'discordUserId':'123'})
        self.assertEqual([x.text for x in modal.children],['Dein Charaktername','Gemeinsamer Beta-PIN deiner Gilde','Klasse','Rolle'])
        self.assertEqual(len(modal.cls.options),9)
        self.assertEqual([x.value for x in modal.role.options],['tank','dd','heal'])
        self.assertEqual([x['type'] for x in modal.to_components()],[18]*4)
        modal.name._value='Aria';modal.pin._value='TESTPIN';modal.cls._values=['priest'];modal.role._values=['heal']
        i=SimpleNamespace(user=SimpleNamespace(id=123),response=SimpleNamespace(defer=AsyncMock(),is_done=lambda:True),followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(f,'send_choices',new_callable=AsyncMock) as choices:
            await modal.on_submit(i)
            self.assertEqual(call.call_args.kwargs['className'],'priest')
            self.assertEqual(call.call_args.kwargs['role'],'heal')
            self.assertNotIn('role',choices.call_args.args[2])
            self.assertEqual(result['raid']['signups'][0]['role'],'heal')
    async def test_missing_role_does_not_call_api(self):
        call=AsyncMock();modal=f.BetaModal(SimpleNamespace(api=SimpleNamespace(call=call)),{'discordUserId':'123'})
        modal.cls._values=['mage']
        i=SimpleNamespace(user=SimpleNamespace(id=123),response=SimpleNamespace(defer=AsyncMock(),is_done=lambda:True),followup=SimpleNamespace(send=AsyncMock()))
        await modal.on_submit(i)
        call.assert_not_called()
        self.assertIn('Tank',str(i.followup.send.call_args))
