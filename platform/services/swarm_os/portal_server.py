import os
import json
import uuid
import hashlib
import logging
import re
import shutil
import socket
import sys
from datetime import datetime, timezone
from fastapi import FastAPI, Form, Cookie, Depends, HTTPException, status, Body
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import pymongo

RAPHIIA_ROOT = os.environ.get("RAPHIIA_ROOT", "/home/rlopez/projects/raphiia-openai")
if RAPHIIA_ROOT not in sys.path:
    sys.path.insert(0, RAPHIIA_ROOT)

from raphiia_openai import portal_bridge  # noqa: E402
from raphiia_openai.ops_routes import router as ops_router  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI(title="Ralphi IA Control Center")
app.include_router(ops_router)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTAL_DIR = os.path.join(BASE_DIR, "portal")
SERVICES_JSON = os.path.join(PORTAL_DIR, "services.json")
SERVICES_BACKUP_DIR = os.path.join(PORTAL_DIR, "backups")

ACTIVE_SESSIONS = {}

def get_db():
    try:
        # Use hackathon_autopilot to share the users collection
        client = pymongo.MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=2000)
        return client["hackathon_autopilot"]
    except Exception as e:
        logging.error(f"Error connecting to MongoDB: {e}")
        return None

async def get_current_user(session_token: str = Cookie(None)):
    if not session_token:
        return None
    db = get_db()
    if db is not None:
        try:
            sess = db.sessions.find_one({"session_token": session_token})
            if sess:
                return sess["username"]
        except Exception as e:
            logging.error(f"Error verifying session: {e}")
    return None

def get_user_record(username: str | None):
    if not username:
        return None
    db = get_db()
    if db is not None:
        try:
            return db.users.find_one({"username": username}, {"password_hash": 0})
        except Exception as e:
            logging.error(f"Error querying user record: {e}")
    return None

def is_admin_user(username: str | None) -> bool:
    user = get_user_record(username)
    role = (user or {}).get("role", "")
    return username in {"admin", "rlopez"} or role == "admin"

def load_services_config():
    if os.path.exists(SERVICES_JSON):
        with open(SERVICES_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"featured": [], "services": []}

def save_services_config(config: dict):
    os.makedirs(SERVICES_BACKUP_DIR, exist_ok=True)
    if os.path.exists(SERVICES_JSON):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        shutil.copy2(SERVICES_JSON, os.path.join(SERVICES_BACKUP_DIR, f"services.{stamp}.json"))
    tmp_path = f"{SERVICES_JSON}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, SERVICES_JSON)

def port_is_open(host: str, port: int, timeout: float = 0.45) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False

def service_items(config: dict):
    for item in config.get("featured", []):
        yield item
    for item in config.get("services", []):
        yield item

def safe_service_payload(payload: dict) -> dict:
    service_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(payload.get("id", "")).strip().lower()).strip("-")
    if not service_id:
        raise HTTPException(status_code=400, detail="ID invalido")
    name = str(payload.get("name", "")).strip()
    desc = str(payload.get("desc", "")).strip()
    section = str(payload.get("section", "")).strip() or "Servicios"
    if not name or not desc:
        raise HTTPException(status_code=400, detail="Nombre y descripcion son obligatorios")
    try:
        port = int(payload.get("port"))
    except Exception:
        raise HTTPException(status_code=400, detail="Puerto invalido")
    if port < 1 or port > 65535:
        raise HTTPException(status_code=400, detail="Puerto fuera de rango")
    company = str(payload.get("company", "both")).strip()
    if company not in {"both", "pcdoctor", "innerchispa"}:
        company = "both"
    path = str(payload.get("path", "")).strip()
    if path and not path.startswith("/"):
        path = f"/{path}"
    item = {
        "id": service_id,
        "section": section,
        "company": company,
        "name": name,
        "desc": desc,
        "port": port,
        "path": path,
        "icon": str(payload.get("icon", "▣")).strip() or "▣",
    }
    if payload.get("web") is False:
        item["web"] = False
    public_url = str(payload.get("public_url", "") or payload.get("publicUrl", "")).strip()
    if public_url:
        item["public_url"] = public_url
    return item

