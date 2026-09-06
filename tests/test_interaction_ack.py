import ast
import asyncio
import re
import threading
from io import BytesIO
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from interaction_ack import acknowledge_interaction


class DiscordError(Exception):
    def __init__(self, code):
        self.code = code


class InteractionAckTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, error=None):
        return SimpleNamespace(
            id=123, created_at=datetime.now(timezone.utc), message=SimpleNamespace(id=456),
            data={"custom_id": "p0v2:raid_signup"},
            response=SimpleNamespace(is_done=lambda: False, defer=AsyncMock(side_effect=error)),
        )

    async def test_expired_and_duplicate_click_stop_but_new_click_works(self):
        for code in (10062, 40060):
            self.assertFalse(await acknowledge_interaction(self.interaction(DiscordError(code)), ephemeral=True))
        fresh = self.interaction()
        self.assertTrue(await acknowledge_interaction(fresh, ephemeral=True, thinking=True))
        fresh.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)

    async def test_unrelated_errors_are_not_hidden(self):
        with self.assertRaises(DiscordError):
            await acknowledge_interaction(self.interaction(DiscordError(50013)))

    async def test_expired_signup_does_not_load_or_write_data(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "po_bot.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CombinedSignupView")
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "open_raid_modal")
        scope = {"acknowledge_interaction": acknowledge_interaction}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), method], type_ignores=[])), "signup-test", "exec"), scope)
        api = SimpleNamespace(get_linked_characters=AsyncMock())
        view = SimpleNamespace(bot=SimpleNamespace(api=api))
        await scope["open_raid_modal"](view, self.interaction(DiscordError(10062)), "signed")
        api.get_linked_characters.assert_not_awaited()

    async def test_xlsx_compression_does_not_block_clicks(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "po_bot.py").read_text())
        method = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "post_p0_backup_export")
        released = threading.Event()
        finished_after_click = []
        def build(sheets):
            finished_after_click.append(released.wait(timeout=1))
            return BytesIO(b"xlsx")
        async def history(**kwargs):
            if False:
                yield None
        channel = SimpleNamespace(guild=SimpleNamespace(id=1), history=history, send=AsyncMock(return_value=SimpleNamespace(id=2)))
        embed = SimpleNamespace(set_footer=lambda **kw: None, add_field=lambda **kw: None)
        scope = dict(asyncio=asyncio, re=re, clean=lambda v: str(v or ""), build_xlsx_file=build,
                     copyright_text=lambda v="", **kw: v,
                     discord=SimpleNamespace(Embed=lambda **kw: embed, File=lambda *a, **kw: None,
                                             AllowedMentions=SimpleNamespace(none=lambda: None)))
        exec(compile(ast.Module(body=[method], type_ignores=[]), "export-test", "exec"), scope)
        task = asyncio.create_task(scope["post_p0_backup_export"](SimpleNamespace(get_channel=lambda _: channel),
                                   SimpleNamespace(discord_guild_id="1"), {"channelId": "1", "sheets": [{}]}, "job"))
        await asyncio.sleep(0.02)
        try:
            self.assertTrue(await acknowledge_interaction(self.interaction()))
        finally:
            released.set()
        self.assertEqual(await task, "2")
        self.assertEqual(finished_after_click, [True], "The click must be processed while the export is running")


if __name__ == "__main__":
    unittest.main()
