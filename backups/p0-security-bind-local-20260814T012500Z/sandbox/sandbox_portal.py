#!/usr/bin/env python3
"""Portal web simple — chat/imagen/vídeo sandbox (puerto 3003)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
TOOLS = ROOT / "sandbox_tools.py"
PORT = int(os.getenv("SANDBOX_PORTAL_PORT", "3003"))
NODE = os.getenv("SANDBOX_NODE", "intel").upper()
MODEL = os.getenv("SANDBOX_MODEL", "dolphin-llama3:8b")
WEBUI = os.getenv("SANDBOX_WEBUI_URL", "http://192.168.1.4:3002" if NODE == "INTEL" else "http://192.168.1.5:3004")


def run_tool(args: list[str], timeout: int = 600) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [sys.executable, str(TOOLS), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        # No mostrar tracebacks Python al usuario del portal
        lines = [ln for ln in out.strip().splitlines() if not ln.startswith("Traceback") and "File \"" not in ln]
        clean = "\n".join(lines).strip()
        if proc.returncode != 0 and not clean:
            clean = "Error interno del sandbox. Reintenta en unos segundos."
        return proc.returncode, clean
    except subprocess.TimeoutExpired:
        return 1, "Tiempo de espera agotado. El modelo tardó demasiado — prueba una pregunta más corta."


PAGE = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sandbox IA — Intel</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;background:#0f1117;color:#e8eaed}
  h1{color:#7cb3ff} a{color:#7cb3ff}
  .card{background:#1a1d27;border:1px solid #333;border-radius:12px;padding:1rem;margin:1rem 0}
  input,textarea,select{width:100%;box-sizing:border-box;margin:.4rem 0;padding:.6rem;border-radius:8px;border:1px solid #444;background:#111;color:#eee}
  button{background:#2563eb;color:#fff;border:0;padding:.7rem 1.2rem;border-radius:8px;cursor:pointer;margin-top:.5rem}
  pre{background:#111;padding:1rem;border-radius:8px;overflow:auto;white-space:pre-wrap}
  .imgs{display:flex;flex-wrap:wrap;gap:.5rem} .imgs img{max-width:280px;border-radius:8px}
</style></head><body>
<h1>Sandbox IA ({node}) — uncensored</h1>
<p>Modelo: <b>{model}</b> · Open WebUI: <a href="{webui}" target="_blank">{webui}</a></p>
<div class="card"><h2>Estado</h2><pre id="status">Cargando...</pre><button onclick="loadStatus()">Refrescar</button></div>
<div class="card"><h2>Chat rápido</h2>
<textarea id="chatmsg" rows="3" placeholder="Escribe tu mensaje..."></textarea>
<button onclick="doChat()">Enviar</button><pre id="chatout"></pre></div>
<div class="card"><h2>Generar imagen (ComfyUI)</h2>
<input id="imgprompt" placeholder="Describe la imagen..." value="paisaje futurista al atardecer">
<button onclick="doImage()">Generar imagen</button><pre id="imgout"></pre><div class="imgs" id="imgpreview"></div></div>
<div class="card"><h2>Generar vídeo corto</h2>
<input id="vtitle" placeholder="Título" value="Clip sandbox">
<textarea id="vscript" rows="2" placeholder="Guion: escena uno. escena dos.">Primera escena de prueba. Segunda escena.</textarea>
<button onclick="doVideo()">Generar vídeo (puede tardar ~1 min)</button><pre id="vidout"></pre></div>
<script>
async function api(path, body) {
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});
  return r.json();
}
async function loadStatus(){ document.getElementById('status').textContent = JSON.stringify(await api('/api/status'), null, 2); }
async function doChat(){ document.getElementById('chatout').textContent='Pensando...'; const j=await api('/api/chat',{message:document.getElementById('chatmsg').value}); document.getElementById('chatout').textContent=j.output||j.error; }
async function doImage(){ document.getElementById('imgout').textContent='Generando...'; const j=await api('/api/image',{prompt:document.getElementById('imgprompt').value}); document.getElementById('imgout').textContent=j.output||j.error; if(j.file){ const d=document.getElementById('imgpreview'); const i=document.createElement('img'); i.src='/outputs/'+j.file; d.prepend(i);} }
async function doVideo(){ document.getElementById('vidout').textContent='Generando vídeo...'; const j=await api('/api/video',{title:document.getElementById('vtitle').value, script:document.getElementById('vscript').value}); document.getElementById('vidout').textContent=j.output||j.error; }
loadStatus();
</script></body></html>""".format(node=NODE, model=MODEL, webui=WEBUI)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        return json.loads(self.rfile.read(n))

    def do_GET(self) -> None:
        path = urlparse(self.path)
        if path.path in ("/", "/index.html"):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        if path.path.startswith("/outputs/"):
            fp = OUTPUTS / path.path.split("/outputs/", 1)[1]
            if fp.is_file() and fp.resolve().parent == OUTPUTS.resolve():
                data = fp.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png" if fp.suffix == ".png" else "application/octet-stream")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404)
            return
        if path.path == "/api/status":
            rc, out = run_tool(["status"], timeout=30)
            try:
                self._json(200, json.loads(out))
            except json.JSONDecodeError:
                self._json(200, {"ok": rc == 0, "output": out})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        data = self._read_json()
        if path == "/api/status":
            rc, out = run_tool(["status"], timeout=30)
            self._json(200, {"ok": rc == 0, "raw": out})
            return
        if path == "/api/chat":
            msg = (data.get("message") or "").strip()
            if not msg:
                self._json(400, {"error": "mensaje vacío"})
                return
            rc, out = run_tool(["chat", msg], timeout=360)
            self._json(200, {"ok": rc == 0, "output": out, "error": None if rc == 0 else out})
            return
        if path == "/api/image":
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                self._json(400, {"error": "prompt vacío"})
                return
            rc, out = run_tool(["image", prompt, "--width", "1024", "--height", "1024"], timeout=300)
            file = None
            for line in out.splitlines():
                if "outputs/" in line and line.endswith(".png"):
                    file = Path(line.split("outputs/")[-1].strip()).name
            self._json(200, {"ok": rc == 0, "output": out, "file": file})
            return
        if path == "/api/video":
            title = (data.get("title") or "Clip sandbox").strip()
            script = (data.get("script") or title).strip()
            rc, out = run_tool(["video", title, "--script", script, "--scenes", "2"], timeout=600)
            self._json(200, {"ok": rc == 0, "output": out})
            return
        self.send_error(404)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[portal] {self.address_string()} {fmt % args}")


def main() -> None:
    OUTPUTS.mkdir(exist_ok=True)
    host = "0.0.0.0"
    print(f"Sandbox portal http://{host}:{PORT}")
    HTTPServer((host, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
