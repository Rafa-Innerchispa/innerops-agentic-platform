"""Memory Curator — extracción local Drive/Notion → memoria canónica Mongo (AG-34 + AG-02)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AGENT_ID = "AG-MEMORY-CURATOR"
CHECKPOINT_COL = "ralfia_memory_curator_checkpoint"
DEFAULT_STATE = Path("/home/rlopez/data/memory_curator/state.json")
DEFAULT_LOG = Path("/home/rlopez/data/memory_curator/curator.log")
DEFAULT_ROOTS = [
    "/home/rlopez/data/google_drive",
    "/home/rlopez/data/google_takeout/extracted",
    "/home/rlopez/data/notion_export",
]
MAX_DOC_CHARS = int(os.getenv("MEMORY_CURATOR_MAX_DOC_CHARS", "12000"))
MAX_FACTS = int(os.getenv("MEMORY_CURATOR_MAX_FACTS", "8"))
MODEL = os.getenv("MEMORY_CURATOR_MODEL", "qwen2.5:7b")
OLLAMA_URL = os.getenv("OLLAMA_URL", os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
if OLLAMA_URL and not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = f"http://{OLLAMA_URL}"
WORKER_ID = int(os.getenv("MEMORY_CURATOR_WORKER_ID", "0"))
NUM_WORKERS = max(1, int(os.getenv("MEMORY_CURATOR_NUM_WORKERS", "1")))
WORKER_LABEL = os.getenv("MEMORY_CURATOR_WORKER_LABEL", f"w{WORKER_ID}")
NODE_NAME = os.getenv("MEMORY_CURATOR_NODE", os.getenv("HOSTNAME", "local"))
OPS_TASK_ID = os.getenv("MEMORY_CURATOR_OPS_TASK", "ops_30226c8b57ef")
STRICT_MODE = os.getenv("MEMORY_CURATOR_STRICT", "1").strip().lower() in {"1", "true", "yes"}
TENANT_ID = os.getenv("MEMORY_CURATOR_TENANT", "RAFAEL")
PRIORITY_ROOTS = [
    p.strip()
    for p in os.getenv(
        "MEMORY_CURATOR_PRIORITY_ROOTS",
        "/home/rlopez/data/google_drive/PC-Doctor- Historico/Clientes|"
        "/home/rlopez/data/notion_export|"
        "/home/rlopez/data/google_drive",
    ).split("|")
    if p.strip()
]
VALID_KINDS = frozenset(
    {"fact", "decision", "intention", "hypothesis", "opinion", "summary", "context_rule"}
)
VALID_SCOPES = frozenset(
    {
        "PRIVATE_PERSONAL",
        "PRIVATE_FINANCIAL",
        "INTERNAL_WORK",
        "PROJECT",
        "PUBLIC",
    }
)

_EXTRACT_SYSTEM = """Eres Memory Curator del ecosistema RalfIA/InnerOS.
Extrae hechos atómicos verificables del documento fuente.

Reglas estrictas:
- Solo información explícita en el texto; no inventes ni infieras datos no presentes.
- Clasifica kind: fact, decision, intention, hypothesis, opinion, summary (nunca conviertas planes futuros en hechos).
- privacy_scope: INTERNAL_WORK (default operativo), PROJECT (proyecto específico), PRIVATE_PERSONAL, PRIVATE_FINANCIAL, PUBLIC.
- Máximo {max_facts} items. Cada body ≤ 400 caracteres, claro y autocontenido.
- Incluye entities relevantes (empresas, personas, productos) cuando aparezcan.

Responde SOLO un JSON array válido, sin markdown:
[{{"kind":"fact","title":"...","body":"...","entities":[],"privacy_scope":"INTERNAL_WORK","project":null}}]
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def worker_paths(worker_id: int | None = None) -> tuple[Path, Path]:
    wid = WORKER_ID if worker_id is None else worker_id
    base = Path("/home/rlopez/data/memory_curator")
    if NUM_WORKERS <= 1 and wid == 0:
        return DEFAULT_STATE, DEFAULT_LOG
    return base / f"state.{wid}.json", base / f"curator.{wid}.log"


def _shard_key(path: str) -> int:
    digest = hashlib.md5(path.encode("utf-8")).hexdigest()
    return int(digest, 16) % NUM_WORKERS


