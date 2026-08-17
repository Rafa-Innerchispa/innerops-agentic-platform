"""Contrato único de ciclo de vida de proyectos Ralphi IA — scaffold + systemd 24/7 + Mongo."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import agent_auto_log, mongo_store, service_registry
from raphiia_openai.settings import COL_RALFIA_PROJECTS, COL_SERVICE_REGISTRY, COORD_ROOT, ROOT

PROJECTS_ROOT = Path("/home/rlopez/projects")
SYSTEMD_USER = Path.home() / ".config/systemd/user"

# Puertos reservados del ecosistema — no asignar a proyectos nuevos.
RESERVED_PORTS: frozenset[int] = frozenset(
    {
        2002,
        3000,
        3001,
        5173,
        5188,
        5190,
        5678,
        6333,
        8091,
        8096,
        8097,
        8098,
        8099,
        8100,
        8101,
        8102,
        8103,
        8200,
        8800,
        11434,
        27017,
    }
)

DYNAMIC_PORT_MIN = 8120
DYNAMIC_PORT_MAX = 8999

LIFECYCLE_SCAFFOLD = "scaffold"
LIFECYCLE_ALWAYS_ALIVE = "always_alive"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "project"


def _listening_ports() -> set[int]:
    ports: set[int] = set()
    try:
        out = subprocess.check_output(["ss", "-tlnH"], text=True, timeout=8)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            addr = parts[3]
            if ":" in addr:
                try:
                    ports.add(int(addr.rsplit(":", 1)[-1]))
                except ValueError:
                    pass
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    try:
        db = mongo_store.get_db()
        for row in db[COL_SERVICE_REGISTRY].find({"port": {"$gt": 0}}, {"port": 1}):
            if row.get("port"):
                ports.add(int(row["port"]))
        for row in db[COL_RALFIA_PROJECTS].find({"ports": {"$exists": True}}, {"ports": 1}):
            for p in row.get("ports") or []:
                ports.add(int(p))
    except Exception:
        pass
    return ports


def allocate_port(preferred: int | None = None) -> int:
    """Asigna puerto libre en rango dinámico 8120–8999."""
    used = _listening_ports() | RESERVED_PORTS
    if preferred and preferred not in used and DYNAMIC_PORT_MIN <= preferred <= DYNAMIC_PORT_MAX:
        return preferred
    for port in range(DYNAMIC_PORT_MIN, DYNAMIC_PORT_MAX + 1):
        if port not in used:
            return port
    raise RuntimeError("no hay puertos libres en rango 8120–8999")


def ensure_runtime_baseline() -> dict[str, Any]:
    """Linger + daemon-reload — prerequisito 24/7 para servicios user."""
    SYSTEMD_USER.mkdir(parents=True, exist_ok=True)
    linger = subprocess.run(
        ["loginctl", "enable-linger", os.environ.get("USER", Path.home().name)],
        capture_output=True,
        text=True,
    )
    reload = subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
    return {
        "ok": reload.returncode == 0,
        "linger_enabled": linger.returncode == 0,
        "systemd_user_dir": str(SYSTEMD_USER),
    }


def _systemd_unit_name(slug: str) -> str:
    return f"ralf-{slug}.service"


def _render_systemd_unit(
    *,
    slug: str,
    name: str,
    project_path: Path,
    port: int,
    start_command: str,
) -> str:
    cmd = start_command.replace("{port}", str(port)).replace("{PORT}", str(port))
    free_port = ROOT / "scripts" / "free_port.sh"
    return f"""[Unit]
Description=Ralphi project {name} (:{port})
After=network.target

[Service]
Type=simple
WorkingDirectory={project_path}
Environment=PORT={port}
Environment=PROJECT_PORT={port}
ExecStartPre=/bin/bash {free_port} {port}
ExecStart=/bin/bash -lc '{cmd.replace("'", "'\\''")}'
Restart=always
RestartSec=12

[Install]
WantedBy=default.target
"""


def _write_run_sh(project_path: Path, port: int, start_command: str) -> None:
    cmd = start_command.replace("{port}", str(port)).replace("{PORT}", str(port))
    content = f"""#!/usr/bin/env bash
