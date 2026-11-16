import importlib.util
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "mac_staging", Path(__file__).resolve().parents[2] / "infra/mac-staging.py"
)
assert SPEC is not None and SPEC.loader is not None
staging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(staging)
OLD = "a" * 40
NEW = "b" * 40


class StagingSelectionTest(unittest.TestCase):
    def test_running_ingress_uses_explicit_revision(self):
        with self.staging_state() as (artifacts, compose):
            staging.select(NEW)
            self.assertEqual((artifacts / "current").readlink(), Path(NEW))
            select = compose.call_args
            self.assertEqual(select.args[-1], "staging-ingress")
            self.assertIn("--no-deps", select.args)
            self.assertEqual(select.kwargs["revision"], NEW)

    def test_failed_ingress_switch_restores_previous_selection(self):
        with self.staging_state() as (artifacts, compose):
            compose.side_effect = [
                subprocess.CompletedProcess([], 0, stdout="ingress"),
                subprocess.CalledProcessError(1, "compose"),
                subprocess.CompletedProcess([], 0),
            ]
            with self.assertRaises(subprocess.CalledProcessError):
                staging.select(NEW)
            self.assertEqual((artifacts / "current").readlink(), Path(OLD))
            self.assertEqual(compose.call_args.kwargs["revision"], OLD)

    @contextmanager
    def staging_state(self):
        with tempfile.TemporaryDirectory() as path:
            artifacts = Path(path)
            env_file = artifacts / "staging.env"
            env_file.touch()
            for revision in (NEW, OLD):
                for app in staging.APPS:
                    app_dir = artifacts / revision / app
                    app_dir.mkdir(parents=True)
                    (app_dir / "index.html").touch()
            (artifacts / "current").symlink_to(OLD)
            with (
                patch.object(staging, "ARTIFACTS", artifacts),
                patch.object(staging, "ENV_FILE", env_file),
                patch.object(staging, "compose") as compose,
            ):
                compose.return_value = subprocess.CompletedProcess([], 0, stdout="ingress")
                yield artifacts, compose
