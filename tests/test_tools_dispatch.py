"""Despacho tool + modo de tarefa. Stubs; FS só em tmp."""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

import core.orchestrator as orch_mod
from core.orchestrator import Orchestrator
from core.schemas import AgentAction
from tools import permissions as perm


class FakePage:
    url = "about:blank"

    async def title(self):
        return "t"


async def fake_shot(page, name):
    return ""


def scripted(actions):
    class FakeLLM:
        def __init__(self):
            self.i = 0

        async def decide(self, prompt):
            a = actions[min(self.i, len(actions) - 1)]
            self.i += 1
            return a
    return FakeLLM


def A(atype, **kw):
    d = dict(thought="t", action_type=atype)
    d.update(kw)
    return AgentAction(**d)


class Ctx:
    """Harness: flag on + grants em tmp + LLM fake."""
    def __init__(self, actions, root=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.gfile = os.path.join(self.tmp.name, "grants.json")
        self.root = root or os.path.join(self.tmp.name, "proj")
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, "a.txt"), "w") as f:
            f.write("conteudo de teste\n")
        perm.create(self.root, "teste", "tester", days=1, path=self.gfile)
        self.actions = actions
        self.confirms = 0

    async def __aenter__(self):
        self._p = [
            patch.object(orch_mod.settings, "LOCAL_TOOLS_ENABLED", True),
            patch.object(orch_mod.settings, "GRANTS_PATH", self.gfile),
            patch.object(orch_mod.settings, "LOG_DIR", self.tmp.name),
            patch.object(orch_mod, "LLMClient", scripted(self.actions)),
            patch.object(orch_mod, "get_page", return_value=FakePage()),
            patch.object(orch_mod, "screenshot", side_effect=fake_shot),
        ]
        for p in self._p:
            p.start()
        return self

    async def __aexit__(self, *a):
        for p in reversed(self._p):
            p.stop()
        self.tmp.cleanup()

    async def confirm_yes(self, text, shot):
        self.confirms += 1
        return True

    async def prog(self, t):
        pass


