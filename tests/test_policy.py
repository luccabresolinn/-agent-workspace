"""F-01/A-10: gate de navegação. DNS com mock (determinístico, sem rede)."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["ALLOWED_DOMAINS"] = ""

from browser.policy import check_url


def check(u):
    return asyncio.run(check_url(u))


GLOBAL_IP = ["93.184.216.34"]


class TestCheckUrl(unittest.TestCase):
    def test_public_ok(self):
        self.assertEqual(check("https://example.com/x"), "https://example.com/x")

    def test_bare_domain_gets_https(self):
        self.assertEqual(check("google.com"), "https://google.com")

    def test_about_blank(self):
        self.assertEqual(check("about:blank"), "about:blank")

    def test_blocked_schemes(self):
        for u in ["file:///etc/passwd", "javascript:alert(1)", "data:text/html,x",
                  "chrome://settings", "ftp://x.com/f"]:
            with self.assertRaises(ValueError, msg=u):
                check(u)

    def test_blocked_private_ips(self):
        for u in ["http://127.0.0.1:9222/json", "http://10.0.0.5/",
                  "http://172.16.0.9/", "http://192.168.1.1/",
                  "http://169.254.169.254/", "http://localhost:3000/",
                  "http://0.0.0.0/"]:
            with self.assertRaises(ValueError, msg=u):
                check(u)

    def test_nonstandard_ip_forms_blocked(self):
        # F-07: Chromium interpreta, getaddrinfo talvez não — bloquear antes
        for u in ["http://2130706433/", "http://127.1/",
                  "http://0x7f.0.0.1/", "http://0177.0.0.1/",
                  "http://127.0.0.0x1/", "http://0x7f.0.1/"]:
            with self.assertRaises(ValueError, msg=u):
                check(u)

    def test_localhost_by_name(self):
        # A-10: localhost por nome, com e sem ponto final
        for u in ["http://localhost/", "http://localhost./",
                  "http://app.localhost/", "http://a.b.localhost./x"]:
            with self.assertRaises(ValueError, msg=u):
                check(u)

    def test_backslash_rejected(self):
        with self.assertRaises(ValueError):
            check("http://evil.example\\@allowed.com/")

    def test_allowlist(self):
        os.environ["ALLOWED_DOMAINS"] = "example.com"
        try:
            with patch("browser.policy._resolve_ips", new=AsyncMock(return_value=GLOBAL_IP)):
                self.assertEqual(check("https://example.com/a"), "https://example.com/a")
                self.assertEqual(check("https://sub.example.com/a"), "https://sub.example.com/a")
                with self.assertRaises(ValueError):
                    check("https://evil.com/a")
                with self.assertRaises(ValueError):
                    check("http://evil.example\\@example.com/")
        finally:
            os.environ["ALLOWED_DOMAINS"] = ""

    def test_dns_failure(self):
        # Sem allowlist: DNS falhou → libera (navegação erro natural)
        with patch("browser.policy._resolve_ips", new=AsyncMock(return_value=None)):
            self.assertEqual(check("https://algum-host-qualquer.test/x"),
                             "https://algum-host-qualquer.test/x")
        # Com allowlist: DNS falhou → bloqueia (fail-closed)
        os.environ["ALLOWED_DOMAINS"] = "example.com"
        try:
            with patch("browser.policy._resolve_ips", new=AsyncMock(return_value=None)):
                with self.assertRaises(ValueError):
                    check("https://example.com/a")
        finally:
            os.environ["ALLOWED_DOMAINS"] = ""


if __name__ == "__main__":
    unittest.main()
