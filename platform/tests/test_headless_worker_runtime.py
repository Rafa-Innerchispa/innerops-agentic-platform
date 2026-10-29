from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
