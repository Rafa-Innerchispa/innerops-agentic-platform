from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from inneros_core_runtime import headless_worker_runtime as hwr


class HeadlessWorkerRuntimeTests(unittest.TestCase):
    def test_prefers_inneros_python_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            py = Path(tmp) / "python3"
            py.write_text("#!/bin/sh\n", encoding="utf-8")
            py.chmod(0o755)
            with patch.dict(os.environ, {"INNEROS_PYTHON": str(py)}, clear=False):
                resolved = hwr.resolve_headless_python(platform_root=Path(tmp))
            self.assertEqual(resolved, py)

    def test_falls_back_to_platform_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv_py = root / "venv" / "bin" / "python3"
            venv_py.parent.mkdir(parents=True)
            venv_py.write_text("#!/bin/sh\n", encoding="utf-8")
            venv_py.chmod(0o755)
            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop("INNEROS_PYTHON", None)
                resolved = hwr.resolve_headless_python(platform_root=root)
            self.assertEqual(resolved, venv_py)

    def test_systemd_run_transient_retries_on_stale_unit(self) -> None:
        stale = MagicMock(returncode=1, stderr="Unit was already loaded", stdout="")
        ok = MagicMock(returncode=0, stderr="", stdout="")
        with patch.object(hwr, "prepare_transient_unit"):
            with patch.object(hwr.subprocess, "run", side_effect=[stale, ok]):
                proc, unit = hwr.systemd_run_transient(
                    unit="inneros-codex-headless-ops_test-abc.service",
                    command=["systemd-run", "--unit=inneros-codex-headless-ops_test-abc.service", "true"],
                    cwd="/tmp",
                )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("-r", unit)


if __name__ == "__main__":
    unittest.main()
