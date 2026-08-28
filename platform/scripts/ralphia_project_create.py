#!/usr/bin/env python3
"""ÚNICO camino para crear/adoptar proyectos Ralphi IA con arranque 24/7 automático."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import project_lifecycle  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(
        description="Crear o activar proyecto Ralphi IA (Mongo + systemd user + linger)."
    )
    p.add_argument("--name", help="Nombre legible del proyecto")
    p.add_argument("--slug", help="Slug (default: derivado de --name)")
    p.add_argument("--type", default="web", dest="project_type", help="Tipo: web|api|worker")
    p.add_argument("--port", type=int, help="Puerto preferido (8120–8999)")
    p.add_argument(
        "--start-cmd",
        help="Comando de arranque (use {port}). Si se omite → solo scaffold sin systemd.",
    )
    p.add_argument("--hackathon", default="", help="Nombre hackathon (opcional)")
    p.add_argument("--hackathon-url", default="", help="URL Devpost (opcional)")
    p.add_argument("--health", default="", help="Health endpoint HTTP")
    p.add_argument("--path", default="", help="Ruta existente (adoptar carpeta)")
    p.add_argument("--created-by", default="CURSOR")
    p.add_argument("--activate", metavar="SLUG", help="Activar scaffold existente → always_alive")
    p.add_argument("--adopt-all", action="store_true", help="Adoptar stack legacy completo (Mongo + systemd)")
    p.add_argument("--verify", action="store_true", help="Auditar proyectos always_alive vs systemd")
    p.add_argument("--ensure-baseline", action="store_true", help="Solo linger + daemon-reload")
    args = p.parse_args()

    if args.ensure_baseline:
        print(json.dumps(project_lifecycle.ensure_runtime_baseline(), indent=2))
        return 0

    if args.adopt_all:
        out = project_lifecycle.adopt_legacy_stack(created_by=args.created_by)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0 if out.get("ok") else 1

    if args.verify:
        out = project_lifecycle.verify_projects()
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0 if out.get("ok") else 1

    if args.activate:
        if not args.start_cmd:
            print("ERROR: --activate requiere --start-cmd", file=sys.stderr)
            return 1
        out = project_lifecycle.activate_project(
            slug=args.activate,
            start_command=args.start_cmd,
            port=args.port,
            health_endpoint=args.health,
        )
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0 if out.get("ok") else 1

    if not args.name:
        p.error("--name es obligatorio (o use --verify / --ensure-baseline)")

    out = project_lifecycle.create_project(
        name=args.name,
        slug=args.slug,
        project_type=args.project_type,
        port=args.port,
        start_command=args.start_cmd or "",
        hackathon_name=args.hackathon,
        hackathon_url=args.hackathon_url,
        health_endpoint=args.health,
        created_by=args.created_by,
        adopt_path=args.path,
    )
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