def _belongs_to_worker(path: str, worker_id: int | None = None) -> bool:
    wid = WORKER_ID if worker_id is None else worker_id
    return _shard_key(path) == wid


def _setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"memory_curator.{WORKER_LABEL}")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


def _file_id(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def load_state(path: Path = DEFAULT_STATE) -> dict[str, Any]:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "version": 1,
        "started_at": _now_iso(),
        "last_heartbeat": None,
        "current_file": None,
        "stats": {
            "processed": 0,
            "created": 0,
            "updated": 0,
            "duplicates": 0,
            "skipped": 0,
            "errors": 0,
            "conflicts": 0,
        },
        "files": {},
    }


def save_state(state: dict[str, Any], path: Path = DEFAULT_STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["last_heartbeat"] = _now_iso()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _import_file_io():
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import gdrive_export_ingest as gdi  # noqa: WPS433

    return gdi


def list_files(roots: list[str] | None = None, *, worker_id: int | None = None) -> list[Path]:
    gdi = _import_file_io()
    root_paths = [Path(r) for r in (roots or DEFAULT_ROOTS)]
    if STRICT_MODE and not roots:
        # Prioridad: PC Doctor Clientes → Notion → resto Drive
        ordered: list[Path] = []
        seen: set[str] = set()
        for pr in PRIORITY_ROOTS:
            rp = Path(pr)
            if rp.is_dir():
                for p in gdi.iter_files([rp]):
                    s = str(p)
                    if s not in seen:
                        seen.add(s)
                        ordered.append(p)
        for p in gdi.iter_files(root_paths):
            s = str(p)
            if s not in seen:
                seen.add(s)
                ordered.append(p)
        files = ordered
    else:
        files = gdi.iter_files(root_paths)

    wid = WORKER_ID if worker_id is None else worker_id
    if NUM_WORKERS <= 1:
        return files
    return [p for p in files if _belongs_to_worker(str(p), wid)]


def _checkpoint_db():
    from raphiia_openai import mongo_store

    return mongo_store.get_db()[CHECKPOINT_COL]


def _globally_done(rel: str, mtime: float, content_hash: str) -> bool:
    try:
        doc = _checkpoint_db().find_one({"source_path": rel})
    except Exception:
        return False
    if not doc:
        return False
    if doc.get("mtime") != mtime:
        return False
    if doc.get("hash") != content_hash:
        return False
    return doc.get("status") in {"done", "skipped"}


def _checkpoint_mark(rel: str, entry: dict[str, Any]) -> None:
    try:
        _checkpoint_db().update_one(
            {"source_path": rel},
            {
                "$set": {
                    **entry,
                    "source_path": rel,
                    "worker": WORKER_LABEL,
                    "node": NODE_NAME,
                    "updated_at": _now_iso(),
                }
            },
            upsert=True,
        )
    except Exception:
        pass


def read_document(path: Path) -> str:
    gdi = _import_file_io()
    return gdi.read_file(path)


def _parse_facts(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return []
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        body = str(item.get("body") or "").strip()
        if len(body) < 8:
            continue
        kind = str(item.get("kind") or "fact").strip().lower()
        if kind not in VALID_KINDS:
            kind = "fact"
        scope = str(item.get("privacy_scope") or "INTERNAL_WORK").strip().upper()
        if scope not in VALID_SCOPES:
            scope = "INTERNAL_WORK"
        out.append(
            {
                "kind": kind,
                "title": str(item.get("title") or body[:80]).strip()[:200],
                "body": body[:600],
                "entities": [str(e) for e in (item.get("entities") or []) if e][:12],
                "privacy_scope": scope,
                "project": item.get("project") or None,
            }
        )
    return out[:MAX_FACTS]


def _parse_strict_records(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)][:MAX_FACTS]


_STRICT_EXTRACT_SYSTEM = """Eres Memory Curator enterprise (VKR). Extrae REGISTROS TABULARES verificables.

CONTEXTO DE RUTA (jerarquía Drive):
- Si la ruta contiene PC-Doctor/Clientes/NOMBRE_CLIENTE/ → subject_role=client, subject_name=NOMBRE_CLIENTE
- Cotizaciones/facturas/informes → record_type quote/invoice/process según corresponda
- NO confundas dirección del cliente con dirección de PC Doctor salvo que el documento lo diga explícito
- Proyecciones/planes → epistemic_class=projection (NO fact)

record_type permitidos: person, organization, address, contact, financial_account, identifier, contract, decision, process, asset, quote, invoice, social_profile, other

attribute ejemplos:
- address: billing_address, service_site, registered_address, mailing_address
- contact: email, phone, website
- identifier: tax_id, ruc, cedula, domain
- social_profile: linkedin

Cada registro JSON:
{{"record_type":"...","attribute":"...","subject_role":"client|company|vendor|owner|unknown","subject_name":"...","value_normalized":"...","value_raw":"...","epistemic_class":"fact|decision|projection","confidence":0.0-1.0}}

Reglas:
- Solo datos EXPLÍCITOS en el texto
- confidence < 0.55 → no incluir
- Máximo {max_facts} registros
- Si el documento no tiene datos estructurados útiles, responde: []

Responde SOLO JSON array, sin markdown."""


def extract_strict_records(text: str, *, title: str, source_path: str, hierarchy: Any) -> list[dict[str, Any]]:
    from raphiia_openai.local_model_router import _http_json

    h = hierarchy.to_dict() if hasattr(hierarchy, "to_dict") else hierarchy
    snippet = text[:MAX_DOC_CHARS]
    prompt = (
        f"Archivo: {title}\nRuta: {source_path}\n"
        f"Jerarquía inferida: brand={h.get('brand')} client={h.get('client_name')} "
        f"year={h.get('year')} doc_class={h.get('doc_class')}\n\n"
        f"---\n{snippet}\n---"
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _STRICT_EXTRACT_SYSTEM.replace("{max_facts}", str(MAX_FACTS))},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.05, "num_predict": 2000},
    }
    llm = _http_json(f"{OLLAMA_URL.rstrip('/')}/api/chat", method="POST", body=payload, timeout=240)
    if not llm.get("ok"):
        raise RuntimeError(llm.get("error") or "ollama_chat_failed")
    content = (llm.get("data") or {}).get("message", {}).get("content", "")
    return _parse_strict_records(content)


