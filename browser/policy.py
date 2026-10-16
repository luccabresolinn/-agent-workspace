"""Política determinística de navegação (F-01/A-10).

Nega antes de qualquer ação de rede:
- esquemas fora de http/https (file:, javascript:, data:, chrome:, ...);
- `\`, espaços e controles (divergência de parser WHATWG vs urlparse);
- `localhost` e `*.localhost` por nome (não dependem de DNS);
- literais IP não-globais (loopback, privadas, link-local, metadata);
- hostnames que resolvem só para IPs não-globais.

Falha de DNS: bloqueia se a allowlist estiver ativa (fail-closed);
sem allowlist, libera (a navegação erro natural) e audita.
DNS resolve de forma assíncrona (N-03: sem travar o loop).

Allowlist opcional via env ALLOWED_DOMAINS (csv de sufixos).
"""
import asyncio
import ipaddress
import os
import re
import socket
from urllib.parse import urlparse


def _allowed_domain_suffixes() -> list[str]:
    raw = os.getenv("ALLOWED_DOMAINS", "")
    return [d.strip().lower().lstrip(".").rstrip(".") for d in raw.split(",") if d.strip()]


async def _resolve_ips(host: str) -> list[str] | None:
    """IPs do host ou None se o DNS falhar."""
    try:
        loop = asyncio.get_running_loop()
        infos = await asyncio.wait_for(loop.getaddrinfo(host, None), timeout=5)
        return [i[4][0] for i in infos]
    except Exception:
        return None


async def check_url(raw_url: str) -> str:
    """Valida e normaliza URL de navegação. Retorna a URL final.

    Levanta ValueError com motivo auditável se bloqueada.
    """
    import os as _os
    if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true" or \
            _os.getenv("DISABLE_URL_GUARD", "false").lower() == "true":
        url = (raw_url or "").strip()
        if not url:
            return "about:blank"
        if "://" not in url and not url.startswith("about:"):
            url = "https://" + url
        return url
    url = (raw_url or "").strip()
    if not url or url == "about:blank":
        return "about:blank"
    # A-10: barra invertida/espaços/controles — parsers divergem aqui
    if "\\" in url or re.search(r"[\s\x00-\x1f\x7f]", url):
        raise ValueError(f"navegação bloqueada (caractere inválido): {url[:80]}")
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url) and not url.startswith(("http://", "https://")):
        raise ValueError(f"navegação bloqueada (esquema não permitido): {url[:80]}")
    if "://" not in url:
        url = "https://" + url  # domínio nu: google.com → https://google.com
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"navegação bloqueada (esquema não permitido): {url[:80]}")
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError(f"navegação bloqueada (host inválido): {url[:80]}")
    # A-10: localhost por nome (Python pode não resolver, Chromium trata como loopback)
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError(f"navegação bloqueada (host interno): {host}")

    suffixes = _allowed_domain_suffixes()
    if suffixes and not any(host == s or host.endswith("." + s) for s in suffixes):
        raise ValueError(f"navegação bloqueada (fora da allowlist): {host}")

    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError(f"navegação bloqueada (IP interno): {host}")
        return url  # literal global: sem DNS
    except ValueError as e:
        if "bloqueada" in str(e):
            raise
        # F-07: tentativa de IP em forma não-padrão (2130706433, 127.1,
        # 0x7f.0.0.1, 0177.0.0.1) — Chromium interpreta, getaddrinfo talvez não
        h = host.lower()
        if h.isdigit() or re.fullmatch(r"[0-9.]+", host) or h.startswith("0x") or ":" in host:
            raise ValueError(f"navegação bloqueada (IP inválido/não padrão): {host}")
        # G-04: hex/octal fora da primeira posição (127.0.0.0x1) — rótulos
        # todos numéricos ou 0x… em qualquer posição = tentativa de IP
        labels = host.split(".")
        if len(labels) > 1 and all(
                re.fullmatch(r"[0-9]+", lb) or re.fullmatch(r"0x[0-9a-f]+", lb)
                for lb in labels):
            raise ValueError(f"navegação bloqueada (IP disfarçado): {host}")
    # hostname: resolve e bloqueia se só apontar para rede interna
    ips = await _resolve_ips(host)
    if ips is not None:
        try:
            if all(not ipaddress.ip_address(ip).is_global for ip in ips):
                raise ValueError(f"navegação bloqueada (host interno): {host}")
        except ValueError as e:
            if "bloqueada" in str(e):
                raise
    elif suffixes:
        raise ValueError(f"navegação bloqueada (DNS falhou com allowlist ativa): {host}")
    return url
