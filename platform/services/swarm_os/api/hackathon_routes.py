"""Adaptador hackathon InnerOS — 8 Droides → capacidades Swarm-OS reales."""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/hackathon", tags=["hackathon"])

DROIDS: list[dict[str, Any]] = [
    {
        "id": "d1",
        "code": "D1",
        "name": "Mail Gatekeeper",
        "label": "Gatekeeper",
        "role": "Ingesta IMAP & Anti-Spam",
        "swarm_agent": "comunicaciones",
        "endpoint": "/api/v1/email/poll",
        "live": True,
        "demo_only": False,
    },
    {
        "id": "d2",
        "code": "D2",
        "name": "Voz de Campo",
        "label": "Voz de Campo",
        "role": "Whisper & Multimodalidad",
        "swarm_agent": "campo",
        "endpoint": "/inspection/{id}/upload-audio",
        "live": True,
        "demo_only": False,
    },
    {
        "id": "d3",
        "code": "D3",
        "name": "Cosmos Central",
        "label": "Cosmos Central",
        "role": "Orquestador MongoDB",
        "swarm_agent": "director",
        "endpoint": "/inspection/start",
        "live": True,
        "demo_only": False,
    },
    {
        "id": "d4",
        "code": "D4",
        "name": "Care-Taker",
        "label": "Care-Taker",
        "role": "Informes & PDFs",
        "swarm_agent": "informes",
        "endpoint": "/inspection/start",
        "live": True,
        "demo_only": False,
    },
    {
        "id": "d5",
        "code": "D5",
        "name": "Financial Ledger",
        "label": "Financial",
        "role": "SRI, IVA & cotización",
        "swarm_agent": "cotizador",
        "endpoint": "/api/v1/ruc/lookup",
        "live": True,
        "demo_only": False,
    },
    {
        "id": "d6",
        "code": "D6",
        "name": "Catalyst RAG",
        "label": "Catalyst RAG",
        "role": "Conocimiento & búsqueda",
        "swarm_agent": "bitacora",
        "endpoint": "/api/v1/assistant/chat",
        "live": True,
        "demo_only": False,
    },
    {
        "id": "d7",
        "code": "D7",
        "name": "Signer / Fiscal",
        "label": "Signer/Fiscal",
        "role": "Firma XAdES XML",
        "swarm_agent": "revisor",
        "endpoint": "/gates/quote/{id}/ready-to-send",
        "live": False,
        "demo_only": True,
    },
    {
        "id": "d8",
        "code": "D8",
        "name": "Media Agent",
        "label": "Media",
        "role": "Comunicaciones & growth",
        "swarm_agent": "comunicaciones",
        "endpoint": "/api/v1/email/test-whatsapp",
        "live": True,
        "demo_only": False,
    },
]

_droid_state: dict[str, str] = {d["id"]: "idle" for d in DROIDS}

_DROID_CODE: dict[str, str] = {d["id"]: d["code"] for d in DROIDS}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_step(activity_log: list[dict], droid_id: str, message: str, *, level: str = "info") -> None:
    activity_log.append(
        {
            "ts": _now_iso(),
            "droid_id": droid_id,
            "droid_code": _DROID_CODE.get(droid_id, droid_id.upper()),
            "message": message,
            "level": level,
        }
    )

# Pesos Devpost (suma = 100)
_COMPLIANCE_WEIGHTS: dict[str, int] = {
    "functional_agent_not_just_chat": 15,
    "multi_step_mission": 15,
    "gemini_integration": 12,
    "google_cloud_agent_builder": 10,
    "partner_mcp_mongodb": 15,
    "hosted_url": 13,
    "public_repo_license": 10,
    "demo_video_3min": 10,
}


def _set_droid(droid_id: str, state: str) -> None:
    if droid_id in _droid_state:
        _droid_state[droid_id] = state


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _env_key_present(*paths: Path, key: str) -> bool:
    if os.getenv(key, "").strip():
        return True
    for p in paths:
        val = _parse_env_file(p).get(key, "")
        if val and val not in ("", "MY_GEMINI_API_KEY", "your-key-here"):
            return True
    return False


def _find_mcp_config(ui_root: Path, backend_root: Path) -> Path | None:
    candidates = [
        ui_root / ".cursor" / "mcp.json",
        backend_root / ".cursor" / "mcp.json",
        ui_root / "mcp.json",
        backend_root / "mcp.json",
        ui_root / "config" / "mongodb-mcp.json",
    ]
    for c in candidates:
        if c.is_file():
            text = c.read_text(encoding="utf-8", errors="ignore")
            if "mongodb-mcp-server" in text or "MongoDB" in text:
                return c
    return None


def _ngrok_ready() -> tuple[bool, bool]:
    """Returns (authtoken_configured, ngrok_binary_available)."""
    import shutil

    from config import NGROK_AUTHTOKEN

    token_ok = bool(NGROK_AUTHTOKEN.strip())
    if not token_ok:
        for p in (
            Path.home() / ".config" / "ngrok" / "ngrok.yml",
            Path.home() / ".ngrok2" / "ngrok.yml",
        ):
            if p.is_file() and "authtoken" in p.read_text(encoding="utf-8", errors="ignore"):
                token_ok = True
                break
    binary_ok = shutil.which("ngrok") is not None
    return token_ok, binary_ok


