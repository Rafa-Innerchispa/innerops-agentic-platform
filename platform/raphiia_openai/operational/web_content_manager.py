"""Módulo de gestión y automatización de contenido web InnerChispa (ops_35381b50abb6)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store
import os

COL_WEB_CONTENT = "innerchispa_web_content"
# Editorial opt-in: NO dependencia ops. Vacío = sync portfolio deshabilitado.
CANONICAL_HACKATHON_PORTFOLIO = os.getenv(
    "INNEROS_WEB_PORTFOLIO_JSON",
    "",
).strip() or None
INNEROS_WEB_ASTRO_DATA_DIR = os.getenv("INNEROS_WEB_ASTRO_DATA_DIR", "").strip() or None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    raw = (value or "innerchispa-content").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    return raw or "innerchispa-content"


def _safe_public_status(project: dict[str, Any], default_status: str) -> str:
    if project.get("project_status") in {"published", "submitted"}:
        return "published"
    if project.get("project_status") in {"registered", "upcoming"}:
        return "upcoming"
    return default_status


def create_web_content(
    *,
    content_id: str,
    content_type: str,  # "project" o "hackathon"
    title: str,
    slug: str,
    description: str,
    technologies: list[str] | None = None,
    images: list[dict[str, Any]] | None = None,
    demo_url: str | None = None,
    github_url: str | None = None,
    visibility: str = "public",
    theme: str = "default",
    status: str = "draft",
) -> dict[str, Any]:
    """Crea un contenido para la web InnerChispa con un estado específico."""
    db = mongo_store.get_db()
    existing = db[COL_WEB_CONTENT].find_one({"$or": [{"content_id": content_id}, {"slug": slug}]})
    if existing:
        return {"ok": False, "error": f"Content ID o Slug ya existe: {content_id} / {slug}"}

    doc = {
        "content_id": content_id,
        "type": content_type,
        "title": title,
        "slug": slug,
        "description": description,
        "technologies": technologies or [],
        "images": images or [],
        "demo_url": demo_url or "",
        "github_url": github_url or "",
        "visibility": visibility,
        "theme": theme,
        "status": status,  # draft -> review -> approved -> published -> upcoming
        "created_at": _now(),
        "updated_at": _now(),
        "approved_by": None,
        "published_at": _now() if status in ("published", "upcoming") else None,
    }
    db[COL_WEB_CONTENT].insert_one(doc)
    doc.pop("_id", None)
    
    # Trigger auto-rebuild if published directly
    if status in ("published", "upcoming"):
        trigger_auto_rebuild_in_background()
        
    return {"ok": True, "content": doc}


def update_web_content(content_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Actualiza un borrador o contenido existente."""
    db = mongo_store.get_db()
    existing = db[COL_WEB_CONTENT].find_one({"content_id": content_id})
    if not existing:
        return {"ok": False, "error": f"Content ID no encontrado: {content_id}"}

    forbidden_fields = {"content_id", "type", "created_at"}
    filtered_patch = {k: v for k, v in patch.items() if k not in forbidden_fields}
    filtered_patch["updated_at"] = _now()

    db[COL_WEB_CONTENT].update_one({"content_id": content_id}, {"$set": filtered_patch})
    updated = db[COL_WEB_CONTENT].find_one({"content_id": content_id}, {"_id": 0})
    
    # Trigger auto-rebuild if the content is published or upcoming
    if updated.get("status") in ("published", "upcoming"):
        trigger_auto_rebuild_in_background()
        
    return {"ok": True, "content": updated}