# --- Legacy v0 (solo si MEMORY_CURATOR_STRICT=0) ---
VALID_KINDS = frozenset({"fact", "decision", "intention", "hypothesis", "opinion", "summary", "context_rule"})
VALID_SCOPES = frozenset({"PRIVATE_PERSONAL", "PRIVATE_FINANCIAL", "INTERNAL_WORK", "PROJECT", "PUBLIC"})
_EXTRACT_SYSTEM = """Eres Memory Curator legacy. Extrae hechos atómicos. JSON array kind/title/body."""


def extract_facts(text: str, *, title: str, source_path: str) -> list[dict[str, Any]]:
    from raphiia_openai.local_model_router import _http_json

    snippet = text[:MAX_DOC_CHARS]
    prompt = (
        f"Documento: {title}\n"
        f"Ruta fuente: {source_path}\n\n"
        f"---\n{snippet}\n---\n\n"
        "Extrae hechos atómicos del documento."
    )

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _EXTRACT_SYSTEM.replace("{max_facts}", str(MAX_FACTS))},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1800},
    }
    llm = _http_json(f"{OLLAMA_URL.rstrip('/')}/api/chat", method="POST", body=payload, timeout=240)
    if not llm.get("ok"):
        raise RuntimeError(llm.get("error") or "ollama_chat_failed")
    content = (llm.get("data") or {}).get("message", {}).get("content", "")
    facts = _parse_facts(content)
    if not facts and content.strip() and not STRICT_MODE:
        facts = [{"kind": "summary", "title": title[:120], "body": content.strip()[:500], "entities": [], "privacy_scope": "INTERNAL_WORK", "project": None}]
    return facts


def _brand_project(path: str) -> str | None:
    gdi = _import_file_io()
    brand = gdi.brand_of(path)
    return None if brand == "General" else brand.lower().replace(" ", "-")