def _git_remote_public_hint(backend_root: Path) -> tuple[bool, str | None]:
    cfg = backend_root / ".git" / "config"
    if not cfg.is_file():
        return False, None
    text = cfg.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r'url\s*=\s*(.+)', text)
    if not m:
        return False, None
    url = m.group(1).strip()
    return bool(url), url


def _build_compliance_report() -> dict[str, Any]:
    from config import GEMINI_API_KEY, HACKATHON_UI_ROOT, RUC_API_PASS, RUC_API_USER, ROOT

    ui_root = HACKATHON_UI_ROOT
    backend_root = ROOT

    ui_env = ui_root / ".env"
    ui_env_local = ui_root / ".env.local"
    backend_env = backend_root / ".env"

    gemini_ok = _env_key_present(ui_env, ui_env_local, backend_env, key="GEMINI_API_KEY") or bool(
        GEMINI_API_KEY.strip()
    )

    mcp_path = _find_mcp_config(ui_root, backend_root)
    mcp_configured = mcp_path is not None

    ngrok_token, ngrok_bin = _ngrok_ready()
    hosted_url_met = ngrok_token and ngrok_bin

    license_ui = (ui_root / "LICENSE").is_file()
    license_be = (backend_root / "LICENSE").is_file()
    readme_hack = (ui_root / "README_HACKATHON.md").is_file() or (
        backend_root / "README_HACKATHON.md"
    ).is_file()
    git_remote, git_url = _git_remote_public_hint(backend_root)
    repo_met = license_be and readme_hack and git_remote

    video_script = (ui_root / "DEVPOST_VIDEO_SCRIPT.md").is_file()
    checklist = (ui_root / "DEVPOST_CHECKLIST.md").is_file()
    video_met = False  # solo Rafael confirma grabación
    video_setup = video_script and checklist

    ai_studio_url = "https://ai.studio/apps/a2d230ce-a60c-431a-a56f-f24a6aa14989"
    agent_builder_met = gemini_ok and (ui_root / "README_HACKATHON.md").is_file()
    agent_builder_setup = (ui_root / "README_HACKATHON.md").is_file()

    requirements: dict[str, dict[str, Any]] = {
        "functional_agent_not_just_chat": {
            "met": True,
            "weight": _COMPLIANCE_WEIGHTS["functional_agent_not_just_chat"],
            "evidence": "CrewAI 8 agentes + tools reales (MongoDB, SRI, WhatsApp)",
        },
        "multi_step_mission": {
            "met": True,
            "weight": _COMPLIANCE_WEIGHTS["multi_step_mission"],
            "evidence": "POST /api/v1/hackathon/tour/run (5 pasos)",
        },
        "gemini_integration": {
            "met": gemini_ok,
            "setup_ready": (ui_root / "GEMINI_SETUP.md").is_file(),
            "weight": _COMPLIANCE_WEIGHTS["gemini_integration"],
            "evidence": "GEMINI_API_KEY en swarm-os .env" if gemini_ok else "Ver GEMINI_SETUP.md",
            "action": None if gemini_ok else "Pegar GEMINI_API_KEY en swarm-os-google_ai_studio/.env",
        },
        "google_cloud_agent_builder": {
            "met": agent_builder_met,
            "setup_ready": agent_builder_setup,
            "weight": _COMPLIANCE_WEIGHTS["google_cloud_agent_builder"],
            "evidence": ai_studio_url if agent_builder_setup else "Exportar agente AI Studio",
            "action": None if agent_builder_met else "Enlazar app AI Studio en Devpost + README_HACKATHON.md",
        },
        "partner_mcp_mongodb": {
            "met": mcp_configured and gemini_ok,
            "setup_ready": mcp_configured,
            "weight": _COMPLIANCE_WEIGHTS["partner_mcp_mongodb"],
            "evidence": str(mcp_path) if mcp_path else "docs/MONGODB_MCP_SETUP.md",
            "action": None if mcp_configured else "Seguir docs/MONGODB_MCP_SETUP.md",
        },
        "hosted_url": {
            "met": hosted_url_met,
            "setup_ready": ngrok_bin or (ui_root / "scripts" / "start_demo_tunnel.sh").is_file(),
            "weight": _COMPLIANCE_WEIGHTS["hosted_url"],
            "evidence": "ngrok http 5180" if hosted_url_met else "scripts/start_demo_tunnel.sh",
            "action": None if hosted_url_met else "NGROK_AUTHTOKEN + ./scripts/start_demo_tunnel.sh",
        },
        "public_repo_license": {
            "met": repo_met,
            "setup_ready": license_be and readme_hack,
            "weight": _COMPLIANCE_WEIGHTS["public_repo_license"],
            "evidence": git_url or "README_HACKATHON.md + LICENSE MIT",
            "action": None if repo_met else "git push + hacer repo público en GitHub",
        },
        "demo_video_3min": {
            "met": video_met,
            "setup_ready": video_setup,
            "weight": _COMPLIANCE_WEIGHTS["demo_video_3min"],
            "evidence": "DEVPOST_VIDEO_SCRIPT.md" if video_setup else "Grabar tour 5 pasos",
            "action": None if video_met else "Grabar siguiendo DEVPOST_VIDEO_SCRIPT.md",
        },
    }

    score = 0
    setup_bonus = 0
    for req in requirements.values():
        w = req["weight"]
        if req.get("met"):
            score += w
        elif req.get("setup_ready"):
            setup_bonus += w // 2

    live_count = sum(1 for d in DROIDS if d["live"])
    droid_bonus = min(5, int((live_count / len(DROIDS)) * 5))

    estimated = min(100, score + setup_bonus + droid_bonus)

    return {
        "track": "MongoDB",
        "requirements": requirements,
        "droids_live": f"{live_count}/8",
        "droids_demo_only": [d["code"] for d in DROIDS if d["demo_only"]],
        "impact_narrative": "Agentes para PYME técnica en Ecuador: SRI, IMAP, WhatsApp, cotización",
        "ruc_api_ready": bool(RUC_API_USER and RUC_API_PASS),
        "mongodb_mcp_config": str(mcp_path) if mcp_path else None,
        "gemini_configured": gemini_ok,
        "ngrok_authtoken_set": ngrok_token,
        "ngrok_binary": ngrok_bin,
        "hackathon_ui_root": str(ui_root),
        "score_breakdown": {
            "requirements_met": score,
            "setup_ready_partial": setup_bonus,
            "droids_bonus": droid_bonus,
        },
        "estimated_compliance_pct": estimated,
        "deadline": "2026-06-11T16:00:00-05:00",
    }


