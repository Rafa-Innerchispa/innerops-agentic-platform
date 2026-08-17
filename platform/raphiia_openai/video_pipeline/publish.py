"""Publicación multi-destino de vídeos generados."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def publish_video(
    video_path: str,
    *,
    title: str = "",
    caption: str = "",
    destinations: list[str] | None = None,
    whatsapp_status_jids: list[str] | None = None,
    node: str = "primary",
) -> dict[str, Any]:
    path = Path(video_path)
    if not path.is_file():
        return {"ok": False, "error": f"video not found: {path}"}

    dests = [d.strip().lower() for d in (destinations or ["whatsapp_status"]) if d.strip()]
    outcomes: dict[str, Any] = {}

    if "whatsapp_status" in dests or "whatsapp" in dests:
        from raphiia_openai.notifications.settings import (
            WHATSAPP_AMD_STATUS_ENABLED,
            WHATSAPP_STATUS_ENABLED,
        )

        n = (node or "primary").strip().lower()
        is_amd = n in ("amd", "backup", "5", ".5")
        if not WHATSAPP_STATUS_ENABLED:
            outcomes["whatsapp_status"] = {
                "ok": False,
                "status": "blocked",
                "message": "WHATSAPP_STATUS_ENABLED=0 — estados desactivados",
            }
        elif is_amd and not WHATSAPP_AMD_STATUS_ENABLED:
            outcomes["whatsapp_status"] = {
                "ok": False,
                "status": "blocked",
                "message": "WHATSAPP_AMD_STATUS_ENABLED=0 — estados AMD desactivados durante warm-up",
            }
        else:
            from raphiia_openai import whatsapp_mcp_bridge

            outcomes["whatsapp_status"] = whatsapp_mcp_bridge.send_whatsapp_status(
                content=caption or title,
                status_type="video",
                caption=caption or title,
                file_path=str(path),
                all_contacts=False,
                status_jid_list=whatsapp_status_jids,
                node=node,
            )

    if "linkedin" in dests:
        outcomes["linkedin"] = {
            "ok": False,
            "skipped": True,
            "hint": "LinkedIn video API pendiente — publica imagen+texto vía publish_pipeline_item",
        }

    if "web" in dests or "innerchispa" in dests:
        try:
            from raphiia_openai.operational import web_content_manager

            outcomes["web"] = web_content_manager.export_video_asset(
                str(path), title=title, caption=caption
            )
        except Exception as exc:
            outcomes["web"] = {"ok": False, "error": str(exc)}

    ok = any(isinstance(v, dict) and v.get("ok") for v in outcomes.values())
    return {"ok": ok, "destinations": outcomes, "video_path": str(path)}
