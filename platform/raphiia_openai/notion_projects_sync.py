"""Sincronización Creator OS (DB08 Proyectos) ↔ servidor RalfIA — sin duplicar."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from raphiia_openai import mongo_store
from raphiia_openai.notion_bridge import _headers, _ok_or_error, NOTION_API_BASE
from raphiia_openai.settings import COORD_ROOT, NOTION_DB08_PROYECTOS_ID, NOTION_VERSION

INDEX_COL = "ralfia_notion_projects_index"
SYNC_STATE_COL = "ralfia_notion_projects_sync_state"
DEFAULT_DB08 = "d3710c1b-e655-43e9-ae7d-09f96e9f491b"

# Fragmentos de título Notion → slug servidor (PROJECTS_REGISTRY / Mongo)
TITLE_ALIASES: dict[str, str] = {
    "innersparkideaengine": "innerspark-smart-quoter",
    "ideaplan": "innerspark-smart-quoter",
    "smartquoter": "innerspark-smart-quoter",
    "fundinghub": "hackathon-funding-hub",
    "hackathonfunding": "hackathon-funding-hub",
    "swarmos": "innerspark-swarm-os-cursor-local",
    "innersparkswarm": "innerspark-swarm-os-cursor-local",
    "ralfiamcp": "raphiia-openai",
    "raphiiaopenai": "raphiia-openai",
    "ralfiia": "raphiia-openai",
    "uipathcopilot": "uipath-copilot",
    "chutesdeposit": "chutes-deposit-agent",
    "gitlabtranscend": "gitlab-transcend",
    "srepanel": "ralphi-ia-server-sre",
    "hybridopscopilot": "amd-ralfiia-hybrid-ops-copilot",
    "cozmohackathon": "hackathon_band",
    "innerosadmin": "inneros-admin",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db08_id() -> str:
    return (NOTION_DB08_PROYECTOS_ID or DEFAULT_DB08).strip() or DEFAULT_DB08


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _prop_text(value: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": str(value)[:1800]}}]}


def _prop_select(name: str) -> dict[str, Any]:
    return {"select": {"name": name}}


def _prop_date(iso: str) -> dict[str, Any]:
    return {"date": {"start": iso[:10]}}


def _extract_prop(prop: dict[str, Any]) -> Any:
    if not isinstance(prop, dict):
        return None
    t = prop.get("type")
    if t == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title") or [])
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text") or [])
    if t == "select":
        return (prop.get("select") or {}).get("name")
    if t == "status":
        return (prop.get("status") or {}).get("name")
    if t == "url":
        return prop.get("url")
    if t == "date":
        return (prop.get("date") or {}).get("start")
    return None


def parse_projects_registry() -> list[dict[str, Any]]:
    """Lee PROJECTS_REGISTRY.md → filas con ruta servidor."""
    path = COORD_ROOT / "PROJECTS_REGISTRY.md"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("|") or line.startswith("|--") or "Proyecto |" in line:
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 4:
            continue
        name, server_path = parts[0], parts[1].strip("` ")
        name = re.sub(r"\*+", "", name).strip()
        if not name or name.startswith("~~") or server_path.startswith("…"):
            continue
        slug = Path(server_path).name if server_path.startswith("/") else _norm(name)
        rows.append({
            "name": name.strip("* "),
            "slug": slug,
            "server_path": server_path,
            "ports": parts[2] if len(parts) > 2 else "",
            "built_with": parts[3] if len(parts) > 3 else "",
            "status": parts[5] if len(parts) > 5 else "",
            "notes": parts[6] if len(parts) > 6 else "",
        })
    return rows


def _registry_index(registry: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in registry:
        for key in (row.get("slug"), row.get("name"), Path(row.get("server_path", "")).name):
            if key:
                out[_norm(str(key))] = row
    return out


def _match_registry(title: str, reg_idx: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    t = _norm(title)
    if t in reg_idx:
        return reg_idx[t]
    for key, row in reg_idx.items():
        if key and len(key) >= 4 and (key in t or t in key):
            return row
    for frag, slug in TITLE_ALIASES.items():
        if frag in t:
            return reg_idx.get(slug) or reg_idx.get(_norm(slug))
    return None


def _match_mongo(title: str, mongo_projs: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    t = _norm(title)
    for slug, row in mongo_projs.items():
        ns = _norm(slug)
        nn = _norm(str(row.get("name") or ""))
        if ns and len(ns) >= 4 and (ns in t or t in ns or ns in nn or nn in t):
            return row
    for frag, slug in TITLE_ALIASES.items():
        if frag in t and slug in mongo_projs:
            return mongo_projs[slug]
    return None


def _fetch_all_db08() -> list[dict[str, Any]]:
    dbid = _db08_id()
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    with httpx.Client(timeout=60) as client:
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            resp = client.post(
                f"{NOTION_API_BASE}/databases/{dbid}/query",
                headers=_headers(),
                json=body,
            )
            parsed = _ok_or_error(resp)
            if not parsed.get("ok"):
                break
            batch = parsed.get("results") or []
            items.extend(batch)
            if not parsed.get("has_more"):
                break
            cursor = parsed.get("next_cursor")
            if not cursor:
                break
    return items


def _mongo_projects() -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    return list(db["ralfia_projects"].find({}, {"_id": 0}).limit(500))


def _sync_hash(record: dict[str, Any]) -> str:
    raw = "|".join(
        str(record.get(k) or "")
        for k in ("notion_page_id", "title", "server_path", "estado", "codigo_proyecto")
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _build_records() -> list[dict[str, Any]]:
    registry = parse_projects_registry()
    reg_idx = _registry_index(registry)
    mongo_projs = {p.get("slug"): p for p in _mongo_projects() if p.get("slug")}
    records: list[dict[str, Any]] = []
    for page in _fetch_all_db08():
        props = page.get("properties") or {}
        title = ""
        for v in props.values():
            if v.get("type") == "title":
                title = _extract_prop(v) or ""
                break
        reg = _match_registry(title, reg_idx)
        mongo_p = _match_mongo(title, mongo_projs) or mongo_projs.get((reg or {}).get("slug") or "")
        server_path = (reg or {}).get("server_path") or mongo_p.get("path") or ""
        slug = (reg or {}).get("slug") or mongo_p.get("slug") or (Path(server_path).name if server_path else _norm(title))
        codigo = _extract_prop(props.get("Código proyecto", {}))
        estado = _extract_prop(props.get("Estado", {}))
        rec = {
            "notion_page_id": page.get("id"),
            "notion_url": page.get("url"),
            "title": title,
            "slug": slug,
            "codigo_proyecto": codigo,
            "estado": estado,
            "server_path": server_path or mongo_p.get("path") or "",
            "ports": (reg or {}).get("ports") or mongo_p.get("ports") or [],
            "built_with": (reg or {}).get("built_with") or mongo_p.get("created_by") or "",
            "team_space": "Creator OS",
            "database": "DB08 — Proyectos",
            "matched_registry": bool(reg),
            "matched_mongo": bool(mongo_p),
            "sync_status": "OK" if server_path else "Pending",
            "sync_notes": (
                f"RalfIA · server: {server_path or '—'} · "
                f"ports: {(reg or {}).get('ports') or '—'} · "
                f"slug: {slug}"
            )[:1800],
            "updated_at": _now(),
        }
        rec["sync_hash"] = _sync_hash(rec)
        records.append(rec)
    return records


def _build_server_only_records(
    notion_records: list[dict[str, Any]],
    registry: list[dict[str, Any]],
    mongo_projs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Proyectos en servidor sin fila DB08 (mapa mental completo)."""
    linked_slugs = {r.get("slug") for r in notion_records if r.get("slug")}
    linked_paths = {r.get("server_path") for r in notion_records if r.get("server_path")}
    extra: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(*, slug: str, name: str, server_path: str, ports: Any, built_with: str, source: str) -> None:
        if not server_path or server_path in linked_paths or slug in linked_slugs or slug in seen:
            return
        seen.add(slug)
        rec = {
            "notion_page_id": None,
            "notion_url": None,
            "title": name,
            "slug": slug,
            "codigo_proyecto": None,
            "estado": "Activo",
            "server_path": server_path,
            "ports": ports,
            "built_with": built_with,
            "team_space": "Creator OS",
            "database": "server-only",
            "matched_registry": source == "registry",
            "matched_mongo": source == "mongo",
            "sync_status": "Pending",
            "sync_notes": f"RalfIA · server: {server_path} · sin fila DB08 aún · slug: {slug}",
            "updated_at": _now(),
        }
        rec["sync_hash"] = _sync_hash(rec)
        extra.append(rec)

    for row in registry:
        _append(
            slug=row.get("slug") or "",
            name=row.get("name") or "",
            server_path=row.get("server_path") or "",
            ports=row.get("ports"),
            built_with=row.get("built_with") or "",
            source="registry",
        )
    for mp in mongo_projs:
        _append(
            slug=mp.get("slug") or "",
            name=mp.get("name") or mp.get("slug") or "",
            server_path=mp.get("path") or "",
            ports=mp.get("ports"),
            built_with=mp.get("created_by") or "",
            source="mongo",
        )
    return extra