def _maybe_conflict(existing_body: str, new_body: str) -> bool:
    a = set(re.findall(r"[a-z0-9]{4,}", existing_body.lower()))
    b = set(re.findall(r"[a-z0-9]{4,}", new_body.lower()))
    if not a or not b:
        return False
    overlap = len(a & b) / max(1, len(a | b))
    return overlap < 0.25 and len(existing_body) > 40 and len(new_body) > 40


def persist_facts(
    facts: list[dict[str, Any]],
    *,
    source_path: str,
    file_hash: str,
    mtime: float,
    title: str,
) -> dict[str, int]:
    from raphiia_openai import daily_memory, mongo_store
    from raphiia_openai.daily_memory import PENDING, _id, _now

    counts = {"created": 0, "updated": 0, "duplicates": 0, "conflicts": 0}
    memory_ids: list[str] = []
    source_meta = {
        "source_file_id": _file_id(source_path),
        "source_path": source_path,
        "source_title": title,
        "source_mtime": mtime,
        "source_hash": file_hash,
        "curator": AGENT_ID,
        "curator_worker": WORKER_LABEL,
        "curator_node": NODE_NAME,
    }
    project_default = _brand_project(source_path)
    db = mongo_store.get_db()

    for fact in facts:
        body = fact["body"]
        search = daily_memory.search_memory(
            {
                "query": body[:200],
                "limit": 3,
                "actor": "RAFAEL",
                "owner_id": "RAFAEL",
                "min_score": 0.3,
            }
        )
        items = search.get("items") or []
        if items and items[0].get("score", 0) >= 1.2:
            top = items[0]
            if _maybe_conflict(str(top.get("body") or ""), body):
                pending_id = _id("pending")
                db[PENDING].insert_one(
                    {
                        "pending_id": pending_id,
                        "owner_id": "RAFAEL",
                        "text": f"Conflicto memoria vs documento {title}: {body[:300]}",
                        "status": "open",
                        "privacy_scope": fact["privacy_scope"],
                        "project": fact.get("project") or project_default,
                        "entity_refs": fact.get("entities") or [],
                        "source_message_ids": [],
                        "metadata": {
                            **source_meta,
                            "existing_memory_id": top.get("memory_id"),
                            "new_body_preview": body[:400],
                        },
                        "created_at": _now(),
                        "updated_at": _now(),
                    }
                )
                counts["conflicts"] += 1
                continue

        saved = daily_memory.save_memory(
            {
                "owner_id": "RAFAEL",
                "kind": fact["kind"],
                "title": fact["title"],
                "body": body,
                "privacy_scope": fact["privacy_scope"],
                "project": fact.get("project") or project_default,
                "entities": fact.get("entities") or [],
                "tags": ["memory-curator", "gdrive" if "google_drive" in source_path else "notion"],
                "metadata": source_meta,
                "actor": AGENT_ID,
            }
        )
        mid = saved.get("memory_id")
        if mid:
            memory_ids.append(mid)
        if saved.get("created"):
            counts["created"] += 1
        elif saved.get("duplicate"):
            counts["duplicates"] += 1
        else:
            counts["updated"] += 1

    return {**counts, "memory_ids": memory_ids}


