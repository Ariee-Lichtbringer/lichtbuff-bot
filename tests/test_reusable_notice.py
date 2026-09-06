import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from bot_offline_notice import send_offline_notice, _sent

class NoticeTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_message_for_both_status_changes(self):
        _sent.clear()
        message=SimpleNamespace(id=123,author=SimpleNamespace(id=7),edit=AsyncMock())
        channel=SimpleNamespace(guild=SimpleNamespace(id=9),send=AsyncMock(return_value=message),fetch_message=AsyncMock(return_value=message))
        bot=SimpleNamespace(user=SimpleNamespace(id=7),get_channel=lambda _:channel)
        discord=SimpleNamespace(AllowedMentions=SimpleNamespace(none=lambda:None))
        base={'channelId':'8','discordGuildId':'9','noticeKind':'update','noticeState':'offline'}
        self.assertEqual(await send_offline_notice(bot,base,'first',discord),'123')
        await send_offline_notice(bot,{**base,'editOnly':True,'messageId':'123','noticeState':'online'},'second',discord)
        self.assertIn('wieder erreichbar',message.edit.call_args.kwargs['content'])
        await send_offline_notice(bot,{**base,'editOnly':True,'messageId':'123'},'third',discord)
        self.assertIn('nicht erreichbar',message.edit.call_args.kwargs['content'])
        await send_offline_notice(bot,{**base,'editOnly':True,'messageId':'123'},'third',discord)
        self.assertEqual(channel.send.await_count,1)
        self.assertEqual(message.edit.await_count,2)
        channel.fetch_message.side_effect=RuntimeError('missing')
        with self.assertRaises(RuntimeError):
            await send_offline_notice(bot,{**base,'editOnly':True,'messageId':'123'},'missing',discord)
        self.assertEqual(channel.send.await_count,1)

if __name__=='__main__':unittest.main()
