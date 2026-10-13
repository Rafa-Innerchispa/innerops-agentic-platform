"""Run platform ops on-host without Cursor SDK (pytest + git evidence)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_PYTEST = [
    "tests/test_ops_auto_claim_admission.py",
    "tests/test_amd_hackathons_runtime_registry.py",
    "tests/test_reconcile_ops_mongo_temporal.py",
]


def offers_local_execution(task: dict[str, Any]) -> bool:
    payload = dict(task.get("payload") or {})
    if str(payload.get("local_headless_executor") or "").strip():
        return True
    if payload.get("task_class") == "platform" and _env_truthy("INNEROS_CURSOR_PLATFORM_LOCAL_EXECUTE"):
        return True
    corr = str(task.get("correlation_id") or "")
    if corr.startswith("inneros-phase1-universal-auto-exec") and _env_truthy(
        "INNEROS_CURSOR_PLATFORM_LOCAL_EXECUTE"
    ):
        return True
    return False


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def run_platform_work(task: dict[str, Any], *, worktree: Path, platform_root: Path) -> dict[str, Any]:
    payload = dict(task.get("payload") or {})
    executor = str(payload.get("local_headless_executor") or "platform_pytest").strip()
    if executor not in {"platform_pytest", "pytest"}:
        return {"ok": False, "error": "unsupported_local_headless_executor", "executor": executor}

    tests = list(payload.get("local_pytest_paths") or DEFAULT_PYTEST)
    py = platform_root / "venv" / "bin" / "python3"
    if not py.is_file():
        py = Path(sys.executable)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(platform_root)
    if (worktree / "platform" / "tests").is_dir():
        cwd = worktree / "platform"
        test_args = [f"tests/{Path(t).name}" if t.startswith("tests/") else t for t in tests]
    else:
        cwd = platform_root
        test_args = tests
    cmd = [str(py), "-m", "pytest", "-q", *test_args]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=int(os.getenv("INNEROS_PLATFORM_LOCAL_PYTEST_TIMEOUT", "600")),
    )
    tail = (proc.stdout or "")[-4000:] + (proc.stderr or "")[-2000:]
    return {
        "ok": proc.returncode == 0,
        "primary": "platform_local_pytest",
        "executor": executor,
        "exit_code": proc.returncode,
        "pytest_tail": tail,
        "test_results": {"ok": proc.returncode == 0, "exit_code": proc.returncode, "suite": tests},
    }