def process_file(path: Path, state: dict[str, Any], logger: logging.Logger) -> dict[str, Any]:
    from raphiia_openai.memory_record_schema import PathHierarchy, parse_path_hierarchy

    rel = str(path)
    stats = state.setdefault("stats", {})
    files = state.setdefault("files", {})
    prev = files.get(rel) or {}
    hierarchy = parse_path_hierarchy(rel)

    try:
        mtime = path.stat().st_mtime

        if hierarchy.is_media_only:
            stats["skipped"] = int(stats.get("skipped") or 0) + 1
            entry = {"file_id": _file_id(rel), "mtime": mtime, "skipped": True, "reason": "media_only", "hierarchy": hierarchy.to_dict(), "processed_at": _now_iso()}
            files[rel] = entry
            _checkpoint_mark(rel, {"status": "skipped", "reason": "media_only", "mtime": mtime, "hash": ""})
            return {"ok": True, "skipped": True, "path": rel, "reason": "media_only"}

        text = read_document(path).strip()
        content_hash = _content_hash(text)
        if _globally_done(rel, mtime, content_hash):
            stats["skipped"] = int(stats.get("skipped") or 0) + 1
            return {"ok": True, "skipped": True, "path": rel, "reason": "global_checkpoint"}

        if len(text) < 30:
            stats["skipped"] = int(stats.get("skipped") or 0) + 1
            entry = {**prev, "file_id": _file_id(rel), "mtime": mtime, "hash": content_hash, "skipped": True, "reason": "too_short", "hierarchy": hierarchy.to_dict(), "processed_at": _now_iso()}
            files[rel] = entry
            _checkpoint_mark(rel, {"status": "skipped", "reason": "too_short", "hash": content_hash, "mtime": mtime})
            return {"ok": True, "skipped": True, "path": rel}

        if prev.get("hash") == content_hash and prev.get("record_ids"):
            stats["skipped"] = int(stats.get("skipped") or 0) + 1
            return {"ok": True, "skipped": True, "path": rel, "reason": "unchanged"}

        title = path.stem[:200]
        state["current_file"] = rel
        logger.info("Procesando [%s/%s]: %s", hierarchy.brand, hierarchy.client_name or "-", path.name)

        if STRICT_MODE:
            from raphiia_openai import memory_record_store

            raw_records = extract_strict_records(text, title=title, source_path=rel, hierarchy=hierarchy)
            if not raw_records:
                stats["skipped"] = int(stats.get("skipped") or 0) + 1
                files[rel] = {"file_id": _file_id(rel), "mtime": mtime, "hash": content_hash, "record_ids": [], "hierarchy": hierarchy.to_dict(), "processed_at": _now_iso()}
                _checkpoint_mark(rel, {"status": "skipped", "reason": "no_records", "hash": content_hash, "mtime": mtime})
                return {"ok": True, "skipped": True, "path": rel, "reason": "no_records"}

            result = memory_record_store.save_records_from_extraction(
                raw_records,
                source_path=rel,
                content_hash=content_hash,
                mtime=mtime,
                hierarchy=hierarchy,
                tenant_id=TENANT_ID,
                curator_meta={"worker": WORKER_LABEL, "node": NODE_NAME, "agent": AGENT_ID},
            )
            if result.get("file_duplicate"):
                stats["skipped"] = int(stats.get("skipped") or 0) + 1
                files[rel] = {"file_id": _file_id(rel), "duplicate_of": result.get("duplicate_of"), "hash": content_hash, "mtime": mtime, "processed_at": _now_iso()}
                _checkpoint_mark(rel, {"status": "skipped", "reason": "duplicate_file", "hash": content_hash, "mtime": mtime, "duplicate_of": result.get("duplicate_of")})
                return {"ok": True, "skipped": True, "path": rel, "reason": "duplicate_file"}

            counts = result.get("counts") or {}
            stats["processed"] = int(stats.get("processed") or 0) + 1
            stats["canonical"] = int(stats.get("canonical") or 0) + int(counts.get("canonical") or 0)
            stats["review"] = int(stats.get("review") or 0) + int(counts.get("review") or 0)
            stats["rejected"] = int(stats.get("rejected") or 0) + int(counts.get("rejected") or 0)
            stats["duplicates"] = int(stats.get("duplicates") or 0) + int(counts.get("duplicate") or 0)

            files[rel] = {
                "file_id": _file_id(rel),
                "mtime": mtime,
                "hash": content_hash,
                "record_ids": result.get("record_ids") or [],
                "hierarchy": hierarchy.to_dict(),
                "counts": counts,
                "processed_at": _now_iso(),
            }
            _checkpoint_mark(rel, {"status": "done", "hash": content_hash, "mtime": mtime, "record_ids": result.get("record_ids") or [], "counts": counts})
            logger.info("OK strict %s → canonical=%s review=%s rejected=%s dup=%s", path.name, counts.get("canonical"), counts.get("review"), counts.get("rejected"), counts.get("duplicate"))
            return {"ok": True, "path": rel, "strict": True, **result}

        # Legacy v0 path (MEMORY_CURATOR_STRICT=0)
        facts = extract_facts(text, title=title, source_path=rel)
        if not facts:
            stats["skipped"] = int(stats.get("skipped") or 0) + 1
            entry = {
                "file_id": _file_id(rel),
                "mtime": mtime,
                "hash": content_hash,
                "memory_ids": prev.get("memory_ids") or [],
                "facts_extracted": 0,
                "processed_at": _now_iso(),
            }
            files[rel] = entry
            _checkpoint_mark(rel, {"status": "skipped", "reason": "no_facts", "hash": content_hash, "mtime": mtime})
            return {"ok": True, "skipped": True, "path": rel, "reason": "no_facts"}

        result = persist_facts(facts, source_path=rel, file_hash=content_hash, mtime=mtime, title=title)
        for key in ("created", "updated", "duplicates", "conflicts"):
            stats[key] = int(stats.get(key) or 0) + int(result.get(key) or 0)
        stats["processed"] = int(stats.get("processed") or 0) + 1

        existing_ids = list(prev.get("memory_ids") or [])
        for mid in result.get("memory_ids") or []:
            if mid not in existing_ids:
                existing_ids.append(mid)

        entry = {
            "file_id": _file_id(rel),
            "mtime": mtime,
            "hash": content_hash,
            "memory_ids": existing_ids,
            "facts_extracted": len(facts),
            "processed_at": _now_iso(),
        }
        files[rel] = entry
        _checkpoint_mark(
            rel,
            {
                "status": "done",
                "hash": content_hash,
                "mtime": mtime,
                "memory_ids": existing_ids,
                "facts_extracted": len(facts),
            },
        )
        logger.info(
            "OK %s → facts=%d created=%d dup=%d",
            path.name,
            len(facts),
            result.get("created", 0),
            result.get("duplicates", 0),
        )
        return {"ok": True, "path": rel, **result, "facts": len(facts)}

    except Exception as exc:
        stats["errors"] = int(stats.get("errors") or 0) + 1
        logger.exception("Error en %s: %s", rel, exc)
        files[rel] = {
            **prev,
            "file_id": _file_id(rel),
            "error": str(exc)[:300],
            "processed_at": _now_iso(),
        }
        return {"ok": False, "path": rel, "error": str(exc)}