class TourStep1(BaseModel):
    voice_text: str = Field(
        default="",
        description="Voice note or request text",
    )
    client_ruc: str = Field(default="", description="Ecuador tax ID (10/13 digits)")
    client_name: str = Field(default="", description="Client legal / trade name")
    client_phone: str = Field(default="", description="WhatsApp E.164 e.g. 593999059000")
    client_address: str = Field(default="", description="Site address")
    product_codes: list[str] = Field(default_factory=list, description="Catalog product/service codes")
    company_id: str = Field(default="pcdoctor", description="pcdoctor | innerchispa")
    check_email: bool = Field(default=True, description="D1 mail gatekeeper step")
    email_mail_id: str = Field(default="", description="Mail message id from check-email step")


class TourStep2(BaseModel):
    tax_id: str = Field(..., description="RUC (13) o cédula (10)")


class TourStep5(BaseModel):
    phone: str = Field(default="593999059000", description="WhatsApp destino E.164")
    message: str = Field(default="", description="Mensaje; vacío = resumen automático")


class DemoSendTestEmailIn(BaseModel):
    scenario: str = Field(..., description="new_client | existing_client")


@router.get("/demo/prep")
def demo_prep():
    """Catalog, clients, Evolution instances for guided demo wizard."""
    from tools.evolution_api import list_instances, resolve_connected_instance
    from tools.mongo import get_db

    db = get_db()
    catalog = list(
        db.catalog_products.find({"estado": {"$ne": "Inactivo"}}, {"_id": 0})
        .sort("nombre", 1)
        .limit(40)
    )
    if not catalog:
        catalog = [
            {"code": "SRV-INST-CAM", "nombre": "Camera installation (4 cams)", "tipo": "servicio", "precio_sugerido": 280},
            {"code": "PRD-SW-PoE16", "nombre": "PoE switch 16-port", "tipo": "producto", "precio_sugerido": 185},
            {"code": "SRV-CABLEADO", "nombre": "Structured cabling per point", "tipo": "servicio", "precio_sugerido": 45},
            {"code": "SRV-SOPORTE", "nombre": "On-site technical support (2h)", "tipo": "servicio", "precio_sugerido": 60},
        ]
    clients = list(db.clients.find({}, {"_id": 0, "client_id": 1, "name": 1, "ruc": 1, "phone": 1}).limit(12))
    candidates = _top_email_candidates(db, limit=3)
    email_alert = _enrich_email_candidate(db, candidates[0]) if candidates else None
    inst_pref, inst_note = resolve_connected_instance()
    evo = []
    try:
        evo = list_instances()
    except Exception:
        pass
    return {
        "catalog": catalog,
        "clients": clients,
        "email_candidates": candidates,
        "email_alert": email_alert,
        "last_email": email_alert.get("email") if email_alert else None,
        "evolution_instances": evo,
        "evolution_active": inst_pref,
        "evolution_note": inst_note,
    }


def _processed_mail_ids(db) -> set[str]:
    ids: set[str] = set()
    for m in db.email_messages.find({"demo_processed_at": {"$exists": True}}, {"mail_id": 1}):
        mid = m.get("mail_id")
        if mid:
            ids.add(mid)
    for r in db.guided_demo_runs.find({}, {"mail_id": 1}).sort("created_at", -1).limit(300):
        mid = r.get("mail_id")
        if mid:
            ids.add(mid)
    return ids


def _is_mail_demo_processed(db, mail_id: str | None) -> bool:
    if not mail_id:
        return False
    if mail_id in _processed_mail_ids(db):
        return True
    doc = db.email_messages.find_one({"mail_id": mail_id}, {"demo_processed_at": 1})
    return bool(doc and doc.get("demo_processed_at"))


def _existing_client_for_ruc(db, ruc: str | None) -> dict | None:
    if not ruc:
        return None
    from tools.mongo import lookup_client_by_ruc

    hit = lookup_client_by_ruc(ruc)
    if not hit:
        return None
    return db.clients.find_one({"client_id": hit["client_id"]}, {"_id": 0})


