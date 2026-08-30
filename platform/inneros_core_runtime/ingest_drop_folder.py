"""Canonical local drop-folder ingestion for InnerOS documents."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import document_vault, hybrid_context, mongo_store

ROOT = Path(os.getenv("INNEROS_INGEST_ROOT", "/home/rlopez/data/inneros_ingest")).expanduser()
AUDIT_COL = "inneros_ingest_drop_audit"
ALLOWED_EXTENSIONS = document_vault.ALLOWED_EXTENSIONS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dirs() -> dict[str, Path]:
    return {"root": ROOT, "staging": ROOT / "staging", "promote": ROOT / "promote", "processed": ROOT / "processed", "failed": ROOT / "failed", "audit": ROOT / "audit"}


def ensure_dirs() -> dict[str, Any]:
    created = []
    for key, path in _dirs().items():
        if key == "root":
            continue
        if not path.exists():
            created.append(str(path))
        path.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "root": str(ROOT), "created": created, "dirs": {k: str(v) for k, v in _dirs().items()}}


def _sidecar(path: Path) -> dict[str, Any]:
    side = path.with_suffix(path.suffix + ".json")
    if not side.is_file():
        return {}
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        return {"sidecar_error": str(exc)[:200]}


def _iter_files(limit: int) -> list[Path]:
    ensure_dirs()
    files: list[Path] = []
    for base in (_dirs()["promote"], _dirs()["staging"]):
        for path in sorted(base.iterdir()):
            if len(files) >= limit:
                return files
            if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS and not path.name.endswith(".json"):
                files.append(path)
    return files


def _audit(event: dict[str, Any]) -> None:
    clean = {**event, "ts": _now()}
    try:
        mongo_store.get_db()[AUDIT_COL].insert_one(clean)
    except Exception:
        pass
    try:
        audit_path = _dirs()["audit"] / f"{clean['ts'].replace(':', '').replace('+', 'Z')}.json"
        audit_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def status(limit: int = 20) -> dict[str, Any]:
    dirs = ensure_dirs()
    files = _iter_files(max(1, min(int(limit or 20), 100)))
    qdrant = hybrid_context.qdrant_health()
    return {"ok": True, "root": str(ROOT), "dirs": dirs["dirs"], "pending_count": len(files), "pending": [{"path": str(p), "bytes": p.stat().st_size, "sidecar": _sidecar(p)} for p in files], "qdrant": qdrant, "pipeline": "drop_folder -> Document Vault canonical/versioned -> audit; Qdrant/Memory integration is reported through hybrid_context health and downstream indexers."}


def run(*, dry_run: bool = True, limit: int = 20, default_entity_type: str = "inneros", default_entity_ref: str = "global", default_category: str = "ingest_drop", created_by: str = "inneros_ingest_drop") -> dict[str, Any]:
    ensure_dirs()
    files = _iter_files(max(1, min(int(limit or 20), 100)))
    results: list[dict[str, Any]] = []
    for path in files:
        meta = _sidecar(path)
        entity_type = str(meta.get("entity_type") or default_entity_type).strip() or default_entity_type
        entity_ref = str(meta.get("entity_ref") or meta.get("entity") or default_entity_ref).strip() or default_entity_ref
        category = str(meta.get("category") or default_category).strip() or default_category
        title = str(meta.get("title") or path.stem).strip() or path.stem
        tags = meta.get("tags") or ["inneros_ingest_drop"]
        make_canonical = bool(meta.get("make_canonical") or path.parent.name == "promote")
        record = {"path": str(path), "entity_type": entity_type, "entity_ref": entity_ref, "category": category, "title": title, "make_canonical": make_canonical, "dry_run": dry_run}
        if dry_run:
            results.append({"ok": True, "planned": True, **record})
            continue
        try:
            ingest = document_vault.document_vault_ingest(local_path=str(path), entity_type=entity_type, entity_ref=entity_ref, category=category, title=title, status=meta.get("status"), tags=tags, make_canonical=make_canonical, document_type=meta.get("document_type"), created_by=created_by)
            target_dir = _dirs()["processed"] if ingest.get("ok") else _dirs()["failed"]
            target = target_dir / path.name
            shutil.move(str(path), str(target))
            side = path.with_suffix(path.suffix + ".json")
            if side.exists():
                shutil.move(str(side), str(target.with_suffix(target.suffix + ".json")))
            event = {**record, "ok": bool(ingest.get("ok")), "target": str(target), "document": ingest.get("document"), "error": ingest.get("error")}
            _audit(event)
            results.append(event)
        except Exception as exc:
            target = _dirs()["failed"] / path.name
            try:
                shutil.move(str(path), str(target))
            except Exception:
                pass
            event = {**record, "ok": False, "target": str(target), "error": str(exc)[:300]}
            _audit(event)
            results.append(event)
    return {"ok": all(row.get("ok") for row in results) if results else True, "dry_run": dry_run, "root": str(ROOT), "processed": len(results), "results": results}
