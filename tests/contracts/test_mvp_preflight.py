"""Acceptance preflight must not turn route availability into journey approval."""

import importlib.util
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "e2e" / "mvp_preflight.py"
SPEC = importlib.util.spec_from_file_location("mvp_preflight", SOURCE)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class PreflightTests(unittest.TestCase):
    def test_rejects_nonlocal_or_ambiguous_targets(self):
        for value in (
            "https://maistolovka.me",
            "http://127.0.0.1.evil.test:8180",
            "http://user:secret@localhost:8180",
            "http://localhost:8180/path",
            "http://localhost:8180?token=secret",
            "http://localhost:8180/#cart",
            "ftp://localhost:8180",
            "http://localhost:0",
            "http://localhost",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                preflight.local_origin(value)

    def test_accepts_only_explicit_loopback_origins(self):
        for value in ("http://localhost:8180", "http://127.0.0.1:8181", "http://[::1]:8180"):
            self.assertEqual(preflight.local_origin(value), value)

    def test_a_green_preflight_never_claims_full_acceptance(self):
        report = preflight.run("http://localhost:8180", "http://localhost:8181", self.good)
        self.assertTrue(report["preflight_passed"])
        self.assertEqual(report["journey_acceptance"], "not_run")
        self.assertEqual(report["unexecuted_scenarios"], [f"A{i}" for i in range(1, 9)])
        self.assertEqual(len(report["checks"]), 22)

    def test_wrong_service_and_failed_authorization_gate_are_failures(self):
        def broken(base, path):
            if path == "/health/order/ready":
                return 200, {"service": "menu-service", "status": "ready"}
            if path == "/api/v1/orders/wallet":
                return 200, {"balance": 123, "access_token": "do-not-record"}
            return self.good(base, path)

        report = preflight.run("http://localhost:8180", "http://localhost:8181", broken)
        self.assertFalse(report["preflight_passed"])
        self.assertNotIn("do-not-record", str(report))
        self.assertEqual(sum(not c["passed"] for c in report["checks"]), 4)

    def test_transport_errors_are_sanitized_and_other_checks_still_run(self):
        def broken(base, path):
            raise OSError("Bearer secret in an upstream diagnostic")

        report = preflight.run("http://localhost:8180", "http://localhost:8181", broken)
        self.assertFalse(report["preflight_passed"])
        self.assertNotIn("Bearer", str(report))
        self.assertEqual(len(report["checks"]), 22)

    def test_redirect_handler_never_follows_another_origin(self):
        self.assertIsNone(
            preflight.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")
        )

    @staticmethod
    def good(base, path):
        if path == "/":
            return 200, "<!doctype html><html><body>MAI Food</body></html>"
        if path.startswith("/health/"):
            service = path.split("/")[2]
            return 200, {"service": f"{service}-service", "status": "ready"}
        if path in ("/api/v1/menu/categories", "/api/v1/menu/items?limit=1&offset=0"):
            return 200, [] if path.endswith("categories") else {"items": [], "total": 0}
        return 401, {"detail": "Not authenticated"}


if __name__ == "__main__":
    unittest.main()
