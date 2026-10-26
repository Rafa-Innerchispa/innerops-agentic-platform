#!/usr/bin/env python3
"""Copy a clean preparation kit into a NEW local folder.

This does NOT create a remote GitHub repository, push code or install Switch.
It solves the earlier worktree/ref confusion by using a concrete source path.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

SKIP_PARTS = {".git", "__pycache__", ".venv", ".pytest_cache", "build", "dist"}
SKIP_NAMES = {".env", "id_rsa", "id_ed25519"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
REQUIRED = {
    "README.md", "pyproject.toml", "scripts/preflight.py",
    "src/inneros_incident_room/core.py", "tests/test_core.py",
    "docs/REUSE_MANIFEST.md", "docs/SWITCH_INTEGRATION_PLAN.md",
}


def build_manifest(source: Path) -> dict[str, str]:
    """Return a path -> checksum manifest, rejecting links and forbidden files."""
    if not source.is_dir():
        raise ValueError(f"Source directory missing: {source}")
    found: dict[str, str] = {}
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(p in SKIP_PARTS for p in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Symlinks are not allowed: {relative}")
        if not path.is_file():
            continue
        if path.name in SKIP_NAMES or path.suffix in SKIP_SUFFIXES:
            raise ValueError(f"Forbidden path in preparation kit: {relative}")
        found[relative.as_posix()] = sha256(path.read_bytes()).hexdigest()
    missing = REQUIRED - set(found)
    if missing:
        raise ValueError(f"Preparation kit missing required files: {sorted(missing)}")
    return found


def export_kit(source: Path, target: Path) -> dict[str, str]:
    source = source.resolve(strict=True)
    target = target.resolve(strict=False)
    if target == source or source in target.parents or target in source.parents:
        raise ValueError("Export target and source must be separate folders")
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite destination: {target}")
    manifest = build_manifest(source)
    target.mkdir(parents=True)
    try:
        for relative in manifest:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, destination)
        for relative, checksum in manifest.items():
            if sha256((target / relative).read_bytes()).hexdigest() != checksum:
                raise IOError(f"Copy verification mismatch: {relative}")
    except Exception:
        shutil.rmtree(target)
        raise
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a clean, local, standalone source tree")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = export_kit(args.source, args.destination)
    except (ValueError, OSError) as exc:
        print(f"EXPORT BLOCKED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"exported": True, "files": len(manifest),
                      "destination": str(args.destination.resolve()),
                      "manifest_sha256": sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
