"""Ferramentas de leitura (níveis A/B). Sem escrita, sem execução."""
import fnmatch
import hashlib
import os
import re

from pydantic import BaseModel, Field

from tools.base import ToolSpec, ToolResult, register
from tools.safepath import resolve_within, PathDenied
from tools.secretscan import scrub


def _roots(ctx: dict) -> list[str]:
    return ctx.get("roots", [])


def _lim_chars(ctx: dict) -> int:
    from config.settings import settings
    return int(ctx.get("max_chars") or settings.FS_MAX_RESULT_CHARS)


class ListDirP(BaseModel):
    path: str
    depth: int = Field(default=1, ge=1, le=3)
    limit: int = Field(default=200, ge=1, le=500)


async def _list_dir(a: ListDirP, ctx: dict) -> ToolResult:
    try:
        root = resolve_within(a.path, _roots(ctx))
    except PathDenied as e:
        return ToolResult(False, error_code="PATH_DENIED", audit_meta={"error": str(e)[:120]})
    if not os.path.isdir(root):
        return ToolResult(False, error_code="NOT_FOUND", audit_meta={"path": root[:150]})
    out, base_depth = [], root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        rel_depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
        if rel_depth > a.depth:
            dirnames[:] = []
            continue
        for n in sorted(dirnames)[:a.limit]:
            out.append({"name": n + "/", "type": "dir"})
        for n in sorted(filenames)[:a.limit]:
            fp = os.path.join(dirpath, n)
            try:
                sz = os.path.getsize(fp)
            except OSError:
                sz = -1
            out.append({"name": os.path.relpath(fp, root), "type": "file", "size": sz})
        if len(out) >= a.limit:
            out = out[:a.limit]
            break
    return ToolResult(True, data={"path": root, "entries": out, "count": len(out)},
                      audit_meta={"path": root[:150], "count": len(out)})


class StatP(BaseModel):
    path: str
    sha256: bool = False


