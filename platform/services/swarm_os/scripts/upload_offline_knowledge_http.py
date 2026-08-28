#!/usr/bin/env python3
"""Sube runbook a Knowledge usando la API HTTP de Open WebUI (app viva)."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DB = Path("/mnt/datos_agentes/ai-server-v2/open-webui/webui.db")
RUNBOOK = Path("/mnt/datos_agentes/ai-server-v2/open-webui/offline-knowledge/RALFIA_OFFLINE_RUNBOOK.md")
WEBUI = "http://127.0.0.1:3000"
KB_NAME = "RalfIA Offline"
MODEL_ID = "ralfia-offline"


def _wait_ready(timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{WEBUI}/api/config", timeout=3) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(2)
    raise SystemExit("Open WebUI no responde")


def _ensure_api_key() -> str:
    conn = sqlite3.connect(DB)
    conn.execute(
        "INSERT OR REPLACE INTO config (key,value) VALUES ('auth.enable_api_keys','true')"
    )
    row = conn.execute("SELECT key FROM api_key ORDER BY created_at DESC LIMIT 1").fetchone()
    if row and row[0].startswith("sk-"):
        conn.commit()
        conn.close()
        return row[0]
    import uuid

    key = f"sk-{uuid.uuid4().hex}"
    admin = conn.execute("SELECT id FROM user WHERE role='admin' LIMIT 1").fetchone()[0]
    now = int(time.time())
    conn.execute(
        "INSERT INTO api_key (id,user_id,key,data,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), admin, key, "{}", now, now),
    )
    conn.commit()
    conn.close()
    return key


def _api_key() -> str:
    return _ensure_api_key()


def _request(method: str, path: str, key: str, data: bytes | None = None, headers: dict | None = None) -> dict:
    hdrs = {"Authorization": f"Bearer {key}"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(f"{WEBUI}{path}", data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} {path}: {err[:500]}")


def _kb_id(key: str) -> str:
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT id FROM knowledge WHERE name=? LIMIT 1", (KB_NAME,)).fetchone()
    conn.close()
    if row:
        return row[0]
    out = _request(
        "POST",
        "/api/v1/knowledge/create",
        key,
        data=json.dumps({"name": KB_NAME, "description": "Runbook LAN sin internet", "access_grants": []}).encode(),
        headers={"Content-Type": "application/json"},
    )
    return out["id"]


def _already_linked(kb_id: str) -> bool:
    conn = sqlite3.connect(DB)
    n = conn.execute(
        """
        SELECT COUNT(*) FROM knowledge_file kf
        JOIN file f ON f.id = kf.file_id
        WHERE kf.knowledge_id=? AND f.filename LIKE '%RUNBOOK%'
        """,
        (kb_id,),
    ).fetchone()[0]
    conn.close()
    return n > 0


def _multipart_upload(key: str, kb_id: str) -> str:
    boundary = "----RalfIAOfflineBoundary"
    content = RUNBOOK.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="RALFIA_OFFLINE_RUNBOOK.md"\r\n',
            b"Content-Type: text/markdown\r\n\r\n",
            content,
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="metadata"\r\n\r\n',
            json.dumps({"source": "offline-runbook", "knowledge_id": kb_id}).encode(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    out = _request(
        "POST",
        "/api/v1/files/?process=true&process_in_background=false",
        key,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return out["id"]


def _link_model(kb_id: str) -> None:
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT meta FROM model WHERE id=?", (MODEL_ID,)).fetchone()
    if not row:
        conn.close()
        return
    meta = json.loads(row[0] or "{}")
    meta["knowledge"] = [{"id": kb_id, "name": KB_NAME}]
    meta.setdefault("capabilities", {})["memory"] = True
    conn.execute("UPDATE model SET meta=? WHERE id=?", (json.dumps(meta), MODEL_ID))
    conn.commit()
    conn.close()


def main() -> None:
    if not RUNBOOK.is_file():
        raise SystemExit(f"Falta runbook: {RUNBOOK}")
    _wait_ready()
    key = _api_key()
    kb_id = _kb_id(key)
    print(f"KB {kb_id}")

    if _already_linked(kb_id):
        print("Runbook ya indexado en Knowledge")
    else:
        # Reutilizar file con content si existe y no está enlazado
        conn = sqlite3.connect(DB)
        orphan = conn.execute(
            "SELECT id FROM file WHERE filename LIKE '%RUNBOOK%' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        file_id = orphan[0] if orphan else _multipart_upload(key, kb_id)
        print(f"File {file_id}")
        _request(
            "POST",
            f"/api/v1/knowledge/{kb_id}/file/add",
            key,
            data=json.dumps({"file_id": file_id}).encode(),
            headers={"Content-Type": "application/json"},
        )
        print("Indexado y adjuntado")

    _link_model(kb_id)
    print("Modelo ralfia-offline enlazado")
    print("DONE")


if __name__ == "__main__":
    main()
