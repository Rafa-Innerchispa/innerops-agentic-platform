"""Monitor de correos + alertas WhatsApp (Evolution API)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tools.schema import new_id

router = APIRouter(prefix="/api/v1", tags=["email"])


def _db():
    from tools.mongo import get_db

    return get_db()


def _now():
    return datetime.now(timezone.utc)


def _settings() -> dict:
    db = _db()
    doc = db.email_settings.find_one({"_id": "global"}, {"_id": 0})
    if not doc:
        from config import EVOLUTION_INSTANCE

        doc = {
            "evolution_instance": EVOLUTION_INSTANCE,
            "whatsapp_numbers": [],
            "keywords_important": ["urgente", "factura", "pago", "vencido", "cotización", "reclamo", "falla"],
            "notify_on_high": True,
            "email_view_base_url": "http://192.168.1.4:5173/email",
            "snippet_max": 300,
            "poll_max_per_account": 50,
            "initial_sync_max": 150,
        }
        db.email_settings.insert_one({"_id": "global", **doc})
    return doc


class EmailSettingsIn(BaseModel):
    evolution_instance: str = ""
    whatsapp_numbers: list[str] = []
    keywords_important: list[str] = []
    notify_on_high: bool = True
    email_view_base_url: str = "http://192.168.1.4:5173/email"
    snippet_max: int = 300


class EmailAccountIn(BaseModel):
    address: str
    label: str = ""
    imap_host: str
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    enabled: bool = True
    monitor_since: str = ""  # ISO date — solo correos desde esta fecha
    whatsapp_numbers: list[str] = []  # override por cuenta
    keywords: list[str] = []


class EmailAccountPatch(BaseModel):
    label: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    imap_user: str | None = None
    imap_password: str | None = None
    imap_folder: str | None = None
    enabled: bool | None = None
    monitor_since: str | None = None
    whatsapp_numbers: list[str] | None = None
    keywords: list[str] | None = None


class WhatsAppTestIn(BaseModel):
    number: str
    text: str = "Prueba Ralphi IA — alertas de correo activas ✅"


class EmailDetectIn(BaseModel):
    address: str


class EmailTestIn(BaseModel):
    address: str = ""
    imap_host: str
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"


class EvolutionInstanceIn(BaseModel):
    instance_name: str = "ralphi-pcdoctor"


@router.get("/email/settings")
def get_email_settings():
    s = _settings()
    from config import EVOLUTION_API_KEY, EVOLUTION_BASE_URL

    return {
        **s,
        "evolution_base_url": EVOLUTION_BASE_URL,
        "evolution_configured": bool(EVOLUTION_API_KEY),
    }


@router.put("/email/settings")
def put_email_settings(body: EmailSettingsIn):
    db = _db()
    doc = body.model_dump()
    doc["updated_at"] = _now()
    db.email_settings.update_one({"_id": "global"}, {"$set": doc}, upsert=True)
    return {"ok": True, **doc}


@router.get("/email/accounts")
def list_email_accounts():
    db = _db()
    data = list(db.email_accounts.find({}, {"_id": 0, "imap_password": 0}).sort("address", 1))
    return {"data": data, "total": len(data)}


@router.post("/email/accounts")
def create_email_account(body: EmailAccountIn):
    db = _db()
    if db.email_accounts.find_one({"address": body.address.strip().lower()}):
        raise HTTPException(409, "esa cuenta ya está configurada")
    doc = {
        "email_account_id": new_id("eml"),
        "address": body.address.strip().lower(),
        "label": body.label or body.address,
        "imap_host": body.imap_host,
        "imap_port": body.imap_port,
        "imap_user": body.imap_user or body.address,
        "imap_password": body.imap_password,
        "imap_folder": body.imap_folder,
        "enabled": body.enabled,
        "monitor_since": body.monitor_since or _now().date().isoformat(),
        "whatsapp_numbers": body.whatsapp_numbers,
        "keywords": body.keywords,
        "last_uid": 0,
        "last_poll_at": None,
        "last_error": "",
        "created_at": _now(),
        "updated_at": _now(),
    }
    db.email_accounts.insert_one(doc)
    doc.pop("_id", None)
    doc.pop("imap_password", None)
    return doc


@router.patch("/email/accounts/{account_id}")
def patch_email_account(account_id: str, body: EmailAccountPatch):
    db = _db()
    acc = db.email_accounts.find_one({"email_account_id": account_id})
    if not acc:
        raise HTTPException(404, "cuenta no encontrada")
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    upd["updated_at"] = _now()
    db.email_accounts.update_one({"email_account_id": account_id}, {"$set": upd})
    doc = db.email_accounts.find_one({"email_account_id": account_id}, {"_id": 0, "imap_password": 0})
    return doc


@router.delete("/email/accounts/{account_id}")
def delete_email_account(account_id: str):
    db = _db()
    if not db.email_accounts.find_one({"email_account_id": account_id}):
        raise HTTPException(404, "cuenta no encontrada")
    db.email_accounts.delete_one({"email_account_id": account_id})
    return {"deleted": account_id}


@router.get("/email/messages")
def list_email_messages(skip: int = 0, limit: int = 50, importance: str | None = None):
    db = _db()
    filt: dict[str, Any] = {}
    if importance:
        filt["importance"] = importance
    data = list(
        db.email_messages.find(filt, {"_id": 0})
        .sort("received_at", -1)
        .skip(skip)
        .limit(min(limit, 200))
    )
    total = db.email_messages.count_documents(filt)
    return {"data": data, "total": total}


@router.get("/email/messages/{mail_id}")
def get_email_message(mail_id: str):
    db = _db()
    doc = db.email_messages.find_one({"mail_id": mail_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "correo no encontrado")
    settings = _settings()
    base = (settings.get("email_view_base_url") or "http://192.168.1.4:5173/email").rstrip("/")
    doc["view_url"] = f"{base}?mail={mail_id}"
    return doc


@router.post("/email/poll")
def poll_all_accounts():
    """Revisa todas las cuentas activas — llamar desde cron cada 5 min."""
    db = _db()
    settings = _settings()
    accounts = list(db.email_accounts.find({"enabled": True}))
    summary = {"accounts": len(accounts), "new_messages": 0, "alerts_sent": 0, "errors": []}

    for acc in accounts:
        try:
            result = _poll_one(acc, settings)
            summary["new_messages"] += result["new"]
            summary["alerts_sent"] += result["alerts"]
        except Exception as e:
            summary["errors"].append({"account": acc.get("address"), "error": str(e)})
            db.email_accounts.update_one(
                {"email_account_id": acc["email_account_id"]},
                {"$set": {"last_error": str(e), "updated_at": _now()}},
            )
    return summary


@router.post("/email/accounts/{account_id}/poll")
def poll_one_account(account_id: str):
    db = _db()
    acc = db.email_accounts.find_one({"email_account_id": account_id})
    if not acc:
        raise HTTPException(404, "cuenta no encontrada")
    return _poll_one(acc, _settings())


def _poll_one(acc: dict, settings: dict) -> dict[str, Any]:
    from tools.email_agent import classify_importance, format_whatsapp_alert, suggest_routing
    from tools.email_imap import fetch_new_messages
    from tools.evolution_api import send_whatsapp

    db = _db()
    since = None
    if acc.get("monitor_since"):
        try:
            since = datetime.fromisoformat(acc["monitor_since"]).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    is_first_sync = acc.get("last_uid", 0) == 0
    batch = settings.get("initial_sync_max", 150) if is_first_sync else settings.get("poll_max_per_account", 50)
    msgs = fetch_new_messages(
        acc["imap_host"],
        acc["imap_user"] or acc["address"],
        acc.get("imap_password", ""),
        port=acc.get("imap_port", 993),
        folder=acc.get("imap_folder", "INBOX"),
        since_date=since,
        last_uid=acc.get("last_uid", 0),
        max_messages=batch,
        snippet_max=settings.get("snippet_max", 300),
    )

    keywords = (acc.get("keywords") or []) + (settings.get("keywords_important") or [])
    whatsapp_nums = acc.get("whatsapp_numbers") or settings.get("whatsapp_numbers") or []
    new_count = 0
    alerts = 0
    max_uid = acc.get("last_uid", 0)

    for m in msgs:
        uid = m["uid"]
        if uid <= acc.get("last_uid", 0):
            continue
        existing = db.email_messages.find_one({
            "email_account_id": acc["email_account_id"],
            "uid": uid,
        })
        if existing:
            max_uid = max(max_uid, uid)
            continue

        clf = classify_importance(
            m["subject"],
            m["snippet"],
            m["from_addr"],
            keywords,
            trusted_domains=settings.get("trusted_domains") or [],
        )
        routing = suggest_routing(m["subject"], m["snippet"], m["from_addr"])
        mail_id = new_id("mail")
        view_base = (settings.get("email_view_base_url") or "http://192.168.1.4:5173/email").rstrip("/")
        doc = {
            "mail_id": mail_id,
            "email_account_id": acc["email_account_id"],
            "account_address": acc["address"],
            "uid": uid,
            "message_id": m.get("message_id", ""),
            "from_addr": m["from_addr"],
            "subject": m["subject"],
            "snippet": m["snippet"],
            "importance": clf["importance"],
            "importance_reason": clf.get("reason", ""),
            "classified_by": clf.get("source", ""),
            "suggested_action": routing.get("suggested_action", ""),
            "route_area": routing.get("route_area", ""),
            "route_collection": routing.get("route_collection", ""),
            "view_url": f"{view_base}?mail={mail_id}",
            "has_attachment": m.get("has_attachment", False),
            "whatsapp_sent": False,
            "received_at": _now(),
        }
        db.email_messages.insert_one(doc)
        new_count += 1
        max_uid = max(max_uid, uid)

        if settings.get("notify_on_high") and clf["importance"] == "alta" and whatsapp_nums:
            text = format_whatsapp_alert(
                acc["address"],
                m["subject"],
                m["from_addr"],
                clf["importance"],
                clf.get("reason", ""),
                mail_id=mail_id,
                view_url=view_base,
                suggested_action=routing.get("suggested_action", ""),
                route_area=routing.get("route_area", ""),
            )
            sent_any = False
            for num in whatsapp_nums:
                try:
                    res = send_whatsapp(num, text, instance=settings.get("evolution_instance"))
                    if res.get("status") == "sent":
                        alerts += 1
                        sent_any = True
                except Exception as wa_err:
                    db.email_messages.update_one(
                        {"mail_id": doc["mail_id"]},
                        {"$set": {"whatsapp_error": str(wa_err)[:200]}},
                    )
            if sent_any:
                db.email_messages.update_one(
                    {"mail_id": doc["mail_id"]},
                    {"$set": {"whatsapp_sent": True}},
                )

    db.email_accounts.update_one(
        {"email_account_id": acc["email_account_id"]},
        {"$set": {
            "last_uid": max_uid,
            "last_poll_at": _now(),
            "last_error": "",
            "updated_at": _now(),
        }},
    )
    return {"account": acc["address"], "new": new_count, "alerts": alerts, "scanned": len(msgs)}


@router.post("/email/test-whatsapp")
def test_whatsapp(body: WhatsAppTestIn):
    from tools.evolution_api import check_number, evolution_available, send_whatsapp

    if not evolution_available():
        raise HTTPException(502, "Evolution API no responde en :8082")
    settings = _settings()
    inst = settings.get("evolution_instance")
    chk = check_number(inst, body.number)
    result = send_whatsapp(body.number, body.text, instance=inst)
    result["number_check"] = chk
    return result


@router.delete("/email/evolution/instance/{instance_name}")
def evolution_delete_instance(instance_name: str):
    from tools.evolution_api import delete_instance, evolution_available

    if not evolution_available():
        raise HTTPException(502, "Evolution API offline")
    return delete_instance(instance_name)


@router.post("/email/accounts/{account_id}/resync")
def resync_email_account(account_id: str):
    """Reinicia sincronización desde monitor_since (sin borrar duplicados ya guardados)."""
    db = _db()
    acc = db.email_accounts.find_one({"email_account_id": account_id})
    if not acc:
        raise HTTPException(404, "cuenta no encontrada")
    db.email_accounts.update_one(
        {"email_account_id": account_id},
        {"$set": {"last_uid": 0, "updated_at": _now()}},
    )
    return _poll_one({**acc, "last_uid": 0}, _settings())


@router.post("/email/accounts/detect")
def detect_email_provider(body: EmailDetectIn):
    from tools.email_providers import detect_provider

    return detect_provider(body.address)


@router.post("/email/accounts/test-connection")
def test_email_connection(body: EmailTestIn):
    from tools.email_providers import detect_provider, test_imap_connection

    user = body.imap_user or body.address
    preset = detect_provider(body.address) if body.address else {}
    result = test_imap_connection(
        body.imap_host,
        user,
        body.imap_password,
        port=body.imap_port,
        folder=body.imap_folder,
    )
    return {**result, "provider": preset.get("provider"), "auth_note": preset.get("auth_note", "")}


@router.get("/email/evolution/status")
def evolution_status():
    from config import EVOLUTION_BASE_URL, EVOLUTION_INSTANCE
    from tools.evolution_api import connection_state, evolution_available, evolution_info, list_instances

    settings = _settings()
    inst = settings.get("evolution_instance") or EVOLUTION_INSTANCE
    out: dict[str, Any] = {
        "base_url": EVOLUTION_BASE_URL,
        "manager_url": f"{EVOLUTION_BASE_URL.rstrip('/')}/manager",
        "instance": inst,
        "online": evolution_available(),
        "instances": [],
        "connection": None,
    }
    if out["online"]:
        try:
            from tools.evolution_api import _instance_is_open

            out["api_info"] = evolution_info()
            out["instances"] = list_instances()
            if inst:
                out["connection"] = connection_state(inst)
                is_open, linked = _instance_is_open(inst)
                out["connected"] = is_open
                out["linked_whatsapp"] = linked
        except Exception as e:
            out["instances_error"] = str(e)
    return out


@router.post("/email/evolution/create-instance")
def evolution_create_instance(body: EvolutionInstanceIn):
    from tools.evolution_api import create_instance, evolution_available

    if not evolution_available():
        raise HTTPException(502, "Evolution API no responde — verifica Docker en :8082")
    name = body.instance_name.strip()
    if not name:
        raise HTTPException(400, "nombre de instancia vacío")
    result = create_instance(name)
    if not result.get("ok"):
        raise HTTPException(result.get("http_status", 500), str(result.get("data")))
    db = _db()
    db.email_settings.update_one(
        {"_id": "global"},
        {"$set": {"evolution_instance": name, "updated_at": _now()}},
        upsert=True,
    )
    return result


@router.get("/email/evolution/connect/{instance_name}")
def evolution_get_qr(instance_name: str):
    from tools.evolution_api import connect_instance, evolution_available

    if not evolution_available():
        raise HTTPException(502, "Evolution API offline")
    return connect_instance(instance_name)


@router.get("/email/evolution/connection/{instance_name}")
def evolution_connection(instance_name: str):
    from tools.evolution_api import connection_state

    return connection_state(instance_name)


@router.get("/email/stats")
def email_stats():
    db = _db()
    return {
        "accounts": db.email_accounts.count_documents({}),
        "accounts_enabled": db.email_accounts.count_documents({"enabled": True}),
        "messages_total": db.email_messages.count_documents({}),
        "messages_high": db.email_messages.count_documents({"importance": "alta"}),
        "messages_with_whatsapp": db.email_messages.count_documents({"whatsapp_sent": True}),
    }
