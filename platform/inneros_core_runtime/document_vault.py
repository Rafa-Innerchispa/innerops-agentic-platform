"""Canonical document vault for agent-accessible binary documents."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

COLLECTION = "ralfia_document_vault"
DEFAULT_ROOT = Path("/mnt/datos_agentes/document_vault")
ROOT = Path(os.getenv("DOCUMENT_VAULT_ROOT", str(DEFAULT_ROOT))).expanduser()
MAX_BYTES = int(os.getenv("DOCUMENT_VAULT_MAX_BYTES", str(200 * 1024 * 1024)))

ALLOWED_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".txt",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
}
ALLOWED_STATUS = {"draft", "versioned", "canonical", "historical", "superseded"}
NODE_HOSTS = {
    "intel": os.getenv("DOCUMENT_VAULT_INTEL_HOST", "192.168.1.4"),
    "amd": os.getenv("DOCUMENT_VAULT_AMD_HOST", "192.168.1.5"),
}
SSH_BASE = ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
SCP_BASE = ["scp", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _collection():
    return mongo_store.get_db()[COLLECTION]


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


def _slug(value: Any, *, fallback: str = "item", max_len: int = 80) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    return (text or fallback)[:max_len].strip("-._") or fallback


def _clean_status(status: str | None, make_canonical: bool) -> str:
    clean = _slug(status or "")
    if make_canonical:
        return "canonical"
    if clean in ALLOWED_STATUS:
        return clean
    return "versioned"


def _clean_tags(tags: Any) -> list[str]:
    if not tags:
        return []
    if isinstance(tags, str):
        tags = [part.strip() for part in tags.split(",")]
    if not isinstance(tags, list):
        return []
    return sorted({_slug(tag, fallback="tag", max_len=48) for tag in tags if str(tag or "").strip()})


def _source_path(file_ref: Any = None, local_path: str | None = None) -> Path:
    raw = local_path
    if raw is None and isinstance(file_ref, str):
        raw = file_ref
    if raw is None and isinstance(file_ref, dict):
        raw = file_ref.get("local_path") or file_ref.get("path") or file_ref.get("file_path")
    if not raw:
        raise ValueError("file_ref_or_local_path_required")
    path = Path(str(raw)).expanduser().resolve()
    if not path.is_file():
        raise ValueError("source_file_not_found")
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("extension_not_allowed")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("empty_file_not_allowed")
    if size > MAX_BYTES:
        raise ValueError("file_too_large")
    return path


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _entity_id(entity_ref: str) -> str:
    return _slug(entity_ref, fallback="entity", max_len=96)


def _document_type(path: Path, document_type: str | None = None) -> str:
    explicit = _slug(document_type or "", fallback="")
    if explicit:
        return explicit
    ext = path.suffix.lower().lstrip(".")
    if ext in {"ppt", "pptx"}:
        return "presentation"
    if ext in {"doc", "docx", "md", "txt"}:
        return "document"
    if ext in {"xls", "xlsx", "csv"}:
        return "spreadsheet"
    if ext in {"png", "jpg", "jpeg", "gif", "webp"}:
        return "image"
    if ext == "pdf":
        return "pdf"
    return ext or "binary"


def _logical_key(entity_type: str, entity_id: str, category: str, document_type: str, title: str) -> str:
    return ":".join(
        [
            _slug(entity_type, fallback="entity_type"),
            _slug(entity_id, fallback="entity"),
            _slug(category, fallback="general"),
            _slug(document_type, fallback="document"),
            _slug(title, fallback="untitled"),
        ]
    )


def _next_version(logical_key: str) -> int:
    latest = _collection().find_one({"logical_key": logical_key}, sort=[("version", -1)])
    return int((latest or {}).get("version") or 0) + 1


def _paths(entity_type: str, entity_id: str, document_id: str, filename: str) -> tuple[Path, Path]:
    scope = ROOT / _slug(entity_type, fallback="entity") / _slug(entity_id, fallback="entity") / document_id[:2] / document_id
    return scope, scope / filename


def _file_ref(doc: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("local_primary_path", "local_replica_path"):
        raw = doc.get(key)
        if raw and Path(raw).is_file():
            return {
                "path": raw,
                "filename": doc.get("canonical_filename") or Path(raw).name,
                "mime_type": doc.get("mime_type") or "application/octet-stream",
                "size_bytes": doc.get("size_bytes"),
                "sha256": doc.get("sha256"),
                "document_id": doc.get("document_id"),
            }
    return None


def _public_doc(doc: dict[str, Any], *, return_file_ref: bool = False) -> dict[str, Any]:
    out = _serialize(doc) or {}
    if return_file_ref:
        out["file_ref"] = _file_ref(out)
    return out


def document_vault_ingest(
    *,
    file_ref: Any = None,
    local_path: str | None = None,
    entity_type: str,
    entity_ref: str,
    category: str,
    title: str,
    version_label: str | None = None,
    status: str | None = None,
    tags: Any = None,
    make_canonical: bool = False,
    drive_replica: dict[str, Any] | None = None,
    document_type: str | None = None,
    created_by: str = "agent",
) -> dict[str, Any]:
    try:
        src = _source_path(file_ref=file_ref, local_path=local_path)
        entity_id = _entity_id(entity_ref)
        doc_type = _document_type(src, document_type)
        logical_key = _logical_key(entity_type, entity_id, category, doc_type, title)
        sha = _sha256_file(src)
        existing = _collection().find_one({"logical_key": logical_key, "sha256": sha})
        if existing:
            return {"ok": True, "created": False, "reused": True, "document": _public_doc(existing, return_file_ref=True)}

        now = _now()
        version = _next_version(logical_key)
        document_id = f"doc_{uuid.uuid4().hex[:24]}"
        ext = src.suffix.lower()
        filename = f"{_slug(title, fallback='document')}_v{version}{ext}"
        folder, target = _paths(entity_type, entity_id, document_id, filename)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

        mime_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        clean_status = _clean_status(status, make_canonical)
        doc = {
            "document_id": document_id,
            "logical_key": logical_key,
            "entity_type": _slug(entity_type, fallback="entity"),
            "entity_id": entity_id,
            "entity_ref": str(entity_ref),
            "category": _slug(category, fallback="general"),
            "document_type": doc_type,
            "title": str(title).strip() or "Document",
            "canonical_filename": filename,
            "version": version,
            "version_label": str(version_label or f"v{version}"),
            "status": clean_status,
            "is_canonical": clean_status == "canonical",
            "sha256": sha,
            "size_bytes": target.stat().st_size,
            "mime_type": mime_type,
            "created_at": now,
            "updated_at": now,
            "created_by": _slug(created_by, fallback="agent"),
            "local_primary_path": str(target),
            "local_replica_path": "",
            "replication_status": "pending",
            "drive_file_id": (drive_replica or {}).get("file_id") or "",
            "drive_url": (drive_replica or {}).get("url") or "",
            "external_replicas": [drive_replica] if drive_replica else [],
            "source_channel": (file_ref or {}).get("source_channel") if isinstance(file_ref, dict) else "",
            "source_ref": (file_ref or {}).get("source_ref") if isinstance(file_ref, dict) else "",
            "tags": _clean_tags(tags),
            "supersedes": "",
            "superseded_by": "",
            "revision": 1,
        }
        if doc["is_canonical"]:
            previous = _collection().find_one({"logical_key": logical_key, "is_canonical": True})
            if previous:
                doc["supersedes"] = previous.get("document_id", "")
        _collection().insert_one(doc)
        if doc["is_canonical"] and doc["supersedes"]:
            _collection().update_one(
                {"document_id": doc["supersedes"]},
                {
                    "$set": {
                        "is_canonical": False,
                        "status": "superseded",
                        "superseded_by": document_id,
                        "updated_at": now,
                    },
                    "$inc": {"revision": 1},
                },
            )
        return {"ok": True, "created": True, "document_id": document_id, "document": _public_doc(doc, return_file_ref=True)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def document_vault_register_external(
    *,
    entity_ref: str,
    external_provider: str,
    file_id: str = "",
    url: str = "",
    metadata: dict[str, Any] | None = None,
    document_id: str = "",
    title: str = "",
    entity_type: str = "client",
    category: str = "external",
) -> dict[str, Any]:
    provider = _slug(external_provider, fallback="external")
    now = _now()
    replica = {"provider": provider, "file_id": file_id, "url": url, "metadata": metadata or {}, "updated_at": now}
    if document_id:
        result = _collection().update_one(
            {"document_id": document_id},
            {
                "$set": {"updated_at": now, f"{provider}_file_id": file_id, f"{provider}_url": url},
                "$push": {"external_replicas": replica},
                "$inc": {"revision": 1},
            },
        )
        return {"ok": result.matched_count == 1, "updated": result.modified_count, "document_id": document_id}
    logical_key = _logical_key(entity_type, _entity_id(entity_ref), category, provider, title or file_id or url)
    doc = {
        "document_id": f"doc_ext_{uuid.uuid4().hex[:20]}",
        "logical_key": logical_key,
        "entity_type": _slug(entity_type, fallback="entity"),
        "entity_id": _entity_id(entity_ref),
        "entity_ref": entity_ref,
        "category": _slug(category, fallback="external"),
        "document_type": provider,
        "title": title or file_id or url or "External document",
        "canonical_filename": "",
        "version": _next_version(logical_key),
        "status": "versioned",
        "is_canonical": False,
        "sha256": "",
        "size_bytes": 0,
        "mime_type": "",
        "created_at": now,
        "updated_at": now,
        "created_by": "agent",
        "local_primary_path": "",
        "local_replica_path": "",
        "replication_status": "external_only",
        "drive_file_id": file_id if provider == "drive" else "",
        "drive_url": url if provider == "drive" else "",
        "external_replicas": [replica],
        "tags": [],
        "supersedes": "",
        "superseded_by": "",
        "revision": 1,
    }
    _collection().insert_one(doc)
    return {"ok": True, "created": True, "document_id": doc["document_id"], "document": _public_doc(doc)}


def document_vault_list(entity_ref: str, filters: dict[str, Any] | None = None, limit: int = 50) -> dict[str, Any]:
    filters = filters or {}
    query: dict[str, Any] = {"entity_id": _entity_id(entity_ref)}
    for key in ("entity_type", "category", "document_type", "status", "is_canonical"):
        if key in filters and filters[key] not in ("", None):
            query[key] = filters[key] if key == "is_canonical" else _slug(filters[key], fallback="")
    cursor = _collection().find(query).sort([("is_canonical", -1), ("updated_at", -1)]).limit(max(1, min(int(limit or 50), 200)))
    docs = [_public_doc(doc) for doc in cursor]
    return {"ok": True, "count": len(docs), "documents": docs}


def document_vault_search(
    query: str,
    entity_ref: str = "",
    document_type: str = "",
    status: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    q = str(query or "").strip()
    if not q:
        return {"ok": False, "error": "query_required"}
    mongo_query: dict[str, Any] = {
        "$or": [
            {"title": {"$regex": re.escape(q), "$options": "i"}},
            {"logical_key": {"$regex": re.escape(q), "$options": "i"}},
            {"entity_ref": {"$regex": re.escape(q), "$options": "i"}},
            {"tags": {"$regex": re.escape(_slug(q, fallback=q)), "$options": "i"}},
        ]
    }
    if entity_ref:
        mongo_query["entity_id"] = _entity_id(entity_ref)
    if document_type:
        mongo_query["document_type"] = _slug(document_type, fallback="")
    if status:
        mongo_query["status"] = _slug(status, fallback="")
    cursor = _collection().find(mongo_query).sort([("is_canonical", -1), ("version", -1), ("updated_at", -1)]).limit(max(1, min(int(limit or 10), 50)))
    docs = [_public_doc(doc, return_file_ref=True) for doc in cursor]
    return {"ok": True, "query": q, "count": len(docs), "results": docs}


def _find_document(document_id: str = "", natural_query: str = "") -> dict[str, Any] | None:
    if document_id:
        doc = _collection().find_one({"document_id": document_id})
        if doc:
            return doc
    if natural_query:
        found = document_vault_search(natural_query, limit=1)
        if found.get("results"):
            return _collection().find_one({"document_id": found["results"][0]["document_id"]})
    return None


def document_vault_get(document_id: str = "", natural_query: str = "", return_file_ref: bool = True) -> dict[str, Any]:
    doc = _find_document(document_id, natural_query)
    if not doc:
        return {"ok": False, "error": "document_not_found"}
    return {"ok": True, "document": _public_doc(doc, return_file_ref=return_file_ref)}


def document_vault_set_canonical(document_id: str, actor: str, expected_revision: int | None = None) -> dict[str, Any]:
    doc = _collection().find_one({"document_id": document_id})
    if not doc:
        return {"ok": False, "error": "document_not_found"}
    if expected_revision is not None and int(doc.get("revision") or 0) != int(expected_revision):
        return {"ok": False, "error": "revision_conflict", "current_revision": doc.get("revision")}
    now = _now()
    previous = _collection().find_one({"logical_key": doc["logical_key"], "is_canonical": True, "document_id": {"$ne": document_id}})
    if previous:
        _collection().update_one(
            {"document_id": previous["document_id"]},
            {"$set": {"is_canonical": False, "status": "superseded", "superseded_by": document_id, "updated_at": now}, "$inc": {"revision": 1}},
        )
    _collection().update_one(
        {"document_id": document_id},
        {
            "$set": {
                "is_canonical": True,
                "status": "canonical",
                "supersedes": (previous or {}).get("document_id", doc.get("supersedes", "")),
                "updated_at": now,
                "canonical_set_by": _slug(actor, fallback="agent"),
            },
            "$inc": {"revision": 1},
        },
    )
    updated = _collection().find_one({"document_id": document_id})
    return {"ok": True, "document": _public_doc(updated), "superseded": (previous or {}).get("document_id")}


def document_vault_versions(document_id: str = "", logical_key: str = "") -> dict[str, Any]:
    doc = _collection().find_one({"document_id": document_id}) if document_id else None
    key = logical_key or (doc or {}).get("logical_key")
    if not key:
        return {"ok": False, "error": "logical_key_required"}
    docs = [_public_doc(item) for item in _collection().find({"logical_key": key}).sort("version", 1)]
    return {"ok": True, "logical_key": key, "count": len(docs), "versions": docs}


def _node_name() -> str:
    host = socket.gethostname().lower()
    if "amd" in host or host.endswith("5"):
        return "amd"
    if "intel" in host or host.endswith("4"):
        return "intel"
    return host


def _remote_target(target_node: str) -> str:
    return NODE_HOSTS.get(_slug(target_node), target_node)


def _local_ipv4s() -> set[str]:
    ips = {"127.0.0.1", "localhost"}
    try:
        output = subprocess.run(["hostname", "-I"], timeout=3, text=True, capture_output=True)
        ips.update(part.strip() for part in output.stdout.split() if part.strip())
    except Exception:
        pass
    return ips


def document_vault_replicate(document_id: str, target_node: str = "") -> dict[str, Any]:
    doc = _collection().find_one({"document_id": document_id})
    if not doc:
        return {"ok": False, "error": "document_not_found"}
    source = Path(doc.get("local_primary_path") or "")
    if not source.is_file():
        return {"ok": False, "error": "primary_file_missing"}
    target_node = _slug(target_node or ("intel" if _node_name() == "amd" else "amd"))
    host = _remote_target(target_node)
    remote_path = Path(doc["local_primary_path"])
    remote_dir = str(remote_path.parent)
    try:
        subprocess.run([*SSH_BASE, f"rlopez@{host}", "mkdir", "-p", remote_dir], check=True, timeout=30)
        subprocess.run([*SCP_BASE, str(source), f"rlopez@{host}:{remote_path}"], check=True, timeout=120)
        verify = subprocess.run([*SSH_BASE, f"rlopez@{host}", "sha256sum", str(remote_path)], check=True, timeout=30, text=True, capture_output=True)
        remote_sha = verify.stdout.split()[0] if verify.stdout.split() else ""
        ok = remote_sha == doc.get("sha256")
        _collection().update_one(
            {"document_id": document_id},
            {
                "$set": {
                    "local_replica_path": str(remote_path),
                    "replica_node": target_node,
                    "replication_status": "verified" if ok else "checksum_mismatch",
                    "updated_at": _now(),
                },
                "$inc": {"revision": 1},
            },
        )
        return {"ok": ok, "document_id": document_id, "target_node": target_node, "remote_path": str(remote_path), "sha256": remote_sha}
    except Exception as exc:
        _collection().update_one({"document_id": document_id}, {"$set": {"replication_status": "failed", "replication_error": str(exc), "updated_at": _now()}})
        return {"ok": False, "error": str(exc), "document_id": document_id, "target_node": target_node}


def document_vault_export_file(document_id: str) -> dict[str, Any]:
    doc = _collection().find_one({"document_id": document_id})
    if not doc:
        return {"ok": False, "error": "document_not_found"}
    ref = _file_ref(doc)
    if not ref:
        return {"ok": False, "error": "file_not_available", "document": _public_doc(doc)}
    return {"ok": True, "document_id": document_id, "file_ref": ref}


def document_vault_health() -> dict[str, Any]:
    root_exists = ROOT.exists()
    root_writable = root_exists and os.access(ROOT, os.W_OK)
    mongo_ok = False
    count = 0
    try:
        count = _collection().count_documents({})
        mongo_ok = True
    except Exception:
        pass
    peer_status = {}
    local_ips = _local_ipv4s()
    for name, host in NODE_HOSTS.items():
        if host in local_ips:
            peer_status[name] = root_exists
            continue
        try:
            result = subprocess.run(
                [*SSH_BASE, f"rlopez@{host}", "test", "-d", str(ROOT)],
                timeout=5,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            peer_status[name] = result.returncode == 0
        except Exception:
            peer_status[name] = False
    return {
        "ok": bool(root_exists and root_writable and mongo_ok),
        "node": _node_name(),
        "root": str(ROOT),
        "root_exists": root_exists,
        "root_writable": root_writable,
        "mongo_ok": mongo_ok,
        "document_count": count,
        "peer_root_exists": peer_status,
        "max_bytes": MAX_BYTES,
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
    }


document_vault_status = document_vault_health
