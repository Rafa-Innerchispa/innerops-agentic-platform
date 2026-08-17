"""Seguridad de correo — bloqueo de adjuntos peligrosos antes de procesar.

Política: nunca ejecutar/abrir adjuntos automáticamente. Solo PDF/XML/imagenes
de negocio van a cuarentena revisable; ejecutables y macros se bloquean.
ClamAV opcional si está instalado localmente.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

QUARANTINE_ROOT = Path(
    os.getenv("EMAIL_QUARANTINE_ROOT", "/home/rlopez/data/media/email_quarantine")
)
QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)

SECURITY_COL = "email_security_scans"

# Extensiones nunca permitidas para fetch/guardado automático
BLOCKED_EXTENSIONS = frozenset(
    {
        ".exe", ".bat", ".cmd", ".com", ".scr", ".pif", ".msi", ".msp",
        ".dll", ".sys", ".drv", ".vbs", ".vbe", ".js", ".jse", ".ws", ".wsf",
        ".wsh", ".ps1", ".psm1", ".hta", ".jar", ".reg", ".inf", ".lnk",
        ".iso", ".img", ".dmg", ".app", ".deb", ".rpm", ".apk",
        ".html", ".htm", ".svg", ".xml.exe",  # html/svg pueden llevar XSS
    }
)

# Office con macros — bloquear hasta revisión humana
MACRO_EXTENSIONS = frozenset({".docm", ".xlsm", ".pptm", ".dotm", ".xltm", ".potm"})

# Tipos seguros para extracción documental (facturas, cotizaciones)
SAFE_DOCUMENT_EXTENSIONS = frozenset(
    {".pdf", ".xml", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".csv", ".txt"}
)

# Office sin macros — permitido con precaución
CAUTION_EXTENSIONS = frozenset({".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods"})

DANGEROUS_MIME_PREFIXES = (
    "application/x-msdownload",
    "application/x-msdos-program",
    "application/x-executable",
    "application/x-dosexec",
    "application/vnd.ms-htmlhelp",
    "application/javascript",
    "text/javascript",
    "application/x-sh",
    "application/x-bat",
)

SUSPICION_PATTERNS = (
    re.compile(r"\.(pdf|docx?|xlsx?)\.(exe|scr|bat|cmd|js)\b", re.I),
    re.compile(r"invoice\.(exe|scr|js|vbs)\b", re.I),
    re.compile(r"factura\.(exe|scr|js|vbs)\b", re.I),
    re.compile(r"password.*\.(exe|zip|rar)", re.I),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_filename(name: str) -> str:
    return re.sub(r"[^\w.\- ]", "_", (name or "attachment").strip())[:200]


def _extension(name: str) -> str:
    p = Path(_normalize_filename(name))
    # Doble extensión: archivo.pdf.exe → .exe
    suffixes = [s.lower() for s in p.suffixes if s]
    if len(suffixes) >= 2 and suffixes[-1] in BLOCKED_EXTENSIONS:
        return suffixes[-1]
    return (p.suffix or "").lower()


def _clamav_available() -> bool:
    return bool(shutil.which("clamscan"))


def _scan_with_clamav(path: Path) -> dict[str, Any]:
    if not _clamav_available() or not path.is_file():
        return {"ok": True, "engine": "none", "infected": False}
    try:
        proc = subprocess.run(
            ["clamscan", "--no-summary", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        infected = proc.returncode == 1
        return {
            "ok": True,
            "engine": "clamscan",
            "infected": infected,
            "stdout": (proc.stdout or "")[:500],
            "stderr": (proc.stderr or "")[:200],
        }
    except Exception as exc:
        return {"ok": False, "engine": "clamscan", "error": str(exc)[:180]}


def scan_attachment_metadata(
    *,
    filename: str,
    content_type: str = "",
    size: int | None = None,
    mail_id: str = "",
    from_addr: str = "",
) -> dict[str, Any]:
    """Evalúa adjunto por metadata — sin descargar bytes aún."""
    fname = _normalize_filename(filename)
    ext = _extension(fname)
    mime = (content_type or "").lower().strip()
    blob = f"{fname} {mime} {from_addr}".lower()

    reasons: list[str] = []
    verdict = "allow_safe"
    fetch_allowed = True
    auto_process = False

    for pat in SUSPICION_PATTERNS:
        if pat.search(blob):
            reasons.append(f"suspicion_pattern:{pat.pattern[:40]}")
            verdict = "block"
            fetch_allowed = False
            break

    if ext in BLOCKED_EXTENSIONS:
        reasons.append(f"blocked_extension:{ext}")
        verdict = "block"
        fetch_allowed = False
    elif ext in MACRO_EXTENSIONS:
        reasons.append(f"macro_office:{ext}")
        verdict = "quarantine_manual"
        fetch_allowed = False
    elif ext in CAUTION_EXTENSIONS:
        reasons.append(f"caution_office:{ext}")
        verdict = "quarantine_manual"
        fetch_allowed = True
        auto_process = False
    elif ext in SAFE_DOCUMENT_EXTENSIONS:
        reasons.append(f"safe_document:{ext}")
        verdict = "allow_safe"
        auto_process = ext in {".pdf", ".xml"}
    elif ext and ext not in SAFE_DOCUMENT_EXTENSIONS | CAUTION_EXTENSIONS:
        reasons.append(f"unknown_extension:{ext}")
        verdict = "quarantine_manual"
        fetch_allowed = False

    for prefix in DANGEROUS_MIME_PREFIXES:
        if mime.startswith(prefix):
            reasons.append(f"dangerous_mime:{mime}")
            verdict = "block"
            fetch_allowed = False
            auto_process = False
            break

    if size is not None and size > 25 * 1024 * 1024:
        reasons.append("oversized_attachment")
        verdict = "quarantine_manual" if verdict != "block" else verdict
        auto_process = False

    return {
        "ok": True,
        "filename": fname,
        "extension": ext,
        "content_type": mime,
        "size": size,
        "mail_id": mail_id,
        "verdict": verdict,
        "fetch_allowed": fetch_allowed,
        "auto_process": auto_process and verdict == "allow_safe",
        "reasons": reasons,
        "scanned_at": _now(),
    }


def scan_email_message(doc: dict[str, Any], attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Escaneo completo de un correo + adjuntos (metadata)."""
    mail_id = str(doc.get("mail_id") or "")
    from_addr = str(doc.get("from_addr") or doc.get("from") or "")
    subject = str(doc.get("subject") or "")
    att_list = attachments if attachments is not None else (doc.get("attachments") or [])
    if not isinstance(att_list, list):
        att_list = []

    att_scans = []
    worst = "allow_safe"
    rank = {"allow_safe": 0, "quarantine_manual": 1, "block": 2}
    for att in att_list:
        if not isinstance(att, dict):
            continue
        scan = scan_attachment_metadata(
            filename=str(att.get("filename") or att.get("name") or "attachment"),
            content_type=str(att.get("content_type") or att.get("mime") or ""),
            size=att.get("size"),
            mail_id=mail_id,
            from_addr=from_addr,
        )
        att_scans.append(scan)
        if rank.get(scan["verdict"], 0) > rank.get(worst, 0):
            worst = scan["verdict"]

    # Señales en asunto/cuerpo sin adjunto
    blob = f"{subject} {doc.get('body_text') or ''}".lower()
    phishing_hits = []
    if re.search(r"click (?:here|below).*password|verify your account.*urgent", blob, re.I):
        phishing_hits.append("phishing_urgent")
    if re.search(r"\.exe\b|download.*attachment.*password", blob, re.I):
        phishing_hits.append("executable_mention")

    if phishing_hits and worst == "allow_safe":
        worst = "quarantine_manual"

    record = {
        "mail_id": mail_id,
        "from_addr": from_addr,
        "subject": subject[:240],
        "attachment_count": len(att_scans),
        "verdict": worst,
        "fetch_attachments": worst != "block" and all(s.get("fetch_allowed") for s in att_scans),
        "auto_process_documents": worst == "allow_safe" and any(s.get("auto_process") for s in att_scans),
        "attachment_scans": att_scans,
        "phishing_hits": phishing_hits,
        "clamav_available": _clamav_available(),
        "scanned_at": _now(),
    }

    if mail_id:
        mongo_store.get_db()[SECURITY_COL].update_one(
            {"mail_id": mail_id},
            {"$set": record},
            upsert=True,
        )
    return record


