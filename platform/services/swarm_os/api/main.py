import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.crew import run_inspection_flow
from api.assistant import router as assistant_router
from api.auth_routes import router as auth_router
from api.chat_store import router as chat_router
from api.crud_v1 import router as crud_v1_router
from api.email_routes import router as email_router
from api.hackathon_routes import router as hackathon_router
from api.voice_agent import router as voice_agent_router
from config import API_HOST, API_PORT
from tools.file_reader import read_file
from tools.media_store import save_upload
from tools.mongo import ensure_indexes, get_inspection, seed_inventory_if_empty, update_inspection
from tools.schema import COLLECTIONS
from tools.n8n_webhook import notify
from tools.ruc_api import lookup_ruc, normalize_tax_id
from tools.transcribe import transcribe_audio_file

app = FastAPI(
    title="InnerSpark Swarm-OS (Cursor Local)",
    description="Agentes PC Doctor — inspección, informe, cotización",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://192.168.1.4:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://192.168.1.4:5180",
        "http://localhost:5180",
        "http://127.0.0.1:5180",
        "http://192.168.1.4:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        # UI Google AI Studio (Express+Vite dev)
        "http://192.168.1.4:3000",
        "http://192.168.1.4:5180",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ],
    allow_origin_regex=r"https://.*\.ngrok-free\.(app|dev)|https://.*\.ngrok\.io|http://192\.168\.\d+\.\d+:(5173|5174|5175|5180)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(crud_v1_router)
