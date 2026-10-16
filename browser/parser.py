import hashlib

async def page_state_hash(page) -> str:
    try:
        url = page.url
        title = await page.title()
        return hashlib.md5(f"{url}|{title}".encode()).hexdigest()[:12]
    except Exception:
        return "unknown"

async def build_indexed_state(page, max_elements: int = 60) -> tuple[str, dict[int, str], dict[int, dict]]:
    """Varre só elementos interativos e devolve lista enxuta [id] + mapa id->selector.

    Pilar A: Indexed AXTree em vez de HTML bruto.
    Retorna também metadados por id (href sem query, onclick, bbox) para a
    revalidação de alvo crítico (G-06) — sem vazar query strings ao prompt.
    """
    js = """() => {
      // F-15: limpa marcações de varreduras anteriores (DOM pode ter mudado)
      document.querySelectorAll('[data-agent-id]').forEach(e => e.removeAttribute('data-agent-id'));
      const els = Array.from(document.querySelectorAll('a, button, input, select, textarea, [role="button"], [onclick]'));
      const out = [];
      let i = 0;
      for (const el of els) {
        if (i >= 120) break;
        const r = el.getBoundingClientRect();
        const tag2 = el.tagName.toLowerCase();
        const type2 = (el.getAttribute('type') || '').toLowerCase();
        const isFile = (tag2 === 'input' && type2 === 'file');
        // input[type=file] costuma ser oculto (dropzone): inclui mesmo invisível
        if (!isFile) {
          if (r.width === 0 && r.height === 0) continue;
          const style = getComputedStyle(el);
          if (style.display === 'none' || style.visibility === 'hidden') continue;
        }
        i++;
        el.setAttribute('data-agent-id', i);
        let tag = el.tagName.toLowerCase();
        let type = (el.getAttribute('type') || '').toLowerCase();
        let isPass = (tag === 'input' && type === 'password');
        // A-06: valor de campo de senha NUNCA sai da maquina (nem via label, nem via extra)
        let label = (isPass
          ? (el.placeholder || el.getAttribute('aria-label') || el.name || 'senha')
          : (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.tagName || '')
        ).trim().replace(/\\s+/g, ' ').slice(0, 80);
        let extra = '';
        // A-05: expõe type também em buttons (type=submit vira vetor de envio)
        if (tag === 'input' || tag === 'button') {
          let t2 = (tag === 'input') ? type : (el.getAttribute('type') || '');
          if (isPass) extra = ' type=password';
          else if (t2) extra = ` type=${t2}`;
          if (!isPass && tag === 'input') extra += ` valor="${(el.value||'').slice(0,40)}"`;
        }
        // G-06: comportamento do link p/ assinatura (href sem query, onclick, bbox)
        let dest = '', clicavel = false;
        try {
          let h = el.getAttribute('href') || '';
          if (h) { let u = new URL(h, document.baseURI); dest = (u.host + u.pathname).slice(0, 60); }
          clicavel = el.hasAttribute('onclick') || (el.getAttribute('href') || '').trim().toLowerCase().startsWith('javascript:');
        } catch (e) {}
        let box = [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
        if (dest) extra += ` -> ${dest}`;
        out.push({id: i, desc: `${tag}${extra}: "${label}"`, dest: dest, js: clicavel, box: box});
      }
      return out;
    }"""
    try:
        items = await page.evaluate(js)
    except Exception:
        items = []

    lines: list[str] = []
    id_to_selector: dict[int, str] = {}
    meta: dict[int, dict] = {}
    for it in items[:max_elements]:
        eid = int(it["id"])
        lines.append(f"[{eid}] {it['desc']}")
        id_to_selector[eid] = f'[data-agent-id="{eid}"]'
        meta[eid] = {"dest": it.get("dest", ""), "js": bool(it.get("js", False)),
                     "box": tuple(it.get("box", (0, 0, 0, 0)))}

    text = "\n".join(lines) if lines else "(nenhum elemento interativo visível)"
    return text, id_to_selector, meta
