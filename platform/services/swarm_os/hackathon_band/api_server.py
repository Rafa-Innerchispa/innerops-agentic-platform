"""API hackathon Band — FastAPI :8200 + WebSocket console."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hackathon_band import band_adapter, config, console_log, llm_client
from hackathon_band.agents_meta import get_agents_catalog, get_status_payload, get_suggested_questions
from hackathon_band.exceptions import HackathonConfigError, HackathonIntegrationError
from hackathon_band.memory_source import search_organizational_memory
from hackathon_band.phone_utils import parse_email_list, parse_phone_list
from hackathon_band.pipeline import run_collaboration
from hackathon_band.validate import readiness

app = FastAPI(title="Hackathon Band API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://192.168.1.4:{config.HACKATHON_BAND_PORT}",
        f"http://localhost:{config.HACKATHON_BAND_PORT}",
        f"http://127.0.0.1:{config.HACKATHON_BAND_PORT}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_run_lock = asyncio.Lock()
_last_result: dict[str, Any] | None = None
_ws_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


def _broadcast(entry: dict[str, Any]) -> None:
    if _loop is None or not _ws_clients:
        return

    async def _send() -> None:
        dead: list[WebSocket] = []
        for ws in list(_ws_clients):
            try:
                await ws.send_json(entry)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _ws_clients.discard(ws)

    asyncio.run_coroutine_threadsafe(_send(), _loop)


@app.on_event("startup")
async def startup() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    console_log.subscribe(_broadcast)
    console_log.log("info", "system", "Hackathon API online", port=config.HACKATHON_API_PORT)


class RunRequest(BaseModel):
    question: str = Field(default="", max_length=2000)
    lang: str = Field(default="en", pattern="^(en|es)$")
    notify_phones: str = Field(default="", max_length=500)
    notify_emails: str = Field(default="", max_length=500)


def _phones_from_query(raw: str) -> list[str]:
    return parse_phone_list(raw)


def _emails_from_query(raw: str) -> list[str]:
    return parse_email_list(raw)


@app.get("/api/status")
def api_status():
    return {
        "service": "hackathon_band",
        "port": config.HACKATHON_API_PORT,
        **get_status_payload(),
    }


@app.get("/api/agents")
def api_agents():
    return {"agents": get_agents_catalog(), "suggested_questions": get_suggested_questions()}


@app.get("/api/console/history")
def console_history(limit: int = 200):
    return {"entries": console_log.get_history(limit)}


@app.websocket("/ws/console")
async def ws_console(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        for entry in console_log.get_history(150):
            await websocket.send_json(entry)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


@app.get("/api/memory/preview")
def memory_preview(q: str = ""):
    try:
        result = search_organizational_memory(q or config.DEFAULT_QUESTION)
        return result
    except Exception as exc:
        console_log.log("error", "mongo", str(exc))
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/mongo/stats")
def mongo_stats():
    """Conteos reales por colección — prueba para el jurado."""
    try:
        from tools.mongo import get_db

        db = get_db()
        cols = [
            "sop_visits",
            "technical_reports",
            "reports",
            "inspections",
            "clients",
            "documents",
        ]
        counts = {}
        for name in cols:
            if name in db.list_collection_names():
                counts[name] = db[name].count_documents({})
        return {"database": __import__("os").getenv("MONGO_DB", "pcdoctor_swarm"), "collections": counts}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.post("/api/run")
async def api_run(body: RunRequest):
    global _last_result
    if _run_lock.locked():
        raise HTTPException(409, "Pipeline running")

    question = (body.question or config.DEFAULT_QUESTION).strip()
    events: list[dict[str, Any]] = []

    def on_progress(ev: dict[str, Any]) -> None:
        events.append(ev)
        console_log.log("info", "system", f"Step: {ev.get('step')}", **{k: v for k, v in ev.items() if k != "step"})

    async with _run_lock:
        try:
            phones = _phones_from_query(body.notify_phones)
            emails = _emails_from_query(body.notify_emails)
            result = await asyncio.to_thread(
                run_collaboration,
                question,
                lang=body.lang,
                notify_phones=phones,
                notify_emails=emails,
                on_progress=on_progress,
            )
        except HackathonConfigError as exc:
            console_log.log("error", "system", str(exc))
            raise HTTPException(503, detail={"error": "config", "message": str(exc), "missing": exc.missing})
        except HackathonIntegrationError as exc:
            console_log.log("error", exc.service.lower(), exc.detail)
            raise HTTPException(502, detail={"error": exc.service, "message": exc.detail})
        except Exception as exc:
            console_log.log("error", "system", str(exc))
            raise HTTPException(500, str(exc)) from exc

    _last_result = result
    return {**result, "events": events}


@app.get("/api/run/stream")
async def api_run_stream(q: str = "", lang: str = "en", notify_phones: str = "", notify_emails: str = ""):
    question = (q or config.DEFAULT_QUESTION).strip()
    lang = "es" if lang == "es" else "en"
    phones = _phones_from_query(notify_phones)
    emails = _emails_from_query(notify_emails)

    async def generate():
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        def on_progress(ev: dict[str, Any]) -> None:
            queue.put_nowait(ev)

        async def run_pipeline():
            try:
                result = await asyncio.to_thread(
                    run_collaboration,
                    question,
                    lang=lang,
                    notify_phones=phones,
                    notify_emails=emails,
                    on_progress=on_progress,
                )
                global _last_result
                _last_result = result
                queue.put_nowait({"step": "complete", "result": result})
            except Exception as exc:
                console_log.log("error", "system", str(exc))
                queue.put_nowait({"step": "error", "error": str(exc)})
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(run_pipeline())
        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        finally:
            await task

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/report")
def api_report():
    if config.REPORT_PATH.exists():
        return {"markdown": config.REPORT_PATH.read_text(encoding="utf-8")}
    if _last_result:
        return {"markdown": _last_result.get("report_markdown", "")}
    raise HTTPException(404, "No report yet")


@app.get("/api/report/download")
def api_report_download():
    """Descarga pública del reporte — enlace enviado por WhatsApp."""
    path = config.REPORT_PATH
    if not path.exists() and _last_result and _last_result.get("report_markdown"):
        path.write_text(_last_result["report_markdown"], encoding="utf-8")
    if not path.exists():
        raise HTTPException(404, "No report yet — run the pipeline first")
    return FileResponse(
        path,
        media_type="text/markdown; charset=utf-8",
        filename="PCDoctor_Band_Report.md",
        headers={"Content-Disposition": 'attachment; filename="PCDoctor_Band_Report.md"'},
    )


@app.get("/api/messages")
def api_messages(chat_id: str):
    try:
        return {"chat_id": chat_id, "messages": band_adapter.get_messages(chat_id)}
    except HackathonConfigError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/band/audit")
def band_audit():
    audit_dir = config.BAND_AUDIT_DIR
    rooms: list[dict[str, Any]] = []
    if audit_dir.exists():
        for path in sorted(audit_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                rooms.append({
                    "chat_id": data.get("chat_id", path.stem),
                    "updated_at": data.get("updated_at"),
                    "message_count": len(data.get("messages") or []),
                })
            except Exception:
                continue
    last_chat = _last_result.get("chat_id") if _last_result else None
    return {
        "band_mode": "LIVE",
        "band_rest_url": config.BAND_REST_URL,
        "last_chat_id": last_chat,
        "audit_rooms": rooms,
        "agents": {
            k: {"band_id": v.get("band_id"), "name": v.get("name")}
            for k, v in config.AGENTS.items()
        },
    }


def main():
    import uvicorn

    uvicorn.run(
        "hackathon_band.api_server:app",
        host=config.HACKATHON_API_HOST,
        port=config.HACKATHON_API_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
