#!/usr/bin/env python3
"""Read-only Switch room and participant discovery after agent registration.

Printing room/user identifiers is for LOCAL operator inspection only. Never
commit console output to the public hackathon repo.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from run_agent import DEFAULT_FILE


def invoke(base: str, agent: str, api_key: str, operation: str, payload: dict) -> dict:
    url = f"{base}/agents/{agent}/ops/{operation}"
    req = Request(url, data=json.dumps(payload).encode(), method="POST",
                  headers={"Authorization": "Bearer " + api_key,
                           "Content-Type": "application/json"})
    with urlopen(req, timeout=5) as r:
        return json.load(r)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read room and participant IDs from Switch")
    parser.add_argument("--credentials",type=Path,default=DEFAULT_FILE)
    parser.add_argument("--room",help="Room identifier to list participants in")
    args=parser.parse_args(argv)
    try:
        cfg=json.loads(args.credentials.expanduser().read_text(encoding="utf-8"))
        result=invoke(cfg["base_url"],cfg["agent_id"],cfg["api_key"],"list_rooms",{})
        print("Rooms visible to the registered agent (read-only):")
        print(json.dumps(result,indent=2)[:6000])
        if args.room:
            users=invoke(cfg["base_url"],cfg["agent_id"],cfg["api_key"],
                         "list_participants",{"room_id":args.room})
            print("Participants in selected room (read-only):")
            print(json.dumps(users,indent=2)[:6000])
        return 0
    except (HTTPError,URLError,ValueError,OSError,KeyError) as exc:
        print("Could not list Switch rooms/participants:",type(exc).__name__,file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())