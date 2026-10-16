"""Política central (core/policy.py): níveis de risco. Sem I/O."""
import unittest

from core.policy import classify, is_critical, RISK_READ, RISK_WRITE, RISK_CRITICAL
from core.schemas import AgentAction


def act(atype, label="", url=None, text=None, thought="ver"):
    return (AgentAction(thought=thought, action_type=atype, url=url,
                        element_id=1 if label else None, text_content=text),
            f"[1] {label}" if label else "")


class TestClassify(unittest.TestCase):
    def test_read(self):
        a, s = act("navigate", url="https://example.com/a")
        self.assertEqual(classify(a, s), RISK_READ)
        a, s = act("wait")
        self.assertEqual(classify(a, s), RISK_READ)

    def test_write(self):
        a, s = act("click", 'link: "Ver detalhes"')
        self.assertEqual(classify(a, s), RISK_WRITE)

    def test_critical(self):
        a, s = act("click", 'button: "Finalizar compra"')
        self.assertEqual(classify(a, s), RISK_CRITICAL)
        a, s = act("press_key", text="Enter")
        self.assertTrue(is_critical(a, s))
        self.assertEqual(classify(a, s), RISK_CRITICAL)


if __name__ == "__main__":
    unittest.main()
