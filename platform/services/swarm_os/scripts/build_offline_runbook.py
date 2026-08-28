#!/usr/bin/env python3
"""Genera un runbook único para Knowledge de Open WebUI (modo sin internet)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

COORD = Path("/home/rlopez/data/ai_coordination")
OUT_DIR = Path("/mnt/datos_agentes/ai-server-v2/open-webui/offline-knowledge")
OUT_FILE = OUT_DIR / "RALFIA_OFFLINE_RUNBOOK.md"

SECTIONS = [
    ("00_LEER_PRIMERO.md", "Entrada obligatoria"),
    ("PORTS_CANONICAL.md", "Puertos canónicos"),
    ("ESTADO_ACTUAL.md", "Estado del servidor"),
    ("PROJECTS_REGISTRY.md", "Registro de proyectos"),
    ("TASKS.md", "Tareas activas"),
    ("MEMORIA_PERSISTENTE.md", "Memoria persistente (3 capas)"),
    ("AUTOMACION_COORDINACION.md", "Automatización local"),
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parts = [
        "# RalfIA — Runbook offline (Open WebUI Knowledge)",
        "",
        f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "Usar cuando **no hay internet**. MCP LAN (:8102) y Mongo local siguen activos.",
        "",
        "---",
        "",
    ]
    for rel, title in SECTIONS:
        path = COORD / rel
        parts.append(f"## {title}")
        parts.append(f"*Fuente: `{rel}`*")
        parts.append("")
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8").strip())
        else:
            parts.append(f"_Archivo no encontrado: {path}_")
        parts.append("")
        parts.append("---")
        parts.append("")
    OUT_FILE.write_text("\n".join(parts), encoding="utf-8")
    print(f"OK {OUT_FILE} ({OUT_FILE.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