@app.get("/projects")
async def projects_redirect(user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/#project-panel")

@app.get("/", response_class=HTMLResponse)
async def get_portal(user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login")
    
    index_path = os.path.join(PORTAL_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Inject username
            content = content.replace("<h1>Ralphi IA v2.0</h1>", f"<h1>Ralphi IA v2.0 <span style='font-size:1rem;font-weight:normal;color:#8b5cf6;'>(Usuario: {user})</span></h1>")
            response = HTMLResponse(content=content)
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response
    return HTMLResponse(content="<h1>index.html not found</h1>", status_code=404)

@app.get("/login", response_class=HTMLResponse)
async def get_login_page(user: str = Depends(get_current_user)):
    if user:
        return RedirectResponse(url="/")
    
    login_html = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Iniciar Sesión — Ralphi IA</title>
      <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;800&display=swap" rel="stylesheet">
      <style>
        :root {
          --bg: #05070a;
          --surface: rgba(255, 255, 255, 0.03);
          --border: rgba(255, 255, 255, 0.08);
          --accent: #5bd8ff;
          --text: #f1f5f9;
          --muted: #94a3b8;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
          font-family: 'Outfit', sans-serif;
          background-color: var(--bg);
          color: var(--text);
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          min-height: 100vh;
          overflow: hidden;
          position: relative;
        }
        body::before {
          content: "";
          position: absolute;
          width: 420px; height: 420px;
          background: radial-gradient(circle, rgba(91, 216, 255, 0.22) 0%, transparent 70%);
          top: 5%; left: 15%; filter: blur(50px);
          animation: float 12s ease-in-out infinite;
        }
        body::after {
          content: "";
          position: absolute;
          width: 380px; height: 380px;
          background: radial-gradient(circle, rgba(139, 92, 246, 0.18) 0%, transparent 70%);
          bottom: 5%; right: 10%; filter: blur(50px);
          animation: float 14s ease-in-out infinite reverse;
        }
        @keyframes float { 0%,100%{ transform: translate(0,0); } 50%{ transform: translate(12px,-8px); } }
        .splash { text-align: center; margin-bottom: 1.75rem; position: relative; z-index: 10; }
        .splash h1 {
          font-size: 2.4rem; font-weight: 800; letter-spacing: -0.02em; margin: 0;
          background: linear-gradient(92deg, #5bd8ff, #78a8ff, #c4a5ff);
          -webkit-background-clip: text; background-clip: text; color: transparent;
        }
        .splash .tag { color: #5bd8ff; font-size: 1.05rem; margin-top: 0.35rem; font-weight: 600; }
        .splash .ver { display: inline-block; margin-top: 0.65rem; font-size: 0.72rem; font-weight: 700;
          letter-spacing: 0.12em; padding: 5px 12px; border-radius: 999px;
          border: 1px solid rgba(91,216,255,.35); color: #5bd8ff; background: rgba(91,216,255,.08); }
        .container {
          background: var(--surface);
          border: 1px solid var(--border);
          padding: 2.5rem;
          border-radius: 20px;
          width: 100%;
          max-width: 420px;
          backdrop-filter: blur(20px);
          -webkit-backdrop-filter: blur(20px);
          box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
          position: relative;
          z-index: 10;
        }
        h2 { font-size: 1.8rem; margin-bottom: 0.5rem; font-weight: 700; text-align: center; }
        p.subtitle { color: var(--muted); text-align: center; font-size: 0.88rem; margin-bottom: 2rem; }
        .form-group { margin-bottom: 1.25rem; display: flex; flex-direction: column; gap: 0.4rem; }
        label { font-size: 0.82rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; display: block; margin-bottom: 0.4rem; }
        input {
          width: 100%;
          background: rgba(255, 255, 255, 0.04);
          border: 1px solid var(--border);
          border-radius: 10px;
          padding: 0.8rem 1rem;
          color: #fff;
          font-size: 0.95rem;
          outline: none;
          transition: border-color 0.3s;
        }
        input:focus { border-color: var(--accent); }
        button {
          width: 100%;
          background: linear-gradient(135deg, #24617f, #5bd8ff);
          color: #041018;
          border: none;
          padding: 0.9rem;
          border-radius: 10px;
          font-weight: 700;
          font-size: 1rem;
          cursor: pointer;
          transition: transform 0.2s, box-shadow 0.2s;
          margin-top: 0.5rem;
          box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4);
        }
        button:hover { transform: translateY(-1px); box-shadow: 0 6px 20px rgba(139, 92, 246, 0.5); }
        .toggle-mode { text-align: center; margin-top: 1.5rem; font-size: 0.88rem; color: var(--muted); }
        .toggle-mode a { color: var(--accent); text-decoration: none; font-weight: 600; }
        .toggle-mode a:hover { text-decoration: underline; }
        .hidden { display: none !important; }
      </style>
    </head>
    <body>
      <div class="splash">
        <h1>Ralphi IA</h1>
        <p class="tag">your second brain</p>
        <span class="ver">VERSION 2.0</span>
      </div>
      <div class="container" id="login-box">
        <h2>Iniciar sesión</h2>
        <p class="subtitle">Control Center · ecosistema multi-entidad</p>
        <form action="/api/auth/login" method="POST">
          <div class="form-group">
            <label for="user">Usuario</label>
            <input type="text" id="user" name="username" required placeholder="Ingresa tu usuario">
          </div>
          <div class="form-group">
            <label for="pass">Contraseña</label>
            <input type="password" id="pass" name="password" required placeholder="Ingresa tu contraseña">
          </div>
          <button type="submit">Entrar al Ecosistema</button>
        </form>
        <div class="toggle-mode">
          ¿No tienes cuenta? <a href="#" onclick="toggleRegister(true)">Crear cuenta</a>
        </div>
      </div>

      <div class="container hidden" id="register-box">
        <h2>Crear Usuario</h2>
        <p class="subtitle">Registra una nueva cuenta en el servidor</p>
        <form action="/api/auth/register" method="POST">
          <div class="form-group">
            <label for="reg-user">Usuario</label>
            <input type="text" id="reg-user" name="username" required placeholder="Crea un nombre de usuario">
          </div>
          <div class="form-group">
            <label for="reg-pass">Contraseña</label>
            <input type="password" id="reg-pass" name="password" required placeholder="Crea una contraseña segura">
          </div>
          <button type="submit" style="background:#3b82f6; box-shadow:0 4px 15px rgba(59, 130, 246, 0.4);">Registrarse & Entrar</button>
        </form>
        <div class="toggle-mode">
          ¿Ya tienes cuenta? <a href="#" onclick="toggleRegister(false)">Iniciar Sesión</a>
        </div>
      </div>

      <script>
        function toggleRegister(showRegister) {
          if (showRegister) {
            document.getElementById('login-box').classList.add('hidden');
            document.getElementById('register-box').classList.remove('hidden');
          } else {
            document.getElementById('register-box').classList.add('hidden');
            document.getElementById('login-box').classList.remove('hidden');
          }
        }
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=login_html)

@app.post("/api/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    db = get_db()
    if db is not None:
        try:
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            user = db.users.find_one({"username": username, "password_hash": password_hash})
            if user:
                session_token = str(uuid.uuid4())
                db.sessions.update_one(
                    {"username": username},
                    {"$set": {"session_token": session_token}},
                    upsert=True
                )
                response = RedirectResponse(url="/", status_code=303)
                response.set_cookie(key="session_token", value=session_token, httponly=True)
                return response
            else:
                return HTMLResponse(content="<h3>Usuario o contraseña incorrectos. <a href='/login'>Intentar de nuevo</a></h3>", status_code=401)
        except Exception as e:
            return HTMLResponse(content=f"<h3>Error: {e}</h3>", status_code=500)
    return HTMLResponse(content="<h3>Sin conexión a DB.</h3>", status_code=500)

@app.post("/api/auth/register")
async def register(username: str = Form(...), password: str = Form(...)):
    db = get_db()
    if db is not None:
        try:
            existing = db.users.find_one({"username": username})
            if existing:
                return HTMLResponse(content="<h3>El usuario ya existe. <a href='/login'>Intentar de nuevo</a></h3>", status_code=400)
            
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            new_user = {
                "username": username,
                "password_hash": password_hash,
                "role": "user"
            }
            db.users.insert_one(new_user)
            
            session_token = str(uuid.uuid4())
            db.sessions.update_one(
                {"username": username},
                {"$set": {"session_token": session_token}},
                upsert=True
            )
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie(key="session_token", value=session_token, httponly=True)
            return response
        except Exception as e:
            return HTMLResponse(content=f"<h3>Error: {e}</h3>", status_code=500)
    return HTMLResponse(content="<h3>Sin conexión a DB.</h3>", status_code=500)

@app.post("/api/auth/logout")
async def logout(session_token: str = Cookie(None)):
    db = get_db()
    if db is not None and session_token:
        try:
            db.sessions.delete_one({"session_token": session_token})
        except Exception as e:
            logging.error(f"Error deleting session: {e}")
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="session_token")
    return response

@app.get("/services.json")
async def get_services(user: str = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    response = JSONResponse(content=load_services_config())
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/api/portal/overview")
async def portal_overview(user: str = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    record = get_user_record(user) or {"username": user}
    config = load_services_config()
    mongo_summary = {"ok": False, "counts": {}}
    latest_ideas = []
    latest_pipeline = []
    try:
        client = pymongo.MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=1200)
        db = client["pcdoctor_swarm"]
        collections = [
            "clients",
            "ideas",
            "editorial_pipeline",
            "raphiia_openai_conversations",
            "raphiia_openai_messages",
            "chat_messages",
        ]
        mongo_summary = {
            "ok": True,
            "db": "pcdoctor_swarm",
            "counts": {name: db[name].count_documents({}) for name in collections},
        }
        latest_ideas = [
            {
                "_id": str(doc.get("_id")),
                "title": doc.get("title", ""),
                "status": doc.get("status", ""),
                "created_at": doc.get("created_at", ""),
                "tags": doc.get("tags", []),
                "body": (doc.get("body") or doc.get("content") or "")[:240],
            }
            for doc in db["ideas"].find({}, {"title": 1, "status": 1, "created_at": 1, "tags": 1, "body": 1, "content": 1})
            .sort("created_at", -1)
            .limit(6)
        ]
        latest_pipeline = [
            {
                "_id": str(doc.get("_id")),
                "title": doc.get("title", ""),
                "status": doc.get("status", ""),
                "channel": doc.get("channel", ""),
                "created_at": doc.get("created_at", ""),
                "markdown": (doc.get("markdown") or doc.get("body") or "")[:240],
            }
            for doc in db["editorial_pipeline"].find({}, {"title": 1, "status": 1, "channel": 1, "created_at": 1, "markdown": 1, "body": 1})
            .sort("created_at", -1)
            .limit(6)
        ]
    except Exception as e:
        mongo_summary = {"ok": False, "error": str(e), "counts": {}}
    content = {
        "portal_ok": True,
        "user": {
            "username": user,
            "role": record.get("role", "user"),
            "is_admin": is_admin_user(user),
        },
        "service_count": len(list(service_items(config))),
        "mcp_hint": "127.0.0.1:8102/mcp",
        "mongo": mongo_summary,
        "latest_ideas": latest_ideas,
        "latest_pipeline": latest_pipeline,
    }
    content = portal_bridge.enrich_portal_overview(content)
    response = JSONResponse(content=content)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.get("/api/services/status")
async def services_status(user: str = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    config = load_services_config()
    enriched = portal_bridge.services_health_enriched(config)
    response = JSONResponse(content=enriched)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.post("/api/services")
async def add_service(payload: dict = Body(...), user: str = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Solo admin puede registrar servicios")
    item = safe_service_payload(payload)
    target = "featured" if payload.get("target") == "featured" else "services"
    config = load_services_config()
    config.setdefault("featured", [])
    config.setdefault("services", [])
    existing_ids = {entry.get("id") for entry in service_items(config)}
    if item["id"] in existing_ids:
        raise HTTPException(status_code=409, detail="Ya existe un servicio con ese ID")
    config[target].append(item)
    save_services_config(config)
    return JSONResponse(content={"ok": True, "service": item, "target": target})

@app.get("/assets/{filename}")
async def get_assets(filename: str):
    from fastapi.responses import FileResponse
    asset_path = os.path.join(PORTAL_DIR, "assets", filename)
    if os.path.exists(asset_path):
        return FileResponse(asset_path)
    return HTMLResponse(content="Not Found", status_code=404)

@app.get("/api/users")
async def get_users_list(user: str = Depends(get_current_user)):
    if not user:
         raise HTTPException(status_code=401, detail="No autorizado")
    db = get_db()
    usernames = []
    if db is not None:
        try:
            users = db.users.find({}, {"username": 1, "_id": 0})
            usernames = [u["username"] for u in users]
        except Exception as e:
            logging.error(f"Error querying users: {e}")
    return JSONResponse(content=usernames)


@app.get("/api/system/resources")
async def api_system_resources(user: str = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    return JSONResponse(content=portal_bridge.system_resources())


@app.get("/api/ports/registry")
async def api_ports_registry(
    user: str = Depends(get_current_user),
    operational_only: bool = True,
    all_ports: bool = False,
):
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    return JSONResponse(
        content=portal_bridge.ports_registry(operational_only=not all_ports and operational_only)
    )


@app.get("/api/oauth/users")
async def api_oauth_users(user: str = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Solo admin")
    return JSONResponse(content=portal_bridge.oauth_users_payload())


@app.get("/api/oauth/clients")
async def api_oauth_clients(user: str = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Solo admin")
    return JSONResponse(content=portal_bridge.oauth_clients_payload())


@app.post("/api/oauth/users/{username}/revoke")
async def api_oauth_revoke_user(username: str, user: str = Depends(get_current_user)):
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Solo admin")
    return JSONResponse(content=portal_bridge.revoke_user_tokens(username))


@app.post("/api/oauth/tokens/revoke-all")
async def api_oauth_revoke_all(user: str = Depends(get_current_user)):
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Solo admin")
    return JSONResponse(content=portal_bridge.revoke_all_oauth_tokens())


@app.post("/api/oauth/users")
async def api_oauth_save_user(payload: dict = Body(...), user: str = Depends(get_current_user)):
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Solo admin")
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Sin DB")
    username = str(payload.get("username", "")).strip()
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    patch = {
        "role": payload.get("role", "user"),
        "oauth_enabled": bool(payload.get("oauth_enabled")),
        "oauth_scopes": payload.get("oauth_scopes") or [],
    }
    password = payload.get("password")
    if password:
        patch["password_hash"] = hashlib.sha256(str(password).encode()).hexdigest()
    db.users.update_one({"username": username}, {"$set": patch, "$setOnInsert": {"username": username}}, upsert=True)
    return JSONResponse(content={"ok": True, "user": {"username": username, **patch}})


@app.get("/api/ops/summary")
async def api_ops_summary(user: str = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    return JSONResponse(content=portal_bridge.ops_overview_payload())
