"""Interrupted local initialization can resume without replacing existing keys."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
with patch.object(sys, "path", [str(ROOT / "infra"), *sys.path]):
    spec = importlib.util.spec_from_file_location("local_demo", ROOT / "infra/local-demo.py")
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)

SETTINGS = """POSTGRES_PORT=5544
KAFKA_PORT=9192
MINI_APP_PORT=8180
KITCHEN_APP_PORT=8181
TELEGRAM_BOT_TOKEN=local-demo:synthetic-test-only
"""


class LocalSetupTests(unittest.TestCase):
    def test_missing_key_pair_is_generated_once_on_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / ".env"
            env.write_text(SETTINGS)

            def generate(args):
                self.assertEqual(args[-1], "infra/create-auth-env.py")
                env.write_text(
                    SETTINGS + "JWT_PRIVATE_KEY_BASE64=test\nJWT_PUBLIC_KEY_BASE64=test\n"
                )

            with (
                patch.object(demo, "ROOT", root),
                patch.object(demo, "ACCESS", root / "private/access.json"),
                patch.object(demo, "run", side_effect=generate) as run,
            ):
                demo.init()
                demo.init()
                run.assert_called_once()

    def test_partial_pair_is_preserved_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = SETTINGS + "JWT_PRIVATE_KEY_BASE64=existing-test-value\n"
            (root / ".env").write_text(content)
            with patch.object(demo, "ROOT", root), patch.object(demo, "run") as run:
                with self.assertRaisesRegex(SystemExit, "incomplete"):
                    demo.init()
                run.assert_not_called()
            self.assertEqual((root / ".env").read_text(), content)


if __name__ == "__main__":
    unittest.main()
