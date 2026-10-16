"""Ferramentas de escrita (níveis C/D). Reversíveis via backup em BACKUP_DIR.

Sem escrita o agente só lê e orienta; com ela (modo autônomo aprova
sozinho) ele gera e corrige arquivos HTML, CSS, JSON de verdade.
"""
import os
import shutil
import time

from pydantic import BaseModel, Field

from tools.base import ToolSpec, ToolResult, register
from tools.safepath import resolve_within, PathDenied


def _roots(ctx: dict) -> list[str]:
    return ctx.get("roots", [])


def _backup_dir() -> str:
    from config.settings import settings
    d = settings.BACKUP_DIR or "./logs/backups"
    os.makedirs(d, exist_ok=True)
    return d


def _backup(path: str):
    try:
        if os.path.isfile(path):
            ts = time.strftime("%Y%m%d_%H%M%S")
            base = os.path.basename(path)
            dst = os.path.join(_backup_dir(), f"{ts}_{base}.bak")
            shutil.copy2(path, dst)
    except Exception:
        pass


class MkdirP(BaseModel):
    path: str


async def _mkdir(a: MkdirP, ctx: dict) -> ToolResult:
    import os as _os
    if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true" and not _roots(ctx):
        p = _os.path.realpath(_os.path.abspath(_os.path.expanduser(a.path)))
        try:
            _os.makedirs(p, exist_ok=True)
            return ToolResult(True, data={"path": p}, audit_meta={"path": p[:150]})
        except Exception as e:
            return ToolResult(False, error_code="MKDIR_FAIL", audit_meta={"error": str(e)[:120]})
    try:
        p = resolve_within(a.path, _roots(ctx))
    except PathDenied as e:
        return ToolResult(False, error_code="PATH_DENIED", audit_meta={"error": str(e)[:120]})
    try:
        os.makedirs(p, exist_ok=True)
        return ToolResult(True, data={"path": p}, audit_meta={"path": p[:150]})
    except Exception as e:
        return ToolResult(False, error_code="MKDIR_FAIL", audit_meta={"error": str(e)[:120]})


class WriteP(BaseModel):
    path: str
    content: str = Field(default="", max_length=500000)
    mkdirs: bool = True


async def _write(a: WriteP, ctx: dict) -> ToolResult:
    import os as _os
    from config.settings import settings
    if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true" and not _roots(ctx):
        p = _os.path.realpath(_os.path.abspath(_os.path.expanduser(a.path)))
    else:
        try:
            p = resolve_within(a.path, _roots(ctx))
        except PathDenied as e:
            return ToolResult(False, error_code="PATH_DENIED", audit_meta={"error": str(e)[:120]})
    if a.mkdirs:
        try:
            parent = os.path.dirname(p)
            if parent:
                os.makedirs(parent, exist_ok=True)
        except Exception as e:
            return ToolResult(False, error_code="MKDIR_FAIL", audit_meta={"error": str(e)[:120]})
    if os.path.isdir(p):
        return ToolResult(False, error_code="IS_DIR", audit_meta={"path": p[:150]})
    _backup(p)
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(a.content or "")
    except Exception as e:
        return ToolResult(False, error_code="WRITE_FAIL", audit_meta={"error": str(e)[:120]})
    return ToolResult(True, data={"path": p, "chars": len(a.content or "")},
                      audit_meta={"path": p[:150], "chars": len(a.content or "")})


register(ToolSpec("fs.mkdir", "C", "Cria diretório (com backup n/a, reversível).",
                  MkdirP, side_effects=["cria diretório"], run=_mkdir,
                  verify=lambda c, r: r.ok, path_fields=("path",)))
register(ToolSpec("fs.write_file", "C", "Cria/sobrescreve arquivo de texto (backup automático do anterior).",
                  WriteP, side_effects=["escreve arquivo"], run=_write,
                  verify=lambda c, r: r.ok and bool(r.data.get("path")), path_fields=("path",)))


class EditP(BaseModel):
    path: str
    old: str = Field(min_length=1, max_length=20000)
    new: str = Field(default="", max_length=20000)
    count: int = Field(default=1, ge=1, le=50)