def run_batch(
    *,
    limit: int = 10,
    resume: bool = True,
    roots: list[str] | None = None,
    state_path: Path = DEFAULT_STATE,
    log_path: Path = DEFAULT_LOG,
) -> dict[str, Any]:
    logger = _setup_logging(log_path)
    state = load_state(state_path)
    all_files = list_files(roots)
    processed_this_run = 0
    results: list[dict[str, Any]] = []
    logger.info(
        "Batch start worker=%s node=%s shard=%s/%s files_in_shard=%d model=%s",
        WORKER_LABEL,
        NODE_NAME,
        WORKER_ID,
        NUM_WORKERS,
        len(all_files),
        MODEL,
    )

    for path in all_files:
        rel = str(path)
        if resume and rel in state.get("files", {}) and state["files"][rel].get("memory_ids"):
            entry = state["files"][rel]
            if entry.get("hash") and entry.get("mtime") == path.stat().st_mtime:
                continue
        result = process_file(path, state, logger)
        results.append(result)
        if not result.get("skipped"):
            processed_this_run += 1
        save_state(state, state_path)
        if processed_this_run >= limit:
            break

    _heartbeat(state, logger)
    summary = {
        "ok": True,
        "processed_this_run": processed_this_run,
        "stats": state.get("stats"),
        "last_file": state.get("current_file"),
        "results": results[-5:],
    }
    logger.info("Batch done: %s", json.dumps(summary, default=str))
    if processed_this_run > 0:
        try:
            from raphiia_openai.agent_auto_log import record_agent_run

            stats = state.get("stats") or {}
            record_agent_run(
                "AG-MEMORY-CURATOR",
                action="curator_batch",
                summary=(
                    f"worker={WORKER_LABEL} processed={processed_this_run} "
                    f"total={stats.get('processed', 0)} canonical={stats.get('canonical', 0)}"
                ),
                project="memory-curator",
                tool_used="memory_curator.run_batch",
                metadata={"stats": stats, "node": NODE_NAME, "worker": WORKER_ID},
            )
        except Exception as exc:
            logger.warning("record_agent_run: %s", exc)
    return summary


