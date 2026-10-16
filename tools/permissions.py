"""Grants e avaliação de permissão para ferramentas locais.

Grant = autorização humana explícita de um diretório-raiz, com expiração.
Criado SOMENTE por comando humano (/grant) — nunca por ferramenta ou modelo.
"""
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict

from tools.safepath import resolve_within, PathDenied


@dataclass
class Grant:
    id: str
    kind: str = "dir_root"          # só dir_root existe por enquanto
    value: str = ""                 # caminho-raiz autorizado
    purpose: str = ""
    granted_by: str = ""
    granted_at: float = 0.0
    expires_at: float = 0.0         # 0 = sem expiração (evitar; /grant usa 7 dias)
    revoked: bool = False

    def active(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if self.revoked or self.kind != "dir_root":
            return False
        if self.expires_at and self.expires_at <= now:
            return False
        return bool(self.value)


def _default_path() -> str:
    from config.settings import settings
    return settings.GRANTS_PATH


def load(path: str | None = None) -> list[Grant]:
    p = path or _default_path()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return [Grant(**g) for g in data if isinstance(g, dict)]
    except (FileNotFoundError, ValueError, TypeError):
        return []


def save(grants: list[Grant], path: str | None = None):
    p = path or _default_path()
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump([asdict(g) for g in grants], f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def create(root: str, purpose: str, granted_by: str, days: int = 7,
           path: str | None = None, validate: bool = True,
           project_root: str | None = None) -> Grant:
    grants = load(path)
    if validate:
        root = validate_root(root, project_root=project_root)
    g = Grant(id=uuid.uuid4().hex[:8], value=os.path.abspath(root), purpose=purpose,
              granted_by=granted_by, granted_at=time.time(),
              expires_at=time.time() + days * 86400 if days > 0 else 0.0)
    grants.append(g)
    save(grants, path)
    return g


def revoke(gid: str, path: str | None = None) -> bool:
    grants = load(path)
    for g in grants:
        if g.id == gid and not g.revoked:
            g.revoked = True
            save(grants, path)
            return True
    return False


def active_roots(grants: list[Grant] | None = None, path: str | None = None) -> list[str]:
    grants = load(path) if grants is None else grants
    now = time.time()
    return [g.value for g in grants if g.active(now)]


def validate_root(path: str, project_root: str | None = None) -> str:
    """Higiene de escopo para /grant (P0-2). Retorna realpath ou levanta PathDenied."""
    from tools.safepath import SENSITIVE_DIR_PARTS
    real = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    if not os.path.isdir(real):
        raise PathDenied("caminho inexistente ou não é diretório")
    # Raiz de drive: C:\ → dirname == ele mesmo
    if os.path.dirname(real) == real:
        raise PathDenied("raiz de drive não pode ser concedida")
    parts = [p.lower() for p in real.replace("/", os.sep).split(os.sep) if p]
    # Profundidade mínima: ao menos 2 níveis (ex.: C:\\Users\\x OK; C:\\dados NÃO)
    if len(parts) < 3:  # ['c:', ...] conta o drive
        raise PathDenied("escopo muito amplo (mínimo 2 níveis abaixo do drive)")
    sysdirs = {"windows", "program files", "program files (x86)", "programdata"}
    if parts[1] in sysdirs if len(parts) > 1 else False:
        raise PathDenied("diretório de sistema protegido")
    # Raiz do perfil do usuário sem subdiretório (C:\Users\<nome> puro)
    if len(parts) == 3 and parts[1] in ("users", "home"):
        raise PathDenied("raiz do perfil sem subdiretório")
    # Repo do próprio agente nunca é raiz concedível
    if project_root:
        pr = os.path.realpath(os.path.abspath(project_root))
        try:
            inside_repo = (real == pr or os.path.commonpath([real, pr]) == pr)
        except ValueError:
            inside_repo = False  # drives distintos → nunca é o repo (Q-04)
        if inside_repo:
            raise PathDenied("diretório do agente não pode ser concedido")
    # Componentes sensíveis no caminho (.ssh, perfil do Chrome do agente...)
    if any(p in SENSITIVE_DIR_PARTS for p in parts):
        raise PathDenied("caminho contém diretório sensível")
    return real


def operation_sig(tool: str, args: dict) -> str:
    """Assinatura estável p/ vincular aprovação a parâmetros exatos."""
    canon = json.dumps({"tool": tool, "args": args or {}}, sort_keys=True,
                       ensure_ascii=False, default=str)
    return hashlib.md5(canon.encode()).hexdigest()[:12]


def path_args_of(spec, args: dict) -> list[str]:
    """Campos de caminho vêm da DECLARAÇÃO do ToolSpec, não de adivinhação (H-05).

    D: None (não declarado) → fallback legado por nome; () explícito → nenhum.
    """
    declared = getattr(spec, "path_fields", None)
    fields = declared if declared is not None else ("path", "root", "dir", "file")
    return [str(v) for k, v in (args or {}).items()
            if k in fields and isinstance(v, str)]


def evaluate(spec_name: str, level: str, args: dict, grants: list[Grant],
             task_ctx: dict, spec=None) -> tuple[str, str]:
    """Retorna (ALLOW | APPROVE | DENY, detalhe). Determinística, sem LLM.

    Com spec (ToolSpec), os campos de caminho vêm da declaração (H-05);
    sem spec, usa o palpite legado por nome de campo.
    """
    import os as _os
    if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true":
        if level == "F":
            return "DENY", "ferramenta proibida"
        return "ALLOW", "modo autônomo: auto-aprovado"
    if level == "F":
        return "DENY", "ferramenta proibida"
    roots = [g.value for g in grants if g.active()]
    if not roots:
        return "DENY", "sem grant vigente — use /grant"
    # Contenção de todo argumento de caminho declarado (fail-closed)
    try:
        for p in path_args_of(spec if spec is not None else spec_name, args):
            resolve_within(p, roots)
    except PathDenied as e:
        return "DENY", str(e)
    if level in ("A", "B"):
        return "ALLOW", "observação/leitura em escopo"
    sig = operation_sig(spec_name, args)
    approved = task_ctx.setdefault("approved_sigs", set())
    if level == "C":
        if sig in approved:
            return "ALLOW", "assinatura já aprovada nesta tarefa"
        return "APPROVE", "escrita reversível: primeira vez por assinatura"
    return "APPROVE", f"nível {level}: aprovação sempre por operação"