def change_web_content_status(
    content_id: str,
    new_status: str,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Controla la máquina de estados: draft -> review -> approved -> published."""
    valid_statuses = {"draft", "review", "approved", "published", "upcoming"}
    if new_status not in valid_statuses:
        return {"ok": False, "error": f"Estado inválido: {new_status}"}

    db = mongo_store.get_db()
    existing = db[COL_WEB_CONTENT].find_one({"content_id": content_id})
    if not existing:
        return {"ok": False, "error": f"Content ID no encontrado: {content_id}"}

    patch: dict[str, Any] = {"status": new_status, "updated_at": _now()}
    if new_status == "approved":
        if not approved_by:
            return {"ok": False, "error": "Aprobación requiere especificar 'approved_by'"}
        patch["approved_by"] = approved_by
    elif new_status in {"published", "upcoming"}:
        if not existing.get("approved_by") and not patch.get("approved_by") and not approved_by:
            return {"ok": False, "error": "No se puede publicar contenido no aprobado previamente."}
        patch["published_at"] = _now()
        if approved_by:
            patch["approved_by"] = approved_by

    db[COL_WEB_CONTENT].update_one({"content_id": content_id}, {"$set": patch})
    updated = db[COL_WEB_CONTENT].find_one({"content_id": content_id}, {"_id": 0})
    
    # Trigger real-time auto-rebuild and sync on both nodes
    if new_status in ("published", "upcoming"):
        trigger_auto_rebuild_in_background()
        
    return {"ok": True, "content": updated}


def upsert_web_content(
    *,
    content_id: str,
    content_type: str,
    title: str,
    slug: str,
    description: str,
    technologies: list[str] | None = None,
    images: list[dict[str, Any]] | None = None,
    demo_url: str | None = None,
    github_url: str | None = None,
    event_url: str | None = None,
    submission_url: str | None = None,
    video_url: str | None = None,
    visibility: str = "internal",
    theme: str = "living-lab",
    status: str = "review",
    approved_by: str | None = None,
    source: str = "canonical_sync",
) -> dict[str, Any]:
    """Crea o actualiza contenido web sin duplicar por content_id."""
    db = mongo_store.get_db()
    now = _now()
    patch = {
        "content_id": content_id,
        "type": content_type,
        "title": title,
        "slug": slug,
        "description": description,
        "technologies": technologies or [],
        "images": images or [],
        "demo_url": demo_url or "",
        "github_url": github_url or "",
        "event_url": event_url or "",
        "submission_url": submission_url or "",
        "video_url": video_url or "",
        "visibility": visibility,
        "theme": theme,
        "source": source,
        "updated_at": now,
    }
    existing = db[COL_WEB_CONTENT].find_one({"content_id": content_id}, {"_id": 0})
    if existing:
        # Do not demote already-approved/published content unless explicitly draft/review.
        if existing.get("status") not in {"published", "upcoming", "approved"}:
            patch["status"] = status
        db[COL_WEB_CONTENT].update_one({"content_id": content_id}, {"$set": patch})
        item = db[COL_WEB_CONTENT].find_one({"content_id": content_id}, {"_id": 0})
        return {"ok": True, "created": False, "content": item}

    patch.update(
        {
            "status": status,
            "created_at": now,
            "approved_by": approved_by,
            "published_at": now if status in {"published", "upcoming"} else None,
        }
    )
    db[COL_WEB_CONTENT].insert_one(patch)
    patch.pop("_id", None)
    return {"ok": True, "created": True, "content": patch}


def sync_hackathon_portfolio(
    source_path: str | None = CANONICAL_HACKATHON_PORTFOLIO,
    *,
    default_status: str = "review",
    publish_safe_items: bool = True,
) -> dict[str, Any]:
    """Importa inventario hackathons/proyectos hacia cola Web/Astro (opt-in vía env)."""
    if not source_path:
        return {
            "ok": False,
            "error": "INNEROS_WEB_PORTFOLIO_JSON no configurado — sync editorial deshabilitado",
            "skipped": True,
        }
    src = Path(source_path)
    if not src.is_file():
        return {"ok": False, "error": f"canonical portfolio not found: {src}"}

    data = json.loads(src.read_text(encoding="utf-8"))
    projects = data.get("projects") or []
    results = []
    created = updated = skipped = 0
    for project in projects:
        if project.get("safe_to_display_publicly") is False:
            skipped += 1
            continue
        content_id = f"canonical_{project.get('id') or _slugify(project.get('canonical_project_name', 'project'))}"
        title = project.get("canonical_project_name") or project.get("event_name") or "InnerChispa project"
        description = project.get("solution_statement") or project.get("problem_statement") or ""
        content_type = "hackathon" if project.get("event_url") or project.get("submission_url") else "project"
        status = _safe_public_status(project, default_status) if publish_safe_items else default_status
        approved_by = "canonical_sync" if status in {"published", "upcoming"} else None
        result = upsert_web_content(
            content_id=content_id,
            content_type=content_type,
            title=title,
            slug=_slugify(project.get("event_name") or title),
            description=description,
            technologies=project.get("technologies") or [],
            demo_url=project.get("live_demo_url") or "",
            github_url=project.get("repository_url") or "",
            event_url=project.get("event_url") or "",
            submission_url=project.get("submission_url") or "",
            video_url=project.get("video_url") or "",
            visibility="public",
            theme="living-lab",
            status=status,
            approved_by=approved_by,
            source="canonical_hackathons_portfolio",
        )
        if result.get("created"):
            created += 1
        else:
            updated += 1
        results.append({"content_id": content_id, "status": result.get("content", {}).get("status"), "created": result.get("created")})

    if created or updated:
        trigger_auto_rebuild_in_background()

    return {
        "ok": True,
        "source_path": str(src),
        "total": len(projects),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "items": results,
    }


def list_web_content(
    content_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Lista el contenido web InnerChispa con filtros opcionales."""
    db = mongo_store.get_db()
    query: dict[str, Any] = {}
    if content_type:
        query["type"] = content_type
    if status:
        query["status"] = status

    items = list(db[COL_WEB_CONTENT].find(query, {"_id": 0}).sort("created_at", -1).limit(limit))
    return {"ok": True, "count": len(items), "items": items}


def get_web_content(content_id: str) -> dict[str, Any]:
    """Recupera un contenido web por su ID."""
    db = mongo_store.get_db()
    item = db[COL_WEB_CONTENT].find_one({"content_id": content_id}, {"_id": 0})
    if not item:
        return {"ok": False, "error": f"Content ID no encontrado: {content_id}"}
    return {"ok": True, "item": item}


def export_web_content_for_astro(output_dir: str) -> dict[str, Any]:
    """Exporta todo el contenido con status='published' en formato JSON/Markdown para Astro."""
    db = mongo_store.get_db()
    published_items = list(db[COL_WEB_CONTENT].find({"status": {"$in": ["published", "upcoming"]}}, {"_id": 0}))

    out_path = Path(output_dir)
    try:
        out_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "error": f"No se pudo crear el directorio de exportación: {e}"}

    # Guardar índice general JSON
    index_file = out_path / "published_content.json"
    index_file.write_text(json.dumps(published_items, indent=2, ensure_ascii=False), encoding="utf-8")

    # Exportar fichas individuales (Markdown con Frontmatter) para el sitemap de Astro
    exported = []
    for item in published_items:
        content_type = item.get("type", "projects")
        type_dir = out_path / f"{content_type}s"
        type_dir.mkdir(parents=True, exist_ok=True)

        frontmatter = {
            "title": item.get("title"),
            "slug": item.get("slug"),
            "technologies": item.get("technologies"),
            "images": item.get("images"),
            "demo_url": item.get("demo_url"),
            "github_url": item.get("github_url"),
            "event_url": item.get("event_url", ""),
            "submission_url": item.get("submission_url", ""),
            "video_url": item.get("video_url", ""),
            "visibility": item.get("visibility"),
            "theme": item.get("theme"),
            "published_at": item.get("published_at"),
            "approved_by": item.get("approved_by"),
        }

        # Formato Markdown con frontmatter YAML básico
        import yaml
        fm_yaml = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False)
        md_content = f"---\n{fm_yaml}---\n\n{item.get('description', '')}\n"

        file_name = type_dir / f"{item.get('slug')}.md"
        file_name.write_text(md_content, encoding="utf-8")
        exported.append(str(file_name))

    return {
        "ok": True,
        "exported_count": len(published_items),
        "index_file": str(index_file),
        "files": exported,
    }


