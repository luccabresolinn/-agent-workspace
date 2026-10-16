from collections import deque
from dataclasses import dataclass

@dataclass
class Step:
    n: int
    thought: str
    action: str
    detail: str
    url: str
    state_hash: str = ""

class ShortMemory:
    """Histórico deslizante curto — evita estouro de contexto."""
    def __init__(self, maxlen: int = 6):
        self._buf: deque[Step] = deque(maxlen=maxlen)

    def add(self, step: Step):
        self._buf.append(step)

    def render(self) -> str:
        if not self._buf:
            return "(nenhum passo anterior)"
        lines = []
        for s in self._buf:
            lines.append(f"Passo {s.n}: [{s.action}] {s.detail} | thought: {s.thought} | url: {s.url}")
        return "\n".join(lines)

    def last_actions(self, k: int = 3) -> list[str]:
        return [f"{s.action}:{s.detail}" for s in list(self._buf)[-k:]]


def load_task_context(max_items: int = 3) -> str:
    """Memória entre tarefas: últimas conclusões (pasta de site, nomes, URLs).

    Grátis e local (logs/context.json). Sem isso cada tarefa é autocontida.
    """
    import json as _json
    import os as _os
    try:
        from config.settings import settings as _s
        p = _os.path.join(_s.LOG_DIR, "context.json")
        with open(p, encoding="utf-8") as f:
            data = _json.load(f)
        items = [d for d in data if isinstance(d, dict)][-max_items:]
        if not items:
            return "(nenhuma tarefa anterior registrada)"
        lines = []
        for d in items:
            lines.append(f"- [{d.get('tid', '?')}] {str(d.get('task', ''))[:100]} => {str(d.get('result', ''))[:200]}")
        return "\n".join(lines)
    except Exception:
        return "(nenhuma tarefa anterior registrada)"


def save_task_context(tid: str, task: str, result: str, ok: bool):
    """Registra conclusão para a próxima tarefa continuar de onde parou."""
    import json as _json
    import os as _os
    import time as _t
    try:
        from config.settings import settings as _s
        _os.makedirs(_s.LOG_DIR, exist_ok=True)
        p = _os.path.join(_s.LOG_DIR, "context.json")
        try:
            with open(p, encoding="utf-8") as f:
                data = _json.load(f)
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
        data.append({"tid": tid, "task": task[:200], "result": result[:300],
                     "ok": ok, "ts": _t.time()})
        data = data[-10:]
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        _os.replace(tmp, p)
    except Exception:
        pass
