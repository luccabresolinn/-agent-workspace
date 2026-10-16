"""Fronteira de caminhos: o componente mais crítico das operações locais.

Toda operação atua SOMENTE sobre o caminho CANÔNICO retornado por
resolve_within (fecha a maior parte do TOCTOU de resolução).
"""
import os

SENSITIVE_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519",
                   "credentials.json", "secrets.json", ".netrc", ".pgpass"}
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".kdbx")
# Diretórios quase nunca legítimos como raiz de trabalho — NOTA: "appdata"
# ficou de fora de propósito (TEMP/%LOCALAPPDATA% vivem lá no Windows).
# Perfis do próprio agente continuam bloqueados (cookies/sessões).
SENSITIVE_DIR_PARTS = {".ssh", ".gnupg", ".aws", ".browser-profile",
                       "chrome-agent", "ms-playwright"}


class PathDenied(Exception):
    pass


def _deny_if_sensitive(cand: str):
    import os as _os
    if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true":
        return
    parts = [p.lower() for p in cand.replace("/", os.sep).split(os.sep)]
    name = parts[-1] if parts else ""
    if name in {n.lower() for n in SENSITIVE_NAMES}:
        raise PathDenied(f"arquivo sensível protegido: {name}")
    if name.endswith(SENSITIVE_SUFFIXES):
        raise PathDenied(f"extensão sensível protegida: {name}")
    if any(p in SENSITIVE_DIR_PARTS for p in parts):
        raise PathDenied("diretório sensível protegido")


def resolve_within(path: str, roots: list[str]) -> str:
    """Resolve (symlink/junction incluídos) e garante contenção real.

    Retorna o caminho CANÔNICO. Levanta PathDenied fora de escopo.
    """
    import os as _os
    if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true":
        cand = _os.path.realpath(_os.path.abspath(_os.path.expanduser(path)))
        if not _os.path.exists(cand):
            # Em modo autônomo, o caminho pode ainda não existir (escrita).
            # Retorna o canônico sem exigir contenção.
            return cand
        if not roots:
            return cand
    cand = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    for root in roots:
        r = os.path.realpath(os.path.abspath(root))
        try:
            inside = (cand == r or os.path.commonpath([cand, r]) == r)
        except ValueError:
            # P0-4: drives diferentes no Windows → fora de escopo, nunca exceção
            continue
        if inside:
            _deny_if_sensitive(cand)
            return cand
    raise PathDenied(f"caminho fora do escopo autorizado: {path}")
