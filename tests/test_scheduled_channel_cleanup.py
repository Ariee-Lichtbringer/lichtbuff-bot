import unittest
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock

from scheduled_channel_cleanup import cleanup_scheduled_channel


class NotFound(Exception):
    pass


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    def setup_channel(self, messages):
        self.current = Obj(id=300, author=Obj(id=7))
        self.rows = messages
        async def history(**kwargs):
            self.assertIsNone(kwargs['limit'])
            self.assertEqual(kwargs['before'].id, 300)
            for row in list(self.rows):
                yield row
        self.channel = Obj(guild=Obj(id=2), fetch_message=AsyncMock(return_value=self.current), history=history)
        self.bot = Obj(user=Obj(id=7), fetch_channel=AsyncMock(return_value=self.channel))
        self.guild = Obj(guild_id='g', discord_guild_id='2')
        self.posted = Obj(guild_id='g', discord_channel_id='5', discord_message_id='300')

    def message(self, id, pinned=False):
        row = Obj(id=id, pinned=pinned)
        async def delete():
            self.rows.remove(row)
        row.delete = AsyncMock(side_effect=delete)
        return row

    async def run_cleanup(self):
        return await cleanup_scheduled_channel(self.bot, self.guild, self.posted, Obj(NotFound=NotFound))

    async def test_full_history_and_retries_preserve_newer_and_pinned(self):
        old = [self.message(i) for i in range(1, 202)]
        pinned, current, newer = self.message(210, True), self.message(300), self.message(301)
        self.setup_channel(old + [pinned, current, newer])
        self.assertEqual(await self.run_cleanup(), 201)
        self.assertEqual(await self.run_cleanup(), 0)
        for row in (pinned, current, newer):
            row.delete.assert_not_awaited()

    async def test_missing_new_post_or_wrong_guild_prevents_deletion(self):
        old = self.message(1); self.setup_channel([old])
        self.channel.fetch_message.side_effect = NotFound()
        with self.assertRaises(NotFound): await self.run_cleanup()
        old.delete.assert_not_awaited()
        self.channel.guild.id = 99
        with self.assertRaises(ValueError): await self.run_cleanup()
        old.delete.assert_not_awaited()

    async def test_foreign_author_prevents_deletion(self):
        old = self.message(1); self.setup_channel([old]); self.current.author.id = 8
        with self.assertRaises(ValueError): await self.run_cleanup()
        old.delete.assert_not_awaited()

    async def test_partial_failure_is_retryable_without_deleting_new_messages(self):
        first, second, newer = self.message(1), self.message(2), self.message(301)
        self.setup_channel([first, second, newer])
        original = second.delete.side_effect
        second.delete.side_effect = PermissionError('missing permission')
        with self.assertRaises(PermissionError): await self.run_cleanup()
        second.delete.side_effect = original
        self.assertEqual(await self.run_cleanup(), 1)
        first.delete.assert_awaited_once(); newer.delete.assert_not_awaited()

    async def test_concurrent_deleted_message_is_skipped(self):
        old = self.message(1); self.setup_channel([old]); old.delete.side_effect = NotFound()
        self.assertEqual(await self.run_cleanup(), 0)


if __name__ == '__main__':
    unittest.main()