def scan_file_bytes(path: Path, *, mail_id: str = "", filename: str = "") -> dict[str, Any]:
    """Escaneo post-descarga — ClamAV si disponible."""
    meta = scan_attachment_metadata(filename=filename or path.name, size=path.stat().st_size if path.is_file() else 0, mail_id=mail_id)
    if meta["verdict"] == "block":
        return {**meta, "file_scan": {"skipped": True, "reason": "blocked_by_policy"}}
    clam = _scan_with_clamav(path)
    if clam.get("infected"):
        meta["verdict"] = "block"
        meta["reasons"] = list(meta.get("reasons") or []) + ["clamav_infected"]
        meta["fetch_allowed"] = False
        meta["auto_process"] = False
    return {**meta, "file_scan": clam}


def quarantine_path(mail_id: str, filename: str) -> Path:
    safe_name = _normalize_filename(filename)
    dest = QUARANTINE_ROOT / mail_id / safe_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def get_security_status() -> dict[str, Any]:
    db = mongo_store.get_db()
    blocked = db[SECURITY_COL].count_documents({"verdict": "block"})
    quarantine = db[SECURITY_COL].count_documents({"verdict": "quarantine_manual"})
    return {
        "ok": True,
        "clamav_available": _clamav_available(),
        "quarantine_root": str(QUARANTINE_ROOT),
        "blocked_count": blocked,
        "quarantine_count": quarantine,
        "policy": {
            "auto_execute_attachments": False,
            "macro_office": "block_until_human_review",
            "safe_for_invoice_extract": sorted(SAFE_DOCUMENT_EXTENSIONS),
        },
    }