# Generado por ralphia_project_create — NO editar puerto a mano; usar metadata.json
set -euo pipefail
cd "$(dirname "$0")"
export PORT={port}
export PROJECT_PORT={port}
exec bash -lc '{cmd.replace("'", "'\\''")}'
"""
    run_path = project_path / "run.sh"
    run_path.write_text(content, encoding="utf-8")
    run_path.chmod(0o755)


def install_systemd_unit(
    *,
    slug: str,
    name: str,
    project_path: Path,
    port: int,
    start_command: str,
    enable: bool = True,
    start: bool = True,
) -> dict[str, Any]:
    ensure_runtime_baseline()
    unit_name = _systemd_unit_name(slug)
    unit_path = SYSTEMD_USER / unit_name
    unit_path.write_text(
        _render_systemd_unit(
            slug=slug,
            name=name,
            project_path=project_path,
            port=port,
            start_command=start_command,
        ),
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    result: dict[str, Any] = {"ok": True, "unit": unit_name, "unit_path": str(unit_path)}
    if enable:
        subprocess.run(["systemctl", "--user", "enable", unit_name], check=False)
    if start:
        proc = subprocess.run(["systemctl", "--user", "restart", unit_name], capture_output=True, text=True)
        result["start_exit"] = proc.returncode
        result["start_stderr"] = (proc.stderr or "").strip()[:500]
        active = subprocess.run(
            ["systemctl", "--user", "is-active", unit_name],
            capture_output=True,
            text=True,
        )
        result["is_active"] = (active.stdout or "").strip()
    return result


def register_project(doc: dict[str, Any]) -> dict[str, Any]:
    db = mongo_store.get_db()
    slug = doc["slug"]
    now = _now_iso()
    payload = {**doc, "updated_at": now}
    db[COL_RALFIA_PROJECTS].update_one(
        {"slug": slug},
        {"$set": payload, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    saved = db[COL_RALFIA_PROJECTS].find_one({"slug": slug}, {"_id": 0})
    port = int((doc.get("ports") or [0])[0])
    if port and doc.get("lifecycle") == LIFECYCLE_ALWAYS_ALIVE:
        service_registry.upsert_service(
            {
                "service_id": f"proj-{slug}",
                "name": doc.get("name", slug),
                "project": slug,
                "type": doc.get("project_type", "web"),
                "owner": doc.get("created_by", "RAFAEL"),
                "port": port,
                "local_url": f"http://192.168.1.4:{port}/",
                "health_endpoint": doc.get("health_endpoint") or f"http://127.0.0.1:{port}/",
                "systemd_unit": doc.get("systemd_unit", _systemd_unit_name(slug)),
                "risk_level": doc.get("risk_level", "medium"),
                "visible_in_panel": True,
                "notes": f"Proyecto always_alive — {doc.get('path', '')}",
            }
        )
    mongo_store.log_coordination(
        agent=doc.get("created_by", "RALFIA"),
        summary=f"Proyecto registrado: {slug} ({doc.get('lifecycle')})",
        event="project_lifecycle",
        project=slug,
        metadata={"port": port, "lifecycle": doc.get("lifecycle")},
    )
    return {"ok": True, "project": saved}


def _append_projects_registry_markdown(slug: str, name: str, port: int, path: str) -> None:
    reg_path = COORD_ROOT / "PROJECTS_REGISTRY.md"
    if not reg_path.is_file():
        return
    line = f"| {name} | `{path}` | {port} | ralphia_project_create | {_now_iso()[:10]} | Activo | always_alive systemd |\n"
    text = reg_path.read_text(encoding="utf-8")
    if slug in text or path in text:
        return
    marker = "## Plantilla fila nueva"
    if marker in text:
        text = text.replace(marker, line + "\n" + marker)
        reg_path.write_text(text, encoding="utf-8")


def create_project(
    *,
    name: str,
    slug: str | None = None,
    project_type: str = "web",
    port: int | None = None,
    start_command: str = "",
    hackathon_name: str = "",
    hackathon_url: str = "",
    health_endpoint: str = "",
    created_by: str = "CURSOR",
    adopt_path: str = "",
    fixed_port: bool = False,
    skip_systemd: bool = False,
    existing_systemd_unit: str = "",
    systemd_scope: str = "user",
) -> dict[str, Any]:
    """
    Punto único de creación.

    - Con ``start_command``: lifecycle ``always_alive`` + systemd + run.sh + registro.
    - Sin ``start_command``: lifecycle ``scaffold`` (solo carpetas + metadata; sin systemd).
    """
    slug = _slugify(slug or name)
    project_path = Path(adopt_path) if adopt_path else PROJECTS_ROOT / slug
    (project_path / "docs").mkdir(parents=True, exist_ok=True)

    assigned_port = 0
    if start_command or fixed_port:
        if fixed_port and port:
            assigned_port = int(port)
        elif start_command:
            assigned_port = allocate_port(port)
    lifecycle = (
        LIFECYCLE_ALWAYS_ALIVE
        if start_command or (skip_systemd and existing_systemd_unit) or (fixed_port and adopt_path)
        else LIFECYCLE_SCAFFOLD
    )

    metadata = {
        "project_name": slug,
        "display_name": name,
        "hackathon_name": hackathon_name or None,
        "hackathon_url": hackathon_url or None,
        "assigned_port": assigned_port or None,
        "server_ip": "192.168.1.4",
        "lifecycle": lifecycle,
        "created_by": created_by,
        "created_at": _now_iso(),
    }
    meta_path = project_path / "docs" / "metadata.json"
    if meta_path.parent.exists():
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest = {
        "slug": slug,
        "name": name,
        "lifecycle": lifecycle,
        "rules": [
            "Un solo camino: scripts/ralphia_project_create.py",
            "Servicios HTTP = always_alive + systemd user + Restart=always",
            "Puertos dinámicos 8120–8999; reservados en PORTS_CANONICAL.md",
            "Reinicio: bash scripts/restart_ralphia.sh (plataforma) o systemctl --user restart ralf-{slug}",
        ],
    }
    manifest_path = project_path / "PROJECT_MANIFEST.json"
    if project_path.exists():
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    systemd_result: dict[str, Any] | None = None
    unit_name = existing_systemd_unit or ""
    if start_command and not skip_systemd:
        _write_run_sh(project_path, assigned_port, start_command)
        systemd_result = install_systemd_unit(
            slug=slug,
            name=name,
            project_path=project_path,
            port=assigned_port,
            start_command=start_command,
        )
        unit_name = systemd_result.get("unit", _systemd_unit_name(slug))
    elif skip_systemd and existing_systemd_unit:
        unit_name = existing_systemd_unit

    project_doc = {
        "project_id": f"proj_{slug.replace('-', '_')}",
        "slug": slug,
        "name": name,
        "path": str(project_path),
        "ports": [assigned_port] if assigned_port else [],
        "project_type": project_type,
        "lifecycle": lifecycle,
        "systemd_unit": unit_name or None,
        "start_command": start_command or None,
        "health_endpoint": health_endpoint or (f"http://127.0.0.1:{assigned_port}/" if assigned_port else ""),
        "hackathon_name": hackathon_name or None,
        "hackathon_url": hackathon_url or None,
        "created_by": created_by,
        "systemd_scope": systemd_scope,
    }
    reg = register_project(project_doc)

    if lifecycle == LIFECYCLE_ALWAYS_ALIVE and assigned_port:
        _append_projects_registry_markdown(slug, name, assigned_port, str(project_path))

    notion_sync: dict[str, Any] | None = None
    try:
        from raphiia_openai.notion_projects_sync import notify_new_project

        notion_sync = notify_new_project(
            name=name,
            slug=slug,
            server_path=str(project_path),
            ports=[assigned_port] if assigned_port else None,
            created_by=created_by,
        )
    except Exception as exc:
        notion_sync = {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "slug": slug,
        "path": str(project_path),
        "port": assigned_port or None,
        "lifecycle": lifecycle,
        "systemd": systemd_result,
        "register": reg,
        "notion_sync": notion_sync,
        "next_steps": _next_steps(lifecycle, slug, assigned_port),
    }


def consolidate_duplicate_user_units() -> dict[str, Any]:
    """Quita units user ralf-* que duplican swarm-* de system (evita pelea de puertos)."""
    duplicates = [
        "ralf-funding-hub.service",
        "ralf-uipath-copilot.service",
        "ralf-sre-panel.service",
        "ralf-swarm-api.service",
        "ralf-public-gateway.service",
        "ralf-inneros-admin.service",
        "ralf-hackathon-band-api.service",
        "ralf-hackathon-band-ui.service",
    ]
    actions: list[dict[str, str]] = []
    for unit in duplicates:
        path = SYSTEMD_USER / unit
        for cmd in (
            ["systemctl", "--user", "stop", unit],
            ["systemctl", "--user", "disable", unit],
        ):
            subprocess.run(cmd, capture_output=True, text=True)
        if path.is_file():
            path.unlink(missing_ok=True)
            actions.append({"unit": unit, "action": "removed"})
        else:
            actions.append({"unit": unit, "action": "stopped"})
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    return {"ok": True, "consolidated": actions}


def adopt_legacy_stack(created_by: str = "CURSOR") -> dict[str, Any]:
    """Registra stack legacy — respeta systemd system swarm-* donde ya existe."""
    consolidate = consolidate_duplicate_user_units()
    catalog: list[dict[str, Any]] = [
        # Plataforma Ralphi — ya tienen ralfia-*.service
        {
            "slug": "ralphia-health",
            "name": "Ralphi IA Health + Editorial",
            "path": "/home/rlopez/projects/raphiia-openai",
            "port": 8101,
            "skip_systemd": True,
            "existing_systemd_unit": "ralfia-app.service",
            "health_endpoint": "http://127.0.0.1:8101/status",
        },
        {
            "slug": "ralphia-mcp",
            "name": "Conector RalfIA MCP",
            "path": "/home/rlopez/projects/raphiia-openai",
            "port": 8102,
            "skip_systemd": True,
            "existing_systemd_unit": "ralfia-mcp.service",
            "health_endpoint": "http://127.0.0.1:8102/mcp",
        },
        {
            "slug": "ralphia-oauth",
            "name": "Ralphi IA OAuth",
            "path": "/home/rlopez/projects/raphiia-openai",
            "port": 8103,
            "skip_systemd": True,
            "existing_systemd_unit": "ralfia-auth.service",
            "health_endpoint": "http://127.0.0.1:8103/health",
            "start_command": "venv/bin/python3 raphiia_openai/auth_server.py",
        },
        {
            "slug": "ralphia-portal",
            "name": "Ralphi IA Control Center",
            "path": "/home/rlopez/projects/raphiia-openai",
            "port": 2002,
            "skip_systemd": True,
            "existing_systemd_unit": "ralfia-portal.service",
            "health_endpoint": "http://127.0.0.1:2002/login",
        },
        {
            "slug": "ralphia-coordination",
            "name": "AG-25 Coordination Daemon",
            "path": "/home/rlopez/data/ai_coordination",
            "port": 0,
            "skip_systemd": True,
            "existing_systemd_unit": "ralfia-coordination-daemon.service",
        },
        {
            "slug": "ralphia-editorial-worker",
            "name": "Editorial Worker",
            "path": "/home/rlopez/projects/raphiia-openai",
            "port": 0,
            "skip_systemd": True,
            "existing_systemd_unit": "ralfia-editorial-worker.service",
        },
        # Ecosistema — systemd SYSTEM (swarm-*) ya gestiona la mayoría; no duplicar ralf-*
        {
            "slug": "funding-hub",
            "name": "Hackathon Funding Hub",
            "path": "/home/rlopez/projects/hackathon-funding-hub",
            "port": 8099,
            "skip_systemd": True,
            "existing_systemd_unit": "swarm-funding-hub.service",
            "systemd_scope": "system",
            "health_endpoint": "http://127.0.0.1:8099/api/opportunities",
        },
        {
            "slug": "uipath-copilot",
            "name": "UiPath Copilot",
            "path": "/home/rlopez/projects/uipath-copilot",
            "port": 8097,
            "skip_systemd": True,
            "existing_systemd_unit": "swarm-uipath-copilot.service",
            "systemd_scope": "system",
            "health_endpoint": "http://127.0.0.1:8097/",
        },
        {
            "slug": "chutes-deposit",
            "name": "Chutes Deposit Agent",
            "path": "/home/rlopez/projects/chutes-deposit-agent",
            "port": 8098,
            "start_command": "venv/bin/python3 main.py",
            "health_endpoint": "http://127.0.0.1:8098/",
        },
        {
            "slug": "sre-panel",
            "name": "SRE Project Panel",
            "path": "/home/rlopez/projects/ralphi-ia-server-sre",
            "port": 8096,
            "skip_systemd": True,
            "existing_systemd_unit": "swarm-sre.service",
            "systemd_scope": "system",
            "health_endpoint": "http://127.0.0.1:8096/",
        },
        {
            "slug": "hackathon-autopilot",
            "name": "Hackathon Autopilot Web",
            "path": "/home/rlopez/projects/hackathon-autopilot",
            "port": 8090,
            "start_command": "venv/bin/python3 main.py --serve",
            "health_endpoint": "http://127.0.0.1:8090/",
        },
        {
            "slug": "ai-gateway",
            "name": "AI Server Gateway",
            "path": "/home/rlopez/ai-server-v2",
            "port": 8091,
            "start_command": ".venv-gateway/bin/python -m uvicorn apps.gateway.app:app --host 0.0.0.0 --port {port}",
            "health_endpoint": "http://127.0.0.1:8091/",
        },
        {
            "slug": "swarm-api",
            "name": "Swarm-OS API",
            "path": "/home/rlopez/projects/innerspark-swarm-os-cursor-local",
            "port": 8100,
            "skip_systemd": True,
            "existing_systemd_unit": "swarm-api.service",
            "systemd_scope": "system",
            "health_endpoint": "http://127.0.0.1:8100/docs",
        },
        {
            "slug": "public-gateway",
            "name": "Public Gateway ngrok",
            "path": "/home/rlopez/projects/innerspark-swarm-os-cursor-local",
            "port": 5188,
            "skip_systemd": True,
            "existing_systemd_unit": "swarm-public-gateway.service",
            "systemd_scope": "system",
            "health_endpoint": "http://127.0.0.1:5188/",
        },
        {
            "slug": "inneros-admin",
            "name": "InnerOS Admin UI",
            "path": "/home/rlopez/projects/innerspark-swarm-os-cursor-local/admin",
            "port": 5173,
            "skip_systemd": True,
            "existing_systemd_unit": "swarm-admin.service",
            "systemd_scope": "system",
            "health_endpoint": "http://127.0.0.1:5173/",
        },
        {
            "slug": "hackathon-band-api",
            "name": "Hackathon Band API",
            "path": "/home/rlopez/projects/innerspark-swarm-os-cursor-local",
            "port": 8200,
            "skip_systemd": True,
            "existing_systemd_unit": "swarm-hackathon-api.service",
            "systemd_scope": "system",
            "health_endpoint": "http://127.0.0.1:8200/",
        },
        {
            "slug": "hackathon-band-ui",
            "name": "Hackathon Band UI",
            "path": "/home/rlopez/projects/innerspark-swarm-os-cursor-local/hackathon_band/ui",
            "port": 5190,
            "skip_systemd": True,
            "existing_systemd_unit": "swarm-hackathon-ui.service",
            "systemd_scope": "system",
            "health_endpoint": "http://127.0.0.1:5190/",
        },
        {
            "slug": "gitlab-transcend",
            "name": "GitLab Transcend",
            "path": "/home/rlopez/projects/gitlab-transcend",
            "port": 8095,
            "start_command": "venv/bin/uvicorn src.main:app --host 0.0.0.0 --port {port}",
            "health_endpoint": "http://127.0.0.1:8095/",
        },
    ]

    ensure_runtime_baseline()
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for item in catalog:
        try:
            out = create_project(
                name=item["name"],
                slug=item["slug"],
                port=int(item.get("port") or 0) or None,
                start_command=item.get("start_command", ""),
                health_endpoint=item.get("health_endpoint", ""),
                adopt_path=item["path"],
                fixed_port=bool(item.get("port")),
                skip_systemd=bool(item.get("skip_systemd")),
                existing_systemd_unit=item.get("existing_systemd_unit", ""),
                systemd_scope=item.get("systemd_scope", "user"),
                created_by=created_by,
            )
            results.append({"slug": item["slug"], "ok": out.get("ok"), "port": out.get("port")})
        except Exception as exc:
            errors.append({"slug": item["slug"], "error": str(exc)[:300]})

    verify = verify_projects()
    agent_auto_log.record_agent_run(
        created_by,
        action="adopt_legacy_stack",
        summary=f"Adoptados {len(results)} servicios, {len(errors)} errores",
        project="ralfia-ops",
        tool_used="adopt_legacy_stack",
        metadata={"adopted": len(results), "errors": len(errors)},
    )
    return {"ok": len(errors) == 0, "adopted": results, "errors": errors, "verify": verify, "consolidate": consolidate}


def _unit_active(unit: str, scope: str) -> str:
    cmd = ["systemctl", "is-active", unit] if scope == "system" else ["systemctl", "--user", "is-active", unit]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return (proc.stdout or proc.stderr or "").strip()


def _unit_enabled(unit: str, scope: str) -> str:
    cmd = ["systemctl", "is-enabled", unit] if scope == "system" else ["systemctl", "--user", "is-enabled", unit]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return (proc.stdout or proc.stderr or "").strip()


def activate_project(
    *,
    slug: str,
    start_command: str,
    port: int | None = None,
    health_endpoint: str = "",
) -> dict[str, Any]:
    """Convierte scaffold → always_alive (systemd + arranque)."""
    db = mongo_store.get_db()
    doc = db[COL_RALFIA_PROJECTS].find_one({"slug": slug}, {"_id": 0})
    if not doc:
        return {"ok": False, "error": f"proyecto no registrado: {slug}"}
    return create_project(
        name=doc.get("name", slug),
        slug=slug,
        project_type=doc.get("project_type", "web"),
        port=port or (doc.get("ports") or [None])[0],
        start_command=start_command,
        health_endpoint=health_endpoint or doc.get("health_endpoint", ""),
        created_by=doc.get("created_by", "CURSOR"),
        adopt_path=doc.get("path", ""),
    )


def verify_projects() -> dict[str, Any]:
    """Auditoría: proyectos always_alive deben tener systemd activo o enabled."""
    ensure_runtime_baseline()
    db = mongo_store.get_db()
    issues: list[dict[str, Any]] = []
    ok_count = 0
    for doc in db[COL_RALFIA_PROJECTS].find({"lifecycle": LIFECYCLE_ALWAYS_ALIVE}):
        slug = doc.get("slug", "")
        unit = doc.get("systemd_unit") or _systemd_unit_name(slug)
        if not unit:
            continue
        scope = doc.get("systemd_scope", "user")
        st_active = _unit_active(unit, scope)
        st_enabled = _unit_enabled(unit, scope)
        if st_active != "active" or st_enabled not in ("enabled", "static", "indirect"):
            issues.append(
                {
                    "slug": slug,
                    "unit": unit,
                    "is_active": st_active,
                    "is_enabled": st_enabled,
                    "port": (doc.get("ports") or [None])[0],
                }
            )
        else:
            ok_count += 1
    linger = subprocess.run(
        ["loginctl", "show-user", Path.home().name, "-p", "Linger"],
        capture_output=True,
        text=True,
    )
    return {
        "ok": len(issues) == 0,
        "always_alive_ok": ok_count,
        "issues": issues,
        "linger": (linger.stdout or "").strip(),
        "rule": "Todo proyecto HTTP = ralphia_project_create + systemd user + linger",
    }


def _next_steps(lifecycle: str, slug: str, port: int | None) -> list[str]:
    if lifecycle == LIFECYCLE_SCAFFOLD:
        return [
            f"Desarrollar app en ~/projects/{slug}",
            f"Activar 24/7: python3 scripts/ralphia_project_create.py --activate {slug} --start-cmd '...'",
        ]
    return [
        f"Panel: http://192.168.1.4:2002/ — servicio proj-{slug}",
        f"Estado: systemctl --user status ralf-{slug}",
        f"URL local: http://192.168.1.4:{port}/",
    ]
