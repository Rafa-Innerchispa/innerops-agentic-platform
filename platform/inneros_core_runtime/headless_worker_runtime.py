"""Resolve Python interpreter for systemd-spawned ops headless workers."""

from __future__ import annotations

import os
import shutil
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