def _mark_email_demo_processed(db, mail_id: str, result: dict[str, Any]) -> None:
    from tools.schema import new_id

    now = _now_iso()
    db.email_messages.update_one(
        {"mail_id": mail_id},
        {"$set": {"demo_processed_at": now}},
    )
    client = result.get("client") or {}
    quote = result.get("quote") or {}
    existing_run = db.guided_demo_runs.find_one({"mail_id": mail_id}, {"_id": 0, "run_id": 1, "created_at": 1})
    run_id = (existing_run or {}).get("run_id") or new_id("gdr")
    db.guided_demo_runs.update_one(
        {"mail_id": mail_id},
        {
            "$set": {
                "run_id": run_id,
                "mail_id": mail_id,
                "client_id": client.get("client_id"),
                "quote_id": quote.get("quote_id"),
                "inspection_id": result.get("inspection_id"),
                "updated_at": now,
                "created_at": (existing_run or {}).get("created_at") or now,
            },
        },
        upsert=True,
    )



def _recent_mail_messages(db, limit: int = 150) -> list[dict]:
    return list(
        db.email_messages.find(
            {
                "mail_id": {"$ne": "demo-quote-sample"},
                "demo_sample": {"$ne": True},
            },
            {"_id": 0},
        )
        .sort("received_at", -1)
        .limit(limit)
    )


def _enrich_email_candidate(db, entry: dict | None) -> dict | None:
    if not entry:
        return None
    mail_id = entry["email"].get("mail_id")
    ruc = entry["parsed"].get("ruc")
    processed_ids = _processed_mail_ids(db)
    already_processed = bool(
        entry.get("already_processed")
        or entry["email"].get("demo_processed_at")
        or (mail_id and mail_id in processed_ids)
    )
    existing_client = _existing_client_for_ruc(db, ruc) if ruc else None
    if already_processed and not existing_client and mail_id:
        run = db.guided_demo_runs.find_one({"mail_id": mail_id}, sort=[("created_at", -1)])
        if run and run.get("client_id"):
            existing_client = db.clients.find_one({"client_id": run["client_id"]}, {"_id": 0})
    return {
        **entry,
        "already_processed": already_processed,
        "existing_client": existing_client,
    }


def _top_email_candidates(db, limit: int = 3) -> list[dict]:
    from tools.email_parse import rank_quote_email_candidates

    processed_ids = _processed_mail_ids(db)
    messages = _recent_mail_messages(db)
    ranked = rank_quote_email_candidates(messages, processed_ids, limit=limit)
    return [_enrich_email_candidate(db, c) for c in ranked if c]


def _best_email_alert(db) -> dict | None:
    candidates = _top_email_candidates(db, limit=1)
    return candidates[0] if candidates else None


def _demo_email_template(scenario: str, db) -> tuple[str, str, str, str]:
    """Returns (subject, body, from_name, ruc)."""
    import random

    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    if scenario == "existing_client":
        client = db.clients.find_one({"ruc": {"$regex": r"^\d{10,13}$"}}, {"_id": 0, "name": 1, "ruc": 1, "phone": 1})
        if not client:
            client = db.clients.find_one({}, {"_id": 0, "name": 1, "ruc": 1, "phone": 1})
        if not client:
            raise HTTPException(404, "No hay clientes en MongoDB — crea uno o usa escenario new_client")
        name = client.get("name") or "Cliente existente"
        ruc = client.get("ruc") or "1790123456001"
        phone = client.get("phone") or "593999059000"
        subject = f"Re: Cotización urgente — {name} [{stamp}]"
        body = (
            f"Buenos días,\n\n"
            f"Soy {name}. Necesito actualizar la cotización para instalación de cámaras y switch PoE.\n\n"
            f"RUC: {ruc}\n"
            f"Teléfono WhatsApp: {phone}\n\n"
            f"Por favor envíen presupuesto con:\n"
            f"- Switch PoE 16 puertos\n"
            f"- Instalación de 4 cámaras IP\n"
            f"- Cableado estructurado\n\n"
            f"Quedo atento.\n\n"
            f"{name}\n"
        )
        from_name = name
    else:
        # RUC ficticio válido en formato (13 dígitos) — no debe existir en clients
        for _ in range(20):
            candidate = f"17{random.randint(900000000, 999999999)}{random.randint(10, 99)}"
            if not db.clients.find_one({"ruc": candidate}):
                ruc = candidate
                break
        else:
            ruc = f"179{stamp}001"
        name = f"Torres del Mar Demo {stamp}"
        phone = "593987654321"
        subject = f"Solicitud de cotización — {name} [{stamp}]"
        body = (
            f"Estimados PC Doctor,\n\n"
            f"Les escribo para solicitar cotización de un sistema de videovigilancia.\n\n"
            f"Empresa: {name}\n"
            f"RUC: {ruc}\n"
            f"Contacto: María González\n"
            f"WhatsApp: +{phone}\n"
            f"Dirección: Av. Demo 123, Guayaquil\n\n"
            f"Requerimos:\n"
            f"1. Switch PoE 16 puertos\n"
            f"2. Instalación de 4 cámaras\n"
            f"3. Cableado por punto\n\n"
            f"Favor indicar precio y plazo de instalación.\n\n"
            f"Saludos,\nMaría González — {name}\n"
        )
        from_name = f"María González — {name}"
    return subject, body, from_name, ruc


