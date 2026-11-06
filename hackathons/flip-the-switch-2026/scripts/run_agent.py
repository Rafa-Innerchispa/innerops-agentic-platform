#!/usr/bin/env python3
"""Start the Switch room agent using a private, registered credential file.

Never print secrets. State stays inside the user's private home directory.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from inneros_incident_room.switch_event import SwitchConfig, serve

DEFAULT_FILE = Path.home() / ".config" / "inneros-switch" / "agent-credentials.json"


def load_config(path: Path, room_id: str, approver_id: str) -> SwitchConfig:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not room_id or not approver_id:
        raise ValueError("SWITCH_ROOM_ID and SWITCH_APPROVER_ID must be provided")
    base = value.get("base_url", "").rstrip("/")
    agent_id = value.get("agent_id", "")
    api_key = value.get("api_key", "")
    if not base or not agent_id or not api_key:
        raise ValueError("Credential file missing one or more required fields")
    # Reuse strict transport validation from original environment-based contract.
    from unittest.mock import patch  # only affects the brief configuration read
    env = {"SWITCH_URL": base, "SWITCH_AGENT_ID": agent_id,
           "SWITCH_AGENT_API_KEY": api_key,
           "SWITCH_ROOM_ID": room_id, "SWITCH_APPROVER_ID": approver_id,
           "SWITCH_STATE_PATH": str(path.with_name("room-connection.json"))}
    with patch.dict(os.environ, env):
        return SwitchConfig.from_env()


def doctor(config: SwitchConfig) -> bool:
    base = config.base_url
    try:
        with urlopen(base + "/health", timeout=4) as result:
            if result.status != 200:
                raise ValueError("health returned non-200")
        req = Request(base + "/agents/" + config.agent_id + "/ops",
                      headers={"Authorization": "Bearer " + config.api_key})
        with urlopen(req, timeout=4) as result:
            if result.status != 200:
                raise ValueError("authenticated ops returned non-200")
        print("PASS: Switch API is reachable; agent credential accepted. No room traffic asserted.")
        return True
    except (HTTPError, URLError, OSError, ValueError):
        print("BLOCKED: Switch API or agent key is not ready. No commands were executed.",file=sys.stderr)
        return False


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="Run synthetic-only InnerOS Switch agent")
    parser.add_argument("--credentials",type=Path,default=DEFAULT_FILE)
    parser.add_argument("--room", default=os.getenv("SWITCH_ROOM_ID", ""))
    parser.add_argument("--approver",default=os.getenv("SWITCH_APPROVER_ID", ""))
    parser.add_argument("--doctor",action="store_true",help="Read-only server and auth verification")
    args=parser.parse_args(argv)
    try:
        cfg=load_config(args.credentials.expanduser(),args.room,args.approver)
    except (ValueError,OSError,TypeError,KeyError,json.JSONDecodeError):
        print("BLOCKED: bad credential file or missing room/approver IDs.",file=sys.stderr)
        return 2
    if args.doctor:
        return 0 if doctor(cfg) else 1
    print("Starting synthetic-only room agent. No device/network mutation capability.")
    try:
        asyncio.run(serve(cfg))
    except KeyboardInterrupt:
        print("Stopped by operator")
    return 0


if __name__=="__main__":
    raise SystemExit(main())