def trigger_auto_rebuild_in_background() -> None:
    """Dispara la exportación y el rebuild de Astro en segundo plano para ambos servidores."""
    import threading
    import subprocess
    import sys

    def worker():
        try:
            astro_data_dir = INNEROS_WEB_ASTRO_DATA_DIR
            astro_web_root = os.getenv("INNEROS_WEB_ASTRO_ROOT", "").strip() or None
            if not astro_data_dir or not astro_web_root:
                return  # rebuild web deshabilitado — no dependencia hackathon en ops
            export_web_content_for_astro(astro_data_dir)

            local_cmd = 'bash -c "source ~/.nvm/nvm.sh && nvm use --delete-prefix v20.20.2 && npm run build"'
            subprocess.run(local_cmd, shell=True, cwd=astro_web_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            scp_dest = os.getenv("INNEROS_WEB_ASTRO_SCP_DEST", "").strip()
            if scp_dest:
                scp_cmd = f"scp {astro_data_dir}/published_content.json {scp_dest}"
                subprocess.run(scp_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            remote_cmd = os.getenv("INNEROS_WEB_ASTRO_REMOTE_BUILD_CMD", "").strip()
            if remote_cmd:
                subprocess.run(remote_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            print("Auto-rebuild and sync completed successfully on both servers.")
        except Exception as e:
            print(f"Error in auto-rebuild: {e}", file=sys.stderr)

    threading.Thread(target=worker, daemon=True).start()


def export_video_asset(video_path: str, *, title: str = "", caption: str = "") -> dict[str, Any]:
    """Registra vídeo en media library web y copia a staging estático."""
    import shutil

    src = Path(video_path)
    if not src.is_file():
        return {"ok": False, "error": f"video not found: {src}"}
    dest_dir = Path("/home/rlopez/data/media/web/videos")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    db = mongo_store.get_db()
    doc = {
        "kind": "video",
        "title": title or src.stem,
        "caption": caption,
        "path": str(dest),
        "source_path": str(src),
        "created_at": _now(),
    }
    db["innerchispa_media_assets"].insert_one(doc)
    public_url = None
    public_urls: list[str] = []
    try:
        from raphiia_openai import artifact_delivery

        info = artifact_delivery.artifact_info(dest, title=doc["title"])
        public_url = info.get("public_url")
        public_urls = list(info.get("public_urls") or [])
    except Exception:
        pass
    return {
        "ok": True,
        "path": str(dest),
        "title": doc["title"],
        "public_url": public_url,
        "public_urls": public_urls,
        "url": public_url,
    }
