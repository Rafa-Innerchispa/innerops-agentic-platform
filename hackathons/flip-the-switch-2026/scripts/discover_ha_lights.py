#!/usr/bin/env python3
"""List real Home Assistant lights from authenticated REST API. Read-only."""
from __future__ import annotations

import os
import sys

from inneros_incident_room.live_homeassistant import HomeAssistantClient, LiveHAError, LIGHT_ID


def main() -> int:
    try:
        ha = HomeAssistantClient(os.environ["HA_URL"], os.environ["HA_TOKEN"])
        if not ha.ping():
            raise LiveHAError("Home Assistant API identity could not be verified")
        items = ha._request("/api/states")
        if not isinstance(items, list):
            raise LiveHAError("Unexpected Home Assistant state response")
        lights = sorted([v for v in items if isinstance(v, dict) and
                         LIGHT_ID.fullmatch(str(v.get("entity_id", "")))],
                        key=lambda v: v["entity_id"])
        print("REAL HA light entities, read-only discovery (no commands sent):")
        if not lights:
            print("No light entities found; check the actual HA server and integration.")
            return 2
        for item in lights:
            entity = item["entity_id"]
            state = item.get("state", "UNKNOWN")
            name = str((item.get("attributes") or {}).get("friendly_name", entity))[:80]
            print(f"  {entity} = {state}; {name}")
        return 0
    except (OSError, ValueError, LiveHAError, KeyError) as exc:
        print("BLOCKED: live HA light inventory could not be fetched: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())