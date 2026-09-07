import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock


class MissingRefreshTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree = ast.parse((Path(__file__).parents[1] / 'po_bot.py').read_text())
        error = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MissingStoredPost')
        bot = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PoBotV2')
        method = next(n for n in bot.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'refresh_scheduled_post')
        scope = {'clean': lambda v: str(v or '').strip(), 'required': lambda v, k: v}
        exec('from __future__ import annotations\n' + ast.unparse(error) + '\n' + ast.unparse(method), scope)
        self.error = scope['MissingStoredPost']
        self.run_refresh = scope['refresh_scheduled_post']
        self.bot = N(_missing_refresh_posts={}, refresh_existing_post=AsyncMock())
        self.guild = N(guild_id='g')
        self.raid = dict(raidId='r', discordChannelId='c', discordMessageId='m')

    async def test_confirmed_deleted_message_only_checked_once(self):
        self.bot.refresh_existing_post.side_effect = self.error('c', 'm')
        for _ in range(3):
            await self.run_refresh(self.bot, self.guild, self.raid)
        self.assertEqual(self.bot.refresh_existing_post.await_count, 1)

    async def test_transient_failure_retries(self):
        self.bot.refresh_existing_post.side_effect = RuntimeError('503 Service Unavailable')
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await self.run_refresh(self.bot, self.guild, self.raid)
        self.assertEqual(self.bot.refresh_existing_post.await_count, 2)
        self.assertFalse(self.bot._missing_refresh_posts)

    async def test_new_message_and_other_guild_are_not_suppressed(self):
        self.bot._missing_refresh_posts[('g', 'r')] = ('c', 'm')
        await self.run_refresh(self.bot, N(guild_id='other'), self.raid)
        await self.run_refresh(self.bot, self.guild, dict(self.raid, discordMessageId='replacement'))
        self.assertEqual(self.bot.refresh_existing_post.await_count, 2)
        self.assertNotIn(('g', 'r'), self.bot._missing_refresh_posts)

    async def test_changed_target_during_fetch_is_recorded_exactly(self):
        self.bot.refresh_existing_post.side_effect = self.error('c', 'replacement')
        await self.run_refresh(self.bot, self.guild, self.raid)
        self.assertEqual(self.bot._missing_refresh_posts[('g', 'r')], ('c', 'replacement'))
