"""Política centralizada de autorização (determinística, sem LLM).

Toda decisão de "ação sensível?" passa por aqui — orquestrador, testes e
futuras ferramentas usam este módulo, nunca regex espalhado. Níveis:
READ (navegar dentro da política, esperar), WRITE (clicar/digitar comum),
CRITICAL (exige aprovação humana vinculada).
"""
import re
from core.schemas import AgentAction

RISK_READ = "read"
RISK_WRITE = "write"
RISK_CRITICAL = "critical"

_CRIT_RE = re.compile(
    r"\b(compr\w*|buy\w*|purchase\w*|order\w*|pedido|checkout|check-out|"
    r"pag(amento(s)?|ar|a|o|os|as)\b|pay\w*|payment|billet|boleto|pix|transfer\w*|"
    r"enviar|send|submit\w*|"
    r"confirm\w*|finaliz\w*|conclu\w*|apagar|excluir|delet\w*|remov\w*|eras\w*|"
    r"publicar|postar|post\b|publish|tweet|twittar|assinar|subscribe|"
    r"aceitar|permitir|autorizar|sacar|saque|withdraw|criar conta|excluir conta|"
    r"cancel\w* conta)\b", re.I)
_SENSITIVE_PATH_RE = re.compile(
    r"(checkout|confirm|payment|pagamento|transfer|order|pedido|carrinho|/cart|"
    r"/buy|/pay|/delet|/remov|/admin|/account|login|signin|senha|password|2fa|token|api[_-]?key)", re.I)
_SUBMIT_RE = re.compile(r"type\s*=\s*submit", re.I)
_ENTER_KEYS = {"enter", "return"}


def target_label(action: AgentAction, state_text: str) -> str:
    if action.element_id is None:
        return ""
    for line in state_text.splitlines():
        if line.startswith(f"[{action.element_id}]"):
            return line
    return ""


def target_sig(action: AgentAction, state_text: str, meta: dict | None = None) -> str:
    """Assinatura do alvo para revalidação pós-aprovação (F-05/G-06).

    Inclui destino (href sem query), onclick e bbox: mesmo rótulo com
    comportamento trocado gera assinatura distinta.
    """
    import hashlib
    label = re.sub(r"\s+", " ", target_label(action, state_text)).strip().lower()
    m = (meta or {}).get(action.element_id, {}) if action.element_id is not None else {}
    raw = "|".join([action.action_type, label, action.url or "",
                    str(m.get("dest", "")), str(m.get("js", False)),
                    str(tuple(m.get("box", ()))), str(len(action.text_content or ""))])
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def is_critical(action: AgentAction, state_text: str) -> bool:
    """True se a ação concreta exige aprovação humana."""
    try:
        import os as _os
        if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true":
            return False
    except Exception:
        pass
    label = target_label(action, state_text)
    target = f"{label} {action.url or ''} {action.text_content or ''}"
    if action.action_type == "press_key" and \
            (action.text_content or "").strip().lower() in _ENTER_KEYS:
        return True
    if action.action_type == "click" and _SUBMIT_RE.search(label):
        return True
    if action.action_type in ("click", "press_key", "select") and _CRIT_RE.search(target):
        return True
    if action.action_type == "navigate" and action.url \
            and _SENSITIVE_PATH_RE.search(action.url):
        return True
    if action.action_type == "type" and (
            "password" in label.lower() or _CRIT_RE.search(target)):
        return True
    if action.action_type == "upload":
        # Upload de arquivo: crítico se o alvo/página sugere envio,
        # publicação ou pagamento (mesma regra do click/type).
        if _CRIT_RE.search(target) or _SENSITIVE_PATH_RE.search(action.url or ""):
            return True
        if _CRIT_RE.search(f"{action.thought} {action.reason or ''}"):
            return True
        return False
    if _CRIT_RE.search(f"{action.thought} {action.reason or ''}"):
        return True
    return False


def classify(action: AgentAction, state_text: str) -> str:
    """Nível de risco da ação concreta."""
    if action.action_type in ("wait", "finish", "ask_user", "scroll", "reload"):
        return RISK_READ
    if is_critical(action, state_text):
        return RISK_CRITICAL
    if action.action_type == "navigate":
        return RISK_READ
    return RISK_WRITE


_CRED_RE = re.compile(
    r"(senha|password|passwd|api[_-]?key|\btoken\b|\botp\b|2fa|"
    r"c[oó]digo de verifica|verification code|\bsecret\b)", re.I)
_CRED_VERB_RE = re.compile(
    r"(informe|digite|forne[cç]a|envie|diga|passe|compartilhe|qual \u00e9|me (d[êe]|passe))", re.I)
_SECRET_LIKE_RE = re.compile(r"(?=.*[a-z])(?=.*[A-Z])(?=.*[\d\W]).{8,}$")


def asks_for_credential(reason: str) -> bool:
    """True se o pedido é 'me passe sua senha/token' (firewall de credenciais)."""
    r = reason or ""
    return bool(_CRED_RE.search(r) and _CRED_VERB_RE.search(r))


def looks_like_secret(text: str) -> bool:
    """True se o texto parece credencial: palavra-chave + valor colado, ou token forte."""
    t = (text or "").strip()
    if not t:
        return False
    if re.search(r"(senha|password|passwd|api[_-]?key|\btoken\b|\botp\b|2fa|"
                 r"c[oó]digo de verifica|verification code|\bsecret\b)\s*[:=]\s*\S+", t, re.I):
        return True
    if re.search(r"(senha|password|passwd)\s+\S{4,}\s*$", t, re.I):
        return True
    return bool(_SECRET_LIKE_RE.fullmatch(t))


CRED_GUIDANCE = ("Por segurança, não processo senhas, tokens ou códigos pelo chat. "
                 "Faça login manualmente no Chrome do agente (o perfil é persistente) "
                 "e mande a tarefa de novo já logado.")
