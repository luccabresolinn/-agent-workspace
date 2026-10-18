"""Interface Telegram: fila limitada, registry com IDs, comandos e cancelamento."""
import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from config.settings import settings
from core.orchestrator import Orchestrator

VERSION = "2.9.3"

orch = Orchestrator()
task_queue: asyncio.Queue = asyncio.Queue(maxsize=settings.QUEUE_MAX)
# (chat_id, msg_id) -> (future, allowed_uid) — message_id só é único por chat (F-15)
_pending_confirm: dict[tuple[int, int], tuple[asyncio.Future, int]] = {}

def _confirm_key(chat_id: int, msg_id: int) -> tuple[int, int]:
    return (chat_id, msg_id)

# chat_id -> (future_resposta, tid): pergunta pendente; próxima mensagem
# do solicitante resolve como RESPOSTA, não como tarefa nova (v2.6)
_pending_ask: dict[int, tuple[asyncio.Future, str]] = {}
# tid -> {task, chat_id, msg_id, uid, status, created, updated, result}
_tasks: dict[str, dict] = {}
_history: list[dict] = []
_running_cancel: dict[str, asyncio.Event] = {}
_last_enqueue: dict[int, float] = {}
_last_text: dict[int, tuple[str, float]] = {}
_START_TIME = time.time()

def _history_path() -> str:
    return os.path.join(settings.LOG_DIR, "history.json")