class TestDispatch(unittest.TestCase):
    def test_flag_off_denies(self):
        async def go():
            with patch.object(orch_mod.settings, "LOCAL_TOOLS_ENABLED", False):
                orch = Orchestrator()
                r = await orch._run_tool(A("tool", tool="fs.list_dir", args={"path": "/x"}),
                                         {"tid": "t"}, "t", "u", None, None)
                return r
        self.assertIn("desligadas", asyncio.run(go()))

    def test_unknown_tool(self):
        async def go():
            async with Ctx([]) as c:
                orch = Orchestrator()
                return await orch._run_tool(A("tool", tool="fs.nope", args={}),
                                            {"tid": "t"}, "t", "u", None, None)
        self.assertIn("desconhecida", asyncio.run(go()))

    def test_invalid_args(self):
        async def go():
            async with Ctx([]) as c:
                orch = Orchestrator()
                return await orch._run_tool(A("tool", tool="fs.list_dir", args={"depth": 99}),
                                            {"tid": "t"}, "t", "u", None, None)
        self.assertIn("inválidos", asyncio.run(go()))

    def test_read_level_a_no_approval(self):
        async def go():
            async with Ctx([]) as c:
                orch = Orchestrator()
                r = await orch._run_tool(
                    A("tool", tool="fs.list_dir", args={"path": c.root}),
                    {"tid": "t"}, "t", "u", c.confirm_yes, c.prog)
                return r, c.confirms
        r, n = asyncio.run(go())
        self.assertIn("ok", r)
        self.assertEqual(n, 0)

    def test_outside_grant_denied(self):
        async def go():
            async with Ctx([]) as c:
                orch = Orchestrator()
                return await orch._run_tool(
                    A("tool", tool="fs.read_file", args={"path": "C:\\Windows\\x"}),
                    {"tid": "t"}, "t", "u", c.confirm_yes, c.prog)
        self.assertIn("NEGADO", asyncio.run(go()))

    def test_mode_switch_blocks_navigate(self):
        async def go():
            async with Ctx([A("tool", tool="fs.list_dir", args={"path": "ROOT"}),
                            A("navigate", url="https://example.com/"),
                            A("finish", reason="fim")]) as c:
                # injeta root real na 1ª ação
                c.actions[0] = A("tool", tool="fs.list_dir", args={"path": c.root})
                orch = Orchestrator()
                state = '[1] link: "x"'
                with patch.object(orch_mod, "build_indexed_state",
                                  return_value=(state, {1: "s"}, {})):
                    res = await orch.run_task("tarefa local", on_progress=c.prog,
                                              on_confirm=c.confirm_yes, task_id="tt")
                    with open(os.path.join(c.tmp.name, "agent.log"), encoding="utf-8") as f:
                        log = f.read()
                    return res, log
        res, log = asyncio.run(go())
        self.assertTrue(res.ok)  # finish chega; navigate foi barrado no meio
        self.assertIn("mode_switch", log)
        self.assertIn("blocked_mode", log)

    def test_local_mode_blocks_all_browser_actions(self):
        # P0-1: type/click após tool não tocam na página
        async def go():
            async with Ctx([A("tool", tool="fs.list_dir", args={"path": "ROOT"}),
                            A("type", element_id=1, text_content="ola"),
                            A("click", element_id=1),
                            A("finish", reason="fim")]) as c:
                c.actions[0] = A("tool", tool="fs.list_dir", args={"path": c.root})
                orch = Orchestrator()
                states = [(f"[1] input type=text valor=\"\": \"n{i}\"", {1: "s"}, {})
                          for i in range(8)]
                seen = {}

                async def spy_do(page, action, id_map):
                    seen[action.action_type] = seen.get(action.action_type, 0) + 1
                    return "fake-ok"

                with patch.object(orch_mod, "build_indexed_state",
                                  side_effect=states), \
                     patch.object(orch_mod, "do_action", side_effect=spy_do):
                    res = await orch.run_task("tarefa local", on_progress=c.prog,
                                              on_confirm=c.confirm_yes, task_id="tt")
                    with open(os.path.join(c.tmp.name, "agent.log"), encoding="utf-8") as f:
                        log = f.read()
                    return res, log, seen
        res, log, seen = asyncio.run(go())
        self.assertTrue(res.ok)
        self.assertNotIn("type", seen)
        self.assertNotIn("click", seen)
        self.assertEqual(log.count("blocked_mode"), 2)

    def test_mixed_without_allowlist_blocks_navigate(self):
        async def go():
            async with Ctx([A("navigate", url="https://example.com/"),
                            A("finish", reason="fim")]) as c:
                orch = Orchestrator()
                state = '[1] link: "x"'
                with patch.object(orch_mod, "build_indexed_state",
                                  return_value=(state, {1: "s"}, {})), \
                     patch.object(orch_mod.settings, "TASK_MODE_DEFAULT", "mixed"):
                    res = await orch.run_task("tarefa", on_progress=c.prog,
                                              on_confirm=c.confirm_yes, task_id="tt")
                    with open(os.path.join(c.tmp.name, "agent.log"), encoding="utf-8") as f:
                        log = f.read()
                    return res, log
        with patch.dict(os.environ, {"ALLOWED_DOMAINS": ""}, clear=False):
            res, log = asyncio.run(go())
        self.assertTrue(res.ok)
        self.assertIn("blocked_mode", log)

    def test_mixed_symmetric_no_page_writes(self):
        # T6/Achado B: em mixed, type/click bloqueados; navigate allowlisted passa
        async def go():
            async with Ctx([A("tool", tool="fs.list_dir", args={"path": "ROOT"}),
                            A("type", element_id=1, text_content="ola"),
                            A("click", element_id=1),
                            A("navigate", url="https://example.com/"),
                            A("finish", reason="fim")]) as c:
                c.actions[0] = A("tool", tool="fs.list_dir", args={"path": c.root})
                orch = Orchestrator()
                seen = {}

                async def spy_do(page, action, id_map):
                    seen[action.action_type] = seen.get(action.action_type, 0) + 1
                    return "fake-ok"

                states = [(f"[1] x {i}", {1: "s"}, {}) for i in range(10)]
                with patch.object(orch_mod, "build_indexed_state", side_effect=states), \
                     patch.object(orch_mod, "do_action", side_effect=spy_do), \
                     patch.object(orch_mod.settings, "TASK_MODE_DEFAULT", "mixed"):
                    with patch.dict(os.environ, {"ALLOWED_DOMAINS": "example.com"}):
                        res = await orch.run_task("t", on_progress=c.prog,
                                                  on_confirm=c.confirm_yes, task_id="tt")
                        with open(os.path.join(c.tmp.name, "agent.log"), encoding="utf-8") as f:
                            log = f.read()
                        return res, log, seen
        res, log, seen = asyncio.run(go())
        self.assertTrue(res.ok)
        self.assertNotIn("type", seen)
        self.assertNotIn("click", seen)
        self.assertIn("navigate", seen)
        self.assertIn("mode_switch", log)
        self.assertIn("blocked_mode", log)

    def test_broken_tools_import_flag_off(self):
        # T8/Achado C: tools/ quebrado + flag off + tool alucinada → erro estruturado
        import sys as _sys
        async def go():
            async with Ctx([A("tool", tool="fs.nope", args={}),
                            A("finish", reason="fim")]) as c:
                orch = Orchestrator()
                with patch.object(orch_mod, "build_indexed_state",
                                  return_value=("(modo local: sem página)", {}, {})), \
                     patch.object(orch_mod.settings, "LOCAL_TOOLS_ENABLED", False), \
                     patch.dict(_sys.modules, {"tools.permissions": None}):
                    res = await orch.run_task("t", on_progress=c.prog,
                                              on_confirm=c.confirm_yes, task_id="tt")
                    return res
        res = asyncio.run(go())
        self.assertTrue(res.ok)

    def test_tool_skips_browser_hitl(self):        # P1-6: thought crítico em tool usa aprovação da ferramenta, não HITL
        async def go():
            async with Ctx([A("tool", tool="fs.list_dir",
                               args={"path": "ROOT"}, thought="vou enviar o relatório"),
                            A("finish", reason="fim")]) as c:
                c.actions[0] = A("tool", tool="fs.list_dir", args={"path": c.root},
                                 thought="vou enviar o relatório")
                orch = Orchestrator()
                calls = []

                async def spy_confirm(text, shot):
                    calls.append(text)
                    return True

                state = '[1] link: "x"'
                with patch.object(orch_mod, "build_indexed_state",
                                  return_value=(state, {1: "s"}, {})):
                    res = await orch.run_task("t", on_progress=c.prog,
                                              on_confirm=spy_confirm, task_id="tt")
                    return res, calls
        res, calls = asyncio.run(go())
        self.assertTrue(res.ok)
        self.assertEqual(calls, [], "tool nível A não deve pedir HITL de navegador")

    def test_five_distinct_tools_finish(self):
        # T1 (Q-01): 5 tools distintas consecutivas concluem (sem aborto espúrio)
        async def go():
            async with Ctx([]) as c:
                orch = Orchestrator()
                c.actions.extend([
                    A("tool", tool="fs.list_dir", args={"path": c.root}),
                    A("tool", tool="fs.stat", args={"path": c.root}),
                    A("tool", tool="fs.hash", args={"path": os.path.join(c.root, "a.txt")}),
                    A("tool", tool="fs.read_file", args={"path": os.path.join(c.root, "a.txt")}),
                    A("tool", tool="fs.search_names", args={"root": c.root}),
                    A("finish", reason="fim"),
                ])
                with patch.object(orch_mod, "build_indexed_state",
                                  return_value=("(modo local: sem página)", {}, {})):
                    res = await orch.run_task("tarefa local", on_progress=c.prog,
                                              on_confirm=c.confirm_yes, task_id="tt")
                    with open(os.path.join(c.tmp.name, "agent.log"), encoding="utf-8") as f:
                        log = f.read()
                    return res, log
        res, log = asyncio.run(go())
        self.assertTrue(res.ok)
        self.assertEqual(log.count('"ev": "tool_exec"'), 5)

    def test_three_identical_tools_abort(self):
        # T2 (Q-01): mesma tool+args 3x aborta por repetição (sem 4ª execução)
        async def go():
            async with Ctx([]) as c:
                orch = Orchestrator()
                arg = {"path": c.root}
                c.actions.extend([A("tool", tool="fs.list_dir", args=arg)] * 5 + [A("finish", reason="x")])
                with patch.object(orch_mod, "build_indexed_state",
                                  return_value=("(modo local: sem página)", {}, {})):
                    res = await orch.run_task("tarefa local", on_progress=c.prog,
                                              on_confirm=c.confirm_yes, task_id="tt")
                    with open(os.path.join(c.tmp.name, "agent.log"), encoding="utf-8") as f:
                        log = f.read()
                    return res, log
        res, log = asyncio.run(go())
        self.assertFalse(res.ok)
        self.assertIn("repetidas", res.message)
        self.assertEqual(log.count('"ev": "tool_exec"'), 2)


if __name__ == "__main__":
    unittest.main()