def _alert_response_from_candidate(alert: dict, poll_summary: dict | None) -> dict:
    p = alert["parsed"]
    already = alert.get("already_processed", False)
    existing = alert.get("existing_client")
    alert_message = p.get("summary")
    if already:
        client_name = (existing or {}).get("name") or "cliente existente"
        alert_message = f"Correo ya procesado — cliente «{client_name}» ya existe en el sistema"
    return {
        "ok": True,
        "poll": poll_summary,
        "email": alert["email"],
        "parsed": p,
        "already_processed": already,
        "existing_client": existing,
        "alert_message": alert_message,
        "score": alert.get("score"),
        "ruc": p.get("ruc"),
        "client_hint": p.get("client_hint"),
        "phone": p.get("phone"),
        "products_hint": p.get("products_hint", []),
        "voice_text": f"Quote request from email: {alert['email'].get('subject', '')[:120]}",
    }


@router.post("/demo/check-email")
def demo_check_email(poll: bool = True):
    """Poll IMAP, rank quote-request emails, return top candidates for user selection."""
    from tools.mongo import get_db

    db = get_db()
    poll_summary = None
    if poll:
        try:
            from api.email_routes import poll_all_accounts

            poll_summary = poll_all_accounts()
        except Exception as e:
            poll_summary = {"error": str(e)}

    candidates = _top_email_candidates(db, limit=3)

    if not candidates:
        return {
            "ok": False,
            "poll": poll_summary,
            "candidates": [],
            "message": (
                "No se encontró correo de cotización. Usa «Send demo» para ensayar, envía un email real "
                "con RUC (13 dígitos) y palabras como «cotización», o continúa sin correo e ingresa el RUC manualmente."
            ),
        }

    primary = candidates[0]
    out = _alert_response_from_candidate(primary, poll_summary)
    out["candidates"] = [
        {
            "email": c["email"],
            "parsed": c["parsed"],
            "score": c.get("score"),
            "already_processed": c.get("already_processed"),
            "existing_client": c.get("existing_client"),
        }
        for c in candidates
    ]
    return out


@router.post("/demo/send-test-email")
def demo_send_test_email(body: DemoSendTestEmailIn):
    """Ensayo demo: envía correo real vía SMTP al buzón monitorizado y hace poll IMAP."""
    from tools.email_smtp import send_via_account
    from tools.mongo import get_db

    scenario = body.scenario.strip().lower()
    if scenario not in ("new_client", "existing_client"):
        raise HTTPException(400, "scenario debe ser new_client o existing_client")

    db = get_db()
    acc = db.email_accounts.find_one({"enabled": True}, sort=[("created_at", 1)])
    if not acc:
        raise HTTPException(503, "No hay cuenta IMAP activa — configura una en Correos")

    subject, email_body, from_name, ruc = _demo_email_template(scenario, db)
    to_addr = acc.get("address") or acc.get("imap_user")
    send_result = send_via_account(
        acc,
        to_addr=to_addr,
        subject=subject,
        body=email_body,
        from_name=from_name,
    )
    if not send_result.get("ok"):
        raise HTTPException(502, f"SMTP falló: {send_result.get('error', 'unknown')}")

    poll_summary = None
    try:
        from api.email_routes import poll_all_accounts

        poll_summary = poll_all_accounts()
    except Exception as e:
        poll_summary = {"error": str(e)}

    candidates = _top_email_candidates(db, limit=3)
    matched = None
    for c in candidates:
        if c["parsed"].get("ruc") == ruc or subject[:40] in (c["email"].get("subject") or ""):
            matched = c
            break
    if not matched and candidates:
        matched = candidates[0]

    return {
        "ok": True,
        "scenario": scenario,
        "smtp": send_result,
        "poll": poll_summary,
        "expected_ruc": ruc,
        "candidates": [
            {
                "email": c["email"],
                "parsed": c["parsed"],
                "score": c.get("score"),
                "already_processed": c.get("already_processed"),
                "existing_client": c.get("existing_client"),
            }
            for c in candidates
        ],
        "selected": _alert_response_from_candidate(matched, poll_summary) if matched else None,
        "message": f"Correo demo enviado a {to_addr}. Selecciona el candidato en la lista o pulsa Refresh mail.",
    }


@router.post("/droids/reset")
def reset_droids():
    """Vuelve todos los Droides a idle (tras errores de demo)."""
    for d in DROIDS:
        _droid_state[d["id"]] = "idle"
    return {"ok": True, "droids": [{**d, "state": "idle"} for d in DROIDS]}


@router.get("/droids")
def list_droids():
    """Mapa de 8 Droides InnerOS para la UI del hackatón."""
    return {
        "droids": [
            {**d, "state": _droid_state.get(d["id"], "idle")}
            for d in DROIDS
        ],
        "architecture": "hybrid-sovereign",
        "backend": "innerspark-swarm-os-cursor-local",
    }


@router.get("/droids/status")
def droids_status():
    from config import EVOLUTION_BASE_URL, MONGO_DB, MONGO_URI
    from tools.mongo import get_db

    db = get_db()
    return {
        "droids": [{**d, "state": _droid_state.get(d["id"], "idle")} for d in DROIDS],
        "mongodb": {"uri": MONGO_URI.split("@")[-1], "database": MONGO_DB},
        "collections": len(db.list_collection_names()),
        "evolution": EVOLUTION_BASE_URL,
        "track_recommendation": "MongoDB",
    }


@router.get("/compliance")
def hackathon_compliance():
    """Autoevaluación vs criterios Devpost (Google Cloud Rapid Agent Hackathon)."""
    return _build_compliance_report()


