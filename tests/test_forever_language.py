import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
import discord
import forever_signup as f
from signup_language import user_language, guild_language
from test_forever_signup import POST

class LanguageTest(unittest.IsolatedAsyncioTestCase):
    async def test_personal_locale_and_guild_are_independent(self):
        self.assertEqual(user_language(SimpleNamespace(locale=discord.Locale.german)),'de')
        self.assertEqual(user_language(SimpleNamespace(locale=discord.Locale.american_english)),'en')
        self.assertEqual(user_language(SimpleNamespace(locale=discord.Locale.french)),'en')
        p=copy.deepcopy(POST);p['guild']['language']='en'
        self.assertEqual(guild_language(p),'en')
        self.assertEqual(guild_language(POST),'de')
        view=f.SignupView(None,p)
        self.assertEqual(view.children[0].custom_id,'forever:signup')
        self.assertNotIn('anmelden',view.children[0].label)
        embed=f.build_embed(p)
        self.assertIn('Signup status',[x.name for x in embed.fields])
        self.assertEqual(embed.description,'Test')
        self.assertIn('Lichtbringer',[x.value for x in embed.fields])
        self.assertIn('lang=en',f.raid_url(p))
    async def test_english_modal_preserves_all_values(self):
        de=f.BetaModal(None,{'discordUserId':'123'},'de').to_dict()
        en=f.BetaModal(None,{'discordUserId':'123'},'en').to_dict()
        self.assertNotEqual(en['title'],de['title'])
        for a,b in zip(de['components'],en['components']):
            ca,cb=a['component'],b['component']
            if ca['type']==3:
                self.assertEqual([o['value'] for o in ca['options']],[o['value'] for o in cb['options']])
                self.assertNotIn('disabled',cb)
        self.assertIn('Mage',str(en))
    async def test_private_save_response_uses_interaction_locale(self):
        call=AsyncMock(return_value={'status':'signed'})
        worker=SimpleNamespace(api=SimpleNamespace(call=call),wake=SimpleNamespace(set=lambda:None))
        choice=SimpleNamespace(user_id=123,worker=worker,identity={'betaPin':'PRIVATE','characterName':'Schatten','className':'mage'},character_id='char',role='dd',status='signed',note='',language='de')
        modal=f.SaveModal(choice)
        interaction=SimpleNamespace(locale=discord.Locale.american_english,user=SimpleNamespace(id=123),response=SimpleNamespace(defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        await modal.on_submit(interaction)
        self.assertEqual(call.call_args.kwargs['characterName'],'Schatten')
        self.assertEqual(call.call_args.kwargs['className'],'mage')
        self.assertIn('saved',interaction.followup.send.call_args.args[0])
        self.assertNotIn('PRIVATE',str(interaction.followup.send.call_args))
