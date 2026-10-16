"""Contrato de ferramentas locais: ToolSpec, ToolResult, Registry.

Ferramenta fora do REGISTRY = inexistente para o orquestrador.
"""
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional


@dataclass
class ToolSpec:
    name: str                      # "fs.read_file"
    level: str                     # "A".."F"
    description: str               # o que pode / o que NÃO pode
    params_model: Any              # pydantic BaseModel de entrada
    side_effects: list = field(default_factory=list)
    reversible: bool = True
    needs_approval: str = "never"  # "never" | "first_per_task" | "always"
    # D: None = não declarado (fallback legado); () = explicitamente sem campos
    path_fields: tuple | None = None
    run: Optional[Callable] = None       # async (args, ctx) -> ToolResult
    verify: Optional[Callable] = None    # (ctx, result) -> bool


@dataclass
class ToolResult:
    ok: bool
    data: dict = field(default_factory=dict)   # estruturado, filtrado, truncado
    error_code: str | None = None              # PATH_DENIED | NOT_FOUND | ...
    audit_meta: dict = field(default_factory=dict)  # NUNCA conteúdo


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec):
    if spec.name in REGISTRY:
        raise ValueError(f"ferramenta duplicada: {spec.name}")
    REGISTRY[spec.name] = spec
