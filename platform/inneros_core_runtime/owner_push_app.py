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


def _list_pending_merged(limit: int = 20) -> list[dict]:
    """Decisión Atlas + inbox; evita PWA vacía si falta una rama."""
    import time

    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from raphiia_openai import mongo_store

    lim = max(1, min(int(limit), 50))
    now = time.time()
    rows: list[dict] = []
    seen: set[str] = set()

    try:
        reg = decisions.list_pending_authorizations(limit=lim)
    except AttributeError:
        reg = list(
            mongo_store.get_db()["atlas_ops_owner_decisions"].find(
                {
                    "status": {"$in": ["pending", "awaiting_owner_decision"]},
                    "expires_at": {"$gt": now},
                },
                {"_id": 0},
            ).sort("created_at", -1).limit(lim)
        )

    for row in reg:
        tid = str(row.get("task_id") or row.get("_id") or "")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        task = mongo_store.get_db()[OPS_TASKS_COL].find_one({"task_id": tid}, {"_id": 0, "title": 1, "objective": 1}) or {}
        rows.append(
            {
                **row,
                "task_id": tid,
                "title": task.get("title") or row.get("title"),
                "objective": task.get("objective"),
                "source": "decision_registry",
            }
        )

    for row in inbox.list_inbox(limit=lim, kinds=["auth_request"]):
        if str(row.get("status") or "") != "pending":
            continue
        tid = str(row.get("task_id") or "")
        if not tid or tid in seen:
            continue
        nonce = str(row.get("nonce") or "")
        if not nonce:
            reg_row = mongo_store.get_db()["atlas_ops_owner_decisions"].find_one({"task_id": tid}, {"nonce": 1})
            nonce = str((reg_row or {}).get("nonce") or "")
        seen.add(tid)
        rows.append(
            {
                "task_id": tid,
                "human_task_id": row.get("human_task_id") or tid,
                "provider": row.get("provider") or "?",
                "nonce": nonce,
                "status": "pending",
                "created_at": row.get("created_at"),
                "title": row.get("title"),
                "objective": row.get("message"),
                "source": "inbox",
            }
        )
    rows.sort(key=lambda x: float(x.get("created_at") or 0), reverse=True)
    return rows[:lim]


@app.get("/api/owner-ops/pending")
def api_pending(limit: int = 20):
    pending = _list_pending_merged(limit=limit)
    return {"ok": True, "pending": pending, "count": len(pending), "public_url": public_base_url()}


@app.get("/api/owner-ops/history")
def api_history(limit: int = 40, include_ntfy: bool = True):
    mongo_items = [
        r
        for r in inbox.list_inbox(limit=limit)
        if not (r.get("kind") == "auth_request" and str(r.get("status") or "") == "pending")
    ]
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