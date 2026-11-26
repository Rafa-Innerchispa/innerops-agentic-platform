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
        task = mongo_store.get_db()[OPS_TASKS_COL].find_one(
            {"task_id": tid},
            {"_id": 0, "title": 1, "objective": 1, "owner_authorized_at": 1, "status": 1},
        ) or {}
        if task.get("owner_authorized_at"):
            continue
        if str(task.get("status") or "") in {"completed", "done", "verification", "cancelled", "archived"}:
            continue
        seen.add(tid)
        display_status = row.get("display_status")
        if not display_status and row.get("auth_stale"):
            display_status = "auth_expired"
        rows.append(
            {
                **row,
                "task_id": tid,
                "title": task.get("title") or row.get("title"),
                "objective": task.get("objective"),
                "source": "decision_registry",
                "display_status": display_status or row.get("status") or "pending",
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


@app.get("/api/owner-ops/active")
def api_active(limit: int = 20):
    """Trabajos ya autorizados o en vuelo — misma clave ops_ + nombre humano en pantalla."""
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL
    from raphiia_openai import mongo_store

    lim = max(1, min(int(limit), 50))
    active_status = {
        "claimed",
        "in_progress",
        "running",
        "verification",
        "awaiting_antigravity_claim",
        "awaiting_cursor_claim",
        "awaiting_codex_claim",
        "awaiting_gemini_claim",
    }
    rows = list(
        mongo_store.get_db()[OPS_TASKS_COL]
        .find(
            {
                "owner_authorized_at": {"$exists": True, "$ne": None},
                "status": {"$in": sorted(active_status)},
            },
            {
                "_id": 0,
                "task_id": 1,
                "human_task_id": 1,
                "task_alias": 1,
                "correlation_id": 1,
                "title": 1,
                "status": 1,
                "assignee": 1,
                "from_agent": 1,
                "updated_at": 1,
                "created_at": 1,
            },
        )
        .sort("updated_at", -1)
        .limit(lim)
    )
    out: list[dict] = []
    for t in rows:
        tid = str(t.get("task_id") or "")
        human = str(t.get("human_task_id") or t.get("task_alias") or t.get("correlation_id") or tid)
        out.append(
            {
                **t,
                "ops_label": f"{tid} · {human}",
                "human_task_id": human,
            }
        )
    return {"ok": True, "active": out, "count": len(out), "public_url": public_base_url()}


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


def _decide_result_html(*, title: str, body: str, ok: bool, task_id: str = "") -> str:
    accent = "#4ade80" if ok else "#f87171"
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta http-equiv="refresh" content="4;url=/owner-ops/"/>
<title>InnerOS · {title}</title>
<style>
  body {{ margin:0; min-height:100dvh; display:flex; align-items:center; justify-content:center;
    font-family:system-ui,sans-serif; background:#0f172a; color:#e2e8f0; padding:1.25rem; }}
  .box {{ max-width:22rem; text-align:center; background:#1e293b; border:1px solid #334155;
    border-radius:16px; padding:1.5rem 1.25rem; }}
  h1 {{ margin:0 0 .75rem; font-size:1.35rem; color:{accent}; }}
  p {{ margin:.5rem 0; line-height:1.45; font-size:.95rem; color:#cbd5e1; }}
  .tid {{ font-size:.8rem; color:#94a3b8; word-break:break-all; }}
  a {{ display:inline-block; margin-top:1rem; color:#38bdf8; font-weight:600; text-decoration:none; }}
</style></head>
<body><div class="box">
  <h1>{title}</h1>
  <p>{body}</p>
  {"<p class='tid'>" + task_id + "</p>" if task_id else ""}
  <p style="font-size:.78rem;color:#64748b">Volviendo al panel en 4 s…</p>
  <a href="/owner-ops/">Ir a InnerOS Owner</a>
</div></body></html>"""


@app.get("/owner-ops/decide")
def owner_decide(
    request: Request,
    task_id: str = Query(...),
    nonce: str = Query(...),
    decision: str = Query(...),
    token: str = Query(""),
):
    out = apply_owner_push_decision(task_id=task_id, nonce=nonce, decision=decision, token=token)
    wants_json = "application/json" in (request.headers.get("accept") or "")
    if out.get("ok"):
        if decision == "approve":
            if out.get("authorize_ok", True):
                title, body = "Aprobada", "La autorización quedó registrada. Te avisaremos cuando la tarea avance o termine."
            else:
                title, body = "Aprobada (parcial)", str(
                    out.get("message") or "Autorización guardada; el IDE aún debe tomar la tarea en Intel."
                )
        else:
            title, body = "Cancelada", "La solicitud fue cancelada. No se ejecutará."
        html = _decide_result_html(title=title, body=body, ok=True, task_id=task_id)
        if wants_json:
            return JSONResponse(out)
        return HTMLResponse(html)
    err = str(out.get("error") or "No se pudo aplicar la decisión")
    hint = {
        "invalid_token": "Enlace caducado. Abre InnerOS → Pendientes y vuelve a intentar.",
        "decision_already_resolved": "Ya habías decidido esta tarea antes.",
        "decision_not_found_or_expired": "La solicitud expiró. Pide un nuevo canario o autorización.",
    }.get(err, err)
    html = _decide_result_html(title="No se pudo", body=hint, ok=False, task_id=task_id)
    if wants_json:
        return JSONResponse(out, status_code=400)
    return HTMLResponse(html, status_code=200)


@app.get("/api/owner-ops/sign-links")
def sign_links(task_id: str = Query(...), nonce: str = Query(...)):
    base = public_base_url()
    return {
        "approve": f"{base}/owner-ops/decide?task_id={task_id}&nonce={nonce}&decision=approve&token={sign_decision(task_id=task_id, nonce=nonce, decision='approve')}",
        "cancel": f"{base}/owner-ops/decide?task_id={task_id}&nonce={nonce}&decision=cancel&token={sign_decision(task_id=task_id, nonce=nonce, decision='cancel')}",
    }


if STATIC_DIR.is_dir():
    app.mount("/owner-ops/static", StaticFiles(directory=STATIC_DIR), name="owner_static")