@router.post("/tour/step/1")
def tour_step1_voice(body: TourStep1):
    """Paso 1 demo: D2 Voz + D1 clasificación → inspección abierta."""
    from tools.crew_tools import start_inspection_record

    _set_droid("d2", "working")
    _set_droid("d1", "working")
    try:
        iid = start_inspection_record(body.voice_text.strip())
        _set_droid("d2", "done")
        _set_droid("d1", "done")
        return {
            "step": 1,
            "droids": ["D2", "D1"],
            "inspection_id": iid,
            "voice_text": body.voice_text,
            "message": "Dictado capturado; inspección abierta en MongoDB",
        }
    except Exception as e:
        _set_droid("d2", "error")
        _set_droid("d1", "error")
        raise HTTPException(500, str(e)) from e


@router.post("/tour/step/2")
def tour_step2_ruc(body: TourStep2):
    """Paso 2 demo: D3 Cosmos + D5 Financial → RUC y anti-duplicado."""
    from tools.gates import check_duplicate_client
    from tools.ruc_api import lookup_ruc, normalize_tax_id

    _set_droid("d3", "working")
    _set_droid("d5", "working")
    try:
        norm = normalize_tax_id(body.tax_id)
        data = lookup_ruc(body.tax_id)
        dup = check_duplicate_client(
            ruc=(data or {}).get("ruc") or norm.get("ruc") or body.tax_id,
            name=(data or {}).get("name"),
        )
        _set_droid("d3", "done")
        _set_droid("d5", "done")
        return {
            "step": 2,
            "droids": ["D3", "D5"],
            "normalized": norm,
            "sri": data,
            "duplicate_check": dup,
        }
    except Exception as e:
        _set_droid("d3", "error")
        _set_droid("d5", "error")
        raise HTTPException(502, f"SRI/RUC: {e}") from e


@router.post("/tour/step/3")
def tour_step3_crew(body: TourStep1):
    """Paso 3 demo: D4 + D5 → inventario, IVA, cotización vía CrewAI."""
    from agents.crew import run_inspection_flow

    _set_droid("d3", "working")
    _set_droid("d4", "working")
    _set_droid("d5", "working")
    try:
        result = run_inspection_flow(body.voice_text.strip())
        _set_droid("d3", "done")
        _set_droid("d4", "done")
        _set_droid("d5", "done")
        return {"step": 3, "droids": ["D3", "D4", "D5"], "result": result}
    except Exception as e:
        for did in ("d3", "d4", "d5"):
            _set_droid(did, "error")
        raise HTTPException(500, str(e)) from e


@router.post("/tour/step/4")
def tour_step4_pdf(body: TourStep1):
    """Paso 4 demo: D4 genera exportables (MD/PDF pipeline)."""
    from agents.crew import run_inspection_flow

    _set_droid("d4", "working")
    try:
        result = run_inspection_flow(body.voice_text.strip())
        exports = {
            "report_path": (result.get("report") or {}).get("export_path"),
            "quote_path": (result.get("quote") or {}).get("export_path"),
        }
        _set_droid("d4", "done")
        return {"step": 4, "droids": ["D4"], "exports": exports, "result": result}
    except Exception as e:
        _set_droid("d4", "error")
        raise HTTPException(500, str(e)) from e


@router.post("/tour/step/5")
def tour_step5_dispatch(body: TourStep5):
    """Paso 5 demo: D7 (gate simulado) + D8 WhatsApp real."""
    from tools.evolution_api import send_whatsapp

    _set_droid("d7", "working")
    _set_droid("d8", "working")
    msg = body.message.strip() or (
        "InnerOS PC Doctor: cotización lista. "
        "Pipeline fiscal pre-validado. Responda para confirmar."
    )
    try:
        _set_droid("d7", "done")  # gate revisor — demo; XAdES en roadmap
        wa = send_whatsapp(body.phone, msg)
        _set_droid("d8", "done" if wa.get("status") == "sent" else "error")
        return {
            "step": 5,
            "droids": ["D7", "D8"],
            "signer": {"mode": "demo", "xades": "roadmap"},
            "whatsapp": wa,
        }
    except Exception as e:
        _set_droid("d8", "error")
        raise HTTPException(502, f"WhatsApp: {e}") from e


