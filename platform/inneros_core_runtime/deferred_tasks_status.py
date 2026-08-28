"""AG-36 — Estado tareas diferidas (archivo PST/GDrive, cleanup) desde state + KB ingest."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STATE_FILE = Path("/home/rlopez/data/ralfia/.ag36_deferred_state.json")
MANIFEST_FILE = Path("/home/rlopez/data/ralfia/deferred_tasks_manifest.json")
LOG_FILE = Path("/home/rlopez/data/ralfia/ag36_deferred.log")

TASK_DEFS: list[dict[str, Any]] = [
    {
        "id": "cleanup_hdd2tb",
        "title": "Eliminar symlink circular hdd2tb",
        "condition": "Siempre — inmediato al detectar /home/rlopez/data/hdd2tb",
        "paths": {"target": "/home/rlopez/data/hdd2tb"},
    },
    {
        "id": "pst_archive_intel",
        "title": "Archivar PST Intel → /mnt/datos_agentes/backups/pst_archive",
        "condition": "pst_extract.pct >= 100 AND pst_ingest.finished",
        "paths": {
            "source": "/home/rlopez/projects/ralphiia-quoteops/data/pst_backups",
            "dest": "/mnt/datos_agentes/backups/pst_archive",
            "node": "intel",
        },
    },
    {
        "id": "pst_archive_amd",
        "title": "Archivar PST AMD → /home/rlopez/data/pst_archive",
        "condition": "pst_ingest.finished AND emails extraídos existen",
        "paths": {
            "source": "/home/rlopez/projects/ralphiia-quoteops/data/pst_backups",
            "dest": "/home/rlopez/data/pst_archive",
            "node": "amd",
        },
    },
    {
        "id": "gdrive_archive_amd",
        "title": "Archivar GDrive → google_drive_archive (rsync incremental)",
        "condition": "gdrive.pct >= 100 AND gdrive.finished",
        "paths": {
            "source": "/home/rlopez/data/google_drive",
            "dest": "/home/rlopez/data/google_drive_archive",
            "node": "amd",
        },
    },
    {
        "id": "post_gdrive_verify",
        "title": "Verificar Qdrant post-archivo GDrive (no borrar origen hasta verified)",
        "condition": "gdrive_archive rsync_complete; verified manual o tras 24h",
        "paths": {},
    },
]


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _task_status(task_id: str, state: dict, kb: dict | None) -> dict[str, Any]:
    """Derive human-readable status for one task."""
    st = state.get(task_id) or {}
    kb_ph = (kb or {}).get("phases") or {}

    if task_id == "cleanup_hdd2tb":
        done = bool(st.get("done"))
        exists = Path("/home/rlopez/data/hdd2tb").exists()
        return {
            "status": "done" if done else ("pending" if exists else "done"),
            "done": done or not exists,
            "note": "Eliminado" if done else ("Pendiente eliminar" if exists else "No existe"),
        }

    if task_id == "pst_archive_intel":
        ext = kb_ph.get("pst_extract") or {}
        ing = kb_ph.get("pst_ingest") or {}
        ready = float(ext.get("pct", 0)) >= 100 and bool(ing.get("finished"))
        sub = st.get("status") or "pending"
        return {
            "status": sub if ready else "waiting_kb",
            "done": sub == "done",
            "ready": ready,
            "kb_pct_extract": ext.get("pct"),
            "kb_ingest_finished": ing.get("finished"),
            "note": st.get("note", ""),
        }

    if task_id == "pst_archive_amd":
        ing = kb_ph.get("pst_ingest") or {}
        ready = bool(ing.get("finished"))
        sub = st.get("status") or "pending"
        return {
            "status": sub if ready else "waiting_kb",
            "done": sub == "done",
            "ready": ready,
            "note": st.get("note", ""),
        }

    if task_id == "gdrive_archive_amd":
        gd = kb_ph.get("gdrive") or {}
        ready = float(gd.get("pct", 0)) >= 100 and bool(gd.get("finished"))
        sub = st.get("status") or "pending"
        return {
            "status": sub if ready else "waiting_kb",
            "done": sub in ("done", "verified"),
            "ready": ready,
            "gdrive_pct": gd.get("pct"),
            "note": st.get("note", ""),
        }

    if task_id == "post_gdrive_verify":
        gda = state.get("gdrive_archive_amd") or {}
        rsync_ok = gda.get("status") in ("rsync_complete", "done", "verified")
        verified = bool(gda.get("gdrive_archive_verified"))
        return {
            "status": "verified" if verified else ("pending_verify" if rsync_ok else "waiting_archive"),
            "done": verified,
            "gdrive_archive_verified": verified,
            "qdrant_points": st.get("qdrant_points"),
            "note": st.get("note", ""),
        }

    return {"status": "unknown", "done": False}


def build_manifest(state: dict | None = None, kb: dict | None = None) -> dict[str, Any]:
    """Manifest único — condiciones, rutas y estado actual."""
    state = state if state is not None else _read_json(STATE_FILE)
    if kb is None:
        try:
            from raphiia_openai.kb_ingest_status import get_kb_ingest_status

            kb = get_kb_ingest_status()
        except Exception:
            kb = {}

    tasks = []
    pending_actions: list[str] = []

    for td in TASK_DEFS:
        tid = td["id"]
        ts = _task_status(tid, state, kb)
        entry = {**td, **ts}
        tasks.append(entry)
        if not ts.get("done") and ts.get("status") not in ("waiting_kb", "waiting_archive"):
            if ts.get("ready", True):
                pending_actions.append(tid)
        elif ts.get("status") == "waiting_kb" and ts.get("ready"):
            pending_actions.append(tid)

    return {
        "agent": "AG-36 Deferred Tasks Sentinel",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "state_file": str(STATE_FILE),
        "log_file": str(LOG_FILE),
        "tasks": tasks,
        "pending_automatic_actions": pending_actions,
        "kb_snapshot": {
            "overall_pct": kb.get("overall_pct"),
            "gdrive_pct": (kb.get("phases") or {}).get("gdrive", {}).get("pct"),
            "pst_extract_pct": (kb.get("phases") or {}).get("pst_extract", {}).get("pct"),
            "pst_ingest_finished": (kb.get("phases") or {}).get("pst_ingest", {}).get("finished"),
            "qdrant_points": kb.get("qdrant_points"),
        },
    }


def get_deferred_tasks_status() -> dict[str, Any]:
    """Estado AG-36 para MCP — manifest + state resumido."""
    state = _read_json(STATE_FILE)
    try:
        from raphiia_openai.kb_ingest_status import get_kb_ingest_status

        kb = get_kb_ingest_status()
    except Exception as e:
        kb = {"ok": False, "error": str(e)}

    manifest = build_manifest(state, kb if kb.get("ok") else None)
    manifest["ok"] = True
    manifest["owner"] = "AG-36 — timer ralfia-deferred-tasks cada 30-60 min"
    return manifest


def write_manifest(state: dict | None = None) -> Path:
    manifest = build_manifest(state)
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return MANIFEST_FILE
