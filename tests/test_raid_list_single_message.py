import unittest
from unittest.mock import patch
import discord
import po_bot


class SingleMessageRaidList(unittest.TestCase):
    def build(self, count=12, same_item=False):
        guild = po_bot.GuildIdentity('g', 'lichtloot', '123')
        rows = [dict(player=f'Player{i:04}', item='Shared item' if same_item else f'Item{i:04}', p0PlusPoints=i+1) for i in range(count)]
        classes = ['warrior', 'druid', 'paladin', 'rogue', 'hunter', 'priest', 'mage', 'warlock', 'shaman']
        helper = {'raid': {'raidId': 'r', 'internalRaidId': 'internal', 'guildId': 'g', 'raidName': 'Naxx', 'raidHelperEnabled': True},
                  'signups': [dict(player=f'Roster{i:04}', className=classes[i % len(classes)], status='signed', signupNumber=i+1) for i in range(40)]}
        with patch.object(po_bot, '_emoji', return_value='<:Beutegrun:123456789012345678>'), patch.object(po_bot, '_item_icon', return_value='<:hammerdeswir:123456789012345678>'), patch.object(po_bot, '_row_spec_icon', return_value='<:specialization:123456789012345678>'):
            return po_bot.build_combined_embed(guild, helper, {'signups': rows})

    def test_full_roster_and_p0_list_in_one_embed(self):
        for count, same_item in [(12, False), (40, False), (40, True)]:
            embed = self.build(count, same_item)
            self.assertIsInstance(embed, discord.Embed)
            text = '\n'.join(f.name + '\n' + f.value for f in embed.fields)
            for i in range(count):
                self.assertEqual(text.count(f'`Player{i:04}`'), 1)
                self.assertIn(f'**{i+1} P0+**', text)
                self.assertIn('Shared item' if same_item else f'Item{i:04}', text)
            for i in range(40):
                self.assertEqual(text.count(f'Roster{i:04}'), 1)
            self.assertNotIn('weitere Einträge', text)
            self.assertLessEqual(len(embed), 5900)
            self.assertLessEqual(len(embed.fields), 25)
            for field in embed.fields:
                self.assertLessEqual(len(field.value), 1024)
                self.assertEqual(field.value.count('<:'), field.value.count('>'))
            self.assertTrue(embed.image.url)

    def test_impossible_size_is_not_silently_truncated(self):
        with self.assertRaisesRegex(ValueError, 'vollständige Liste'):
            self.build(300)

    def test_small_embed_preserves_custom_icons(self):
        embed = discord.Embed(title='Raid')
        embed.add_field(name='Item', value='<:Beutegrun:123456789012345678> `Player` · **3 P0+**')
        before = embed.to_dict()
        self.assertEqual(po_bot._fit_embed_to_discord_limit(embed).to_dict(), before)