def _heartbeat(state: dict[str, Any], logger: logging.Logger) -> None:
    try:
        from raphiia_openai import coordination_live

        stats = state.get("stats") or {}
        coordination_live.heartbeat_ops_task(
            OPS_TASK_ID,
            "cursor",
            next_action=f"curator processed={stats.get('processed', 0)} created={stats.get('created', 0)}",
            files_touched=["raphiia_openai/memory_curator.py"],
        )
    except Exception as exc:
        logger.warning("heartbeat_ops_task: %s", exc)


def run_daemon(
    *,
    interval: int = 300,
    batch_size: int = 1,
    state_path: Path = DEFAULT_STATE,
    log_path: Path = DEFAULT_LOG,
) -> None:
    logger = _setup_logging(log_path)
    logger.info(
        "Memory Curator daemon worker=%s node=%s shard=%s/%s model=%s interval=%ds batch=%d",
        WORKER_LABEL,
        NODE_NAME,
        WORKER_ID,
        NUM_WORKERS,
        MODEL,
        interval,
        batch_size,
    )
    while True:
        try:
            run_batch(limit=batch_size, resume=True, state_path=state_path, log_path=log_path)
        except Exception:
            logger.exception("daemon cycle error")
        time.sleep(max(5, interval))


def status(state_path: Path | None = None) -> dict[str, Any]:
    sp = state_path or worker_paths()[0]
    state = load_state(sp)
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "strict_mode": STRICT_MODE,
        "model": MODEL,
        "worker": WORKER_LABEL,
        "node": NODE_NAME,
        "shard": f"{WORKER_ID}/{NUM_WORKERS}",
        "state_path": str(sp),
        "last_heartbeat": state.get("last_heartbeat"),
        "current_file": state.get("current_file"),
        "stats": state.get("stats"),
        "files_indexed": len(state.get("files") or {}),
    }


def fleet_status() -> dict[str, Any]:
    base = Path("/home/rlopez/data/memory_curator")
    workers: list[dict[str, Any]] = []
    for sp in sorted(base.glob("state*.json")):
        try:
            st = json.loads(sp.read_text(encoding="utf-8"))
            workers.append({"state_path": str(sp), "stats": st.get("stats"), "current_file": st.get("current_file")})
        except Exception:
            workers.append({"state_path": str(sp), "error": "unreadable"})
    if DEFAULT_STATE.is_file() and not any(w.get("state_path") == str(DEFAULT_STATE) for w in workers):
        workers.append({"state_path": str(DEFAULT_STATE), "stats": load_state(DEFAULT_STATE).get("stats")})

    mongo_stats: dict[str, Any] = {}
    try:
        from raphiia_openai import memory_record_store, mongo_store

        mongo_stats = memory_record_store.stats(TENANT_ID)
        mongo_stats["legacy_memory_curator_tag"] = mongo_store.get_db()["ralfia_memory_items"].count_documents({"tags": "memory-curator"})
        mongo_stats["checkpoint_entries"] = mongo_store.get_db()[CHECKPOINT_COL].estimated_document_count()
    except Exception as exc:
        mongo_stats = {"error": str(exc)}

    totals = {"processed": 0, "created": 0, "skipped": 0, "errors": 0}
    for w in workers:
        for k in totals:
            totals[k] += int((w.get("stats") or {}).get(k) or 0)

    return {"ok": True, "workers": workers, "totals": totals, "mongo": mongo_stats}


def run_system_test(queries: list[str] | None = None) -> dict[str, Any]:
    from raphiia_openai import daily_memory, hybrid_context, memory_record_store

    qs = queries or [
        "linkedin hlopezgye",
        "Novomode cotización",
        "cliente PC Doctor",
    ]
    tests: list[dict[str, Any]] = []
    for q in qs:
        records = memory_record_store.search_records(q, tenant_id=TENANT_ID, canonical_only=True, limit=5)
        mem = daily_memory.search_memory({"query": q, "limit": 2, "actor": "RAFAEL", "owner_id": "RAFAEL"})
        tests.append(
            {
                "query": q,
                "canonical_records": records.get("count", 0),
                "record_top": (records.get("items") or [{}])[0] if records.get("items") else None,
                "legacy_memory_hits": mem.get("count", 0),
            }
        )
    return {"ok": True, "strict_mode": STRICT_MODE, "fleet": fleet_status(), "search_tests": tests, "record_stats": memory_record_store.stats(TENANT_ID)}
