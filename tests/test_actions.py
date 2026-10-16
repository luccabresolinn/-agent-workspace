"""A-06: texto digitado nunca é ecoado. Stub de página, sem browser."""
import asyncio
import unittest

from browser.actions import do_action
from core.schemas import AgentAction


class FakePage:
    def __init__(self):
        self.filled = {}

    async def fill(self, sel, text, timeout=None):
        self.filled[sel] = text


class TestNoEcho(unittest.TestCase):
    def test_type_result_hides_secret(self):
        page = FakePage()
        a = AgentAction(thought="t", action_type="type", element_id=3,
                        text_content="s3nh4-sup3r-s3cr3t4")
        res = asyncio.run(do_action(page, a, {3: '[data-agent-id="3"]'}))
        self.assertNotIn("s3nh4", res)
        self.assertIn("[3]", res)
        self.assertEqual(page.filled['[data-agent-id="3"]'], "s3nh4-sup3r-s3cr3t4")


if __name__ == "__main__":
    unittest.main()
