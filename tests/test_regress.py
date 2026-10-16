"""Regressões da reauditoria v2.3: F-02, F-07, F-13, F-15. Sem rede/browser."""
import asyncio
import unittest

from core.orchestrator import Orchestrator
from core.policy import target_sig
from core.schemas import AgentAction
from interface.telegram_bot import _confirm_key


class TestRedaction(unittest.TestCase):
    def test_hitl_hides_password(self):
        o = Orchestrator()
        a = AgentAction(thought="vou digitar", action_type="type", element_id=1,
                        text_content="s3nh4-s3cr3t4")
        desc = o._describe_action(a, ['[1] input type=password: "senha"'])
        self.assertNotIn("s3nh4", desc)
        self.assertIn("omitido", desc)

    def test_hitl_hides_any_type(self):
        o = Orchestrator()
        a = AgentAction(thought="t", action_type="type", element_id=1,
                        text_content="dado-qualquer")
        desc = o._describe_action(a, ['[1] input type=text valor="x": "nome"'])
        self.assertNotIn("dado-qualquer", desc)

    def test_hitl_shows_key(self):
        # NF-01: tecla de press_key aparece (consentimento informado)
        o = Orchestrator()
        a = AgentAction(thought="t", action_type="press_key", text_content="Enter")
        desc = o._describe_action(a, [])
        self.assertIn("Enter", desc)


class TestDetail(unittest.TestCase):
    def test_press_key_detail_is_key(self):
        # F-13/NF-03: exercita o helper real usado pelo orquestrador
        from core.orchestrator import build_detail
        a = AgentAction(thought="t", action_type="press_key", text_content="Enter")
        self.assertEqual(build_detail(a), "Enter")


class TestConfirmKey(unittest.TestCase):
    def test_no_collision_across_chats(self):
        # F-15: mesmo message_id em chats distintos → chaves distintas
        self.assertNotEqual(_confirm_key(111, 42), _confirm_key(222, 42))
        self.assertEqual(_confirm_key(111, 42), (111, 42))


class TestTargetSig(unittest.TestCase):
    def test_stable_and_sensitive(self):
        a = AgentAction(thought="t", action_type="click", element_id=1)
        s1 = target_sig(a, '[1] button: "Pagar"')
        s2 = target_sig(a, '[1] button: "Pagar"')
        s3 = target_sig(a, '[1] button: "Cancelar"')
        self.assertEqual(s1, s2)
        self.assertNotEqual(s1, s3)


if __name__ == "__main__":
    unittest.main()
