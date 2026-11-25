"""Servicio HTTP InnerOS Owner Push (PWA + decide API). Puerto 8244."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from inneros_core_runtime import ops_owner_decision_registry as decisions
from inneros_core_runtime import owner_push_history as inbox
from inneros_core_runtime.owner_push_decide import apply_owner_push_decision
from inneros_core_runtime.owner_push_tokens import public_base_url, sign_decision

STATIC_DIR = Path(__file__).resolve().parent / "static" / "inneros_owner"

app = FastAPI(title="InnerOS Owner Push", version="1.0.0")


@app.get("/health")
def health():
    return {"ok": True, "service": "inneros-owner-push", "public": public_base_url()}


@app.get("/owner-ops/", response_class=HTMLResponse)
def owner_home():
    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse("<h1>InnerOS Owner</h1><p>static missing</p>")


@app.get("/api/owner-ops/pending")
def api_pending(limit: int = 20):
    return {"ok": True, "pending": decisions.list_pending_authorizations(limit=limit), "public_url": public_base_url()}


@app.get("/api/owner-ops/history")
def api_history(limit: int = 40, include_ntfy: bool = True):
    mongo_items = inbox.list_inbox(limit=limit)
    return {
        "ok": True,
        "items": mongo_items,
        "public_url": public_base_url(),
        "ntfy_cache": inbox.fetch_ntfy_topic_cache(limit=min(limit, 30)) if include_ntfy else [],
    }


@app.get("/owner-ops/decide")
def owner_decide(
    task_id: str = Query(...),
    nonce: str = Query(...),
    decision: str = Query(...),
    token: str = Query(""),
):
    out = apply_owner_push_decision(task_id=task_id, nonce=nonce, decision=decision, token=token)
    if out.get("ok"):
        label = "Aprobado" if decision == "approve" else "Cancelado"
        html = f"""<!DOCTYPE html><html><head><meta charset=utf-8>
        <meta name=viewport content="width=device-width,initial-scale=1">
        <title>InnerOS · {label}</title></head>
        <body style="font-family:system-ui;padding:1.5rem;background:#0f172a;color:#e2e8f0">
        <h1>{label}</h1><p>{task_id}</p>
        <p><a href="/owner-ops/" style="color:#38bdf8">Volver al panel owner</a></p></body></html>"""
        return HTMLResponse(html)
    return JSONResponse(out, status_code=400)


@app.get("/api/owner-ops/sign-links")
def sign_links(task_id: str = Query(...), nonce: str = Query(...)):
    base = public_base_url()
    return {
        "approve": f"{base}/owner-ops/decide?task_id={task_id}&nonce={nonce}&decision=approve&token={sign_decision(task_id=task_id, nonce=nonce, decision='approve')}",
        "cancel": f"{base}/owner-ops/decide?task_id={task_id}&nonce={nonce}&decision=cancel&token={sign_decision(task_id=task_id, nonce=nonce, decision='cancel')}",
    }


if STATIC_DIR.is_dir():
    app.mount("/owner-ops/static", StaticFiles(directory=STATIC_DIR), name="owner_static")