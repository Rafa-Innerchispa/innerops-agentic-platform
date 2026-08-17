"""AG-43 Platform Sync — sync dual-nodo, failover dry-run, clone tenant."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run
from raphiia_openai.settings import RALFIA_AMD_HOST, RALFIA_INTEL_HOST

AGENT_ID = "AG-43_PLATFORM_SYNC"
INNEROS_ROOT = Path("/home/rlopez/inneros/inneros_core")
FAILOVER_SCRIPT = INNEROS_ROOT / "scripts" / "failover_intel_to_amd.sh"
CLONE_SCRIPT = INNEROS_ROOT / "scripts" / "clone_deployment.sh"


def sync_platform_to_intel(*, dry_run: bool = False) -> dict[str, Any]:
    from raphiia_openai import mcp_fleet

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "agent_id": AGENT_ID,
            "would_run": "mcp_fleet.sync_intel_from_local()",
            "local_node": mcp_fleet.local_node_id(),
        }
    result = mcp_fleet.sync_intel_from_local()
    record_agent_run(AGENT_ID, action="sync_platform_to_intel", summary=f"ok={result.get('ok')}", project="ralfia-ops")
    return {"ok": bool(result.get("ok")), "agent_id": AGENT_ID, **result}


def run_failover_dry_run() -> dict[str, Any]:
    if not FAILOVER_SCRIPT.is_file():
        return {"ok": False, "error": "failover_script_missing", "path": str(FAILOVER_SCRIPT)}
    try:
        proc = subprocess.run(
            ["bash", str(FAILOVER_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(INNEROS_ROOT),
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0
        record_agent_run(AGENT_ID, action="run_failover_dry_run", summary=f"exit={proc.returncode}", project="ralfia-ops")
        return {
            "ok": ok,
            "agent_id": AGENT_ID,
            "exit_code": proc.returncode,
            "output_tail": output[-3000:],
            "intel_host": RALFIA_INTEL_HOST,
            "amd_host": RALFIA_AMD_HOST,
        }
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"ok": False, "agent_id": AGENT_ID, "error": str(exc)}


def clone_tenant_deployment(slug: str, entity_id: str, dest_dir: str = "", *, dry_run: bool = True) -> dict[str, Any]:
    slug = (slug or "").strip()
    entity_id = (entity_id or "").strip()
    if not slug or not entity_id:
        return {"ok": False, "error": "slug_and_entity_id_required"}
    dest = dest_dir.strip() or f"/home/rlopez/inneros/deployments/{slug}"
    cmd = ["bash", str(CLONE_SCRIPT), slug, entity_id, dest]
    if dry_run:
        return {"ok": True, "dry_run": True, "agent_id": AGENT_ID, "would_run": cmd}
    if not CLONE_SCRIPT.is_file():
        return {"ok": False, "error": "clone_script_missing", "path": str(CLONE_SCRIPT)}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(INNEROS_ROOT))
        record_agent_run(AGENT_ID, action="clone_tenant_deployment", summary=f"slug={slug} ok={proc.returncode==0}", project="ralfia-ops")
        return {
            "ok": proc.returncode == 0,
            "agent_id": AGENT_ID,
            "slug": slug,
            "entity_id": entity_id,
            "dest": dest,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-1000:],
        }
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"ok": False, "agent_id": AGENT_ID, "error": str(exc)}