def _load_history():
    try:
        with open(_history_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            _history.extend(data[-settings.HISTORY_MAX:])
    except Exception:
        pass

def _save_history():
    # F-17: escrita atômica — crash no meio não corrompe o arquivo anterior
    try:
        os.makedirs(settings.LOG_DIR, exist_ok=True)
        tmp = os.path.join(settings.LOG_DIR, "history.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_history[-settings.HISTORY_MAX:], f, ensure_ascii=False)
        os.replace(tmp, _history_path())
    except Exception:
        pass

_load_history()

HELP_TEXT = (
    "🤖 *Agente de navegação*\n\n"
    "Envie uma tarefa em texto. Ex:\n"
    "`abra o example.com e me diga o título`\n\n"
    "*Comandos:*\n"
    "/help — esta ajuda\n"
    "/status — fila, tarefa atual e histórico\n"
    "/cancel `<id>` — cancela tarefa pendente ou em execução\n"
    "/grant `<caminho> [dias=N] [finalidade]` — autoriza diretório p/ ferramentas\n"
    "/revoke `<id>` — revoga grant\n"
    "/grants — lista grants\n"
    "/stop — para a tarefa atual e limpa a fila\n"
    "/reset — reset completo de estado (fila, pendências, travas)\n"
    "/diag — saúde dos componentes (CDP, browser, LLM, falhas)\n"
    "/version — versões dos componentes\n\n"
    "Ações críticas (compra, pagamento, exclusão…) pedem "
    "[Autorizar]/[Cancelar] com os detalhes exatos."
)

def _auth(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    return uid in settings.TELEGRAM_WHITELIST_IDS

def _msg(update: Update):
    """Mensagem de texto, incluindo edições (edited_message não tem .message)."""
    m = update.message or update.edited_message
    if m is None or not getattr(m, "text", None):
        return None
    return m

def _deny(update: Update, what: str):
    uid = update.effective_user.id if update.effective_user else 0
    print(f"[AUTH] negado ({what}) para uid={uid}", flush=True)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        _deny(update, "/start")
        try:
            uid = update.effective_user.id if update.effective_user else 0
            await update.message.reply_text(f"Acesso negado. Seu ID é {uid}. Avise o operador para liberar.")
        except Exception:
            pass
        return
    await update.message.reply_text("Agente online. Envie uma tarefa ou /help.")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        _deny(update, "/help")
        return
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

async def diag_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Diagnóstico read-only: componentes, dependências e falhas recentes."""
    if not _auth(update):
        _deny(update, "/diag")
        return
    lines = ["🩺 Diagnóstico"]
    up = int(time.time() - _START_TIME)
    lines.append(f"uptime bot: {up // 3600}h {(up % 3600) // 60}m")
    # CDP (socket rápido, sem abrir browser)
    import socket as _sock
    try:
        s = _sock.create_connection(("127.0.0.1", 9222), timeout=3)
        s.close()
        lines.append("CDP 127.0.0.1:9222: OK")
    except Exception as e:
        lines.append(f"CDP 127.0.0.1:9222: FALHA ({e})")
    # Guarda pré-requisição (F-03): armado, inativo ou ainda não criado
    try:
        from browser.session import _guard_armed
        lines.append("route guard: " + ({True: "ARMADO", False: "INATIVO (só verify pós-ação)", None: "N/D (nenhuma tarefa ainda)"}[_guard_armed]))
    except Exception:
        lines.append("route guard: N/D")
    # Chromium do Playwright
    found = False
    for base in (os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright"),
                 os.path.expanduser("~/.cache/ms-playwright")):
        try:
            if base and os.path.isdir(base):
                found = any(os.path.exists(os.path.join(base, d, "chrome-win", "chrome.exe"))
                            or os.path.exists(os.path.join(base, d, "chrome-linux", "chrome"))
                            for d in os.listdir(base) if d.startswith("chromium"))
                if found:
                    break
        except Exception:
            pass
    lines.append(f"playwright chromium: {'OK' if found else 'NÃO ENCONTRADO (rode: playwright install chromium)'}")
    # OpenCode CLI
    import shutil as _sh
    exe = _sh.which("opencode")
    lines.append(f"opencode CLI: {exe or 'NÃO ESTÁ NO PATH'}")
    lines.append(f"llm: {settings.LLM_BACKEND}/{settings.LLM_MODEL}")
    # Falhas recentes do agent.log + latência por etapa (G-21)
    try:
        with open(os.path.join(settings.LOG_DIR, "agent.log"), encoding="utf-8") as f:
            tail = f.readlines()[-300:]
        evs = []
        for l in tail:
            try:
                evs.append(json.loads(l))
            except Exception:
                pass
        fails = [e for e in evs if str(e.get("ev", "")).startswith("blocked")
                 or e.get("ev") == "cancelled" or "falhou" in str(e).lower()]
        lines.append(f"eventos de falha recentes (300 linhas): {len(fails)}")
        for ev in fails[-3:]:
            lines.append(f"- {ev.get('ts', '?')} {ev.get('ev', '?')} {str(ev.get('why') or ev.get('action') or '')[:60]}")
        for key, label in (("llm_ms", "LLM"), ("action_ms", "ação"), ("scan_ms", "scan")):
            vals = sorted(e[key] for e in evs if isinstance(e.get(key), (int, float)))
            if vals:
                p50 = vals[len(vals) // 2]
                lines.append(f"latência {label}: n={len(vals)} p50={p50}ms")
    except FileNotFoundError:
        lines.append("agent.log: ainda sem eventos")
    except Exception as e:
        lines.append(f"agent.log: erro ao ler ({e})")
    await update.message.reply_text("\n".join(lines)[:4000])

async def version_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        _deny(update, "/version")
        return
    import playwright
    import telegram as ptb
    await update.message.reply_text(
        f"agent {VERSION}\n"
        f"python {sys.version.split()[0]}\n"
        f"PTB {ptb.__version__} | playwright {playwright.__version__}\n"
        f"model {settings.LLM_MODEL} ({settings.LLM_BACKEND})")

async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        _deny(update, "/status")
        return
    running = [f"#{t} {d['task'][:60]}" for t, d in _tasks.items() if d["status"] == "running"]
    queued = [f"#{t} {d['task'][:60]}" for t, d in _tasks.items() if d["status"] == "queued"]
    hist = [f"#{h['tid']} {'✅' if h['ok'] else '⛔'} {h['task'][:50]}" for h in _history[-5:]]
    disk = shutil.disk_usage(settings.LOG_DIR if os.path.isdir(settings.LOG_DIR) else ".")
    lines = ["📊 Status (v" + VERSION + ")",
             f"Fila: {task_queue.qsize()}/{settings.QUEUE_MAX}",
             f"Executando: {running[0] if running else '—'}"]
    if queued:
        lines.append("Pendentes:\n" + "\n".join(queued))
    lines.append("Histórico:\n" + ("\n".join(hist) if hist else "—"))
    lines.append(f"Disco logs: {disk.free // (1024**3)} GB livres")
    # N-01: texto de tarefa com _ ou * quebra o Markdown — plain text
    await update.message.reply_text("\n".join(lines)[:4000])

async def grants_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        _deny(update, "/grants")
        return
    from tools import permissions as _perm
    grants = _perm.load()
    if not grants:
        await update.message.reply_text("Nenhum grant. Use /grant <caminho> [dias=N] [finalidade].")
        return
    import time as _t
    lines = ["🔑 Grants:"]
    for g in grants:
        st = "ativo" if g.active() else ("revogado" if g.revoked else "expirado")
        lines.append(f"- {g.id}: {g.value} [{st}] {g.purpose[:60]}")
    await update.message.reply_text("\n".join(lines)[:4000])

# token -> {uid, path, days, purpose, exp}: proposta de grant aguardando
# `confirmar <token>` (P0-2). Expira em 120s.
_pending_grants: dict[str, dict] = {}

def _split_grant_args(args: list[str]) -> tuple[str, int, str, str]:
    """Separa caminho (com espaços), dias e finalidade. Retorna (path, days, purpose, erro).

    Dias SOMENTE via token explícito dias=N (Q-03): tokens numéricos soltos
    pertencem à finalidade — nunca são reinterpretados como dias.
    """
    import os as _os
    import re as _re
    rest, days = list(args), 7
    for i, t in enumerate(rest):
        m = _re.fullmatch(r"(?i)dias=(\d+)", t)
        if m:
            days = int(m.group(1))
            rest.pop(i)
            break
    # caminho: maior prefixo que existe como diretório (suporta espaços)
    for n in range(len(rest), 0, -1):
        cand = " ".join(rest[:n])
        if _os.path.isdir(cand):
            return cand, days, " ".join(rest[n:])[:200], ""
    return "", days, "", "Caminho inexistente ou não é diretório."

async def grant_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Propõe grant; cria SOMENTE após `confirmar <token>` (P0-2)."""
    if not _auth(update):
        _deny(update, "/grant")
        return
    _auto = bool(getattr(settings, "AUTONOMOUS_MODE", False))
    if not settings.LOCAL_TOOLS_ENABLED and not _auto:
        await update.message.reply_text("Ferramentas locais desligadas (LOCAL_TOOLS_ENABLED=false).")
        return
    if not ctx.args:
        await update.message.reply_text("Uso: /grant <caminho> [dias=N 1-90] [finalidade]")
        return
    import os as _os
    import time as _t
    import secrets as _secrets
    from tools import permissions as _perm
    # Q-05: poda propostas expiradas a cada novo /grant (in-place: dict é global)
    for _k in [k for k, v in _pending_grants.items() if v["exp"] <= _t.time()]:
        _pending_grants.pop(_k, None)
    path, days, purpose, err = _split_grant_args(ctx.args)
    if err:
        await update.message.reply_text(err)
        return
    if not 1 <= days <= 90:
        await update.message.reply_text("Dias deve ser 1–90.")
        return
    repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    try:
        if _auto:
            real = _os.path.realpath(_os.path.abspath(_os.path.expanduser(path)))
        else:
            real = _perm.validate_root(path, project_root=repo_root)
    except Exception as e:
        await update.message.reply_text(f"Grant negado: {e}")
        return
    if _auto:
        try:
            g = _perm.create(real, purpose, str(update.effective_user.id), days=days, validate=False)
        except Exception as e:
            await update.message.reply_text(f"Grant negado: {e}")
            return
        await update.message.reply_text(f"✅ Grant {g.id}: {g.value}\nModo autônomo: criado sem confirmação.")
        return
    token = _secrets.token_hex(3)
    _pending_grants[token] = {"uid": update.effective_user.id,
                              "path": real, "days": days, "purpose": purpose,
                              "exp": _t.time() + 120}
    await update.message.reply_text(
        f"Confirme o escopo (realpath):\n{real}\nValidade: {days} dias\n"
        f"Finalidade: {purpose or '—'}\nResponda `confirmar {token}` em 120s.")

async def revoke_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        _deny(update, "/revoke")
        return
    if not ctx.args:
        await update.message.reply_text("Uso: /revoke <id>")
        return
    from tools import permissions as _perm
    ok = _perm.revoke(ctx.args[0].lstrip("#"))
    await update.message.reply_text("Grant revogado." if ok else "Grant não encontrado.")

async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        _deny(update, "/cancel")
        return
    if not ctx.args:
        await update.message.reply_text("Uso: /cancel `<id>` (veja o id no /status)")
        return
    tid = ctx.args[0].lstrip("#")
    entry = _tasks.get(tid)
    if not entry or entry["status"] in ("done", "failed", "cancelled"):
        await update.message.reply_text(f"#{tid} não está ativa.")
        return
    entry["status"] = "cancelled"
    entry["updated"] = time.time()
    ev = _running_cancel.get(tid)
    if ev:
        ev.set()
    await update.message.reply_text(f"#{tid} cancelada.")

def _drain_queue() -> int:
    n = 0
    while True:
        try:
            task_queue.get_nowait()
            n += 1
        except asyncio.QueueEmpty:
            return n

def _resolve_pendings() -> tuple[int, int]:
    """Resolve pendências de confirmação (nega) e perguntas (sem resposta).
    Retorna (n_confirm, n_ask)."""
    n_c = len(_pending_confirm)
    n_a = len(_pending_ask)
    for key, (fut, _uid) in list(_pending_confirm.items()):
        if not fut.done():
            try:
                fut.set_result(False)
            except Exception:
                pass
        _pending_confirm.pop(key, None)
    for chat, (fut, _tid) in list(_pending_ask.items()):
        if not fut.done():
            try:
                fut.set_result(None)
            except Exception:
                pass
        _pending_ask.pop(chat, None)
    return n_c, n_a

async def stop_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Para a tarefa em execução e limpa a fila. O bot continua online."""
    if not _auth(update):
        _deny(update, "/stop")
        return
    running = [t for t, d in _tasks.items() if d["status"] == "running"]
    for tid in running:
        _tasks[tid]["status"] = "cancelled"
        _tasks[tid]["updated"] = time.time()
        ev = _running_cancel.get(tid)
        if ev:
            ev.set()
    # Pendências de confirmação/pergunta das tarefas paradas: negar/resolver
    _resolve_pendings()
    dropped = _drain_queue()
    for _tid, d in _tasks.items():
        if d["status"] == "queued":
            d["status"] = "cancelled"
            d["updated"] = time.time()
    await update.message.reply_text(
        f"⏹ Parado: {len(running)} em execução, {dropped} na fila descartadas.")

async def reset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Reset completo de estado em memória (fila, pendências, travas, registry).
    Histórico persistido e logs são preservados. O processo continua rodando —
    para reiniciar o processo, use o iniciar_agente.bat."""
    if not _auth(update):
        _deny(update, "/reset")
        return
    n_c, n_a = _resolve_pendings()
    dropped = _drain_queue()
    n_tasks = len(_tasks)
    for tid, d in _tasks.items():
        if d["status"] in ("queued", "running"):
            d["status"] = "cancelled"
            d["updated"] = time.time()
        ev = _running_cancel.get(tid)
        if ev:
            ev.set()
    _running_cancel.clear()
    _pending_grants.clear()
    _last_enqueue.clear()
    _last_text.clear()
    _save_history()
    await update.message.reply_text(
        f"♻️ Reset: {dropped} da fila, {n_c} confirmações, {n_a} perguntas, "
        f"{n_tasks} registros marcados. Bot online e ocioso.")

async def enqueue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        uid = update.effective_user.id if update.effective_user else 0
        m = _msg(update)
        print(f"[AUTH] mensagem negada para uid={uid}: {((m.text if m else '') or '')[:80]}", flush=True)
        try:
            if m is not None:
                await m.reply_text(f"Acesso negado. Seu ID é {uid}.")
        except Exception:
            pass
        return
    uid = update.effective_user.id
    now = time.time()
    m = _msg(update)
    text = ((m.text if m else "") or "").strip()
    if not text:
        return
    # v2.6: resposta a pergunta pendente — resolve, não enfileira.
    # Comandos (/) furam a espera (ex.: /cancel continua funcionando).
    low = text.lower()
    if low.startswith("confirmar "):
        # P0-2: conclusão do /grant em dois passos
        import time as _t2
        from tools import permissions as _perm2
        tok = low.split(None, 1)[1].strip()
        prop = _pending_grants.pop(tok, None)
        if prop is None or prop["uid"] != uid or prop["exp"] < _t2.time():
            await m.reply_text("Proposta inválida ou expirada. Use /grant de novo.")
            return
        try:
            # Revalida na criação: o diretório pode ter mudado nos 120s
            real = _perm2.validate_root(prop["path"])
            g = _perm2.create(real, prop["purpose"], str(uid), days=prop["days"])
        except Exception as e:
            await m.reply_text(f"Grant negado na confirmação: {e}")
            return
        exp = _t2.strftime("%Y-%m-%d", _t2.localtime(g.expires_at)) if g.expires_at else "sem expiração"
        await m.reply_text(f"✅ Grant {g.id}: {g.value}\nExpira: {exp}\nRevogar: /revoke {g.id}")
        return
    if m.chat_id in _pending_ask and not text.startswith("/"):
        fut, atid = _pending_ask.pop(m.chat_id)
        if not fut.done():
            fut.set_result(text)
        await m.reply_text(f"↩️ Resposta registrada para [#{atid}].")
        return
    task = text
    # Rate limit por usuário (ignorado em modo autônomo)
    _auto = bool(getattr(settings, "AUTONOMOUS_MODE", False))
    if not _auto and now - _last_enqueue.get(uid, 0) < settings.RATE_LIMIT_SEC:
        await m.reply_text(
            f"Calma — aguarde {settings.RATE_LIMIT_SEC}s entre tarefas.")
        return
    # Anti-duplicata: mesmo texto em DUP_WINDOW_SEC (ignorado em modo autônomo)
    prev, ts = _last_text.get(uid, ("", 0))
    if not _auto and task == prev and now - ts < settings.DUP_WINDOW_SEC:
        await m.reply_text("Tarefa idêntica já enviada há pouco. Use /status.")
        return
    if task_queue.full():
        await m.reply_text(
            f"Fila cheia ({settings.QUEUE_MAX}). Use /status e /cancel.")
        return
    tid = uuid.uuid4().hex[:6]
    status = await m.reply_text(f"Enfileirado [#{tid}]: {task[:80]}")
    _tasks[tid] = {"task": task, "chat_id": m.chat_id,
                   "msg_id": status.message_id, "uid": uid,
                   "status": "queued", "created": now, "updated": now, "result": ""}
    _last_enqueue[uid] = now
    _last_text[uid] = (task, now)
    await task_queue.put((tid, task, m.chat_id, status.message_id, uid))

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # Callback só vale para usuário da whitelist E solicitante da tarefa
    uid = q.from_user.id if q.from_user else 0
    if uid not in settings.TELEGRAM_WHITELIST_IDS:
        print(f"[AUTH] callback negado para uid={uid}", flush=True)
        return
    # NF-02: espiar antes de remover — clique de terceiro não destrói a pendência
    key = _confirm_key(q.message.chat_id, q.message.message_id)
    entry = _pending_confirm.get(key)
    if not entry:
        return
    fut, allowed_uid = entry
    if uid != allowed_uid:
        print(f"[AUTH] callback de uid={uid} ignorado (esperado={allowed_uid})", flush=True)
        return
    _pending_confirm.pop(key, None)
    if fut and not fut.done():
        fut.set_result(q.data == "ok")

def _finish_task(tid: str, ok: bool, result: str):
    entry = _tasks.get(tid)
    if entry:
        entry["status"] = "done" if ok else "failed"
        entry["result"] = result[:200]
        entry["updated"] = time.time()
    _history.append({"tid": tid, "task": entry["task"] if entry else "?",
                     "ok": ok, "result": result[:200], "ts": time.time()})
    while len(_history) > settings.HISTORY_MAX:
        _history.pop(0)
    _save_history()
    # _tasks podado: concluídas antigas saem do registry (memória limitada)
    done = [t for t, d in _tasks.items() if d["status"] in ("done", "failed", "cancelled")]
    while len(done) > settings.HISTORY_MAX:
        _tasks.pop(done.pop(0), None)
    _running_cancel.pop(tid, None)

async def worker(app: Application):
    while True:
        tid, task, chat_id, msg_id, requester_uid = await task_queue.get()
        entry = _tasks.get(tid)
        if entry is None or entry["status"] == "cancelled":
            try:
                await app.bot.send_message(chat_id, f"[#{tid}] cancelada antes de iniciar.")
            except Exception:
                pass
            continue
        entry["status"] = "running"
        cancel_ev = asyncio.Event()
        _running_cancel[tid] = cancel_ev
        async def progress(text: str):
            try:
                await app.bot.edit_message_text(text[:4000], chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass
        async def confirm(text: str, shot: str) -> bool:
            if bool(getattr(settings, "AUTONOMOUS_MODE", False)):
                try:
                    await app.bot.send_message(chat_id, f"🚀 [#{tid}] auto-autorizado (modo autônomo).")
                except Exception:
                    pass
                return True
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Autorizar", callback_data="ok"),
                                        InlineKeyboardButton("Cancelar", callback_data="no")]])
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            sent = None
            try:
                # Sem foto (screenshot falhou) confirma só com texto + botões
                if shot:
                    with open(shot, "rb") as f:
                        sent = await app.bot.send_photo(chat_id, f, caption=text[:1000], reply_markup=kb)
                else:
                    sent = await app.bot.send_message(chat_id, text[:1000], reply_markup=kb)
                _pending_confirm[_confirm_key(chat_id, sent.message_id)] = (fut, requester_uid)
                return await asyncio.wait_for(fut, timeout=120)
            except Exception:
                if sent is not None:
                    _pending_confirm.pop(_confirm_key(chat_id, sent.message_id), None)
                return False
        async def ask(question: str, shot: str):
            if bool(getattr(settings, "AUTONOMOUS_MODE", False)):
                return "Autorizado automaticamente (modo autônomo) — prossiga com a melhor decisão."
            # v2.6: pergunta textual — a próxima mensagem do solicitante resolve.
            # Avisa para NÃO mandar senhas (firewall valida de novo no retorno).
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            _pending_ask[chat_id] = (fut, tid)
            try:
                text = (f"❓ [#{tid}] {question[:1500]}\n\n"
                        f"Responda em texto (120s). ⚠️ Nunca envie senhas ou tokens.")
                if shot:
                    with open(shot, "rb") as f:
                        await app.bot.send_photo(chat_id, f, caption=text[:1000])
                else:
                    await app.bot.send_message(chat_id, text[:4000])
                return await asyncio.wait_for(fut, timeout=120)
            except Exception:
                return None
            finally:
                _pending_ask.pop(chat_id, None)
        try:
            try:
                res = await asyncio.wait_for(
                    orch.run_task(task, on_progress=progress, on_confirm=confirm,
                                  on_ask=ask,
                                  task_id=tid, actor=str(requester_uid),
                                  should_stop=cancel_ev.is_set),
                    timeout=settings.TASK_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                res = None
                final = f"⛔ [#{tid}] timeout de {settings.TASK_TIMEOUT_SEC}s. Use /cancel se travou."
            if res is not None:
                final = (f"✅ [#{tid}] " if res.ok else f"⛔ [#{tid}] ") + res.message
            _finish_task(tid, res.ok if res is not None else False, final)
            if res is not None and res.screenshot_path:
                try:
                    with open(res.screenshot_path, "rb") as f:
                        await app.bot.send_photo(chat_id, f, caption=final[:1000])
                    await app.bot.edit_message_text(f"[#{tid}] Concluído: {task[:60]}", chat_id=chat_id, message_id=msg_id)
                except Exception:
                    await app.bot.send_message(chat_id, final[:4000])
            else:
                await app.bot.send_message(chat_id, final[:4000])
        except Exception as e:
            # Erro ao reportar não pode matar o worker (fila pararia em silêncio)
            _finish_task(tid, False, str(e)[:200])
            try:
                await app.bot.send_message(chat_id, f"Erro interno [#{tid}]: {e}")
            except Exception:
                print(f"[WORKER] falha ao reportar erro: {e}", flush=True)

def build_telegram_app() -> Application:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("grant", grant_cmd))
    app.add_handler(CommandHandler("revoke", revoke_cmd))
    app.add_handler(CommandHandler("grants", grants_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("diag", diag_cmd))
    app.add_handler(CommandHandler("version", version_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    # Só chat privado recebe tarefa (screenshots de sessão logada)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, enqueue))
    return app
