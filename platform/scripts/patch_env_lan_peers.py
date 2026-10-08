#!/usr/bin/env python3
"""Reemplaza hosts Tailscale (100.x) por LAN (192.168.1.4/5) en platform/.env."""

from __future__ import annotations

import re
import sys
from pathlib import Path

LAN_INTEL = "192.168.1.4"
LAN_AMD = "192.168.1.5"
TS_INTEL = "100.94.99.12"
TS_AMD = "100.72.153.124"

KEEP_TS_KEYS = frozenset(
    {
        "RALFIA_TS_INTEL",
        "RALFIA_TS_AMD",
    }
)

SET_KEYS_INTEL = {
    "RALFIA_LAN_IP": LAN_INTEL,
    "RALFIA_INTEL_HOST": LAN_INTEL,
    "RALFIA_AMD_HOST": LAN_AMD,
    "RALFIA_PEER_INTEL": LAN_INTEL,
    "RALFIA_PEER_AMD": LAN_AMD,
    "MCP_LAN_URL_INTEL": f"http://{LAN_INTEL}:8102/mcp",
    "MCP_LAN_URL_AMD": f"http://{LAN_AMD}:8102/mcp",
    "MCP_LAN_URL": f"http://{LAN_INTEL}:8102/mcp",
}

SET_KEYS_AMD = {
    **SET_KEYS_INTEL,
    "RALFIA_LAN_IP": LAN_AMD,
    "MCP_LAN_URL": f"http://{LAN_AMD}:8102/mcp",
    "MONGO_URI": f"mongodb://{LAN_INTEL}:27017/",
    "MONGO_URI_PRIMARY": f"mongodb://{LAN_INTEL}:27017/",
    "SWARM_API_BASE": f"http://{LAN_INTEL}:8100",
    "WHISPER_URL_INTEL": f"http://{LAN_INTEL}:9001",
    "QDRANT_URL_PRIMARY": f"http://{LAN_INTEL}:6333",
}


def _detect_role(lines: list[str]) -> str:
    for line in lines:
        if line.startswith("RALFIA_NODE="):
            v = line.split("=", 1)[1].strip().lower()
            if v in ("amd", "primary", "intel"):
                return "amd" if v == "amd" else "intel"
        if line.startswith("RALFIA_LAN_IP="):
            ip = line.split("=", 1)[1].strip()
            if ip == LAN_AMD:
                return "amd"
            if ip == LAN_INTEL or ip == TS_INTEL:
                return "intel"
    return "intel"


def patch_env(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    raw = path.read_text()
    lines = raw.splitlines()
    role = _detect_role(lines)
    overrides = SET_KEYS_AMD if role == "amd" else SET_KEYS_INTEL
    seen: set[str] = set()
    out: list[str] = []
    changed = False
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            out.append(line)
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if key in overrides:
            new_val = overrides[key]
            if val != new_val:
                changed = True
            out.append(f"{key}={new_val}")
            seen.add(key)
            continue
        if key in KEEP_TS_KEYS:
            out.append(line)
            seen.add(key)
            continue
        new_val = val.replace(TS_INTEL, LAN_INTEL).replace(TS_AMD, LAN_AMD)
        if new_val != val:
            changed = True
        out.append(f"{key}={new_val}")
        seen.add(key)
    for key, val in overrides.items():
        if key not in seen:
            out.append(f"{key}={val}")
            changed = True
    if changed:
        path.write_text("\n".join(out).rstrip() + "\n")
    return changed, role


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / ".env")
    ok, role = patch_env(path)
    print(f"{'patched' if ok else 'unchanged'} role={role} path={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
