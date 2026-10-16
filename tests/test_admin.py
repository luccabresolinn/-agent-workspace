"""/stop e /reset: mocks, sem rede."""
import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from interface import telegram_bot as tb


class FakeMsg:
    def __init__(self, mid=1, chat=50):
        self.message_id = mid
        self.chat_id = chat
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)
        m = FakeMsg(999, self.chat_id)
        return m


class FakeUpdate:
    def __init__(self, uid=111, msg=None):
        self.effective_user = type("U", (), {"id": uid})()
        self.message = msg or FakeMsg()


class FakeCtx:
    args = []


def _clean():
    while True:
        try:
            tb.task_queue.get_nowait()
        except Exception:
            break
    tb._tasks.clear()
    tb._pending_confirm.clear()
    tb._pending_ask.clear()
    tb._running_cancel.clear()
    tb._last_enqueue.clear()
    tb._last_text.clear()


class TestStopReset(unittest.TestCase):
    def setUp(self):
        _clean()

    def tearDown(self):
        _clean()

    def _run(self, coro):
        return asyncio.run(coro)

    def test_stop_clears_all(self):
        tb._tasks["aa"] = {"task": "t1", "chat_id": 50, "msg_id": 1, "uid": 111,
                           "status": "running", "created": time.time(),
                           "updated": time.time(), "result": ""}
        tb._tasks["bb"] = {"task": "t2", "chat_id": 50, "msg_id": 2, "uid": 111,
                           "status": "queued", "created": time.time(),
                           "updated": time.time(), "result": ""}
        tb._running_cancel["aa"] = asyncio.Event()
        tb.task_queue.put_nowait(("bb", "t2", 50, 2, 111))
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        tb._pending_confirm[(50, 9)] = (fut, 111)
        msg = FakeMsg()
        with patch.object(tb.settings, "TELEGRAM_WHITELIST_IDS", [111]):
            self._run(tb.stop_cmd(FakeUpdate(111, msg), FakeCtx()))
        self.assertEqual(tb._tasks["aa"]["status"], "cancelled")
        self.assertEqual(tb._tasks["bb"]["status"], "cancelled")
        self.assertTrue(tb._running_cancel["aa"].is_set())
        self.assertTrue(tb.task_queue.empty())
        self.assertNotIn((50, 9), tb._pending_confirm)
        self.assertTrue(fut.done() and fut.result() is False)
        self.assertTrue(any("Parado" in r for r in msg.replies))
        loop.close()

    def test_reset_clears_state(self):
        tb._tasks["aa"] = {"task": "t1", "chat_id": 50, "msg_id": 1, "uid": 111,
                           "status": "running", "created": time.time(),
                           "updated": time.time(), "result": ""}
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        tb._pending_ask[50] = (fut, "aa")
        tb._last_enqueue[111] = time.time()
        msg = FakeMsg()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(tb.settings, "TELEGRAM_WHITELIST_IDS", [111]), \
                patch.object(tb.settings, "LOG_DIR", tmp):
            self._run(tb.reset_cmd(FakeUpdate(111, msg), FakeCtx()))
        self.assertEqual(tb._tasks["aa"]["status"], "cancelled")
        self.assertEqual(tb._pending_ask, {})
        self.assertEqual(tb._last_enqueue, {})
        self.assertTrue(fut.done() and fut.result() is None)
        self.assertTrue(any("Reset" in r for r in msg.replies))
        loop.close()

    def test_stop_denied_outside_whitelist(self):
        msg = FakeMsg()
        with patch.object(tb.settings, "TELEGRAM_WHITELIST_IDS", [999]):
            self._run(tb.stop_cmd(FakeUpdate(111, msg), FakeCtx()))
        self.assertEqual(msg.replies, [])


