"""Contrato doc_id + esquema Notion para Docs — RalfIA (Numerados)."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai.settings import COORD_ROOT

REPO_ROOT = Path(__file__).resolve().parents[1]

# Docs del repo raphiia-openai a incluir en sync Notion (Capa B ampliada)
REPO_SYNC_DOCS: tuple[str, ...] = (
    "docs/HANDOFF.md",
    "docs/CONEXION.md",
    "docs/MCP_CHATGPT.md",
    "docs/BACKUPS.md",
    "docs/INTEGRATION.md",
    "docs/ARRANQUE_RAPIDO.md",
    "docs/CURSOR_SSH.md",
    "docs/PROJECT_LIFECYCLE.md",
)

# Formato canónico: 02.01.004 (jerárquico, estable; título puede cambiar)
DOC_ID_PATTERN = re.compile(r"^\d{2}(\.\d{2}){0,2}(\.\d{3})?$")
DRAFT_ID_PREFIX = "DRAFT-"

STATUS_VALUES = ("Draft", "Active", "Deprecated")
DOMAIN_VALUES = (
    "Core",
    "Ops",
    "Accounting",
    "PC Doctor",
    "WhatsApp",
    "Infra",
    "Editorial",
    "Communications",
    "Other",
)
AUDIENCE_VALUES = ("internal", "team", "public")

PATH_DOMAIN_MAP: list[tuple[tuple[str, ...], str]] = [
    (("accounting",), "Accounting"),
    (("notion",), "Core"),
    (("cursor",), "Ops"),
    (("codex",), "Ops"),
    (("antigravity",), "Ops"),
    (("chatgpt",), "Ops"),
    (("gemini",), "Ops"),
    (("whatsapp",), "WhatsApp"),
    (("hub",), "Core"),
    (("log",), "Ops"),
]

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def normalize_doc_id(value: str) -> str:
    return (value or "").strip()


def is_canonical_doc_id(doc_id: str) -> bool:
    return bool(DOC_ID_PATTERN.match(normalize_doc_id(doc_id)))


def parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_RE.match(content or "")
    if not match:
        return {}, content or ""
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        meta[key.strip().lower()] = val.strip().strip('"').strip("'")
    body = content[match.end() :]
    return meta, body


def infer_domain(relative_path: str, meta: dict[str, str] | None = None) -> str:
    if meta and meta.get("domain"):
        dom = meta["domain"]
        if dom in DOMAIN_VALUES:
            return dom
    parts = relative_path.strip("/").lower().split("/")
    for prefixes, domain in PATH_DOMAIN_MAP:
        if parts[: len(prefixes)] == list(prefixes):
            return domain
    return "Other"


def infer_status(meta: dict[str, str], *, has_canonical_id: bool) -> str:
    raw = (meta.get("status") or meta.get("estado") or "").strip()
    if raw in STATUS_VALUES:
        return raw
    return "Active" if has_canonical_id else "Draft"


def draft_doc_id_from_path(relative_path: str) -> str:
    rel = relative_path.strip().lstrip("/")
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]
    return f"{DRAFT_ID_PREFIX}{digest}"


def extract_title(relative_path: str, content: str, meta: dict[str, str]) -> str:
    if meta.get("title"):
        return meta["title"][:200]
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()[:200]
    base = Path(relative_path).stem
    return base[:200] or relative_path[:200]


def build_doc_record(
    relative_path: str,
    content: str,
    *,
    source_mtime: float | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    rel = relative_path.strip().lstrip("/")
    meta, body = parse_frontmatter(content)
    doc_id = normalize_doc_id(meta.get("doc_id") or "")
    has_canonical = is_canonical_doc_id(doc_id)
    if not doc_id:
        doc_id = draft_doc_id_from_path(rel)
        has_canonical = False
    title = extract_title(rel, body, meta)
    sync_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    mtime_iso = None
    if source_mtime is not None:
        mtime_iso = datetime.fromtimestamp(source_mtime, tz=timezone.utc).isoformat()
    sp = source_path or f"ai_coordination/{rel}"
    return {
        "doc_id": doc_id,
        "title": title,
        "content_md": body,
        "source_path": sp,
        "status": infer_status(meta, has_canonical_id=has_canonical),
        "domain": infer_domain(rel, meta),
        "audience": meta.get("audience") if meta.get("audience") in AUDIENCE_VALUES else "internal",
        "sync_hash": sync_hash,
        "source_last_modified": mtime_iso,
        "canonical_id": has_canonical,
        "relative_path": rel,
        "tags": [t.strip() for t in (meta.get("tags") or "").split(",") if t.strip()],
    }


def load_coordination_doc(relative_path: str, max_chars: int = 50000) -> dict[str, Any]:
    rel = relative_path.strip().lstrip("/")
    if rel.startswith("repo/"):
        path = REPO_ROOT / rel[5:]
        source_path = str(path)
        rel_key = rel
    else:
        path = COORD_ROOT / rel
        source_path = f"ai_coordination/{rel}"
        rel_key = rel
    if not path.is_file():
        return {"ok": False, "error": "file_not_found", "relative_path": rel}
    raw = path.read_text(encoding="utf-8", errors="replace")
    if len(raw) > max_chars:
        raw = raw[:max_chars]
    record = build_doc_record(rel_key, raw, source_mtime=path.stat().st_mtime, source_path=source_path)
    return {"ok": True, **record}


def list_sync_candidates(limit: int = 200) -> list[str]:
    """Paths elegibles para sync Notion (numerados, frontmatter doc_id, o lista canónica)."""
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(rel: str) -> None:
        if rel not in seen:
            seen.add(rel)
            candidates.append(rel)

    if COORD_ROOT.is_dir():
        for path in sorted(COORD_ROOT.rglob("*.md")):
            try:
                rel = path.relative_to(COORD_ROOT).as_posix()
            except ValueError:
                continue
            if rel.startswith("."):
                continue
            head = path.read_text(encoding="utf-8", errors="replace")[:800]
            meta, _ = parse_frontmatter(head)
            if meta.get("doc_id") or meta.get("notion_sync") == "true":
                _add(rel)
                continue
            if rel in {
                "MAPA_CENTRAL.md",
                "TASKS.md",
                "SESSION_LOG.md",
                "PROJECTS_REGISTRY.md",
                "MONGO_SCHEMA.md",
                "PORTS_CANONICAL.md",
            }:
                _add(rel)
            if len(candidates) >= limit:
                break

    for repo_rel in REPO_SYNC_DOCS:
        path = REPO_ROOT / repo_rel
        if path.is_file():
            _add(f"repo/{repo_rel}")
        if len(candidates) >= limit:
            break

    return candidates[:limit]


NOTION_DOCS_DB_SCHEMA: dict[str, Any] = {
    "title": "Docs — RalfIA (Numerados)",
    "description": "Índice canónico de documentación numerada. Contenido en página hija (Patrón 1).",
    "properties": {
        "doc_id": {"type": "rich_text", "rich_text": {}},
        "Estado": {
            "type": "select",
            "select": {
                "options": [
                    {"name": "Draft", "color": "yellow"},
                    {"name": "Active", "color": "green"},
                    {"name": "Deprecated", "color": "gray"},
                ]
            },
        },
        "Dominio": {
            "type": "select",
            "select": {
                "options": [{"name": name, "color": "default"} for name in DOMAIN_VALUES],
            },
        },
        "source_path": {"type": "rich_text", "rich_text": {}},
        "last_sync_at": {"type": "date", "date": {}},
        "source_last_modified": {"type": "date", "date": {}},
        "sync_hash": {"type": "rich_text", "rich_text": {}},
        "audience": {
            "type": "select",
            "select": {
                "options": [
                    {"name": "internal", "color": "blue"},
                    {"name": "team", "color": "purple"},
                    {"name": "public", "color": "green"},
                ]
            },
        },
    },
    "title_property": "Título",
}

NOTION_SAFE_READ_TOOLS = [
    "system_health",
    "health_check",
    "mcp_version",
    "list_mcp_capabilities",
    "list_mcp_tool_profiles",
    "get_project_map",
    "read_coordination_doc",
    "read_coordination_file",
    "search_coordination_docs",
    "get_notion_status",
    "get_notion_sync_log",
    "search_notion_pages",
]

NOTION_SAFE_WRITE_TOOLS = [
    "notion_upsert_doc_metadata",
    "notion_push_doc",
    "notion_append_audit_event",
    "sync_documentation_now",
    "log_coordination_event",
    "run_service_watchdog",
]
