#!/usr/bin/env python3
"""Launch Switch agent against real Home Assistant, never synthetic devices."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sys

from inneros_incident_room.live_homeassistant import LiveHAError, policy_from_env
from inneros_incident_room.switch_event import serve
from run_agent import DEFAULT_FILE, doctor, load_config


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Switch + real Home Assistant light bridge")
    parser.add_argument("--credentials", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--doctor", action="store_true")
    args = parser.parse_args(argv)
    try:
        room = os.environ["SWITCH_ROOM_ID"]
        approver = os.environ["SWITCH_APPROVER_ID"]
        config = load_config(args.credentials.expanduser(), room, approver)
        policy = policy_from_env(room, approver)
        if not policy.ha.ping():
            raise LiveHAError("Home Assistant did not return a valid live API health response")
        lights = policy.ha.lights(policy.allowed_lights)
        if not lights:
            raise LiveHAError("No allowlisted lights in Home Assistant; choose a real light ID")
        print(f"HA LIVE OK: {len(lights)} allowlisted lights; write_enabled={policy.actions_enabled}; no mutations attempted")
        for light in lights:
            print(f"  {light['entity_id']} = {light['state']} ({light['name']})")
        if args.doctor:
            return 0 if doctor(config) else 1
        print("Starting REAL Home Assistant Switch agent; approval is required for every write.")
        asyncio.run(serve(config, policy_factory=lambda: policy))
        return 0
    except (ValueError, KeyError, OSError, LiveHAError) as exc:
        print("BLOCKED: live integration prerequisites missing or failed: " + type(exc).__name__, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())