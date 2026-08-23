"""Pipeline unificado de ingesta local — AG-34.

Fuentes: email_archive → VKR, ChatGPT handoffs/notes → backlog, PST → email_archive.
Todo con Ollama local + Mongo Intel; sin créditos cloud.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import dev_backlog, mongo_store
from raphiia_openai.agent_auto_log import record_agent_run
from raphiia_openai.memory_record_schema import PathHierarchy, parse_path_hierarchy

AGENT_ID = "AG-34_KB_INGEST"
CHECKPOINT_COL = "ingest_pipeline_checkpoint"
COORD_ROOT = Path("/home/rlopez/data/ai_coordination")
CHATGPT_DIRS = (
    COORD_ROOT / "chatgpt" / "handoff",
    COORD_ROOT / "chatgpt" / "notes",
    COORD_ROOT / "ChatGPT" / "handoff",
    COORD_ROOT / "ChatGPT" / "notes",
)
PST_SEARCH_ROOTS = (
    Path("/home/rlopez/data/pst_archive/pc_doctor"),
    Path("/home/rlopez/data/pst_archive"),
    Path("/home/rlopez/data/google_drive"),
    Path("/home/rlopez/data/media"),
    Path("/home/rlopez/data/backups"),
    Path("/home/rlopez/Downloads"),
)
EMAIL_VKR_CATEGORIES = frozenset(
    {
        "factura",
        "sri_fiscal",
        "cotizacion",
        "pago",
        "payment",
        "transferencia",
        "extracto",
        "contrato",
        "document",
        "invoice",
        "trusted_sender",
        "keyword_match",
    }
)
EMAIL_VKR_SUBJECT_RE = re.compile(
    r"factur|retenc|cotiz|pedido|transfer|pago|invoice|sri|comprobante|orden\s+de|"
    r"nota\s+de\s+credito|gu[ií]a|xml|clave\s+de\s+acceso",
    re.I,
)
PST_PARALLEL_IMPORT_WORKERS = max(2, min(8, int(os.getenv("PST_IMPORT_WORKERS", "6"))))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _checkpoint(key: str) -> dict[str, Any]:
    return _db()[CHECKPOINT_COL].find_one({"_id": key}) or {}


def _save_checkpoint(key: str, data: dict[str, Any]) -> None:
    _db()[CHECKPOINT_COL].update_one(
        {"_id": key},
        {"$set": {**data, "updated_at": _now()}},
        upsert=True,
    )


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- ChatGPT / coordinación → backlog ---

def _infer_status(text: str, title: str) -> str:
    blob = f"{title} {text}".lower()
    if re.search(r"\b(hecho|completado|done|implementado|desplegado|pass)\b", blob):
        return "done"
    if re.search(r"\b(p0|p1|pendiente|planned|todo|falta|implementar|crear)\b", blob):
        return "planned"
    if re.search(r"\b(deferred|después|post-nucleo|pospuesto)\b", blob):
        return "deferred"
    return "discussed"


def _infer_kind(title: str, body: str) -> str:
    blob = f"{title} {body}".lower()
    if re.search(r"\barquitect|migraci|diseño|schema\b", blob):
        return "architecture"
    if re.search(r"\bbug|fix|error|roto\b", blob):
        return "bug"
    if re.search(r"\bpregunta\b|¿", blob):
        return "question"
    return "idea"


def import_chatgpt_coordination_docs(*, limit: int = 200, dry_run: bool = False) -> dict[str, Any]:
    """Importa handoffs y notes de ChatGPT a ralfia_dev_backlog."""
    cp = _checkpoint("chatgpt_docs")
    seen = set(cp.get("imported_hashes") or [])
    created = updated = skipped = 0
    files: list[Path] = []
    for d in CHATGPT_DIRS:
        if d.is_dir():
            files.extend(sorted(d.glob("*.md")))
    files = files[: max(1, limit)]

    for path in files:
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped += 1
            continue
        h = _content_hash(body)
        if h in seen:
            skipped += 1
            continue
        title = path.stem
        if re.match(r"^\d{8}_\d{6}_", title):
            title = title.split("_", 2)[-1].replace("-", " ")
        status = _infer_status(body, title)
        kind = _infer_kind(title, body)
        item = {
            "title": title[:160],
            "body": body[:4000],
            "status": status,
            "kind": kind,
            "source_agent": "CHATGPT",
            "project": "inneros",
            "tags": ["chatgpt-import", path.parent.name],
            "conversation_ref": f"chatgpt-doc:{path.name}",
            "metadata": {"source_path": str(path), "content_hash": h},
        }
        if dry_run:
            created += 1
        else:
            res = dev_backlog.capture_backlog_item(**item)
            if res.get("action") == "created":
                created += 1
            else:
                updated += 1
        seen.add(h)

    if not dry_run:
        _save_checkpoint("chatgpt_docs", {"imported_hashes": list(seen)[-5000:], "last_run": _now()})
        record_agent_run(
            AGENT_ID,
            action="import_chatgpt_docs",
            summary=f"created={created} updated={updated} skipped={skipped}",
            project="coordination",
        )
    return {"ok": True, "source": "chatgpt_coordination", "created": created, "updated": updated, "skipped": skipped, "files": len(files)}


# --- Email → VKR ---

def _email_hierarchy(mail: dict[str, Any]) -> PathHierarchy:
    subject = str(mail.get("subject") or "")
    review = mail.get("ralfia_review") or mail.get("review") or {}
    cat = review.get("category") or "correspondencia"
    doc_map = {
        "factura": "factura",
        "sri_fiscal": "contabilidad",
        "cotizacion": "cotizacion",
        "pago": "contabilidad",
        "transferencia": "contabilidad",
        "extracto": "contabilidad",
        "contrato": "contrato",
    }
    doc_class = doc_map.get(cat, "correspondencia")
    fake_path = f"email_archive/{mail.get('account_address', 'unknown')}/{doc_class}/{subject[:80]}"
    return parse_path_hierarchy(fake_path)


def _resolve_ollama_model() -> str:
    import os

    preferred = os.getenv("MEMORY_CURATOR_MODEL", "qwen2.5:7b")
    try:
        from raphiia_openai.local_model_router import list_local_models

        models = list_local_models().get("models") or []
        names = [m.get("name") or m.get("model") for m in models if isinstance(m, dict)]
        if preferred in names:
            return preferred
        for cand in (
            "qwen2.5:7b",
            "qwen2.5:14b-instruct-q4_K_M",
            "llama3.1:8b",
            "uncensored-qwen3-8b:latest",
            "mannix/llama3.1-8b-abliterated:q5_K_M",
        ):
            if cand in names:
                return cand
        if names:
            return str(names[0])
    except Exception:
        pass
    return preferred


def _vkr_email_filter(done_ids: set[str], *, worker_shard: int = 0, worker_shards: int = 1) -> dict[str, Any]:
    cats = list(EMAIL_VKR_CATEGORIES)
    ors: list[dict[str, Any]] = [
        {"ralfia_review.category": {"$in": cats}},
        {"review.category": {"$in": cats}},
        {"source": "pst_import", "ralfia_review.priority": {"$in": ["high", "normal"]}},
        {"source": "pst_import", "ralfia_review.category": {"$in": ["payment", "document"]}},
        {"source": "pst_import", "subject": EMAIL_VKR_SUBJECT_RE},
        {"source": "pst_import", "has_attachment": True},
    ]
    filt: dict[str, Any] = {"mail_id": {"$nin": list(done_ids)}, "$or": ors}
    if worker_shards > 1:
        chars = "0123456789abcdef"
        shard_chars = "".join(chars[i] for i in range(worker_shard, 16, worker_shards))
        filt["mail_id"] = {"$nin": list(done_ids), "$regex": f"[{shard_chars}]$"}
    return filt


def count_vkr_pending(*, worker_shard: int = 0, worker_shards: int = 1) -> int:
    cp = _checkpoint("email_vkr")
    done_ids = set(cp.get("mail_ids") or [])
    return _db().email_messages.count_documents(
        _vkr_email_filter(done_ids, worker_shard=worker_shard, worker_shards=worker_shards)
    )


def ingest_email_vkr_batch(
    *,
    limit: int = 25,
    dry_run: bool = False,
    worker_shard: int = 0,
    worker_shards: int = 1,
) -> dict[str, Any]:
    """Correos high-priority → extracción VKR local (Ollama)."""
    import os

    from raphiia_openai.notifications import email_archive, email_review
    from raphiia_openai import memory_record_store
    from raphiia_openai.memory_curator import extract_strict_records

    model = _resolve_ollama_model()
    os.environ["MEMORY_CURATOR_MODEL"] = model

    cp = _checkpoint("email_vkr")
    done_ids = set(cp.get("mail_ids") or [])
    db = _db()
    email_archive.sync_email_archive_from_messages(limit=1000)

    filt = _vkr_email_filter(done_ids, worker_shard=worker_shard, worker_shards=worker_shards)
    cap = max(1, min(limit, 500))
    rows = list(db.email_messages.find(filt).sort("received_at", -1).limit(cap))

    stats = {"processed": 0, "skipped": 0, "canonical": 0, "review": 0, "errors": 0}
    for row in rows:
        mail_id = str(row.get("mail_id") or "")
        if not mail_id:
            continue
        try:
            review = email_review.get_review(mail_id, hydrate=True)
            if not review.get("ok"):
                stats["skipped"] += 1
                done_ids.add(mail_id)
                continue
            msg = review.get("message") or row
            body = str(msg.get("body_text") or msg.get("snippet") or "")
            if len(body.strip()) < 40:
                stats["skipped"] += 1
                done_ids.add(mail_id)
                continue
            subject = str(msg.get("subject") or mail_id)
            hierarchy = _email_hierarchy({**msg, "ralfia_review": review.get("analysis")})
            source_path = f"email://{msg.get('account_address', 'unknown')}/{mail_id}"
            content_hash = _content_hash(body[:50000])

            if dry_run:
                stats["processed"] += 1
                done_ids.add(mail_id)
                continue

            raw_records = extract_strict_records(body, title=subject, source_path=source_path, hierarchy=hierarchy)
            if not raw_records:
                stats["skipped"] += 1
                done_ids.add(mail_id)
                continue

            result = memory_record_store.save_records_from_extraction(
                raw_records,
                source_path=source_path,
                content_hash=content_hash,
                mtime=time.time(),
                hierarchy=hierarchy,
                curator_meta={"agent": AGENT_ID, "mail_id": mail_id, "model": model},
            )
            counts = result.get("counts") or {}
            stats["processed"] += 1
            stats["canonical"] += int(counts.get("canonical") or 0)
            stats["review"] += int(counts.get("review") or 0)
            done_ids.add(mail_id)
        except Exception:
            stats["errors"] += 1

    if not dry_run:
        _save_checkpoint("email_vkr", {"mail_ids": list(done_ids)[-10000:], "last_run": _now(), "stats": stats})
        record_agent_run(
            AGENT_ID,
            action="ingest_email_vkr",
            summary=f"processed={stats['processed']} canonical={stats['canonical']}",
            project="memory-curator",
            metadata=stats,
        )
    return {
        "ok": True,
        "source": "email_archive",
        **stats,
        "model": model,
        "pending": count_vkr_pending(worker_shard=worker_shard, worker_shards=worker_shards),
        "worker_shard": worker_shard,
        "worker_shards": worker_shards,
    }


# --- PST → email_archive ---

def _find_pst_files() -> list[Path]:
    seen: set[str] = set()
    found: list[Path] = []
    for root in PST_SEARCH_ROOTS:
        if not root.is_dir():
            continue
        try:
            for p in root.rglob("*.pst"):
                key = str(p.resolve())
                if key in seen or not p.is_file() or p.stat().st_size <= 0:
                    continue
                seen.add(key)
                found.append(p)
        except OSError:
            continue
    found.sort(key=lambda p: p.stat().st_size)
    return found


def _pst_timeout_seconds(size_bytes: int) -> int:
    size_mb = max(1, size_bytes // (1024 * 1024))
    return min(14400, max(900, size_mb * 45))


def _upsert_pst_email(doc: dict[str, Any], *, raw_eml: bytes) -> None:
    from raphiia_openai.notifications.email_review import analyze_email

    mail_id = str(doc.get("mail_id") or "")
    if not mail_id:
        return
    analysis = analyze_email(doc)
    account = str(doc.get("account_address") or "pst-import@ralfia.local")
    doc = {
        **doc,
        "source": "pst_import",
        "email_account_id": f"pst:{account}",
        "uid": mail_id,
        "ralfia_review": analysis,
        "updated_at": _now(),
    }
    db = _db()
    db.email_messages.update_one({"mail_id": mail_id}, {"$set": doc}, upsert=True)
    try:
        from raphiia_openai.notifications import email_archive

        email_archive.archive_email_message(doc, body_text=doc.get("body_text"), raw_eml=raw_eml)
    except Exception:
        pass


def _claim_next_pst(*, worker_id: str = "default") -> tuple[Path, str] | None:
    from pymongo import ReturnDocument

    db = _db()
    now = time.time()
    db[CHECKPOINT_COL].update_one(
        {"_id": "pst"},
        {"$setOnInsert": {"pst_hashes": [], "imported_total": 0, "pst_in_progress": {}}},
        upsert=True,
    )
    cp = _checkpoint("pst")
    done = set(cp.get("pst_hashes") or [])
    in_progress = dict(cp.get("pst_in_progress") or {})
    stale = 7200
    for ph, meta in list(in_progress.items()):
        if now - float(meta.get("ts") or 0) > stale:
            db[CHECKPOINT_COL].update_one({"_id": "pst"}, {"$unset": {f"pst_in_progress.{ph}": ""}})

    for pst in _find_pst_files():
        ph = _content_hash(str(pst) + str(pst.stat().st_mtime))
        if ph in done:
            continue
        updated = db[CHECKPOINT_COL].find_one_and_update(
            {
                "_id": "pst",
                "pst_hashes": {"$nin": [ph]},
                f"pst_in_progress.{ph}": {"$exists": False},
            },
            {"$set": {f"pst_in_progress.{ph}": {"worker": worker_id, "ts": now, "path": str(pst)}}},
            upsert=False,
            return_document=ReturnDocument.AFTER,
        )
        if updated and (updated.get("pst_in_progress") or {}).get(ph, {}).get("worker") == worker_id:
            return pst, ph
    return None


def _release_pst_claim(pst_hash: str, *, success: bool) -> None:
    db = _db()
    update: dict[str, Any] = {"$unset": {f"pst_in_progress.{pst_hash}": ""}}
    if success:
        update["$addToSet"] = {"pst_hashes": pst_hash}
    db[CHECKPOINT_COL].update_one({"_id": "pst"}, update)


def _import_eml_batch(eml_paths: list[Path], pst: Path) -> int:
    imported = 0
    for eml in eml_paths:
        try:
            raw = eml.read_bytes()
            doc = _eml_to_email_doc(raw, source_path=str(eml), pst_source=str(pst))
            if doc:
                _upsert_pst_email(doc, raw_eml=raw)
                imported += 1
        except Exception:
            continue
    return imported


def ingest_pst_files(*, dry_run: bool = False, max_pst: int = 1, worker_id: str = "default") -> dict[str, Any]:
    """Exporta PST con readpst; importa .eml → email_messages + email_archive."""
    pst_files = _find_pst_files()
    if not pst_files:
        return {
            "ok": True,
            "source": "pst",
            "pst_found": 0,
            "note": "No se encontraron .pst en rutas conocidas. Coloca PST en data/pst_archive/pc_doctor.",
        }

    readpst = subprocess.run(["which", "readpst"], capture_output=True, text=True)
    if readpst.returncode != 0:
        return {
            "ok": False,
            "source": "pst",
            "pst_found": len(pst_files),
            "paths": [str(p) for p in pst_files[:5]],
            "error": "readpst_not_installed",
            "hint": "sudo apt install pst-utils",
        }

    out_root = Path("/home/rlopez/data/media/pst_export")
    out_root.mkdir(parents=True, exist_ok=True)
    imported = 0
    cp = _checkpoint("pst")
    done_pst = set(cp.get("pst_hashes") or [])
    processed_pst = 0
    current_pst: str | None = None
    pending = [p for p in pst_files if _content_hash(str(p) + str(p.stat().st_mtime)) not in done_pst]

    for _ in range(max(1, max_pst)):
        claim = _claim_next_pst(worker_id=worker_id)
        if not claim:
            break
        pst, ph = claim
        current_pst = pst.name
        dest = out_root / pst.stem
        dest.mkdir(parents=True, exist_ok=True)
        if dry_run:
            imported += 1
            _release_pst_claim(ph, success=True)
            processed_pst += 1
            continue
        timeout = _pst_timeout_seconds(pst.stat().st_size)
        proc = subprocess.run(
            ["readpst", "-o", str(dest), "-e", "-D", str(pst)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            _release_pst_claim(ph, success=False)
            record_agent_run(
                AGENT_ID,
                action="ingest_pst_error",
                summary=f"readpst failed {pst.name}",
                project="email",
                metadata={"stderr": (proc.stderr or "")[:2000], "pst": str(pst)},
            )
            continue
        eml_paths = list(dest.rglob("*.eml"))
        if len(eml_paths) <= 200:
            imported += _import_eml_batch(eml_paths, pst)
        else:
            chunk = max(50, len(eml_paths) // PST_PARALLEL_IMPORT_WORKERS)
            chunks = [eml_paths[i : i + chunk] for i in range(0, len(eml_paths), chunk)]
            with ThreadPoolExecutor(max_workers=PST_PARALLEL_IMPORT_WORKERS) as pool:
                futures = [pool.submit(_import_eml_batch, part, pst) for part in chunks]
                for fut in as_completed(futures):
                    imported += int(fut.result() or 0)
        _release_pst_claim(ph, success=True)
        processed_pst += 1
        _save_checkpoint(
            "pst",
            {
                "pst_hashes": list(set(_checkpoint("pst").get("pst_hashes") or []) | {ph}),
                "last_pst": str(pst),
                "last_run": _now(),
                "imported_total": int(cp.get("imported_total") or 0) + imported,
                "worker_id": worker_id,
            },
        )

    remaining = max(0, len(pending) - processed_pst)
    if not dry_run and processed_pst:
        record_agent_run(
            AGENT_ID,
            action="ingest_pst",
            summary=f"imported={imported} pst_done={processed_pst} remaining={remaining}",
            project="email",
        )
    return {
        "ok": True,
        "source": "pst",
        "pst_found": len(pst_files),
        "pst_pending": len(pending),
        "pst_processed": processed_pst,
        "pst_remaining": max(0, remaining),
        "imported": imported,
        "current_pst": current_pst,
        "paths": [str(p) for p in pst_files[:8]],
    }


def _eml_to_email_doc(raw: bytes, *, source_path: str, pst_source: str) -> dict[str, Any] | None:
    from email import policy
    from email.parser import BytesParser
    from email.utils import parsedate_to_datetime

    msg = BytesParser(policy=policy.default).parsebytes(raw)
    subject = str(msg.get("subject") or "(sin asunto)")
    from_addr = str(msg.get("from") or "")
    mid = msg.get("Message-ID") or source_path
    mail_id = "mail_" + hashlib.sha256(str(mid).encode()).hexdigest()[:12]
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = str(part.get_content() or "")
                break
    else:
        body = str(msg.get_content() or "")
    received = datetime.now(timezone.utc)
    if msg.get("Date"):
        try:
            received = parsedate_to_datetime(str(msg.get("Date") or ""))
        except (TypeError, ValueError, OverflowError):
            received = datetime.now(timezone.utc)
    return {
        "mail_id": mail_id,
        "message_id": str(mid),
        "subject": subject[:500],
        "from_addr": from_addr[:300],
        "account_address": "pst-import@ralfia.local",
        "body_text": body[:50000],
        "received_at": received,
        "source_path": source_path,
        "pst_source": pst_source,
        "importance": "alta",
    }


def run_full_local_ingest(
    *,
    email_limit: int = 20,
    chatgpt_limit: int = 100,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Orquestador: ChatGPT docs + email VKR + PST en una pasada."""
    results = {
        "chatgpt": import_chatgpt_coordination_docs(limit=chatgpt_limit, dry_run=dry_run),
        "email_vkr": ingest_email_vkr_batch(limit=email_limit, dry_run=dry_run),
        "pst": ingest_pst_files(dry_run=dry_run),
    }
    record_agent_run(
        AGENT_ID,
        action="run_full_local_ingest",
        summary=f"chatgpt={results['chatgpt'].get('created', 0)} email={results['email_vkr'].get('processed', 0)} pst={results['pst'].get('imported', 0)}",
        project="ingest-pipeline",
        metadata={k: {kk: vv for kk, vv in v.items() if kk != "paths"} for k, v in results.items()},
    )
    return {"ok": True, "agent_id": AGENT_ID, "results": results, "dry_run": dry_run}
