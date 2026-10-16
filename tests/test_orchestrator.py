"""Núcleo de controle com stubs: loop, estagnação, cancel, HITL sem canal, finish.
Sem LLM, sem browser, sem rede."""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

import core.orchestrator as orch_mod
from core.orchestrator import Orchestrator
from core.schemas import AgentAction


class FakeKB:
    def __init__(self, page):
        self.page = page

    async def press(self, key):
        self.page.log.append(("press", key))


class FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.log = []
        self.keyboard = FakeKB(self)

    async def title(self):
        return "t"

    async def goto(self, url, **kw):
        self.url = url
        self.log.append(("goto", url))

    async def click(self, sel, **kw):
        self.log.append(("click", sel))

    async def fill(self, sel, text, **kw):
        self.log.append(("fill", sel))


def scripted_llm(actions):
    class FakeLLM:
        def __init__(self):
            self.i = 0

        async def decide(self, prompt):
            a = actions[min(self.i, len(actions) - 1)]
            self.i += 1
            return a
    return FakeLLM


async def fake_shot(page, name):
    return ""


def run(task_actions, **kw):
    async def go():
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(orch_mod.settings, "LOG_DIR", tmp), \
                patch.object(orch_mod, "LLMClient", scripted_llm(task_actions)), \
                patch.object(orch_mod, "get_page", return_value=FakePage()), \
                patch.object(orch_mod, "screenshot", side_effect=fake_shot):
            orch = Orchestrator()
            prog = []
            async def on_progress(t):
                prog.append(t)
            kwargs = dict(task="t", on_progress=on_progress,
                          on_confirm=kw.get("on_confirm"), task_id="tt",
                          should_stop=kw.get("should_stop"))
            state = kw.get("state", '[1] button: "Ver"')
            with patch.object(orch_mod, "build_indexed_state",
                              return_value=(state, {1: '[data-agent-id="1"]'}, {})):
                res = await orch.run_task(**kwargs)
            return res, prog
    return asyncio.run(go())


def A(atype, **kw):
    d = dict(thought="t", action_type=atype)
    d.update(kw)
    return AgentAction(**d)


class TestLoop(unittest.TestCase):
    def test_repeat_aborts(self):
        res, _ = run([A("click", element_id=1)] * 5)
        self.assertFalse(res.ok)
        self.assertIn("repetidas", res.message)

    def test_stagnation_aborts(self):
        acts = [A("click", element_id=1, thought="a"), A("click", element_id=1, thought="b")] * 3
        # mesma assinatura? não — thought difere mas sig não inclui thought;
        # usa element_ids distintos para forçar só estagnação:
        acts = [A("click", element_id=1), A("type", element_id=1, text_content="x")] * 3
        res, _ = run(acts)
        self.assertFalse(res.ok)
        self.assertIn("não reagiu", res.message)

    def test_critical_no_channel_blocks(self):
        async def nope(text, shot):
            return True
        res, _ = run([A("click", element_id=1)],
                     state='[1] button: "Finalizar compra"', on_confirm=None)
        self.assertFalse(res.ok)
        self.assertIn("Bloqueada", res.message)

    def test_cancel_returns(self):
        res, _ = run([A("wait")], should_stop=lambda: True)
        self.assertFalse(res.ok)
        self.assertIn("cancelada", res.message)

    def test_finish_ok(self):
        res, _ = run([A("finish", reason="feito")])
        self.assertTrue(res.ok)
        self.assertIn("feito", res.message)


if __name__ == "__main__":
    unittest.main()
