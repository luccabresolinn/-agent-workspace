"""F-03/A-05: classificador de criticidade. Sem LLM, sem browser."""
import unittest

from core.orchestrator import Orchestrator
from core.schemas import AgentAction


def crit(atype, label="", url=None, text=None, thought="ver a pagina"):
    return Orchestrator()._is_critical(
        AgentAction(thought=thought, action_type=atype, url=url,
                    element_id=1 if label else None, text_content=text),
        f"[1] {label}" if label else "")


class TestHitl(unittest.TestCase):
    def test_true_negatives_fixed(self):
        self.assertTrue(crit("click", 'button: "Finalizar compra"'))
        self.assertTrue(crit("click", 'button: "Place order"'))
        self.assertTrue(crit("click", 'button: "Compre agora"'))
        self.assertTrue(crit("click", 'button: "Pagamento"'))
        self.assertTrue(crit("click", 'button: "Enviar"'))
        self.assertTrue(crit("navigate", url="https://loja.com/checkout/confirm"))

    def test_benign(self):
        self.assertFalse(crit("click", 'link: "Ver detalhes"'))
        self.assertFalse(crit("click", 'button: "Repayment history"'))
        self.assertFalse(crit("navigate", url="https://example.com/sobre"))

    def test_password_typing(self):
        self.assertTrue(crit("type", 'input type=password: "senha"', text="s3cr3t"))

    def test_enter_is_critical(self):
        # A-05: Enter sem alvo pode submeter formulário/mensagem/pagamento
        self.assertTrue(crit("press_key", text="Enter"))
        self.assertTrue(crit("press_key", text="Return"))

    def test_submit_button(self):
        self.assertTrue(crit("click", 'button type=submit: "OK"'))
        self.assertTrue(crit("click", 'button: "Aceitar"'))
        self.assertTrue(crit("click", 'button: "Sacar"'))
        self.assertTrue(crit("click", 'button: "Post"'))
        self.assertTrue(crit("click", 'link: "Criar conta"'))

    def test_sensitive_paths(self):
        self.assertTrue(crit("navigate", url="https://x.com/account/delete"))
        self.assertTrue(crit("navigate", url="https://x.com/transferencia"))


if __name__ == "__main__":
    unittest.main()
