"""safepath/permissions/read/secretscan. Só tmp, sem rede."""
import asyncio
import os
import tempfile
import unittest

from tools.safepath import resolve_within, PathDenied
from tools import permissions as perm
from tools import secretscan
import tools.filesystem.read  # noqa: F401  (registra no REGISTRY)
from tools.base import REGISTRY


class TestSafepath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "proj")
        os.makedirs(os.path.join(self.root, "sub"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_inside_ok(self):
        p = resolve_within(os.path.join(self.root, "sub", "a.txt"), [self.root])
        self.assertTrue(p.endswith(os.path.join("sub", "a.txt")))

    def test_traversal_blocked(self):
        with self.assertRaises(PathDenied):
            resolve_within(os.path.join(self.root, "..", "fora.txt"), [self.root])

    def test_absolute_outside_blocked(self):
        with self.assertRaises(PathDenied):
            resolve_within(tempfile.gettempdir(), [self.root])

    def test_sensitive_names(self):
        for n in [".env", "id_rsa.pem", "k.key"]:
            with self.assertRaises(PathDenied, msg=n):
                resolve_within(os.path.join(self.root, n), [self.root])

    def test_sensitive_dirs(self):
        with self.assertRaises(PathDenied):
            resolve_within(os.path.join(self.root, ".ssh", "x"), [self.root])

    def test_symlink_escape_blocked(self):
        # POSIX; no Windows sem privilégio, pula
        link = os.path.join(self.root, "elo")
        try:
            os.symlink(tempfile.gettempdir(), link)
        except OSError:
            self.skipTest("sem privilégio p/ symlink")
        with self.assertRaises(PathDenied):
            resolve_within(os.path.join(link, "x"), [self.root])

    def test_cross_drive_never_raises(self):
        # P0-4: drives diferentes → PathDenied, nunca ValueError
        try:
            resolve_within("D:\\algum\\lugar", ["C:\\outro"])
        except PathDenied:
            return
        except ValueError as e:
            self.fail(f"ValueError escapou: {e}")
        self.fail("deveria negar")


class TestPermissions(unittest.TestCase):
    def test_no_grants_deny(self):
        v, _ = perm.evaluate("fs.read_file", "B", {"path": "/x"}, [], {})
        self.assertEqual(v, "DENY")

    def test_expired_revoked_deny(self):
        g = perm.Grant(id="g", value="/tmp", expires_at=1.0)
        v, _ = perm.evaluate("fs.read_file", "B", {"path": "/tmp/a"}, [g], {})
        self.assertEqual(v, "DENY")

    def test_sig_stable(self):
        self.assertEqual(perm.operation_sig("t", {"a": 1}),
                         perm.operation_sig("t", {"a": 1}))
        self.assertNotEqual(perm.operation_sig("t", {"a": 1}),
                            perm.operation_sig("t", {"a": 2}))

    def test_level_c_first_approve_then_allow(self):
        g = perm.Grant(id="g", value="/tmp", expires_at=0.0)
        ctx = {}
        v, _ = perm.evaluate("x", "C", {"path": "/tmp/a"}, [g], ctx)
        self.assertEqual(v, "APPROVE")
        ctx.setdefault("approved_sigs", set()).add(perm.operation_sig("x", {"path": "/tmp/a"}))
        v, _ = perm.evaluate("x", "C", {"path": "/tmp/a"}, [g], ctx)
        self.assertEqual(v, "ALLOW")

    def test_level_f_always_deny(self):
        g = perm.Grant(id="g", value="/", expires_at=0.0)
        v, _ = perm.evaluate("x", "F", {}, [g], {})
        self.assertEqual(v, "DENY")

    def test_path_fields_sentinel(self):
        # T9: () explícito = sem campos; ausente = fallback legado
        from tools.base import ToolSpec
        self.assertEqual(perm.path_args_of(ToolSpec("t", "A", "d", object), {"target": "/x"}), [])
        calls = perm.path_args_of("somename", {"target": "/x"})
        self.assertEqual(calls, [])  # "target" não está no fallback legado
        calls2 = perm.path_args_of("somename", {"path": "/x"})
        self.assertEqual(calls2, ["/x"])


class TestValidateRoot(unittest.TestCase):
    def test_drive_root_denied(self):
        with self.assertRaises(PathDenied):
            perm.validate_root("C:\\")

    def test_cross_drive_repo_check(self):
        # T7: repo em outro drive → nunca ValueError; e não é o repo
        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "a", "b")
            os.makedirs(sub)
            try:
                real = perm.validate_root(sub, project_root="D:\\repo")
            except ValueError as e:
                self.fail(f"ValueError escapou: {e}")
            except PathDenied:
                return  # negado por outra regra, mas com exceção tipada: ok
            self.assertTrue(os.path.isdir(real))

    def test_shallow_denied(self):
        with self.assertRaises(PathDenied):
            perm.validate_root("C:\\dados")

    def test_repo_denied(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with self.assertRaises(PathDenied):
            perm.validate_root(repo, project_root=repo)

    def test_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "a", "b")
            os.makedirs(sub)
            try:
                real = perm.validate_root(sub)
            except PathDenied as e:
                self.skipTest(f"ambiente: {e}")
            self.assertTrue(os.path.isdir(real))


class TestSecretscan(unittest.TestCase):
    def test_redacts_known(self):
        txt, n = secretscan.scrub('aws_secret = "AKIAIOSFODNN7EXAMPLE"\nkey="ghp_abcdefghijklmnopqrst"')
        self.assertGreater(n, 0)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", txt)
        self.assertNotIn("ghp_abcdefghijklmnopqrst", txt)

    def test_truncates(self):
        txt, _ = secretscan.scrub("x" * 100, max_chars=10)
        self.assertIn("truncado", txt)


def _run(coro):
    return asyncio.run(coro)


class TestReadTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "sub"))
        with open(os.path.join(self.root, "a.txt"), "w") as f:
            f.write("ola mundo\nsenha: Xy@99ab\n")
        with open(os.path.join(self.root, ".env"), "w") as f:
            f.write("TOKEN=abc")
        self.ctx = {"roots": [self.root]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_registry_has_six(self):
        for n in ["fs.list_dir", "fs.stat", "fs.read_file",
                  "fs.search_names", "fs.search_content", "fs.hash"]:
            self.assertIn(n, REGISTRY)

    def test_list(self):
        r = _run(REGISTRY["fs.list_dir"].run(
            REGISTRY["fs.list_dir"].params_model(path=self.root), self.ctx))
        self.assertTrue(r.ok and r.data["count"] >= 2)

    def test_read_redacts(self):
        P = REGISTRY["fs.read_file"].params_model
        r = _run(REGISTRY["fs.read_file"].run(P(path=os.path.join(self.root, "a.txt")), self.ctx))
        self.assertTrue(r.ok)
        self.assertNotIn("Xy@99ab", r.data["content"])
        self.assertGreater(r.data["redacted"], 0)

    def test_env_denied(self):
        P = REGISTRY["fs.read_file"].params_model
        r = _run(REGISTRY["fs.read_file"].run(P(path=os.path.join(self.root, ".env")), self.ctx))
        self.assertFalse(r.ok)
        self.assertEqual(r.error_code, "PATH_DENIED")

    def test_outside_denied(self):
        P = REGISTRY["fs.stat"].params_model
        r = _run(REGISTRY["fs.stat"].run(P(path=os.path.join(self.root, "..", "x")), self.ctx))
        self.assertFalse(r.ok)

    def test_search_content(self):
        P = REGISTRY["fs.search_content"].params_model
        r = _run(REGISTRY["fs.search_content"].run(
            P(root=self.root, regex="ola"), self.ctx))
        self.assertTrue(r.ok and r.data["hits"])


if __name__ == "__main__":
    unittest.main()
