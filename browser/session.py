from playwright.async_api import async_playwright, BrowserContext, Page
from config.settings import settings
import os

_playwright = None
_context: BrowserContext | None = None

_guard_armed: bool | None = None  # estado real p/ /diag (F-03)

async def _guard_route(route):
    """A-10: aborta navegações diretas para hosts bloqueados.

    Validado: bloqueia o goto inicial pré-requisição (0 hits no alvo).
    Limite medido: redirect 302 server-side NÃO passa pelo handler como
    nova navigation request — cai na verificação pós-ação do orquestrador.
    """
    import os as _os
    if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true" or \
            _os.getenv("DISABLE_URL_GUARD", "false").lower() == "true":
        try:
            await route.continue_()
        except Exception:
            pass
        return
    from browser.policy import check_url
    try:
        if route.request.is_navigation_request():
            await check_url(route.request.url)
    except ValueError:
        try:
            await route.abort("blockedbyclient")
            return
        except Exception:
            return
    except Exception:
        pass
    try:
        await route.continue_()
    except Exception:
        pass

async def _arm_guard(context) -> None:
    global _guard_armed
    try:
        await context.route("**/*", _guard_route)
        _guard_armed = True
    except Exception as e:
        # CDP/antigos podem não suportar route — o verify pós-ação cobre
        _guard_armed = False
        print(f"[BROWSER] route guard indisponível ({e}).", flush=True)

async def get_page() -> Page:
    """Sessão persistente + suporte a CDP. Pilar D."""
    global _playwright, _context
    if _context:
        # A-16: contexto morto se recupera em vez de travar a tarefa
        try:
            pages = _context.pages
            if pages:
                return pages[0]
            return await _context.new_page()
        except Exception as e:
            print(f"[BROWSER] contexto obsoleto ({e}), recriando.", flush=True)
            _context = None

    _playwright = await async_playwright().start()
    os.makedirs(settings.BROWSER_USER_DATA_DIR, exist_ok=True)

    if settings.BROWSER_CDP_URL:
        # Pluga no Chrome real já aberto com --remote-debugging-port.
        # Se o Chrome fechou, faz fallback para perfil persistente em vez de erro fatal.
        try:
            browser = await _playwright.chromium.connect_over_cdp(settings.BROWSER_CDP_URL)
            _context = browser.contexts[0] if browser.contexts else await browser.new_context()
        except Exception as e:
            print(f"[BROWSER] CDP {settings.BROWSER_CDP_URL} indisponível ({e}), usando perfil persistente.", flush=True)
            _context = await _playwright.chromium.launch_persistent_context(
                user_data_dir=settings.BROWSER_USER_DATA_DIR,
                headless=settings.BROWSER_HEADLESS,
                viewport={"width": 1366, "height": 768},
                args=["--disable-blink-features=AutomationControlled"],
            )
    else:
        # Perfil persistente: logins feitos manualmente continuam salvos
        _context = await _playwright.chromium.launch_persistent_context(
            user_data_dir=settings.BROWSER_USER_DATA_DIR,
            headless=settings.BROWSER_HEADLESS,
            viewport={"width": 1366, "height": 768},
            args=["--disable-blink-features=AutomationControlled"],
        )
    await _arm_guard(_context)
    pages = _context.pages
    if pages:
        return pages[0]
    return await _context.new_page()
