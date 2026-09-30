"""AG-57 DMX Stage Orchestrator — runner for InnerOS agent fabric."""

from __future__ import annotations

from typing import Any


AGENT_ID = "AG-57"


def _import_runner():
    import sys
    dmx_path = "/home/rlopez/projects/inneros-dmx-engine"
    if dmx_path not in sys.path:
        sys.path.insert(0, dmx_path)
    from src.effects_engine import DynamicEffectsRunner
    return DynamicEffectsRunner(target_ip="192.168.1.10", universe=0)


def run_ag57(message: str = "", *, dry_run: bool = True, **kwargs: Any) -> dict[str, Any]:
    text = (message or "").strip().lower()
    if dry_run and not text:
        import sys
        dmx_path = "/home/rlopez/projects/inneros-dmx-engine"
        if dmx_path not in sys.path:
            sys.path.insert(0, dmx_path)
        from src.fixture_profiles import FIXTURES as FX
        return {
            "ok": True,
            "agent_id": AGENT_ID,
            "ping": True,
            "display_name": "DMX Stage Orchestrator",
            "mcp_tools": ["dmx_status", "dmx_set_scene", "dmx_blackout"],
            "fixture_count": len(FX),
            "supported_scenes": ["rainbow", "frenzy", "police", "fire", "chill_lounge", "morado_uv", "static", "blackout"],
        }

    runner = _import_runner()
    if any(word in text for word in ("blackout", "apaga", "apagar")):
        runner.blackout()
        return {"ok": True, "agent_id": AGENT_ID, "action": "blackout"}
    if any(word in text for word in ("rainbow", "arcoiris", "arco iris")):
        runner.start_effect("rainbow", speed=1.0)
        return {"ok": True, "agent_id": AGENT_ID, "action": "rainbow"}
    if any(word in text for word in ("frenzy", "fiesta", "disco")):
        runner.start_effect("frenzy", speed=1.0)
        return {"ok": True, "agent_id": AGENT_ID, "action": "frenzy"}
    if "morado" in text or "uv" in text:
        runner.apply_static_scene(color_name="morado", brightness=255, target="todas")
        return {"ok": True, "agent_id": AGENT_ID, "action": "morado_uv"}
    if "rojo" in text or "sangre" in text:
        runner.apply_static_scene(color_name="rojo", brightness=255, target="todas")
        return {"ok": True, "agent_id": AGENT_ID, "action": "rojo_sangre"}
    return {
        "ok": False,
        "agent_id": AGENT_ID,
        "error": "unsupported_dmx_intent",
        "hint": "Use dmx_status, dmx_set_scene, or dmx_blackout MCP/WebMCP tools",
    }