app.include_router(assistant_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(voice_agent_router)
app.include_router(email_router)
app.include_router(hackathon_router)

_branding = ROOT / "assets" / "branding"
_branding.mkdir(parents=True, exist_ok=True)
app.mount("/assets/branding", StaticFiles(directory=str(_branding)), name="branding")


class InspectionStart(BaseModel):
    input: str = Field(..., description="Notas de campo, dictado o texto del técnico")
    inspection_id: str | None = None


class SendNotification(BaseModel):
    channel: str = "email"
    to: str = ""
    subject: str = ""
    body: str = ""
    inspection_id: str = ""


class RucLookup(BaseModel):
    id: str = Field(..., description="RUC (13) o cédula (10)")


class FileAnalyze(BaseModel):
    path: str = Field(..., description="Ruta local del archivo ya subido")
    question: str = ""


@app.on_event("startup")
def startup():
    from tools.companies import ensure_companies, seed_innerchispa_catalog
    from tools.mongo import get_db

    ensure_indexes()
    seed_inventory_if_empty()
    db = get_db()
    from api.auth_users import ensure_users

    ensure_companies(db)
    seed_innerchispa_catalog(db)
    ensure_users(db)
    db.chat_messages.create_index([("username", 1), ("created_at", -1)])
    db.chat_messages.create_index([("session_id", 1), ("created_at", 1)])
    db.chat_sessions.create_index([("username", 1), ("updated_at", -1)])
    db.chat_sessions.create_index("session_id", unique=True)
    db.chat_files.create_index([("session_id", 1), ("created_at", -1)])
    db.email_accounts.create_index("email_account_id", unique=True)
    db.email_accounts.create_index("address", unique=True)
    db.email_messages.create_index([("email_account_id", 1), ("uid", 1)], unique=True)
    db.email_messages.create_index([("importance", 1), ("received_at", -1)])


@app.get("/status")
def status():
    from config import RUC_API_PASS, RUC_API_USER, WHISPER_URL
    from tools.mongo import get_db

    db = get_db()
    registry = list(db["_schema_registry"].find({}, {"_id": 0, "dbxx": 1, "collection": 1, "name": 1}))
    return {
        "status": "online",
        "project": "innerspark-swarm-os-cursor-local",
        "mongodb_db": db.name,
        "collections_total": len(db.list_collection_names()),
        "dbxx_collections_defined": len(COLLECTIONS),
        "schema_registry_entries": len(registry),
        "ruc_api_configured": bool(RUC_API_USER and RUC_API_PASS),
        "whisper_url": WHISPER_URL,
        "agents": [
            "director",
            "campo",
            "cliente",
            "bitacora",
            "informes",
            "cotizador",
            "revisor",
            "comunicaciones",
        ],
    }


@app.post("/inspection/start")
def inspection_start(body: InspectionStart):
    if not body.input.strip():
        raise HTTPException(400, "input vacío")
    try:
        result = run_inspection_flow(body.input, inspection_id=body.inspection_id)
        return result
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.get("/inspection/{inspection_id}")
def inspection_get(inspection_id: str):
    doc = get_inspection(inspection_id)
    if not doc:
        raise HTTPException(404, "inspección no encontrada")
    return doc


@app.post("/inspection/{inspection_id}/upload")
async def inspection_upload(inspection_id: str, file: UploadFile = File(...)):
    if not get_inspection(inspection_id):
        raise HTTPException(404, "inspección no encontrada")
    content = await file.read()
    entry = save_upload(inspection_id, file.filename or "upload.bin", content)
    return {"saved": entry}


@app.post("/inspection/{inspection_id}/upload-audio")
async def inspection_upload_audio(inspection_id: str, file: UploadFile = File(...)):
    """Sube audio, transcribe con Whisper local y agrega texto a la inspección."""
    insp = get_inspection(inspection_id)
    if not insp:
        raise HTTPException(404, "inspección no encontrada")
    content = await file.read()
    entry = save_upload(inspection_id, file.filename or "audio.wav", content)
    try:
        tr = transcribe_audio_file(entry["path"])
    except Exception as e:
        raise HTTPException(502, f"Whisper no disponible: {e}") from e
    merged = (insp.get("raw_input") or "").strip()
    if merged:
        merged += "\n\n[TRANSCRIPCIÓN AUDIO]\n" + tr["text"]
    else:
        merged = tr["text"]
    update_inspection(
        inspection_id,
        {"raw_input": merged, "transcription": tr},
    )
    return {"saved": entry, "transcription": tr, "raw_input": merged}


@app.post("/inspection/{inspection_id}/analyze-file")
def inspection_analyze_file(inspection_id: str, body: FileAnalyze):
    """Lee PDF/texto/imagen local y agrega extracción a la inspección."""
    insp = get_inspection(inspection_id)
    if not insp:
        raise HTTPException(404, "inspección no encontrada")
    try:
        extracted = read_file(body.path, question=body.question)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    annex = f"\n\n[ARCHIVO {extracted.get('kind', 'file')}]\n{extracted.get('text', '')}"
    merged = (insp.get("raw_input") or "") + annex
    files_read = insp.get("files_read", [])
    files_read.append(extracted)
    update_inspection(inspection_id, {"raw_input": merged.strip(), "files_read": files_read})
    return {"extracted": extracted, "raw_input": merged.strip()}


@app.post("/ruc/lookup")
def ruc_lookup(body: RucLookup):
    norm = normalize_tax_id(body.id)
    data = lookup_ruc(body.id)
    return {"normalized": norm, "result": data}


@app.post("/inspection/{inspection_id}/notify")
def inspection_notify(inspection_id: str, body: SendNotification):
    if not get_inspection(inspection_id):
        raise HTTPException(404, "inspección no encontrada")
    payload = {
        "channel": body.channel,
        "to": body.to,
        "subject": body.subject,
        "body": body.body,
        "inspection_id": inspection_id,
    }
    return notify(payload)


@app.get("/schema/registry")
def schema_registry():
    """Mapa DBxx → colecciones Mongo (desde 192.168.1.4)."""
    from tools.mongo import get_db

    db = get_db()
    return list(db["_schema_registry"].find({}, {"_id": 0}))


@app.get("/schema/flows")
def schema_flows():
    """Flujos operativos SOP → pasos y gates."""
    from tools.mongo import get_db

    db = get_db()
    return list(db["_flow_registry"].find({}, {"_id": 0}))


@app.post("/gates/client/duplicate-check")
def gate_duplicate_client(body: RucLookup):
    """Gate anti-duplicación DB04 por RUC/cédula."""
    from tools.gates import check_duplicate_client
    from tools.ruc_api import lookup_ruc

    data = lookup_ruc(body.id)
    return check_duplicate_client(
        ruc=data.get("ruc") if data else body.id,
        name=data.get("name") if data else None,
    )


@app.post("/gates/quote/{quote_id}/ready-to-send")
def gate_ready_to_send(quote_id: str, client_id: str | None = None):
    """Gate compuesto Listo para enviar (SOP Master A3)."""
    from tools.gates import run_ready_to_send

    return run_ready_to_send(quote_id, client_id=client_id)


@app.post("/gates/quote/{quote_id}/validate-rules")
def gate_validate_rules(quote_id: str):
    """Evalúa reglas DB41 y guarda validation_results."""
    from tools.gates import run_verification_rules

    return {"results": run_verification_rules("quote", quote_id)}


@app.post("/inspection/quick")
def inspection_quick(body: InspectionStart):
    """Crea ID y devuelve sin ejecutar crew (útil para subir fotos antes)."""
    from tools.crew_tools import start_inspection_record

    text = body.input.strip() or "inspección en campo"
    iid = start_inspection_record(text, inspection_id=body.inspection_id)
    return {"inspection_id": iid, "status": "open"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host=API_HOST, port=API_PORT, reload=False)
