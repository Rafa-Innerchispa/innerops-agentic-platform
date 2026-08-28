"""Estado unificado ingesta knowledge base (Notion + GDrive + PST) con % y ETA."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NOTION_STATE = Path("/home/rlopez/data/notion_export/.ingest_state.json")
NOTION_TOTAL = 3685
GDRIVE_STATE = Path("/home/rlopez/data/google_drive/.ingest_state.json")
GDRIVE_ROOTS = [
    Path("/home/rlopez/data/google_drive"),
    Path("/home/rlopez/data/google_takeout/extracted"),
]
PST_INTEL_STATE = "/home/rlopez/projects/ralphiia-quoteops/data/extracted_pst_emails/.extract_state.json"
PST_AMD_DIR = Path("/home/rlopez/data/pst_emails")
PST_AMD_STATE = PST_AMD_DIR / ".ingest_state.json"
PST_TOTAL = 22
INTEL = os.getenv("RALFIA_INTEL_IP", "192.168.1.4")
QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "inneros_kb")


@dataclass
class PhaseStatus:
    name: str
    done: int
    total: int
    chunks: int
    finished: bool
    running: bool
    pct: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "done": self.done,
            "total": self.total,
            "chunks": self.chunks,
            "finished": self.finished,
            "running": self.running,
            "pct": round(self.pct, 1),
            "note": self.note,
        }


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pgrep(pattern: str) -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _ssh_intel_json(remote_path: str) -> dict:
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
        f"rlopez@{INTEL}",
        f"python3 -c \"import json;from pathlib import Path;p=Path('{remote_path}');print(p.read_text() if p.is_file() else '{{}}')\"",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if r.returncode != 0 or not r.stdout.strip():
            return {}
        return json.loads(r.stdout)
    except Exception:
        return {}


def _qdrant_points() -> int | None:
    try:
        import httpx
        r = httpx.get(f"{QDRANT_URL.rstrip('/')}/collections/{QDRANT_COLLECTION}", timeout=8)
        if r.is_success:
            return (r.json().get("result") or {}).get("points_count")
    except Exception:
        pass
    return None


def _gdrive_total_cached(state: dict) -> int:
    if state.get("total_files"):
        return int(state["total_files"])
    # Contar una vez y cachear en estado externo
    cache = Path("/home/rlopez/data/google_drive/.ingest_total_files")
    if cache.is_file():
        try:
            return int(cache.read_text().strip())
        except Exception:
            pass
    return 53997  # último conteo conocido


def get_kb_ingest_status() -> dict[str, Any]:
    """Estado completo para MCP, voz y AG-34 sentinel."""
    # Notion
    ns = _read_json(NOTION_STATE)
    n_done = len(ns.get("done_files") or [])
    n_fin = bool(ns.get("finished_at"))
    notion = PhaseStatus(
        "notion", n_done, NOTION_TOTAL, int(ns.get("total_chunks") or 0),
        n_fin, _pgrep("notion_export_ingest"), 100.0 if n_fin else min(100, 100 * n_done / max(1, NOTION_TOTAL)),
        "OK" if n_fin else "",
    )

    # GDrive
    gs = _read_json(GDRIVE_STATE)
    g_total = _gdrive_total_cached(gs)
    g_done = len(gs.get("done_files") or [])
    g_fin = bool(gs.get("finished_at"))
    g_run = _pgrep("gdrive_export_ingest")
    g_pct = 100.0 if g_fin else min(99.9, 100 * g_done / max(1, g_total))
    gdrive = PhaseStatus(
        "gdrive", g_done, g_total, int(gs.get("total_chunks") or 0),
        g_fin, g_run, g_pct,
        "GPU AMD embeddings" if g_run else ("detenido — AG-34 puede relanzar" if not g_fin else ""),
    )

    # PST extract (Intel)
    ps = _ssh_intel_json(PST_INTEL_STATE)
    p_ext_done = len(ps.get("done_psts") or [])
    p_ext_fin = bool(ps.get("finished_at"))
    p_ext_run = False
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", f"rlopez@{INTEL}", "pgrep -f pst_email_extract.py"],
            capture_output=True, timeout=10,
        )
        p_ext_run = r.returncode == 0
    except Exception:
        pass
    pst_extract = PhaseStatus(
        "pst_extract", p_ext_done, PST_TOTAL, int(ps.get("messages") or 0),
        p_ext_fin, p_ext_run, 100.0 if p_ext_fin else 100 * p_ext_done / PST_TOTAL,
        f"Intel .4 readpst" + (" activo" if p_ext_run else ""),
    )

    # PST ingest (AMD → Qdrant)
    pis = _read_json(PST_AMD_STATE)
    p_ing_done = len(pis.get("done") or [])
    p_ing_fin = bool(pis.get("finished_at"))
    p_ing_run = _pgrep("pst_email_ingest")
    pst_ingest = PhaseStatus(
        "pst_ingest", p_ing_done, max(p_ext_done, PST_TOTAL), int(pis.get("chunks") or 0),
        p_ing_fin, p_ing_run,
        100.0 if p_ing_fin else (100 * p_ing_done / max(1, p_ext_done) if p_ext_done else 0),
        "pendiente rsync+ingest AMD" if p_ext_fin and not p_ing_fin and not p_ing_run else "",
    )

    phases = [notion, gdrive, pst_extract, pst_ingest]
    weights = [0.15, 0.55, 0.20, 0.10]  # peso relativo del trabajo
    overall_pct = sum(p.pct * w for p, w in zip(phases, weights))

    all_done = notion.finished and gdrive.finished and pst_extract.finished and pst_ingest.finished
    any_running = any(p.running for p in phases)

    # ETA rough for gdrive
    eta_note = ""
    if gdrive.running and g_done > 10 and gs.get("started_at"):
        try:
            import dateutil.parser  # may not exist
        except Exception:
            pass
        # files per minute from state updates
        eta_note = f"GDrive ~{g_done}/{g_total} — varias horas si sigue activo"

    points = _qdrant_points()

    return {
        "ok": True,
        "agent": "AG-34 KB Ingest Sentinel",
        "overall_pct": round(overall_pct, 1),
        "all_complete": all_done,
        "any_running": any_running,
        "qdrant_points": points,
        "phases": {p.name: p.to_dict() for p in phases},
        "eta_note": eta_note,
        "owner": "AG-34 — reporta por WhatsApp cada 25% vía ralfia-kb-ingest-sentinel.timer",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
