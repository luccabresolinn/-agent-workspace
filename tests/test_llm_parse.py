"""Parsing da saída do LLM: narração + JSON, fences, erros. Sem subprocesso."""
import json
import unittest

from llm.client import parse_agent_action, _extract_texts, _opencode_errors


class TestParse(unittest.TestCase):
    def test_direct_json(self):
        a = parse_agent_action('{"thought":"t","action_type":"finish","reason":"ok"}')
        self.assertEqual(a.action_type, "finish")

    def test_narration_prefix(self):
        # Caso real visto em produção: modelo narra antes do JSON
        raw = ('Vou ler o arquivo para responder. {"thought": "vou clicar", '
               '"action_type": "click", "element_id": 2, "url": null, '
               '"text_content": null, "reason": null}')
        a = parse_agent_action(raw)
        self.assertEqual((a.action_type, a.element_id), ("click", 2))

    def test_fences(self):
        raw = '```json\n{"thought":"t","action_type":"wait"}\n```'
        self.assertEqual(parse_agent_action(raw).action_type, "wait")

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            parse_agent_action("   ")

    def test_extract_texts(self):
        line = json.dumps({"type": "text", "part": {"text": "OLA"}})
        self.assertEqual(_extract_texts(line + "\n" + json.dumps({"type": "step_start"})), "OLA")

    def test_error_lines(self):
        line = json.dumps({"type": "error", "error": {"message": "Agent not found"}})
        self.assertIn("Agent not found", _opencode_errors(line))


if __name__ == "__main__":
    unittest.main()
