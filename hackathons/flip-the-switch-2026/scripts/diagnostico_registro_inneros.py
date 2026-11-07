#!/usr/bin/env python3
"""Read-only Switch 0.40.1 local registration diagnosis, no secrets printed.

Uses local native admin credentials only for an in-memory login session.
Checks health, gateway auth configuration, login and temporary-key listing.
Does not create or revoke any keys or agents.
"""
from __future__ import annotations
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, HTTPCookieProcessor, build_opener

BASE = "http://127.0.0.1:62226"
PREFIX = "InnerOS LiveOps temporary local registration"
ENV_FILE = Path(os.environ.get("APPDATA", "")) / "switchdash" / "local-switch-server" / "native" / "run" / "switch-core.env"
CREDENTIALS = Path.home() / ".config" / "inneros-switch" / "agent-credentials.json"


def probe(label: str, opener, method: str, path: str, body=None, timeout: int = 25):
    print(label + " ...", flush=True)
    start = time.monotonic()
    try:
        req = Request(BASE + path,
                      data=(json.dumps(body).encode("utf-8") if body is not None else None),
                      headers={"Content-Type": "application/json"}, method=method)
        with opener.open(req, timeout=timeout) as response:
            result = json.load(response)
        print("  OK (%.1f s)" % (time.monotonic() - start), flush=True)
        return result
    except HTTPError as exc:
        print("  ERROR HTTP %s (%.1f s)" % (exc.code, time.monotonic() - start), flush=True)
    except (TimeoutError, URLError, OSError, ValueError) as exc:
        print("  ERROR %s (%.1f s)" % (type(exc).__name__, time.monotonic() - start), flush=True)
    return None


def main() -> int:
    print("=== SWITCH 0.40.1 | DIAGNOSTICO SOLO LECTURA ===")
    print("Credencial de agente guardada:", "SI" if CREDENTIALS.exists() else "NO")
    if not ENV_FILE.is_file():
        print("BLOCKED: Switch native runtime config not found. No secret accessed.")
        return 1
    config = {}
    with ENV_FILE.open(encoding="utf-8-sig") as fh:
        for line in fh:
            key, sep, val = line.rstrip("\r\n").partition("=")
            if sep and key in {"GATEWAY_ADMIN_EMAIL", "GATEWAY_ADMIN_PASSWORD", "SERVER_PORT"}:
                config[key] = val
    if config.get("SERVER_PORT") != "62226" or not all(config.get(k) for k in ("GATEWAY_ADMIN_EMAIL", "GATEWAY_ADMIN_PASSWORD")):
        print("BLOCKED: local server port or admin settings differ. No password was sent.")
        return 1
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
    health = probe("[1/4] Health", opener, "GET", "/health", timeout=8)
    if not isinstance(health, dict) or health.get("status") != "ok":
        return 1
    auth = probe("[2/4] Auth config", opener, "GET", "/gateway/auth/config", timeout=15)
    if not isinstance(auth, dict):
        return 1
    login = probe("[3/4] Admin login", opener, "POST", "/gateway/auth/login",
                  {"email": config["GATEWAY_ADMIN_EMAIL"], "password": config["GATEWAY_ADMIN_PASSWORD"]}, timeout=25)
    if not isinstance(login, dict):
        return 1
    print("  Rol autorizado:", "admin" if login.get("role") == "admin" else "no_admin")
    if login.get("role") != "admin":
        return 1
    keys = probe("[4/4] List personal API keys", opener, "GET", "/gateway/api-keys", timeout=25)
    if not isinstance(keys, list):
        return 1
    leftovers = [k for k in keys if isinstance(k, dict) and k.get("label") == PREFIX]
    print("  Claves de registro temporal anteriores:", len(leftovers))
    print("DIAGNOSTICO COMPLETO: Gateway responde. No se crearon claves ni agentes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