class TestGrants(unittest.TestCase):
    def setUp(self):
        _clean()
        tb._pending_grants.clear()

    def tearDown(self):
        _clean()
        tb._pending_grants.clear()

    def _run(self, coro):
        return asyncio.run(coro)

    def test_grant_drive_root_denied(self):
        from tools import permissions as _perm
        with self.assertRaises(Exception):
            _perm.validate_root("C:\\")

    def test_grant_flow_confirm(self):
        import tempfile as _tf
        from tools import permissions as _perm
        tmp = _tf.mkdtemp()
        sub = os.path.join(tmp, "proj", "x")
        os.makedirs(sub)
        msg = FakeMsg()
        ctx = FakeCtx()
        ctx.args = [tmp, "7", "teste"]
        from config import settings as _settings_mod
        with patch.object(tb.settings, "TELEGRAM_WHITELIST_IDS", [111]), \
                patch.object(tb.settings, "LOCAL_TOOLS_ENABLED", True), \
                patch.object(_settings_mod.settings, "GRANTS_PATH",
                             os.path.join(tmp, "grants.json")):
            self._run(tb.grant_cmd(FakeUpdate(111, msg), ctx))
            self.assertTrue(any("confirmar" in r for r in msg.replies))
            tok = next(iter(tb._pending_grants))
            msg2 = FakeMsg()
            u2 = FakeUpdate(111, msg2)
            u2.edited_message = None
            # simula "confirmar <tok>" via enqueue
            m = FakeMsgForConfirm(tok)
            u3 = FakeUpdate(111, m)
            self._run(tb.enqueue(u3, FakeCtx()))
            self.assertTrue(any("Grant" in r for r in m.replies))
            grants = _perm.load(os.path.join(tmp, "grants.json"))
            self.assertEqual(len(grants), 1)


class FakeMsgForConfirm(FakeMsg):
    def __init__(self, tok):
        super().__init__(mid=5, chat=50)
        self.text = f"confirmar {tok}"


class TestGrantParsing(unittest.TestCase):
    def setUp(self):
        _clean()
        tb._pending_grants.clear()

    def tearDown(self):
        _clean()
        tb._pending_grants.clear()

    def test_dias_equals_syntax(self):
        # T3: dias=N explícito; resto é finalidade (mesmo com números)
        import tempfile as _tf
        tmp = _tf.mkdtemp()
        sub = os.path.join(tmp, "meu projeto")
        os.makedirs(sub)
        p, d, purp, err = tb._split_grant_args([sub, "dias=30", "migrar fase 2"])
        self.assertEqual((p, d, purp, err), (sub, 30, "migrar fase 2", ""))

    def test_numeric_purpose_kept(self):
        # T3: "2024" solto é finalidade, não dias
        import tempfile as _tf
        tmp = _tf.mkdtemp()
        p, d, purp, err = tb._split_grant_args([tmp, "2024"])
        self.assertEqual((d, purp, err), (7, "2024", ""))

    def test_expired_proposal_rejected(self):
        # T5: proposta expirada não cria grant
        import tempfile as _tf
        from config import settings as _settings_mod
        tmp = _tf.mkdtemp()
        tb._pending_grants["abc123"] = {"uid": 111, "path": tmp, "days": 7,
                                        "purpose": "x", "exp": 1.0}
        m = FakeMsgForConfirm("abc123")
        with patch.object(tb.settings, "TELEGRAM_WHITELIST_IDS", [111]), \
                patch.object(_settings_mod.settings, "GRANTS_PATH",
                             os.path.join(tmp, "grants.json")):
            asyncio.run(tb.enqueue(FakeUpdate(111, m), FakeCtx()))
        self.assertTrue(any("expirada" in r for r in m.replies))
        self.assertFalse(os.path.exists(os.path.join(tmp, "grants.json")))

    def test_reset_clears_grant_proposals(self):
        # T5/Q-05: reset zera propostas pendentes
        tb._pending_grants["zz"] = {"uid": 1, "path": "x", "days": 1,
                                    "purpose": "", "exp": 9999999999.0}
        msg = FakeMsg()
        with patch.object(tb.settings, "TELEGRAM_WHITELIST_IDS", [111]):
            asyncio.run(tb.reset_cmd(FakeUpdate(111, msg), FakeCtx()))
        self.assertEqual(tb._pending_grants, {})


if __name__ == "__main__":
    unittest.main()
