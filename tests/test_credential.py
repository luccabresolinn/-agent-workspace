"""v2.6: firewall de credenciais e Q&A. Sem rede/browser real."""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

import core.orchestrator as orch_mod
from core.orchestrator import Orchestrator
from core.policy import asks_for_credential, looks_like_secret, CRED_GUIDANCE
from core.schemas import AgentAction


class TestCredentialHelpers(unittest.TestCase):
    def test_ask_detected(self):
        self.assertTrue(asks_for_credential("informe a senha da conta x@y.com para continuar"))
        self.assertTrue(asks_for_credential("Digite seu token para prosseguir"))
        self.assertFalse(asks_for_credential("qual site devo abrir?"))
        self.assertFalse(asks_for_credential("Necessário saber o tipo de site"))

    def test_secret_detected(self):
        self.assertTrue(looks_like_secret("senha Lucca@123"))
        self.assertTrue(looks_like_secret("Lucca@123"))
        self.assertTrue(looks_like_secret("password: abc123!@#"))
        self.assertFalse(looks_like_secret("site para idosos sobre dor nas costas"))
        self.assertFalse(looks_like_secret("a senha da conta x@gmail.com"))
        self.assertFalse(looks_like_secret("netlify"))
        self.assertFalse(looks_like_secret(""))


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


def run_ask(actions, answers):
    """answers: lista de retornos do on_ask. Retorna (res, ask_calls, logdir)."""
    async def go(tmp):
        calls = []
        async def on_ask(q, shot):
            calls.append(q)
            return answers[min(len(calls) - 1, len(answers) - 1)]
        async def prog(t):
            pass
        with patch.object(orch_mod.settings, "LOG_DIR", tmp), \
                patch.object(orch_mod, "LLMClient", scripted(actions)), \
                patch.object(orch_mod, "get_page", return_value=FakePage()), \
                patch.object(orch_mod, "screenshot", side_effect=fake_shot), \
                patch.object(orch_mod, "build_indexed_state",
                             return_value=("", {}, {})):
            orch = Orchestrator()
            res = await orch.run_task("t", on_progress=prog, on_confirm=None,
                                      on_ask=on_ask, task_id="tt")
            return res, calls
    tmp = tempfile.mkdtemp(prefix="credtest-")
    try:
        res, calls = asyncio.run(go(tmp))
    finally:
        pass
    logp = os.path.join(tmp, "agent.log")
    log = open(logp, encoding="utf-8").read() if os.path.exists(logp) else ""
    return res, calls, log


def A(atype, **kw):
    d = dict(thought="t", action_type=atype)
    d.update(kw)
    return AgentAction(**d)


class TestAskFirewall(unittest.TestCase):
    def test_ask_for_password_blocked_without_user(self):
        res, calls, log = run_ask(
            [A("ask_user", reason="informe a senha da conta para continuar")], [])
        self.assertFalse(res.ok)
        self.assertIn("não processo senhas", res.message)
        self.assertEqual(calls, [], "usuário nem deve ser perguntado")

    def test_secret_answer_aborted_and_not_logged(self):
        res, calls, log = run_ask(
            [A("ask_user", reason="qual o nome do site?"),
             A("finish", reason="ok")],
            ["MinhaSenh@123"])
        self.assertFalse(res.ok)
        self.assertIn("não processo senhas", res.message)
        self.assertNotIn("MinhaSenh@123", log)

    def test_normal_answer_flows(self):
        res, calls, log = run_ask(
            [A("ask_user", reason="qual o tema do site?"),
             A("finish", reason="site pronto")],
            ["loja de bolos"])
        self.assertTrue(res.ok)
        self.assertEqual(len(calls), 1)
        # resposta comum alimenta a memória (vai ao LLM), mas não ao log
        self.assertIn("ask_decision", log)

    def test_no_answer_cancels(self):
        res, calls, log = run_ask(
            [A("ask_user", reason="qual o tema?")], [None])
        self.assertFalse(res.ok)
        self.assertIn("Sem resposta", res.message)

    def test_task_with_password_redacted_in_log(self):
        from core.orchestrator import _redact
        self.assertIn("[redacted]", _redact('task "senha Xy@99ab" aqui'))
        self.assertNotIn("Xy@99ab", _redact('task "senha Xy@99ab" aqui'))
        self.assertIn("a senha da conta", _redact("fale sobre a senha da conta"))


if __name__ == "__main__":
    unittest.main()
