"""Indexación de contactos operativos → Qdrant (inneros_kb)."""

from __future__ import annotations

import json
import uuid
import urllib.error
import urllib.request
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.settings import OLLAMA_URL, QDRANT_COLLECTION, QDRANT_URL
from raphiia_openai.operational.constants import COL_OPS_WHATSAPP_GROUPS
from raphiia_openai.whatsapp_contacts import (
    CHIP_IMPORT_PROVENANCE,
    CONTACTS_COL,
    SOURCE_EVOLUTION_INNERCHISPA,
)

EMBED_MODEL = "nomic-embed-text"
BATCH_LOG = 200


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, timeout: float = 120.0) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def embed_text(text: str) -> list[float] | None:
    resp = _http_json(
        f"{OLLAMA_URL.rstrip('/')}/api/embeddings",
        method="POST",
        body={"model": EMBED_MODEL, "prompt": text[:4000]},
        timeout=120.0,
    )
    return resp.get("embedding")


def _contact_text(doc: dict[str, Any]) -> str:
    name = (doc.get("name") or doc.get("push_name") or "").strip()
    digits = (doc.get("whatsapp_digits") or doc.get("phone_digits") or "").strip()
    note = CHIP_IMPORT_PROVENANCE["origin_note"]
    return (
        f"Contacto WhatsApp chip Innerchispa — {name} — tel {digits}. "
        f"NO es contacto personal de Rafael. {note}"
    )


def _contact_payload(doc: dict[str, Any]) -> dict[str, Any]:
    name = (doc.get("name") or doc.get("push_name") or "").strip()
    digits = (doc.get("whatsapp_digits") or doc.get("phone_digits") or "").strip()
    text = _contact_text(doc)
    return {
        "source": SOURCE_EVOLUTION_INNERCHISPA,
        "content_type": "whatsapp_contact",
        "title": name or digits,
        "text": text,
        "brand": "InnerChispa",
        "entity_id": "ent_innerchispa",
        "contact_id": doc.get("contact_id"),
        "whatsapp_digits": digits,
        "remote_jid": doc.get("remote_jid"),
        "known_to_owner": False,
        "relationship": "unknown",
        "contact_class": "chip_import",
        "trust_level": "cold",
        "privacy_scope": "MARKETING_COLD",
        "owner_id": "RAFAEL",
        "warning": "No es contacto personal — chip Innerchispa usado por terceros para trabajo",
    }


def _group_text(doc: dict[str, Any]) -> str:
    name = (doc.get("name") or doc.get("alias") or "").strip()
    jid = (doc.get("group_jid") or "").strip()
    note = CHIP_IMPORT_PROVENANCE["origin_note"]
    return (
        f"Grupo WhatsApp chip Innerchispa — {name} — {jid}. "
        f"NO es grupo personal de Rafael. {note}"
    )


def _group_payload(doc: dict[str, Any]) -> dict[str, Any]:
    name = (doc.get("name") or doc.get("alias") or "").strip()
    jid = (doc.get("group_jid") or "").strip()
    text = _group_text(doc)
    return {
        "source": SOURCE_EVOLUTION_INNERCHISPA,
        "content_type": "whatsapp_group",
        "title": name or jid,
        "text": text,
        "brand": "InnerChispa",
        "entity_id": "ent_innerchispa",
        "group_jid": jid,
        "known_to_owner": False,
        "relationship": "unknown",
        "contact_class": "chip_import_group",
        "trust_level": "cold",
        "privacy_scope": "MARKETING_COLD",
        "owner_id": "RAFAEL",
        "warning": "No es grupo personal — chip Innerchispa usado por terceros para trabajo",
    }


def _upsert_points(points: list[dict[str, Any]], *, qdrant_url: str | None = None) -> dict[str, Any]:
    if not points:
        return {"ok": True, "upserted": 0}
    base = (qdrant_url or QDRANT_URL).rstrip("/")
    resp = _http_json(
        f"{base}/collections/{QDRANT_COLLECTION}/points",
        method="PUT",
        body={"points": points},
        timeout=120.0,
    )
    if resp.get("error"):
        return {"ok": False, "error": resp["error"]}
    return {"ok": True, "upserted": len(points)}


def index_chip_contacts_to_qdrant(
    *,
    source: str = SOURCE_EVOLUTION_INNERCHISPA,
    limit: int | None = None,
    include_groups: bool = True,
    qdrant_url: str | None = None,
) -> dict[str, Any]:
    target_url = (qdrant_url or QDRANT_URL).rstrip("/")
    db = mongo_store.get_db()
    filt = {"source": source, "contact_class": "chip_import"}
    cursor = db[CONTACTS_COL].find(filt, {"_id": 0})
    if limit:
        cursor = cursor.limit(max(1, int(limit)))

    indexed = skipped = 0
    batch: list[dict[str, Any]] = []
    errors: list[str] = []

    for doc in cursor:
        text = _contact_text(doc)
        vector = embed_text(text)
        if not vector:
            skipped += 1
            continue
        pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"chip_contact:{doc.get('contact_id')}"))
        batch.append({"id": pid, "vector": vector, "payload": _contact_payload(doc)})
        if len(batch) >= 32:
            res = _upsert_points(batch, qdrant_url=target_url)
            if not res.get("ok"):
                errors.append(str(res.get("error")))
            else:
                indexed += len(batch)
            batch.clear()
            if indexed and indexed % BATCH_LOG == 0:
                print(f"  … {indexed} contactos indexados", flush=True)

    if batch:
        res = _upsert_points(batch, qdrant_url=target_url)
        if not res.get("ok"):
            errors.append(str(res.get("error")))
        else:
            indexed += len(batch)

    groups_indexed = 0
    if include_groups:
        gfilt = {"source": source}
        gbatch: list[dict[str, Any]] = []
        for gdoc in db[COL_OPS_WHATSAPP_GROUPS].find(gfilt, {"_id": 0}):
            text = _group_text(gdoc)
            vector = embed_text(text)
            if not vector:
                skipped += 1
                continue
            pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"chip_group:{gdoc.get('group_jid')}"))
            gbatch.append({"id": pid, "vector": vector, "payload": _group_payload(gdoc)})
            if len(gbatch) >= 32:
                res = _upsert_points(gbatch, qdrant_url=target_url)
                if res.get("ok"):
                    groups_indexed += len(gbatch)
                gbatch.clear()
        if gbatch:
            res = _upsert_points(gbatch, qdrant_url=target_url)
            if res.get("ok"):
                groups_indexed += len(gbatch)

    return {
        "ok": not errors,
        "collection": QDRANT_COLLECTION,
        "qdrant_url": target_url,
        "contacts_indexed": indexed,
        "groups_indexed": groups_indexed,
        "skipped": skipped,
        "errors": errors[:5],
        "disclaimer": CHIP_IMPORT_PROVENANCE["origin_note"],
    }
