#!/usr/bin/env python3
"""Store Cursor User API key in owner_vault and platform/.env (stdin or --file)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inneros_core_runtime import owner_vault


def _merge_env_line(env_path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="
    lines = [ln for ln in lines if not ln.startswith(prefix)]
    lines.append(f"{prefix}{value}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_path.chmod(0o600)


def main() -> int:
    p = argparse.ArgumentParser(description="Store Cursor API key (owner vault + .env)")
    p.add_argument("--file", type=Path, help="Read key from file instead of stdin")
    args = p.parse_args()
    if args.file:
        secret = args.file.read_text(encoding="utf-8").strip()
    else:
        secret = sys.stdin.read().strip()
    if len(secret) < 20:
        print('{"ok": false, "error": "key_too_short"}')
        return 1
    saved = owner_vault.save_owner_credential(
        key="api_key",
        secret=secret,
        category="cursor",
        label="Cursor User API key (SDK / Cloud Agents)",
    )
    if not saved.get("ok"):
        print(saved)
        return 2
    env_path = ROOT / ".env"
    _merge_env_line(env_path, "CURSOR_API_KEY", secret)
    print('{"ok": true, "vault_id": "%s", "env": "%s"}' % (saved.get("vault_id"), str(env_path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