def _upsert_index(records: list[dict[str, Any]]) -> None:
    db = mongo_store.get_db()
    for rec in records:
        pid = rec.get("notion_page_id")
        if not pid:
            continue
        db[INDEX_COL].update_one({"notion_page_id": pid}, {"$set": rec}, upsert=True)


def _patch_notion_page(page_id: str, rec: dict[str, Any]) -> dict[str, Any]:
    props = {
        "Sync Status": _prop_select(rec.get("sync_status") or "Pending"),
        "Last Synced At": _prop_date(_now()),
        "Sync Notes": _prop_text(rec.get("sync_notes") or ""),
    }
    with httpx.Client(timeout=30) as client:
        resp = client.patch(
            f"{NOTION_API_BASE}/pages/{page_id}",
            headers=_headers(),
            json={"properties": props},
        )
    return _ok_or_error(resp)


def sync_creator_os_projects(*, dry_run: bool = True, limit: int | None = None) -> dict[str, Any]:
    """Harmoniza DB08 Proyectos con PROJECTS_REGISTRY + Mongo ralfia_projects."""
    registry = parse_projects_registry()
    mongo_list = _mongo_projects()
    mongo_projs = {p.get("slug"): p for p in mongo_list if p.get("slug")}
    records = _build_records()
    server_only = _build_server_only_records(records, registry, mongo_list)
    all_records = records + server_only
    if limit is not None:
        all_records = all_records[: max(1, limit)]

    ok = sum(1 for r in all_records if r.get("sync_status") == "OK")
    pending = len(all_records) - ok
    summary = {
        "ok": True,
        "dry_run": dry_run,
        "database": "DB08 — Proyectos",
        "database_id": _db08_id(),
        "total": len(all_records),
        "notion_pages": len(records),
        "server_only": len(server_only),
        "with_server_path": ok,
        "pending_server_path": pending,
        "sample": [
            {
                "title": r.get("title"),
                "server_path": r.get("server_path"),
                "sync_status": r.get("sync_status"),
                "notion_url": r.get("notion_url"),
                "database": r.get("database"),
            }
            for r in all_records[:12]
        ],
    }

    if dry_run:
        return summary

    patched = 0
    errors: list[dict[str, Any]] = []
    for rec in all_records:
        key = {"notion_page_id": rec["notion_page_id"]} if rec.get("notion_page_id") else {"slug": rec.get("slug"), "database": "server-only"}
        mongo_store.get_db()[INDEX_COL].update_one(key, {"$set": rec}, upsert=True)
        if rec.get("notion_page_id"):
            out = _patch_notion_page(rec["notion_page_id"], rec)
            if out.get("ok"):
                patched += 1
            else:
                errors.append({"title": rec.get("title"), "error": out.get("error")})

    mongo_store.get_db()[SYNC_STATE_COL].update_one(
        {"kind": "creator_os"},
        {"$set": {"kind": "creator_os", "last_sync_at": _now(), "total": len(all_records), "patched": patched}},
        upsert=True,
    )
    mongo_store.log_sync("creator_os_projects_sync", total=len(all_records), patched=patched)
    return {**summary, "dry_run": False, "patched": patched, "errors": errors[:5]}