async def _stat(a: StatP, ctx: dict) -> ToolResult:
    try:
        p = resolve_within(a.path, _roots(ctx))
    except PathDenied as e:
        return ToolResult(False, error_code="PATH_DENIED", audit_meta={"error": str(e)[:120]})
    try:
        st = os.stat(p)
    except FileNotFoundError:
        return ToolResult(False, error_code="NOT_FOUND", audit_meta={"path": p[:150]})
    except OSError as e:
        return ToolResult(False, error_code="NOT_FOUND", audit_meta={"error": str(e)[:120]})
    data = {"path": p, "size": st.st_size, "mtime": st.st_mtime,
            "is_dir": os.path.isdir(p)}
    if a.sha256 and os.path.isfile(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        data["sha256"] = h.hexdigest()
    return ToolResult(True, data=data,
                      audit_meta={"path": p[:150], "size": data["size"]})


class ReadP(BaseModel):
    path: str
    max_chars: int = Field(default=60000, ge=1, le=200000)


async def _read(a: ReadP, ctx: dict) -> ToolResult:
    try:
        p = resolve_within(a.path, _roots(ctx))
    except PathDenied as e:
        return ToolResult(False, error_code="PATH_DENIED", audit_meta={"error": str(e)[:120]})
    try:
        size = os.path.getsize(p)
    except OSError:
        return ToolResult(False, error_code="NOT_FOUND", audit_meta={"path": p[:150]})
    from config.settings import settings
    if size > settings.FS_MAX_FILE_MB * 1024 * 1024:
        return ToolResult(False, error_code="SIZE_LIMIT", audit_meta={"size": size})
    with open(p, "rb") as f:
        raw = f.read(settings.FS_MAX_FILE_MB * 1024 * 1024 + 1)
    if b"\x00" in raw[:8192]:
        return ToolResult(False, error_code="BINARY", audit_meta={"path": p[:150]})
    text = raw.decode("utf-8", errors="replace")
    clean, hits = scrub(text, min(a.max_chars, _lim_chars(ctx)))
    return ToolResult(True, data={"path": p, "content": clean, "redacted": hits},
                      audit_meta={"path": p[:150], "chars": len(clean), "redacted": hits})


class SearchNamesP(BaseModel):
    root: str
    pattern: str = Field(default="*", max_length=100)
    limit: int = Field(default=200, ge=1, le=500)


async def _search_names(a: SearchNamesP, ctx: dict) -> ToolResult:
    try:
        root = resolve_within(a.root, _roots(ctx))
    except PathDenied as e:
        return ToolResult(False, error_code="PATH_DENIED", audit_meta={"error": str(e)[:120]})
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for n in filenames:
            if fnmatch.fnmatch(n, a.pattern):
                out.append(os.path.relpath(os.path.join(dirpath, n), root))
                if len(out) >= a.limit:
                    return ToolResult(True, data={"root": root, "paths": out},
                                      audit_meta={"count": len(out)})
    return ToolResult(True, data={"root": root, "paths": out},
                      audit_meta={"count": len(out)})


class SearchContentP(BaseModel):
    root: str
    regex: str = Field(max_length=200)
    max_results: int = Field(default=50, ge=1, le=50)


async def _search_content(a: SearchContentP, ctx: dict) -> ToolResult:
    try:
        root = resolve_within(a.root, _roots(ctx))
    except PathDenied as e:
        return ToolResult(False, error_code="PATH_DENIED", audit_meta={"error": str(e)[:120]})
    try:
        rx = re.compile(a.regex)
    except re.error as e:
        return ToolResult(False, error_code="BAD_REGEX", audit_meta={"error": str(e)[:120]})
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for n in filenames:
            fp = os.path.join(dirpath, n)
            try:
                if os.path.getsize(fp) > 1024 * 1024:
                    continue
                with open(fp, "r", encoding="utf-8", errors="strict") as f:
                    for i, line in enumerate(f, 1):
                        if rx.search(line):
                            snippet, hits = scrub(line.strip()[:300], 300)
                            out.append({"file": os.path.relpath(fp, root), "line": i,
                                        "text": snippet})
                            if len(out) >= a.max_results:
                                return ToolResult(True, data={"root": root, "hits": out},
                                                  audit_meta={"count": len(out)})
            except (OSError, UnicodeDecodeError):
                continue
    return ToolResult(True, data={"root": root, "hits": out},
                      audit_meta={"count": len(out)})


class HashP(BaseModel):
    path: str


async def _hash(a: HashP, ctx: dict) -> ToolResult:
    r = await _stat(StatP(path=a.path, sha256=True), ctx)
    if not r.ok:
        return r
    return ToolResult(True, data={"path": r.data["path"], "sha256": r.data.get("sha256")},
                      audit_meta={"path": r.data["path"][:150]})


register(ToolSpec("fs.list_dir", "A", "Lista diretório (nomes, sem conteúdo).",
                  ListDirP, side_effects=["nenhum"], run=_list_dir,
                  verify=lambda c, r: r.ok, path_fields=("path",)))
register(ToolSpec("fs.stat", "A", "Metadados de caminho + sha256 opcional.",
                  StatP, side_effects=["nenhum"], run=_stat,
                  verify=lambda c, r: r.ok, path_fields=("path",)))
register(ToolSpec("fs.read_file", "B", "Lê texto com filtro de segredos e truncamento.",
                  ReadP, side_effects=["nenhum"], run=_read,
                  verify=lambda c, r: r.ok and "content" in r.data, path_fields=("path",)))
register(ToolSpec("fs.search_names", "A", "Busca nomes por glob (sem conteúdo).",
                  SearchNamesP, side_effects=["nenhum"], run=_search_names,
                  verify=lambda c, r: r.ok, path_fields=("root",)))
register(ToolSpec("fs.search_content", "B", "Busca regex com trechos filtrados.",
                  SearchContentP, side_effects=["nenhum"], run=_search_content,
                  verify=lambda c, r: r.ok, path_fields=("root",)))
register(ToolSpec("fs.hash", "B", "SHA-256 de arquivo (p/ pré-condições).",
                  HashP, side_effects=["nenhum"], run=_hash,
                  verify=lambda c, r: r.ok and bool(r.data.get("sha256")), path_fields=("path",)))
