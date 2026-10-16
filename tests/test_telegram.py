"""Telegram: titularidade de callback (NF-02) e edited_message (F-14). Mocks, sem rede."""
import asyncio
import time
import unittest
from unittest.mock import patch

from interface import telegram_bot as tb


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakeMsg:
    def __init__(self, mid, chat, text="tarefa x"):
        self.message_id = mid
        self.chat_id = chat
        self.chat = FakeChat(chat)
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)
        m = FakeMsg(999, self.chat_id)
        return m


class FakeChat:
    def __init__(self, cid):
        self.id = cid


class FakeCB:
    def __init__(self, uid, chat, mid, data="ok"):
        self.from_user = FakeUser(uid)
        self.message = FakeMsg(mid, chat)
        self.data = data
        self.answered = False

    async def answer(self):
        self.answered = True


class FakeUpdate:
    def __init__(self, uid, msg=None):
        self.effective_user = FakeUser(uid)
        self.message = msg
        self.edited_message = None
        self.callback_query = None


def _cb_update(uid, chat, mid, data="ok"):
    u = FakeUpdate(uid)
    u.message = None
    u.callback_query = FakeCB(uid, chat, mid, data)
    return u


class FakeCtx:
    args = []


class TestCallbackOwnership(unittest.TestCase):
    def test_third_party_keeps_pending(self):
        # NF-02: clique de B (whitelist) não destrói pendência de A
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        tb._pending_confirm[(10, 42)] = (fut, 111)
        try:
            with patch.object(tb.settings, "TELEGRAM_WHITELIST_IDS", [111, 222]):
                asyncio.run(tb.on_button(_cb_update(222, 10, 42), FakeCtx()))
                self.assertIn((10, 42), tb._pending_confirm,
                              "pendência de A destruída por B")
                asyncio.run(tb.on_button(_cb_update(111, 10, 42), FakeCtx()))
                self.assertTrue(fut.result())
                self.assertNotIn((10, 42), tb._pending_confirm)
        finally:
            tb._pending_confirm.pop((10, 42), None)
            loop.close()


class TestEditedMessage(unittest.TestCase):
    def test_error_branches_use_edited(self):
        # F-14: rate limit com update.message=None não explode
        uid = 111
        msg = FakeMsg(7, 50, text="oi")
        u = FakeUpdate(uid, msg=None)
        u.edited_message = msg
        tb._last_enqueue[uid] = time.time()  # força rate limit
        try:
            with patch.object(tb.settings, "TELEGRAM_WHITELIST_IDS", [111]):
                with patch.object(tb.settings, "RATE_LIMIT_SEC", 60):
                    asyncio.run(tb.enqueue(u, FakeCtx()))
            self.assertTrue(any("Calma" in r for r in msg.replies))
        finally:
            tb._last_enqueue.pop(uid, None)


class TestAskRouting(unittest.TestCase):
    def test_answer_resolves_instead_of_enqueue(self):
        # v2.6: resposta a pergunta pendente não vira tarefa
        import asyncio as _aio
        loop = _aio.new_event_loop()
        fut = loop.create_future()
        tb._pending_ask[50] = (fut, "abc123")
        qsize = tb.task_queue.qsize()
        msg = FakeMsg(8, 50, text="loja de bolos")
        u = FakeUpdate(111, msg)
        try:
            with patch.object(tb.settings, "TELEGRAM_WHITELIST_IDS", [111]):
                asyncio.run(tb.enqueue(u, FakeCtx()))
            self.assertTrue(fut.done() and fut.result() == "loja de bolos")
            self.assertEqual(tb.task_queue.qsize(), qsize)
            self.assertTrue(any("abc123" in r for r in msg.replies))
        finally:
            tb._pending_ask.pop(50, None)
            loop.close()


if __name__ == "__main__":
    unittest.main()
