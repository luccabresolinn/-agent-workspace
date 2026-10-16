"""F-03/G-03: guarda pré-requisição contra redirecionamento p/ IP interno.

Servidor A (permitido só no harness) redireciona /go -> servidor B /hit.
Com o route guard armado, B deve receber 0 hits no goto direto.

Manual (precisa de Chromium do Playwright + rede local):
    python tests/manual/guard_redirect.py

Resultado registrado (2026-10-12, Chromium gerenciado headless):
    goto direto p/ IP interno: 0 hits (bloqueado pré-requisição)
    redirect 302 p/ IP interno: 1 hit (NÃO interceptado — contido pós-ação)
Ou seja: o guard cobre navegações diretas; redirects caem no verify
pós-ação do orquestrador (volta a about:blank + auditoria).
"""
import asyncio
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

PORT_A, PORT_B = 18903, 18904
HITS = {"b": 0}


class A(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/go":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{PORT_B}/hit")
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"a")

    def log_message(self, *a):
        pass


class B(BaseHTTPRequestHandler):
    def do_GET(self):
        HITS["b"] += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"hit!")

    def log_message(self, *a):
        pass


async def main():
    import browser.policy as pol
    from browser.session import _guard_route
    orig = pol.check_url

    async def patched(url):
        if f"127.0.0.1:{PORT_A}" in url:
            return url  # harness: só o redirector liberado
        return await orig(url)

    pol.check_url = patched
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        ctx = await pw.chromium.launch_persistent_context(
            tempfile.mkdtemp(prefix="guardtest-"), headless=True)
        await ctx.route("**/*", _guard_route)
        page = await ctx.new_page()
        try:
            await page.goto(f"http://127.0.0.1:{PORT_A}/go", timeout=15000)
        except Exception as e:
            print("GOTO:", str(e)[:80])
        await asyncio.sleep(1)
        print("HITS_NO_ALVO:", HITS["b"], "| URL_FINAL:", page.url)
        await pw.stop()
        return 0 if HITS["b"] == 0 else 2  # 2 = limite conhecido (redirect passa)
    finally:
        pol.check_url = orig


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
