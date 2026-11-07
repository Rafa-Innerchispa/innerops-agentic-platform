#!/usr/bin/env python3
"""One-time custom-agent registration against a user-owned Switch server.

Use a Gateway-generated registration key in SWITCH_REGISTRATION_KEY. The issued
agent API key is saved in a private user-profile file; nothing secret is printed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_CREDENTIAL_FILE = Path.home() / ".config" / "inneros-switch" / "agent-credentials.json"


def valid_switch_url(base: str) -> bool:
    p = urlparse(base)
    return (p.scheme == "https" or (p.scheme == "http" and p.hostname in {"localhost", "127.0.0.1", "::1"})) and bool(p.hostname) and not (p.username or p.password or p.query or p.fragment)


def registration_payload(name: str) -> dict:
    return {
        "name": name,
        "display_name": "InnerOS Incident Room",
        "description": "Local-first Switch agent for real Home Assistant light observations and human-approved actions",
        "connector_type": "inneros-local-python",
        "integration_profile": {
            "connection_model": "always_on",
            "message_exchange": True,
            "pre_invocation_mediation": [],
            "post_invocation_mediation": [],
            "event_reporting": [],
        },
    }


def register(base: str, token: str, name: str, output: Path) -> dict:
    if not valid_switch_url(base):
        raise ValueError("Switch URL must use HTTPS, or loopback HTTP only")
    if not token or not token.strip():
        raise ValueError("SWITCH_REGISTRATION_KEY is missing")
    if output.exists():
        raise FileExistsError("Credential file already exists; refusing to overwrite it")
    req = Request(base.rstrip("/") + "/agents",
                  data=json.dumps(registration_payload(name)).encode(), method="POST",
                  headers={"Authorization": "Bearer " + token,
                           "Content-Type": "application/json"})
    with urlopen(req, timeout=8) as res:
        response = json.load(res)
    agent_id, agent_api_key = response.get("id"), response.get("api_key")
    if not isinstance(agent_id, str) or not agent_id or not isinstance(agent_api_key, str) or not agent_api_key:
        raise RuntimeError("Registration response missing id or API key; no file was saved")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({"base_url": base.rstrip("/"), "agent_id": agent_id,
                       "api_key": agent_api_key,
                       "created_at_utc": datetime.now(timezone.utc).isoformat()}, out)
        try:
            os.chmod(output, 0o600)
        except OSError:
            pass
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return {"registered": True, "agent_id": agent_id, "credential_file": str(output),
            "api_key_printed": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Register a Switch custom agent once")
    parser.add_argument("--url", default=os.environ.get("SWITCH_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--name", default="inneros-incident-triage")
    parser.add_argument("--output", type=Path, default=DEFAULT_CREDENTIAL_FILE)
    args = parser.parse_args(argv)
    try:
        result = register(args.url, os.environ.get("SWITCH_REGISTRATION_KEY", ""),args.name,args.output.expanduser())
        print(json.dumps(result, indent=2))
        return 0
    except HTTPError as exc:
        print("Registration failed: HTTP", exc.code, "(409 means name already registered; do not overwrite)", file=sys.stderr)
    except (URLError, OSError, ValueError, RuntimeError) as exc:
        print("Registration failed:", type(exc).__name__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())