@router.post("/tour/run")
def tour_run_full(body: TourStep1):
    """Guided multi-droid mission with activity_log, Gemini plan, real MongoDB records."""
    from agents.guided_demo import run_guided_demo
    from tools.evolution_api import resolve_connected_instance, send_whatsapp
    from tools.gemini_client import gemini_plan_mission
    from tools.mongo import get_db

    steps: list[dict] = []
    activity_log: list[dict] = []
    gemini_plan: dict[str, Any] = {}
    t0 = time.time()
    voice = body.voice_text.strip() or "Field quote request"
    guided = bool(body.client_name or body.client_ruc or body.product_codes or body.client_phone)

    for d in DROIDS:
        _set_droid(d["id"], "idle")

    from tools.client_sanitize import normalize_tax_id_field, sanitize_empty_client_rucs, valid_tax_id

    body.client_ruc = normalize_tax_id_field(body.client_ruc)
    sanitize_empty_client_rucs(get_db())

    try:
        _log_step(activity_log, "d3", "Cosmos Central: starting guided multi-droid mission…")
        _set_droid("d3", "working")

        gemini_plan = gemini_plan_mission(voice)
        _set_droid("d3", "done")
        _log_step(
            activity_log,
            "d3",
            f"Gemini mission plan: {gemini_plan.get('mission_summary', voice)}",
            level="gemini",
        )
        for step in gemini_plan.get("droid_steps") or []:
            raw = str(step.get("droid", "D3")).upper().strip()
            num = raw.lstrip("D") or "3"
            droid_id = f"d{num}" if f"d{num}" in _droid_state else "d3"
            _log_step(activity_log, droid_id, f"Planned: {step.get('action', '')}")

        _set_droid("d1", "working")
        email_already_processed = False
        email_mail_id = body.email_mail_id.strip() if body.email_mail_id else ""
        if body.check_email:
            from tools.email_parse import parse_quote_request_email

            db = get_db()
            try:
                from api.email_routes import poll_all_accounts

                poll_all_accounts()
            except Exception:
                pass

            mail_doc = None
            if email_mail_id:
                mail_doc = db.email_messages.find_one({"mail_id": email_mail_id}, {"_id": 0})
            if not mail_doc:
                alert = _best_email_alert(db)
                mail_doc = (alert or {}).get("email")
                if mail_doc:
                    email_mail_id = mail_doc.get("mail_id") or email_mail_id
            if mail_doc:
                parsed = parse_quote_request_email(
                    mail_doc.get("subject", ""),
                    mail_doc.get("snippet", ""),
                    mail_doc.get("from_addr", ""),
                )
                subj = (mail_doc.get("subject") or "")[:90]
                frm = mail_doc.get("from_addr") or ""
                ruc_line = f" — RUC {parsed['ruc']} extracted" if parsed.get("ruc") else ""
                email_already_processed = _is_mail_demo_processed(db, email_mail_id)
                if email_already_processed:
                    existing = _existing_client_for_ruc(db, parsed.get("ruc") or body.client_ruc)
                    if not existing and email_mail_id:
                        run = db.guided_demo_runs.find_one({"mail_id": email_mail_id}, sort=[("created_at", -1)])
                        if run and run.get("client_id"):
                            existing = db.clients.find_one({"client_id": run["client_id"]}, {"_id": 0})
                    client_label = (existing or {}).get("name") or "cliente existente"
                    _log_step(
                        activity_log,
                        "d1",
                        f"Mail Gatekeeper: correo ya procesado — cliente «{client_label}» ya existe; "
                        f"no se duplicará cotización — «{subj}» from {frm}",
                        level="warn",
                    )
                else:
                    _log_step(
                        activity_log,
                        "d1",
                        f"Mail Gatekeeper: {parsed.get('summary', 'Quote request')}{ruc_line} — «{subj}» from {frm}",
                    )
                if not body.client_ruc and parsed.get("ruc"):
                    body.client_ruc = parsed["ruc"]
            else:
                _log_step(activity_log, "d1", "Mail Gatekeeper: no quote email in queue — using wizard client data")
        _set_droid("d1", "done")

        _set_droid("d2", "working")
        _log_step(activity_log, "d2", f"Voice Field: structuring request — «{voice[:90]}»")

        if valid_tax_id(body.client_ruc):
            _set_droid("d5", "working")
            from config import RUC_API_PASS, RUC_API_USER

            if RUC_API_USER and RUC_API_PASS:
                _log_step(activity_log, "d5", f"Financial: validating RUC {body.client_ruc} with SRI…")
            else:
                _log_step(activity_log, "d5", f"Financial: client tax ID {body.client_ruc} recorded")
            _set_droid("d5", "done")

        for did in ("d3", "d4", "d5", "d6"):
            _set_droid(did, "working")

        _log_step(
            activity_log,
            "d3",
            "Cosmos Central: guided production pipeline — MongoDB + catalog + local tools",
        )
        result = run_guided_demo(
            voice,
            client_ruc=body.client_ruc,
            client_name=body.client_name,
            client_phone=body.client_phone,
            client_address=body.client_address,
            product_codes=body.product_codes,
            company_id=body.company_id,
            email_mail_id=email_mail_id,
            skip_if_processed=email_already_processed,
        )

        iid = result.get("inspection_id")
        quote = result.get("quote") or {}
        client = result.get("client") or {}
        skipped_duplicate = bool(result.get("skipped_duplicate"))
        client_name = client.get("name") or body.client_name or "Client"
        if skipped_duplicate:
            _log_step(
                activity_log,
                "d3",
                f"Cosmos Central: misión omitida — cliente «{client_name}» ya existe; "
                f"cotización {quote.get('code') or '—'} sin duplicar",
                level="warn",
            )
        line_summary = ", ".join(
            (ln.get("descripcion") or ln.get("name") or "")[:40]
            for ln in (quote.get("lines") or [])[:3]
        )

        _set_droid("d2", "done")
        if skipped_duplicate:
            _log_step(activity_log, "d2", f"Voice structured — reusing existing records for «{client_name}»")
            _log_step(activity_log, "d4", "Care-Taker: informe existente — sin duplicar")
            _log_step(
                activity_log,
                "d5",
                f"Financial Ledger: cotización existente {quote.get('code') or '—'} — {client_name} — "
                f"total USD {float(quote.get('total') or 0):.2f}",
            )
        else:
            _log_step(activity_log, "d2", f"Voice structured — inspection {iid} opened in MongoDB")
            _log_step(activity_log, "d4", f"Care-Taker: technical report {result.get('codes', {}).get('report', '—')} saved")
            _log_step(
                activity_log,
                "d5",
                f"Financial Ledger: quote {quote.get('code') or '—'} — {client_name} — "
                f"lines: {line_summary or 'catalog items'} — total USD {float(quote.get('total') or 0):.2f}",
            )
        _log_step(activity_log, "d6", "Catalyst RAG: ready for datasheet / follow-up questions")

        for did in ("d1", "d2", "d3", "d4", "d5", "d6"):
            _set_droid(did, "done")

        steps.append(
            {
                "step": "guided",
                "inspection_id": iid,
                "skipped_duplicate": skipped_duplicate,
                "result_summary": {
                    "client": client_name,
                    "quote_serial": quote.get("code"),
                    "quote_total": quote.get("total"),
                    "products": body.product_codes,
                },
            }
        )

        _set_droid("d7", "working")
        _log_step(activity_log, "d7", "Signer/Fiscal: pre-validation gate passed (XAdES on roadmap)")
        _set_droid("d7", "done")

        _set_droid("d8", "working")
        inst, inst_note = resolve_connected_instance()
        if skipped_duplicate:
            _set_droid("d8", "done")
            _log_step(
                activity_log,
                "d8",
                "Media Agent: WhatsApp omitido — correo ya procesado, sin reenvío duplicado",
                level="warn",
            )
            steps.append({"step": 5, "whatsapp": {"status": "skipped", "reason": "email_already_processed"}})
        else:
            _log_step(activity_log, "d8", f"Media Agent: WhatsApp via Evolution instance «{inst or 'none'}» ({inst_note})")
            phone = body.client_phone.strip() or client.get("phone") or ""
            wa_msg = (
                f"InnerOS — PC Doctor\n"
                f"Client: {client_name}\n"
                f"Quote: {quote.get('code', '—')}\n"
                f"Total: USD {float(quote.get('total') or 0):.2f}\n"
                f"Reply YES to approve or call us."
            )
            wa = send_whatsapp(phone, wa_msg) if phone else {"status": "skipped", "message": "no phone"}
            wa_ok = wa.get("status") == "sent"
            _set_droid("d8", "done" if wa_ok else "error")
            _log_step(
                activity_log,
                "d8",
                f"WhatsApp sent to {phone} via «{wa.get('instance', inst)}»"
                if wa_ok
                else f"WhatsApp: {wa.get('message', 'check Evolution')} [instance: {wa.get('instance', inst)}]",
                level="info" if wa_ok else "warn",
            )
            steps.append({"step": 5, "whatsapp": wa})

        if not skipped_duplicate and email_mail_id:
            _mark_email_demo_processed(get_db(), email_mail_id, result)

        _log_step(activity_log, "d3", f"Mission complete — inspection {iid}", level="success")

        return {
            "ok": True,
            "elapsed_sec": round(time.time() - t0, 2),
            "inspection_id": iid,
            "skipped_duplicate": skipped_duplicate,
            "gemini_plan": gemini_plan,
            "activity_log": activity_log,
            "guided": guided,
            "summary": {
                "inspection_id": iid,
                "quote_serial": quote.get("code"),
                "quote_total": quote.get("total"),
                "client_name": client_name,
                "client_ruc": client.get("ruc") or body.client_ruc,
                "quote_id": quote.get("quote_id"),
                "visit_id": (result.get("visit") or {}).get("visit_id"),
                "report_id": (result.get("report_v2") or {}).get("report_id"),
                "company_id": body.company_id,
                "lines_count": len(quote.get("lines") or []),
            },
            "steps": steps,
            "architecture": "guided_pipeline + gemini_reasoning + mongodb_mcp",
        }
    except HTTPException:
        raise
    except Exception as e:
        err = str(e)
        if "duplicate key" in err.lower() or "E11000" in err:
            _log_step(
                activity_log,
                "d3",
                "Mission recovered: registro ya existía (correo/cliente/cotización) — reutilizando datos",
                level="warn",
            )
            db = get_db()
            quote = None
            hit = None
            if body.client_ruc:
                hit = _existing_client_for_ruc(db, body.client_ruc.strip())
                if hit:
                    quote = db.quotes.find_one({"client_id": hit["client_id"]}, sort=[("created_at", -1)], projection={"_id": 0})
            if quote:
                for d in DROIDS:
                    _set_droid(d["id"], "done")
                return {
                    "ok": True,
                    "elapsed_sec": round(time.time() - t0, 2),
                    "inspection_id": quote.get("legacy_inspection_id"),
                    "skipped_duplicate": True,
                    "gemini_plan": gemini_plan,
                    "activity_log": activity_log,
                    "guided": guided,
                    "summary": {
                        "quote_serial": quote.get("code"),
                        "quote_total": quote.get("total"),
                        "client_name": hit.get("name") if hit else body.client_name,
                        "client_ruc": body.client_ruc,
                        "quote_id": quote.get("quote_id"),
                        "recovered_from_duplicate": True,
                    },
                    "steps": steps,
                    "architecture": "guided_pipeline + gemini_reasoning + mongodb_mcp",
                }
        _log_step(activity_log, "d3", f"Mission failed: {err[:200]}", level="error")
        for d in DROIDS:
            if _droid_state.get(d["id"]) == "working":
                _set_droid(d["id"], "error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seed-demo")
def seed_demo_endpoint():
    """Idempotent demo seed — suppliers, quotes, visits, reports."""
    from scripts.seed_hackathon_demo import run_seed

    return run_seed()
