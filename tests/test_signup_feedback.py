import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, Mock

from signup_feedback import confirm_saved_action


class SignupFeedbackTests(unittest.IsolatedAsyncioTestCase):
    def method(self, cls, name):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'po_bot.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
        method = next(n for n in node.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        method.decorator_list = []
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), method], type_ignores=[])
        scope = dict(acknowledge_interaction=AsyncMock(return_value=True),
                     clean=lambda v: str(v or '').strip(), required=lambda v, k: v,
                     confirm_saved_action=confirm_saved_action)
        exec(compile(ast.fix_missing_locations(module), 'signup-test', 'exec'), scope)
        return scope[name]

    def scenario(self, api_method, write_error=None, refresh_error=None):
        api = N(**{api_method: AsyncMock(return_value={}, side_effect=write_error)})
        bot = N(api=api, refresh_existing_post=AsyncMock(side_effect=refresh_error))
        view = N(bot=bot, guild_identity=N(guild_id='guild'), raid_id='raid',
                 character='Test', role='heal', spec_name='Heilig', status='signed',
                 discord_user_id=1, discord_name='Test', channel_id=2, message_id=3,
                 item_name='Item', stop=Mock(), values=['entry'],
                 entries_by_value={'entry': {'id':'entry'}}, review_status='approved')
        interaction = N(followup=N(send=AsyncMock()), user=N(id=1, display_name='Test'))
        return view, interaction

    async def invoke(self, cls, name, view, interaction):
        args = () if name == 'callback' else (N(),)
        await self.method(cls, name)(view, interaction, *args)

    cases = [
        ('RaidSignupSelectionView', 'submit', 'save_raid_signup'),
        ('P0SignupSelectionView', 'submit', 'save_p0_signup'),
        ('P0DeleteCharacterView', 'delete_signup', 'delete_p0_signup'),
        ('P0ReviewSelect', 'callback', 'review_p0_signup'),
    ]

    async def test_refresh_failure_preserves_success_for_all_write_flows(self):
        for cls, name, api_method in self.cases:
            with self.subTest(cls=cls):
                view, interaction = self.scenario(api_method, refresh_error=RuntimeError('Discord offline'))
                with self.assertLogs('guildloot.signups', level='WARNING'):
                    await self.invoke(cls, name, view, interaction)
                getattr(view.bot.api, api_method).assert_awaited_once()
                text = interaction.followup.send.call_args.args[0]
                self.assertTrue(text.startswith('✅'))
                self.assertIn('Änderung ist gespeichert', text)
                self.assertNotIn('fehlgeschlagen', text)
                if name != 'callback':
                    view.stop.assert_called_once()

    async def test_write_failure_does_not_refresh_or_claim_success(self):
        for cls, name, api_method in self.cases:
            with self.subTest(cls=cls):
                view, interaction = self.scenario(api_method, write_error=RuntimeError('API offline'))
                await self.invoke(cls, name, view, interaction)
                view.bot.refresh_existing_post.assert_not_awaited()
                self.assertIn('fehlgeschlagen', interaction.followup.send.call_args.args[0])
                view.stop.assert_not_called()

    async def test_successful_refresh_has_no_warning_and_preserves_fallbacks(self):
        view, interaction = self.scenario('save_p0_signup')
        view.bot.api.save_p0_signup.return_value = {'signup': {'id': 'saved'}}
        await self.invoke('P0SignupSelectionView', 'submit', view, interaction)
        self.assertEqual(interaction.followup.send.call_args.args[0], '✅ P0-Anmeldung gespeichert.')
        options = view.bot.refresh_existing_post.call_args.kwargs
        self.assertEqual(options['fallback_channel_id'], '2')
        self.assertEqual(options['fallback_message_id'], '3')
        self.assertEqual(options['fallback_p0_entries'], [{'id': 'saved'}])

    async def test_confirmation_delivery_failure_is_not_reported_as_write_failure(self):
        view, interaction = self.scenario('save_raid_signup')
        interaction.followup.send.side_effect = RuntimeError('response unavailable')
        with self.assertRaisesRegex(RuntimeError, 'response unavailable'):
            await self.invoke('RaidSignupSelectionView', 'submit', view, interaction)
        interaction.followup.send.assert_awaited_once()
        view.bot.api.save_raid_signup.assert_awaited_once()

    async def test_character_switch_updates_text_and_selected_option(self):
        parent = N(character='Alt')
        parent.set_character = lambda index: setattr(parent, 'character', 'Neu')
        select = N(parent_view=parent, values=['1'], options=[N(value='0', default=True), N(value='1', default=False)])
        interaction = N(edit_original_response=AsyncMock())
        await self.method('RaidCharacterSelect', 'callback')(select, interaction)
        kwargs = interaction.edit_original_response.call_args.kwargs
        self.assertIn('**Neu**', kwargs['content'])
        self.assertNotIn('Alt', kwargs['content'])
        self.assertIs(kwargs['view'], parent)
        self.assertEqual([o.default for o in select.options], [False, True])


if __name__ == '__main__':
    unittest.main()
