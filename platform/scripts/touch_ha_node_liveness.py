#!/usr/bin/env python3
"""Keep Cursor HA node liveness fresh (systemd timer on Intel and AMD)."""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from inneros_core_runtime import cursor_headless_lanes as lanes
payload = lanes.touch_node_liveness()
print(json.dumps({"ok": True, "liveness": payload, "lane_status": lanes.lane_status()}, default=str))
