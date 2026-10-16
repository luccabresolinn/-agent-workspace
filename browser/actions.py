import asyncio
import os
import datetime
from config.settings import settings
from browser.policy import check_url

async def do_action(page, action, id_to_selector: dict[int, str]) -> str:
    """Executa AgentAction no Playwright. Retorna descrição do resultado."""
    t = action.action_type
    if t == "navigate":
        try:
            url = await check_url(action.url or "about:blank")
        except ValueError as e:
            return f"BLOQUEADO: {e}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return f"navegou para {url}"
    if t == "click":
        sel = id_to_selector.get(action.element_id or -1)
        if not sel:
            return f"ERRO: element_id {action.element_id} não existe no estado atual"
        await page.click(sel, timeout=10000)
        await asyncio.sleep(1.0)
        return f"clicou em [{action.element_id}]"
    if t == "type":
        sel = id_to_selector.get(action.element_id or -1)
        if not sel:
            return f"ERRO: element_id {action.element_id} não existe"
        await page.fill(sel, action.text_content or "", timeout=10000)
        # A-06: nunca ecoa o texto digitado (pode ser senha/token)
        return f"digitou em [{action.element_id}]"
    if t == "press_key":
        await page.keyboard.press(action.text_content or "Enter")
        await asyncio.sleep(0.8)
        return f"tecla {action.text_content}"
    if t == "upload":
        # Envia arquivo(s) para <input type=file> ou dropzone com input oculto.
        # text_content = caminho do arquivo ou pasta.
        # Adapta ao tipo do input (lido do DOM): webkitdirectory pede a PASTA;
        # input simples (sem multiple) aceita 1 arquivo; multiple aceita lista.
        import os as _os
        sel = id_to_selector.get(action.element_id or -1)
        if not sel:
            return f"ERRO: element_id {action.element_id} não existe no estado atual"
        raw = (action.text_content or "").strip()
        if not raw:
            return "ERRO: upload exige text_content com o caminho do arquivo/pasta"
        p = _os.path.abspath(_os.path.expanduser(raw))
        if not _os.path.exists(p):
            return f"ERRO: caminho não existe: {raw[:120]}"
        try:
            props = await page.eval_on_selector(sel,
                "el => ({multiple: !!el.multiple, dir: el.hasAttribute('webkitdirectory')})")
        except Exception:
            props = {"multiple": True, "dir": False}
        try:
            if _os.path.isdir(p) and props.get("dir"):
                payload = [p]
                desc = "pasta"
            else:
                files: list[str] = []
                if _os.path.isdir(p):
                    for root, _d, fns in _os.walk(p):
                        for n in sorted(fns):
                            if n.startswith("."):
                                continue
                            files.append(_os.path.join(root, n))
                            if len(files) >= 50:
                                break
                        if len(files) >= 50:
                            break
                    if not files:
                        return f"ERRO: pasta vazia: {raw[:120]}"
                else:
                    files = [p]
                if not props.get("multiple"):
                    payload = files[:1]
                    desc = "1 arquivo"
                else:
                    payload = files
                    desc = f"{len(files)} arquivo(s)"
            await page.set_input_files(sel, payload, timeout=30000)
        except Exception as e:
            return (f"ERRO: upload falhou em [{action.element_id}]: {e}. "
                    f"Dica: o alvo precisa ser um campo de arquivo (type=file); "
                    f"em dropzones, clique antes para revelar o seletor.")
        await asyncio.sleep(1.5)
        return f"enviou {desc} em [{action.element_id}]"
    if t == "wait":
        await asyncio.sleep(2.0)
        return "aguardou 2s"
    if t == "scroll":
        # text_content: down|up|top|bottom|pixels (ex.: "down", "500", "-300").
        # Revela conteúdo abaixo da dobra — sem isso o bot aborta por estagnação.
        arg = (action.text_content or "down").strip().lower()
        try:
            if arg == "top":
                await page.evaluate("window.scrollTo(0, 0)")
            elif arg == "bottom":
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif arg == "down":
                await page.evaluate("window.scrollBy(0, Math.max(400, window.innerHeight * 0.8))")
            elif arg == "up":
                await page.evaluate("window.scrollBy(0, -Math.max(400, window.innerHeight * 0.8))")
            else:
                px = int(arg)
                await page.evaluate(f"window.scrollBy(0, {max(-4000, min(4000, px))})")
        except Exception as e:
            return f"ERRO: rolagem falhou ({e})"
        await asyncio.sleep(0.6)
        return f"rolou página ({arg})"
    if t == "select":
        # Seleciona opção de <select>: text_content = value ou rótulo da opção.
        sel = id_to_selector.get(action.element_id or -1)
        if not sel:
            return f"ERRO: element_id {action.element_id} não existe no estado atual"
        opt = (action.text_content or "").strip()
        if not opt:
            return "ERRO: select exige text_content com value/rótulo da opção"
        try:
            vals = await page.eval_on_selector(sel, "el => Array.from(el.options || []).map(o => o.value + '|' + o.text)")
        except Exception:
            vals = []
        picked = None
        for v in vals:
            val, _, lab = v.partition("|")
            if opt.lower() in (val.lower(), lab.strip().lower()) or opt.lower() in v.lower():
                picked = val or lab
                break
        try:
            await page.select_option(sel, picked if picked is not None else opt, timeout=10000)
        except Exception as e:
            return f"ERRO: select falhou em [{action.element_id}]: {e}"
        await asyncio.sleep(0.8)
        return f"selecionou '{opt[:40]}' em [{action.element_id}]"
    if t == "reload":
        try:
            await page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            return f"ERRO: reload falhou ({e})"
        await asyncio.sleep(1.0)
        return "recarregou a página"
    return f"ação {t} (tratada pelo orquestrador)"

async def screenshot(page, name: str) -> str:
    """Tira screenshot. Nunca explode: timeout curto + fallback para ''.

    Sem isso, uma tarefa CONCLUÍDA vira 'Erro interno' se o screenshot
    travar (ex.: CDP em Chrome real esperando fonts). '' é falsy e os
    chamadores já tratam como 'sem foto'.
    """
    os.makedirs(settings.LOG_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(settings.LOG_DIR, f"{ts}_{name}.png")
    try:
        await page.screenshot(path=path, full_page=False, timeout=10000)
        return path
    except Exception as e:
        print(f"[BROWSER] screenshot '{name}' falhou ({e}), seguindo sem foto.", flush=True)
        return ""
