"""Resolve Python interpreter for systemd-spawned ops headless workers."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path


def resolve_headless_python(*, platform_root: Path | None = None) -> Path:
    """Pick a Python that has InnerOS platform deps (Mongo, Temporal, etc.)."""
    root = platform_root or Path(__file__).resolve().parents[1]
    env_py = str(os.getenv("INNEROS_PYTHON") or "").strip()
    candidates: list[Path] = []
    if env_py:
        candidates.append(Path(env_py))
    candidates.extend(
        [
            root / "venv" / "bin" / "python3",
            Path("/home/rlopez/inneros/inneros_core/platform/venv/bin/python3"),
            Path("/home/rlopez/projects/raphiia-openai/venv/bin/python3"),
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    which = shutil.which("python3")
    return Path(which) if which else Path("python3")


def transient_unit_name(*, prefix: str, task_id: str, attempt: str = "") -> str:
    """Bounded systemd unit name; optional attempt salt avoids stale transient collisions."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id).strip("-.") or "task"
    material = f"{task_id}:{attempt}" if attempt else task_id
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{safe[:88]}-{digest}.service"


def prepare_transient_unit(unit: str) -> None:
    """Best-effort cleanup before systemd-run reuses a unit name."""
    for cmd in (
        ["systemctl", "--user", "stop", unit],
        ["systemctl", "--user", "reset-failed", unit],
    ):
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass


def systemd_run_transient(
    *,
    unit: str,
    command: list[str],
    cwd: Path | str,
    retry_suffix: str = "",
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run systemd-run; on stale-unit collision retry once with a fresh unit name."""
    prepare_transient_unit(unit)
    launch = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    detail = (launch.stderr or launch.stdout or "").lower()
    stale = "already loaded" in detail or "fragment file" in detail
    if launch.returncode == 0 or not stale:
        return launch, unit
    if not retry_suffix:
        retry_suffix = hashlib.sha256(detail.encode("utf-8")).hexdigest()[:8]
    retry_unit = unit.replace(".service", f"-r{retry_suffix}.service")
    prepare_transient_unit(retry_unit)
    retry_cmd = list(command)
    for idx, part in enumerate(retry_cmd):
        if part.startswith("--unit="):
            retry_cmd[idx] = f"--unit={retry_unit}"
            break
    retry = subprocess.run(
        retry_cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return retry, retry_unit
