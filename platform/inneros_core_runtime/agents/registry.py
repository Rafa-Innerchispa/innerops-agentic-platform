"""Registro canónico de agentes Ralphi IA — numeración AG-xx."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai.operational.constants import COL_AGENT_REGISTRY

INNEROS_CORE_ROOT = Path(os.getenv("INNEROS_CORE_ROOT", "/home/rlopez/inneros/inneros_core"))
AGENT_POOL_ROOT = Path(os.getenv("INNEROS_AGENTS_POOL", str(INNEROS_CORE_ROOT / "agents_pool")))

MAP_FILES = {
    "central": "MAPA_CENTRAL.md",
    "agents_human": "ESPECIALIDADES_AGENTES.md",
    "agents_auto_log": "AGENT_AUTO_LOG.md",
    "ports": "PORTS_CANONICAL.md",
    "registry_spec": "cursor/specs/AGENT_REGISTRY_AND_MAILBOXES.md",
    "mcp_architecture": "cursor/specs/MCP_STABILIZATION_AND_AGENT_ARCHITECTURE.md",
    "code_registry": "raphiia_openai/agents/registry.py",
}

PC_DOCTOR_AGENT_IDS = {"AG-06", "AG-13", "AG-14", "AG-15", "AG-16", "AG-20", "AG-38", "AG-39"}

DOMAIN_TAGS = {
    "pcdoctor": ("pcdoctor", "field", "technical", "visit", "camera", "alarm", "network", "wifi", "inventory", "ocr"),
    "coordination": ("coordination", "orchestrator", "watchdog", "agent"),
    "social": ("marketing", "media", "linkedin", "content", "editorial"),
    "funding": ("fund", "opportunity", "hackathon", "grant"),
    "whatsapp": ("whatsapp", "evolution"),
    "notion": ("notion",),
    "finance": ("financial", "billing", "invoice", "collections"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _extract_name(readme: Path) -> str:
    if not readme.exists():
        return ""
    for line in _read_text(readme).splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _agent_folder_meta(folder: Path) -> dict[str, Any]:
    agent_id_match = re.match(r"^(AG-\d+)(?:_(.*))?$", folder.name)
    agent_id = agent_id_match.group(1) if agent_id_match else folder.name
    slug = agent_id_match.group(2) if agent_id_match and agent_id_match.group(2) else folder.name.lower().replace("-", "_")
    readme = folder / "README.md"
    config_dir = folder / "config"
    src_dir = folder / "src"
    capabilities: list[str] = []
    if readme.exists():
        capabilities.append("readme")
    if (config_dir / "agent.yaml").exists():
        capabilities.append("config_agent")
    if (config_dir / "tasks.yaml").exists():
        capabilities.append("config_tasks")
    if (src_dir / "logic.py").exists():
        capabilities.append("runtime_logic")

    owner_projects: list[str] = []
    haystack = f"{folder.name} {slug} {_read_text(readme)}".lower()
    for project, needles in DOMAIN_TAGS.items():
        if any(needle in haystack for needle in needles):
            owner_projects.append(project)
    if agent_id in PC_DOCTOR_AGENT_IDS:
        owner_projects.append("pcdoctor")
    if agent_id == "AG-25":
        owner_projects.extend(["coordination", "platform"])
    if agent_id == "AG-31":
        owner_projects.extend(["platform", "ops"])
    if agent_id == "AG-30":
        owner_projects.append("whatsapp")
    if not owner_projects:
        owner_projects.append("platform")
    owner_projects = sorted(dict.fromkeys(owner_projects))

    stat = folder.stat()
    now = _now_iso()
    return {
        "agent_id": agent_id,
        "slug": slug,
        "name": _extract_name(readme) or slug.replace("_", " ").title(),
        "type": "folder",
        "risk_level": "medium" if "platform" in owner_projects else "low",
        "entrypoint": f"inneros_core/agents_pool/{folder.name}/",
        "source_root": str(AGENT_POOL_ROOT),
        "owner_project": owner_projects,
        "capabilities": capabilities,
        "files": {
            "README.md": readme.exists(),
            "config/agent.yaml": (config_dir / "agent.yaml").exists(),
            "config/tasks.yaml": (config_dir / "tasks.yaml").exists(),
            "src/logic.py": (src_dir / "logic.py").exists(),
        },
        "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "created_at": now,
        "updated_at": now,
    }


def _scan_pool() -> list[dict[str, Any]]:
    if not AGENT_POOL_ROOT.exists():
        return []
    items: list[dict[str, Any]] = []
    for folder in sorted([p for p in AGENT_POOL_ROOT.iterdir() if p.is_dir()], key=lambda p: p.name):
        if not re.match(r"^AG-\d+", folder.name):
            continue
        items.append(_agent_folder_meta(folder))
    return items


def _sort_key(agent: dict[str, Any]) -> tuple[int, str]:
    match = re.search(r"AG-(\d+)", agent.get("agent_id", ""))
    number = int(match.group(1)) if match else 999
    return (number, agent.get("agent_id", ""))


def list_agents(project: str | None = None, include_files: bool = False) -> list[dict[str, Any]]:
    agents = _scan_pool()
    if project:
        needle = project.strip().lower()
        agents = [agent for agent in agents if needle in " ".join(agent.get("owner_project", [])).lower()]
    agents = sorted(agents, key=_sort_key)
    if not include_files:
        for agent in agents:
            agent.pop("files", None)
    return agents


def get_agent(agent_id: str) -> dict[str, Any] | None:
    needle = (agent_id or "").strip().lower()
    for agent in _scan_pool():
        if agent.get("agent_id", "").lower() == needle or agent.get("slug", "").lower() == needle:
            return agent
    return None


def list_project_bindings(project: str | None = None) -> dict[str, Any]:
    agents = list_agents()
    bindings: dict[str, list[str]] = {}
    for agent in agents:
        for proj in agent.get("owner_project", []) or []:
            bindings.setdefault(proj, []).append(agent["agent_id"])
    if project:
        needle = project.strip().lower()
        bindings = {k: v for k, v in bindings.items() if needle in k.lower()}
    return {
        "ok": True,
        "count": len(bindings),
        "project_bindings": {k: sorted(v) for k, v in sorted(bindings.items())},
        "source": "inneros_core/agents_pool",
        "updated_at": _now_iso(),
    }


def seed_mongo_registry(force: bool = False) -> dict[str, Any]:
    from raphiia_openai import mongo_store

    db = mongo_store.get_db()
    agents = list_agents(include_files=True)
    upserted = 0
    for meta in agents:
        aid = meta["agent_id"]
        doc = {
            **meta,
            "status": "active",
            "owner": "ralfia-platform",
            "source": "inneros_core/agents_pool",
            "registry_version": "v1",
            "updated_at": _now_iso(),
        }
        if force:
            db[COL_AGENT_REGISTRY].delete_many({"agent_id": aid})
        db[COL_AGENT_REGISTRY].update_one(
            {"agent_id": aid},
            {"$set": doc, "$setOnInsert": {"first_seen_at": _now_iso()}},
            upsert=True,
        )
        upserted += 1
    return {
        "ok": True,
        "count": upserted,
        "source": "inneros_core/agents_pool",
        "updated_at": _now_iso(),
    }
