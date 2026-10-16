"""Filtro de segredos para conteúdo que entra no prompt do modelo."""
import re

_PATTERNS = [
    # chave=valor / chave: valor (aws_, ghp_, sk-, xox-, etc.)
    (re.compile(r"(?i)\b(aws_secret|aws_access|api[_-]?key|secret|senha|password|passwd|pwd|token|private[_-]?key)\b\s*[:=]\s*\S+"),
     "chave redigida"),
    (re.compile(r"\b(AKIA[0-9A-Z]{16}|ghp_[0-9A-Za-z]{20,}|xox[bap]-[0-9A-Za-z-]{10,}|sk-[0-9A-Za-z]{10,})\b"),
     "credencial conhecida"),
    (re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"), "chave privada"),
]


def scrub(text: str, max_chars: int = 200000) -> tuple[str, int]:
    """Redige segredos conhecidos e trunca. Retorna (texto_seguro, n_redações)."""
    out = text or ""
    hits = 0
    for rx, label in _PATTERNS:
        out, n = rx.subn(f"[conteúdo sensível omitido: {label}]", out)
        hits += n
    if len(out) > max_chars:
        out = out[:max_chars] + f"\n…[truncado em {max_chars} chars]"
    return out, hits
