"""Memória deslizante e schemas. Sem I/O."""
import unittest

from core.memory import ShortMemory, Step
from core.schemas import AgentAction


class TestMemory(unittest.TestCase):
    def test_sliding_window(self):
        m = ShortMemory(maxlen=4)
        for i in range(6):
            m.add(Step(n=i, thought="t", action="click", detail="d", url="u"))
        rendered = m.render()
        self.assertNotIn("Passo 0", rendered)
        self.assertNotIn("Passo 1", rendered)
        self.assertIn("Passo 5", rendered)

    def test_empty(self):
        self.assertIn("nenhum", ShortMemory().render())


class TestSchemas(unittest.TestCase):
    def test_valid(self):
        a = AgentAction.model_validate({"thought": "t", "action_type": "finish",
                                        "reason": "ok"})
        self.assertEqual(a.action_type, "finish")

    def test_invalid_type_rejected(self):
        with self.assertRaises(Exception):
            AgentAction.model_validate({"thought": "t", "action_type": "hack"})


if __name__ == "__main__":
    unittest.main()