async def _edit(a: EditP, ctx: dict) -> ToolResult:
    """Troca trecho exato (sem reescrever o arquivo todo). Ideal p/ correções."""
    import os as _os
    if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true" and not _roots(ctx):
        p = _os.path.realpath(_os.path.abspath(_os.path.expanduser(a.path)))
    else:
        try:
            p = resolve_within(a.path, _roots(ctx))
        except PathDenied as e:
            return ToolResult(False, error_code="PATH_DENIED", audit_meta={"error": str(e)[:120]})
    try:
        with open(p, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return ToolResult(False, error_code="NOT_FOUND", audit_meta={"path": p[:150]})
    except OSError as e:
        return ToolResult(False, error_code="NOT_FOUND", audit_meta={"error": str(e)[:120]})
    n = text.count(a.old)
    if n == 0:
        return ToolResult(False, error_code="NOT_FOUND", audit_meta={"hint": "trecho não encontrado"})
    _backup(p)
    text = text.replace(a.old, a.new, a.count)
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        return ToolResult(False, error_code="WRITE_FAIL", audit_meta={"error": str(e)[:120]})
    return ToolResult(True, data={"path": p, "replaced": min(n, a.count)},
                      audit_meta={"path": p[:150], "replaced": min(n, a.count)})


class AppendP(BaseModel):
    path: str
    content: str = Field(default="", max_length=200000)


async def _append(a: AppendP, ctx: dict) -> ToolResult:
    import os as _os
    if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true" and not _roots(ctx):
        p = _os.path.realpath(_os.path.abspath(_os.path.expanduser(a.path)))
    else:
        try:
            p = resolve_within(a.path, _roots(ctx))
        except PathDenied as e:
            return ToolResult(False, error_code="PATH_DENIED", audit_meta={"error": str(e)[:120]})
    if os.path.isdir(p):
        return ToolResult(False, error_code="IS_DIR", audit_meta={"path": p[:150]})
    _backup(p)
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(a.content or "")
    except Exception as e:
        return ToolResult(False, error_code="WRITE_FAIL", audit_meta={"error": str(e)[:120]})
    return ToolResult(True, data={"path": p, "chars": len(a.content or "")},
                      audit_meta={"path": p[:150]})


class DeleteP(BaseModel):
    path: str


async def _delete(a: DeleteP, ctx: dict) -> ToolResult:
    """Apaga arquivo ou pasta vazia (com backup do arquivo). Nível D: sempre aprova."""
    import os as _os
    import shutil as _sh
    if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true" and not _roots(ctx):
        p = _os.path.realpath(_os.path.abspath(_os.path.expanduser(a.path)))
    else:
        try:
            p = resolve_within(a.path, _roots(ctx))
        except PathDenied as e:
            return ToolResult(False, error_code="PATH_DENIED", audit_meta={"error": str(e)[:120]})
    try:
        if os.path.isfile(p):
            _backup(p)
            os.remove(p)
            return ToolResult(True, data={"path": p}, audit_meta={"path": p[:150]})
        if os.path.isdir(p):
            os.rmdir(p)  # só vazia, por segurança
            return ToolResult(True, data={"path": p}, audit_meta={"path": p[:150]})
        return ToolResult(False, error_code="NOT_FOUND", audit_meta={"path": p[:150]})
    except Exception as e:
        return ToolResult(False, error_code="DELETE_FAIL", audit_meta={"error": str(e)[:120]})


class CopyP(BaseModel):
    src: str
    dst: str


async def _copy(a: CopyP, ctx: dict) -> ToolResult:
    import os as _os
    import shutil as _sh
    if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true" and not _roots(ctx):
        s = _os.path.realpath(_os.path.abspath(_os.path.expanduser(a.src)))
        d = _os.path.realpath(_os.path.abspath(_os.path.expanduser(a.dst)))
    else:
        try:
            s = resolve_within(a.src, _roots(ctx))
            d = resolve_within(a.dst, _roots(ctx))
        except PathDenied as e:
            return ToolResult(False, error_code="PATH_DENIED", audit_meta={"error": str(e)[:120]})
    try:
        if os.path.isdir(s):
            _sh.copytree(s, d, dirs_exist_ok=True)
        else:
            parent = os.path.dirname(d)
            if parent:
                os.makedirs(parent, exist_ok=True)
            _backup(d)
            _sh.copy2(s, d)
        return ToolResult(True, data={"src": s, "dst": d}, audit_meta={"dst": d[:150]})
    except Exception as e:
        return ToolResult(False, error_code="COPY_FAIL", audit_meta={"error": str(e)[:120]})


register(ToolSpec("fs.edit_file", "C", "Troca trecho exato dentro do arquivo (backup automático).",
                  EditP, side_effects=["edita arquivo"], run=_edit,
                  verify=lambda c, r: r.ok, path_fields=("path",)))
register(ToolSpec("fs.append_file", "C", "Anexa texto ao final do arquivo (backup automático).",
                  AppendP, side_effects=["edita arquivo"], run=_append,
                  verify=lambda c, r: r.ok, path_fields=("path",)))
register(ToolSpec("fs.delete", "D", "Apaga arquivo (backup) ou pasta vazia. Irreversível sem backup.",
                  DeleteP, side_effects=["apaga"], run=_delete,
                  verify=lambda c, r: r.ok, path_fields=("path",)))
register(ToolSpec("fs.copy", "C", "Copia arquivo ou pasta.",
                  CopyP, side_effects=["cria cópia"], run=_copy,
                  verify=lambda c, r: r.ok, path_fields=("src", "dst")))