def notify_new_project(
    *,
    name: str,
    slug: str,
    server_path: str,
    ports: list[int] | None = None,
    created_by: str = "CURSOR",
) -> dict[str, Any]:
    """Tras create_project: busca fila DB08 por nombre y actualiza sync."""
    records = _build_records()
    match = None
    ns = _norm(slug)
    nt = _norm(name)
    for rec in records:
        rs = _norm(rec.get("slug") or "")
        rt = _norm(rec.get("title") or "")
        if ns in (rs, rt) or nt in (rt, rs) or ns in rt or nt in rt:
            match = rec
            break
    if not match:
        return {
            "ok": True,
            "matched": False,
            "message": "Proyecto no encontrado en DB08 — créalo en Creator OS y re-sync",
            "slug": slug,
            "server_path": server_path,
        }
    match = {
        **match,
        "server_path": server_path,
        "ports": ports or match.get("ports"),
        "built_with": created_by,
        "sync_status": "OK",
        "sync_notes": f"RalfIA · server: {server_path} · ports: {ports or '—'} · slug: {slug}",
        "updated_at": _now(),
    }
    _upsert_index([match])
    out = _patch_notion_page(match["notion_page_id"], match)
    return {"ok": out.get("ok", False), "matched": True, "notion_url": match.get("notion_url"), "details": out}


def get_creator_os_project_map(limit: int = 50) -> dict[str, Any]:
    db = mongo_store.get_db()
    items = list(db[INDEX_COL].find({}, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(limit, 200))))
    if len(items) < 5:
        sync_creator_os_projects(dry_run=False)
        items = list(db[INDEX_COL].find({}, {"_id": 0}).sort("updated_at", -1).limit(max(1, min(limit, 200))))
    with_path = [i for i in items if i.get("server_path")]
    return {
        "ok": True,
        "count": len(items),
        "with_server_path": len(with_path),
        "projects": items,
        "registry_path": str(COORD_ROOT / "PROJECTS_REGISTRY.md"),
    }
