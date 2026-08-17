"""Gateway voz RalfIA — Android, iPhone, tablet, navegador (PWA).

Whisper STT → contexto Rafael (Mongo+Qdrant) → Ollama → Piper TTS

v4 Fluid Assistant: wake «Hola RalfIA», VAD en browser, barge-in, /api/voice/turn.
v5 (roadmap): avatar video SadTalker/Wav2Lip; satélites RPi con wake word en dispositivo.
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

from raphiia_openai.hybrid_context import qdrant_health
from raphiia_openai import mongo_store
from raphiia_openai.settings import GOOGLE_API_KEY, OLLAMA_ROUTER_URL, OLLAMA_URL, RALFIA_OWNER_ID, WHISPER_URL, EDITORIAL_MEDIA_ROOT
from raphiia_openai.user_context import get_user_context, user_search
from raphiia_openai import voice_auth
from raphiia_openai import voice_identity
from raphiia_openai import voice_mcp_bridge
from raphiia_openai import voice_mcp_executor
from raphiia_openai import voice_user_profile
from raphiia_openai.video_pipeline import tts

VOICE_MODEL = os.getenv("VOICE_CHAT_MODEL", "qwen2.5:14b-instruct-q4_K_M")
VOICE_HEAVY_MODEL = os.getenv("VOICE_HEAVY_MODEL", "qwen2.5:32b-instruct-q4_K_M")
VLLM_URL = os.getenv("VLLM_URL", "http://127.0.0.1:8000").rstrip("/")
VLLM_MODEL = os.getenv("VLLM_MODEL", VOICE_MODEL)
OLLAMA_CHAT = os.getenv("OLLAMA_CHAT_URL", OLLAMA_ROUTER_URL or OLLAMA_URL).rstrip("/")
OLLAMA_DIRECT = os.getenv("OLLAMA_DIRECT_URL", OLLAMA_URL).rstrip("/")
USE_VLLM = os.getenv("VOICE_USE_VLLM", "0").strip().lower() in ("1", "true", "yes")
VLLM_PRIMARY = os.getenv("VLLM_PRIMARY", "0").strip().lower() in ("1", "true", "yes")
VLLM_MAX_TOKENS = int(os.getenv("VLLM_MAX_TOKENS", "512"))
VLLM_CONTEXT_CHARS = int(os.getenv("VLLM_CONTEXT_CHARS", "2500"))
VLLM_HISTORY_LIMIT = int(os.getenv("VLLM_HISTORY_LIMIT", "8"))
VOICE_LOCAL_FIRST = os.getenv("VOICE_LOCAL_FIRST", "1").strip().lower() in ("1", "true", "yes")
VOICE_CHAT_BACKEND = os.getenv("VOICE_CHAT_BACKEND", "auto").strip().lower()
GEMINI_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
VOICE_HISTORY_LIMIT = int(os.getenv("VOICE_HISTORY_LIMIT", "40"))
VOICE_FLUID_MODEL = os.getenv("VOICE_FLUID_MODEL", "qwen2.5:7b-instruct-q4_K_M")
VOICE_FLUID_FAST = os.getenv("VOICE_FLUID_FAST", "1").strip().lower() in ("1", "true", "yes")
VOICE_FLUID_MAX_TOKENS = int(os.getenv("VOICE_FLUID_MAX_TOKENS", "256"))
WAKE_RE = re.compile(r"\b(hola|hey|ok)\s+ralf(i|ia|i\s*ia)?\b", re.I)
STOP_RE = re.compile(r"\b(detente|para(mos)?(\s+la\s+conversaci[oó]n)?|stop|silencio|basta|ap[aá]gate)\b", re.I)
COL_VOICE_MESSAGES = "ralfia_voice_messages"
COL_VOICE_CONVERSATIONS = "ralfia_voice_conversations"
VOICE_IMAGE_TIMEOUT = float(os.getenv("VOICE_IMAGE_TIMEOUT", "180"))
IMAGE_JOBS: dict[str, dict[str, Any]] = {}
_IMAGE_JOBS_LOCK = threading.Lock()
_BUSINESS_KEYWORDS = (
    "cliente", "clientes", "cotiz", "empresa", "factura", "proyecto",
    "proveedor", "visita", "inventario", "inner", "doctor", "rafael",
    "tuya", "domótica", "domotica", "correo", "email",
)
WHISPER = WHISPER_URL.rstrip("/")
VOICE_PUBLIC_URL_FILE = Path(
    os.getenv("VOICE_PUBLIC_URL_FILE", "/home/rlopez/data/ralfia/voice_public_url.txt")
)
DEFAULT_HTTPS_URLS = (
    "https://voz.pcdoctor.ai",
    "https://sworn-profusely-alongside.ngrok-free.dev/ralfia-voz",
)
VOICE_SAMPLES_ROOT = Path(os.getenv("VOICE_SAMPLES_ROOT", "/home/rlopez/data/ralfia/voice_samples"))
USER_SPEAKER_ALIASES = {
    "rlopez": "rafael",
    "rafagye": "rafael",
    "admin": "rafael",
}


def _speaker_for_user(user: dict[str, Any]) -> str:
    from raphiia_openai import voice_xtts

    uname = str(user.get("username") or "user").lower().strip()
    mapped = USER_SPEAKER_ALIASES.get(uname, uname)
    sp = voice_xtts._safe_speaker(mapped)
    own_dir = VOICE_SAMPLES_ROOT / uname
    sp_dir = VOICE_SAMPLES_ROOT / sp
    if own_dir.is_dir() and any(own_dir.iterdir()) and not any(sp_dir.iterdir() if sp_dir.is_dir() else []):
        return voice_xtts._safe_speaker(uname)
    return sp


def _default_tts_voice_id() -> str:
    try:
        from raphiia_openai import voice_xtts

        for sp, job in voice_xtts._load_jobs().items():
            if job.get("status") == "ready" and job.get("active"):
                return f"xtts:{sp}"
        for sp, job in voice_xtts._load_jobs().items():
            if job.get("status") == "ready":
                return f"xtts:{sp}"
    except Exception:
        pass
    if tts.PIPER_MODEL.is_file():
        return str(tts.PIPER_MODEL.resolve())
    return "espeak"


def _public_https_urls() -> list[str]:
    urls: list[str] = []
    extra = os.getenv("VOICE_PUBLIC_URL", "").strip()
    if extra:
        urls.append(extra.rstrip("/"))
    if VOICE_PUBLIC_URL_FILE.is_file():
        for line in VOICE_PUBLIC_URL_FILE.read_text(encoding="utf-8").splitlines():
            u = line.strip().rstrip("/")
            if u.startswith("https://") and u not in urls:
                urls.append(u)
    for u in DEFAULT_HTTPS_URLS:
        if u not in urls:
            urls.append(u)
    return urls

app = FastAPI(title="RalfIA Voice", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LEGACY_PREFIXES = ("/ralfia-voz", "/voice")


def _strip_legacy_voice_prefix(path: str) -> str | None:
    for prefix in LEGACY_PREFIXES:
        if path == prefix or path == f"{prefix}/":
            return "/"
        if path.startswith(f"{prefix}/"):
            suffix = path[len(prefix):]
            return suffix or "/"
    return None


@app.middleware("http")
async def legacy_voice_prefix_middleware(request: Request, call_next):
    rewritten = _strip_legacy_voice_prefix(request.scope.get("path", ""))
    if rewritten is not None:
        request.scope["path"] = rewritten
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

PWA_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover"/>
<meta name="apple-mobile-web-app-capable" content="yes"/>
<meta name="mobile-web-app-capable" content="yes"/>
<meta name="theme-color" content="#070b14"/>
<link rel="manifest" href="/manifest.json"/>
<link rel="icon" href="/icon.svg" type="image/svg+xml"/>
<link rel="apple-touch-icon" href="/icon.svg"/>
<meta name="apple-mobile-web-app-title" content="Ralphi IA"/>
<title>Ralphi IA</title>
<style>
:root{
  --bg:#070b14;--surface:#0f1628;--surface2:#151f35;--border:#1e2d4a;
  --text:#e8edf7;--muted:#8b9cb8;--accent:#38bdf8;--accent2:#818cf8;
  --user:#1d4ed8;--bot:#151f35;--glow:rgba(56,189,248,.35);
  --safe-b:env(safe-area-inset-bottom,0px);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);
  background-image:radial-gradient(ellipse 80% 50% at 50% -20%,rgba(56,189,248,.12),transparent),
    radial-gradient(ellipse 60% 40% at 100% 100%,rgba(129,140,248,.08),transparent)}
.app{display:flex;flex-direction:column;height:100dvh;max-width:720px;margin:0 auto}

/* Header */
.hdr{display:flex;align-items:center;gap:.85rem;padding:.85rem 1rem .75rem;
  border-bottom:1px solid var(--border);background:rgba(15,22,40,.85);backdrop-filter:blur(12px)}
.orb-wrap{position:relative;width:44px;height:44px;flex-shrink:0;cursor:pointer}
.orb-mesh{position:absolute;inset:-18px;border-radius:50%;opacity:.55;filter:blur(14px);pointer-events:none;
  background:linear-gradient(135deg,#38bdf8,#818cf8,#6366f1);background-size:200% 200%;
  animation:meshIdle 8s ease-in-out infinite}
.orb-wrap.state-listening .orb-mesh{background:linear-gradient(135deg,#22d3ee,#34d399,#06b6d4);animation:meshListen 3s ease-in-out infinite}
.orb-wrap.state-standby .orb-mesh{background:linear-gradient(135deg,#1e3a5f,#2563eb,#1d4ed8);opacity:.35;animation:meshStandby 5s ease-in-out infinite}
.orb-wrap.state-thinking .orb-mesh{background:linear-gradient(135deg,#fbbf24,#f59e0b,#fb923c);animation:meshThink 4s linear infinite}
.orb-wrap.state-speaking .orb-mesh{background:linear-gradient(135deg,#a78bfa,#c084fc,#818cf8);animation:meshSpeak 2.5s ease-in-out infinite}
@keyframes meshIdle{0%,100%{background-position:0% 50%;opacity:.45;transform:scale(1)}50%{background-position:100% 50%;opacity:.65;transform:scale(1.08)}}
@keyframes meshStandby{0%,100%{opacity:.25;transform:scale(.92)}50%{opacity:.45;transform:scale(1.02)}}
@keyframes meshListen{0%,100%{background-position:0% 0%;opacity:.55}50%{background-position:100% 100%;opacity:.75}}
@keyframes meshThink{0%{background-position:0% 50%;transform:rotate(0deg)}100%{background-position:100% 50%;transform:rotate(360deg)}}
@keyframes meshSpeak{0%,100%{background-position:50% 0%;opacity:.5;transform:scale(.95)}50%{background-position:50% 100%;opacity:.8;transform:scale(1.12)}}
.orb{position:relative;z-index:1;width:44px;height:44px;border-radius:50%;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  box-shadow:0 0 24px var(--glow);transition:transform .3s,box-shadow .3s}
.orb-letter{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font-weight:700;font-size:1.05rem;color:#fff;z-index:2;pointer-events:none;line-height:1}
.orb-menu{position:absolute;top:calc(100% + 6px);left:0;z-index:95;min-width:188px;
  background:var(--surface);border:1px solid var(--border);border-radius:.65rem;padding:.35rem 0;
  box-shadow:0 8px 28px rgba(0,0,0,.5);display:none}
.orb-menu.open{display:block}
.orb-menu button{display:block;width:100%;text-align:left;padding:.55rem .85rem;border:none;
  background:transparent;color:var(--text);font:inherit;font-size:.82rem;cursor:pointer}
.orb-menu button:hover,.orb-menu button:active{background:var(--surface2)}
.orb-menu-divider{height:1px;background:var(--border);margin:.3rem 0}
.orb-menu-user{padding:.4rem .85rem .55rem;font-size:.7rem;color:var(--muted);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:188px}
.orb.listening{animation:orbPulse 1.4s ease-in-out infinite}
.orb.thinking{animation:orbSpin 2s linear infinite}
.orb.speaking{animation:orbSpeak .6s ease-in-out infinite alternate}
.orb.generating{animation:orbSpin 3s linear infinite;filter:hue-rotate(45deg)}
@keyframes orbPulse{0%,100%{transform:scale(1);box-shadow:0 0 20px var(--glow)}50%{transform:scale(1.08);box-shadow:0 0 36px var(--glow)}}
@keyframes orbSpin{to{filter:hue-rotate(30deg)}}
@keyframes orbSpeak{from{transform:scale(1)}to{transform:scale(1.05)}}
.orb-ring{position:absolute;inset:-4px;border-radius:50%;border:2px solid transparent;
  border-top-color:var(--accent);opacity:0;transition:opacity .3s}
.orb-wrap.active .orb-ring{opacity:1;animation:ringSpin .8s linear infinite}
@keyframes ringSpin{to{transform:rotate(360deg)}}
.hdr-text{flex:1;min-width:0;overflow:hidden}
.hdr-text h1{font-size:1.05rem;font-weight:600;letter-spacing:-.02em}
.hdr-text p{font-size:.72rem;color:var(--muted);margin-top:.1rem}
.hdr-text p.status-line{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:.15rem}
.hdr-text p.status-meta{display:flex;align-items:center;gap:.35rem;margin-top:.08rem;min-height:0}
.hdr-text p.status-meta:empty{display:none}
#histBadge{font-size:.62rem;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%}
@media (max-width:640px){.hdr-actions{display:none!important}}
.status-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:#22c55e;margin-right:.35rem;
  box-shadow:0 0 8px #22c55e88}
.status-dot.busy{background:#f59e0b;box-shadow:0 0 8px #f59e0b88}
.status-dot.off{background:#64748b;box-shadow:none}

/* Warn banner */
#warn{display:none;background:#450a0a;color:#fecaca;padding:.65rem 1rem;font-size:.82rem;text-align:center;border-bottom:1px solid #7f1d1d}
#warn.show{display:block}

/* Chat */
.chat{flex:1;overflow-y:auto;padding:1rem .85rem 0;
  padding-bottom:calc(var(--composer-h,148px) + var(--safe-b) + .75rem);
  scroll-behavior:smooth;scroll-padding-bottom:calc(var(--composer-h,148px) + var(--safe-b) + .75rem);
  -webkit-overflow-scrolling:touch}
#chatSpacer{height:1px;flex-shrink:0;pointer-events:none}
.chat::-webkit-scrollbar{width:4px}
.chat::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
.welcome{text-align:center;padding:2rem 1rem 1.5rem;opacity:.9}
.welcome h2{font-size:1.35rem;font-weight:600;margin-bottom:.5rem;
  background:linear-gradient(90deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.welcome p{color:var(--muted);font-size:.88rem;line-height:1.5;max-width:320px;margin:0 auto}
.chips{display:flex;flex-wrap:wrap;gap:.45rem;justify-content:center;margin-top:1.1rem}
.chip{background:var(--surface2);border:1px solid var(--border);color:var(--text);
  padding:.45rem .75rem;border-radius:999px;font-size:.78rem;cursor:pointer;transition:background .2s,border-color .2s}
.chip:active{background:var(--surface);border-color:var(--accent)}

.msg{display:flex;gap:.65rem;margin-bottom:1rem;animation:fadeUp .35s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.msg.user{flex-direction:row-reverse}
.msg-av{width:32px;height:32px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:.75rem;font-weight:600}
.msg.bot .msg-av{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
.msg.user .msg-av{background:var(--user);color:#fff}
.bubble{max-width:82%;padding:.72rem .95rem;border-radius:1rem;font-size:.92rem;line-height:1.55;white-space:pre-wrap;word-break:break-word}
.msg.bot .bubble{background:var(--bot);border:1px solid var(--border);border-bottom-left-radius:.25rem}
.msg.user .bubble{background:linear-gradient(135deg,#1e40af,var(--user));border-bottom-right-radius:.25rem}
.bubble.error{background:#450a0a;border-color:#7f1d1d;color:#fecaca}

.typing{display:flex;gap:.65rem;margin-bottom:1rem;align-items:center}
.typing-dots{display:flex;gap:4px;padding:.8rem 1rem;background:var(--bot);border:1px solid var(--border);border-radius:1rem}
.typing-dots span{width:7px;height:7px;border-radius:50%;background:var(--muted);animation:dotBounce 1.2s infinite}
.typing-dots span:nth-child(2){animation-delay:.15s}
.typing-dots span:nth-child(3){animation-delay:.3s}
@keyframes dotBounce{0%,60%,100%{transform:translateY(0);opacity:.4}30%{transform:translateY(-5px);opacity:1}}

/* Composer */
.composer{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:100%;max-width:720px;
  padding:.65rem .85rem calc(.65rem + var(--safe-b));background:rgba(7,11,20,.92);
  backdrop-filter:blur(16px);border-top:1px solid var(--border)}
.composer-inner{display:flex;align-items:flex-end;gap:.5rem;background:var(--surface);
  border:1px solid var(--border);border-radius:1.25rem;padding:.45rem .55rem .45rem .85rem;
  transition:border-color .2s,box-shadow .2s}
.composer-inner:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px rgba(56,189,248,.12)}
#input{flex:1;border:none;background:transparent;color:var(--text);font:inherit;font-size:.95rem;
  resize:none;max-height:120px;line-height:1.45;padding:.35rem 0;outline:none}
#input::placeholder{color:var(--muted)}
.btn-icon{width:42px;height:42px;border:none;border-radius:50%;cursor:pointer;display:flex;
  align-items:center;justify-content:center;transition:transform .15s,background .2s;flex-shrink:0}
.btn-icon:active{transform:scale(.92)}
#btnSend{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
#btnSend:disabled{opacity:.35;cursor:not-allowed}
#btnMic{display:none!important}
.mode-btn.listening{background:#dc2626!important;color:#fff!important;border-color:#dc2626!important;animation:micPulse 1.2s infinite}
@keyframes micPulse{50%{box-shadow:0 0 0 8px rgba(220,38,38,.25)}}
.composer-hint{text-align:center;font-size:.68rem;color:var(--muted);margin-top:.4rem}
.mode-toggle{display:flex;gap:.35rem;justify-content:center;margin-bottom:.45rem}
.mode-btn{flex:1;max-width:160px;padding:.4rem .55rem;border-radius:999px;border:1px solid var(--border);
  background:var(--surface2);color:var(--muted);font-size:.72rem;cursor:pointer}
.mode-btn.active{background:rgba(56,189,248,.15);border-color:var(--accent);color:var(--accent)}
.mode-badge.fluid-standby{background:rgba(37,99,235,.2);color:#93c5fd;border:1px solid rgba(37,99,235,.35)}
.mode-badge.fluid-active{background:rgba(34,211,238,.15);color:#67e8f9;border:1px solid rgba(34,211,238,.35)}
#btnStop{display:none;background:#dc2626;color:#fff;border:none}
.msg-audio-bar{display:flex;align-items:center;gap:.4rem;margin-top:.5rem;padding-top:.35rem;border-top:1px solid rgba(255,255,255,.06)}
.speak-btn{flex-shrink:0;width:30px;height:30px;border-radius:50%;border:1px solid var(--border);
  background:var(--surface2);color:var(--text);cursor:pointer;font-size:.9rem;display:flex;align-items:center;justify-content:center;padding:0}
.speak-btn:hover,.speak-btn.playing{border-color:var(--accent);background:rgba(56,189,248,.15);color:var(--accent)}
.msg-audio-bar .audio-mini{flex:1;min-width:0;height:32px;max-width:100%}
.msg-audio-bar .audio-mini:not([src]),.msg-audio-bar:not(.has-url) .audio-mini{display:none}
.audio-player{margin-top:.55rem;width:100%}
.msg.user .bubble{position:relative}
.edit-btn{position:absolute;top:-8px;right:-8px;width:22px;height:22px;border-radius:50%;
  border:1px solid var(--border);background:var(--surface2);color:var(--muted);font-size:.65rem;cursor:pointer}
#loginScreen{position:fixed;inset:0;z-index:100;display:flex;align-items:center;justify-content:center;
  background:rgba(7,11,20,.96);backdrop-filter:blur(8px);padding:1rem}
#loginScreen.hidden{display:none}
.login-box{width:100%;max-width:360px;background:var(--surface);border:1px solid var(--border);
  border-radius:1rem;padding:1.5rem}
.login-box h2{font-size:1.2rem;margin-bottom:.35rem}
.login-box p{color:var(--muted);font-size:.85rem;margin-bottom:1rem;line-height:1.45}
.login-box input{width:100%;padding:.65rem .85rem;margin-bottom:.65rem;border-radius:.6rem;
  border:1px solid var(--border);background:var(--surface2);color:var(--text);font:inherit}
.login-box button{width:100%;padding:.75rem;border:none;border-radius:.65rem;cursor:pointer;
  background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;font-weight:600}
#googleBtn{display:none;margin-top:.65rem;background:#fff;color:#1f2937;border:1px solid var(--border);
  font-weight:600;gap:.5rem;align-items:center;justify-content:center}
#googleBtn.show{display:flex}
.login-divider{display:none;text-align:center;color:var(--muted);font-size:.78rem;margin:.75rem 0}
.login-divider.show{display:block}
.login-err{color:#fecaca;font-size:.82rem;margin-top:.65rem;display:none}
.login-err.show{display:block}
.brand-mark{display:flex;align-items:center;gap:.65rem;margin-bottom:1rem}
.brand-mark .logo{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,var(--accent),var(--accent2));
  display:flex;align-items:center;justify-content:center;font-weight:700;font-size:1rem;color:#fff}
.brand-mark span{font-size:.72rem;color:var(--muted);display:block;margin-top:.1rem}
#googleBtn svg{flex-shrink:0}
.hdr-actions{display:flex;align-items:center;gap:.35rem;margin-left:auto}
.hdr-btn{width:36px;height:36px;border:1px solid var(--border);background:var(--surface2);color:var(--muted);
  border-radius:10px;cursor:pointer;display:flex;align-items:center;justify-content:center}
.hdr-btn:hover{color:var(--text);border-color:var(--accent)}
.hdr-btn.text-btn{width:auto;padding:0 .65rem;font-size:.72rem;gap:.25rem;white-space:nowrap}
.user-pill{font-size:.72rem;color:var(--muted);max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mode-badge{display:inline-block;font-size:.62rem;padding:.15rem .45rem;border-radius:999px;margin-left:.35rem;
  background:rgba(56,189,248,.12);border:1px solid rgba(56,189,248,.3);color:var(--accent);vertical-align:middle}
#histPanel{position:fixed;top:0;right:0;z-index:85;width:min(300px,88vw);height:100dvh;background:var(--surface);
  border-left:1px solid var(--border);transform:translateX(100%);transition:transform .25s ease;
  display:flex;flex-direction:column;padding-top:env(safe-area-inset-top,0)}
#histPanel.open{transform:translateX(0)}
#histPanel h3{font-size:.9rem;padding:1rem;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.hist-list{flex:1;overflow-y:auto;padding:.5rem}
.hist-item{display:block;width:100%;text-align:left;padding:.65rem .75rem;border:none;background:transparent;
  color:var(--text);border-radius:.55rem;cursor:pointer;font:inherit;font-size:.82rem;margin-bottom:.25rem}
.hist-item:hover,.hist-item.active{background:var(--surface2)}
.hist-item small{display:block;color:var(--muted);font-size:.68rem;margin-top:.2rem}
#histOverlay{position:fixed;inset:0;z-index:80;background:rgba(0,0,0,.45);display:none}
#histOverlay.show{display:block}
.img-status{display:flex;align-items:center;gap:.5rem;color:var(--muted);font-size:.85rem}
.img-spinner{width:18px;height:18px;border:2px solid var(--border);border-top-color:var(--accent);
  border-radius:50%;animation:ringSpin .8s linear infinite;flex-shrink:0}
#pendingScreen{position:fixed;inset:0;z-index:110;display:flex;align-items:center;justify-content:center;
  background:rgba(7,11,20,.97);backdrop-filter:blur(10px);padding:1.25rem}
#pendingScreen.hidden{display:none}
.pending-box{max-width:400px;text-align:center;background:var(--surface);border:1px solid var(--border);
  border-radius:1rem;padding:2rem 1.5rem}
.pending-box h2{font-size:1.25rem;margin-bottom:.5rem}
.pending-box p{color:var(--muted);font-size:.9rem;line-height:1.55;margin-bottom:1rem}
.pending-icon{font-size:2.5rem;margin-bottom:.75rem}
#adminPanel{display:none;margin:.75rem 1rem;padding:.75rem;background:rgba(56,189,248,.08);
  border:1px solid rgba(56,189,248,.25);border-radius:.75rem;font-size:.82rem}
#adminPanel.show{display:block}
#adminPanel h3{font-size:.85rem;margin-bottom:.5rem;color:var(--accent)}
.admin-user{display:flex;align-items:center;justify-content:space-between;gap:.5rem;padding:.4rem 0;border-top:1px solid var(--border)}
.admin-user:first-of-type{border-top:none}
.admin-user button{padding:.35rem .65rem;border:none;border-radius:.45rem;cursor:pointer;
  background:var(--accent);color:#051018;font-size:.75rem;font-weight:600}
.composer-brand{text-align:center;font-size:.62rem;color:var(--muted);margin-top:.35rem;opacity:.7}
.composer.fluid-mode .mode-btn#btnModeFluid.active{box-shadow:0 0 0 2px rgba(56,189,248,.35)}
.composer.ptt-mode .mode-btn#btnModePtt.active{box-shadow:0 0 0 2px rgba(56,189,248,.35)}
.conv-screen{position:fixed;inset:0;z-index:75;display:none;flex-direction:column;
  background:radial-gradient(ellipse 80% 60% at 50% 40%,rgba(56,189,248,.12),transparent),var(--bg);
  padding:env(safe-area-inset-top) 1rem env(safe-area-inset-bottom);touch-action:none}
.conv-screen.open{display:flex}
.conv-top{display:flex;justify-content:flex-end;padding:.5rem 0}
.conv-exit{padding:.45rem .85rem;border-radius:999px;border:1px solid var(--border);
  background:var(--surface2);color:var(--text);font-size:.78rem;cursor:pointer}
.conv-center{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1.25rem}
.conv-orb-wrap{position:relative;width:min(46vw,200px);height:min(46vw,200px);cursor:default}
.conv-orb-mesh{position:absolute;inset:-28px;border-radius:50%;opacity:.6;filter:blur(18px);pointer-events:none;
  background:linear-gradient(135deg,#38bdf8,#818cf8,#6366f1);background-size:200% 200%;animation:meshIdle 8s ease-in-out infinite}
.conv-orb-wrap.state-listening .conv-orb-mesh{background:linear-gradient(135deg,#22d3ee,#34d399,#06b6d4);animation:meshListen 3s ease-in-out infinite}
.conv-orb-wrap.state-thinking .conv-orb-mesh{background:linear-gradient(135deg,#fbbf24,#f59e0b,#fb923c);animation:meshThink 4s linear infinite}
.conv-orb-wrap.state-speaking .conv-orb-mesh{background:linear-gradient(135deg,#a78bfa,#c084fc,#818cf8);animation:meshSpeak 2.5s ease-in-out infinite}
.conv-orb{position:relative;z-index:1;width:100%;height:100%;border-radius:50%;
  background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 0 48px var(--glow);
  display:flex;align-items:center;justify-content:center}
.conv-orb .orb-letter{font-size:3.2rem;font-weight:800}
.conv-orb.listening{animation:orbPulse 1.4s ease-in-out infinite}
.conv-orb.thinking{animation:orbSpin 2s linear infinite}
.conv-orb.speaking{animation:orbSpeak .55s ease-in-out infinite alternate}
.conv-orb-ring{position:absolute;inset:-6px;border-radius:50%;border:2px solid transparent;border-top-color:var(--accent);opacity:0}
.conv-orb-wrap.active .conv-orb-ring{opacity:1;animation:ringSpin .8s linear infinite}
.conv-status{font-size:1.05rem;font-weight:600;text-align:center;color:var(--text)}
.conv-hint{font-size:.78rem;color:var(--muted);text-align:center;max-width:280px;line-height:1.45}
body.conv-mode .app>.chat,body.conv-mode .app>.composer{visibility:hidden;pointer-events:none;height:0;overflow:hidden;opacity:0}
#settingsOverlay{position:fixed;inset:0;z-index:90;background:rgba(7,11,20,.75);backdrop-filter:blur(6px);
  display:none;align-items:center;justify-content:center;padding:1rem}
#settingsOverlay.show{display:flex}
.settings-panel{width:100%;max-width:380px;background:var(--surface);border:1px solid var(--border);
  border-radius:1rem;padding:1.25rem;max-height:85dvh;overflow-y:auto}
.settings-panel h2{font-size:1.05rem;margin-bottom:.85rem;display:flex;align-items:center;justify-content:space-between}
.settings-panel label{display:block;font-size:.78rem;color:var(--muted);margin:.65rem 0 .3rem}
.settings-panel select,.settings-panel input[type=checkbox]{width:100%;padding:.55rem .7rem;border-radius:.55rem;
  border:1px solid var(--border);background:var(--surface2);color:var(--text);font:inherit;font-size:.88rem}
.settings-row{display:flex;align-items:center;gap:.55rem;margin:.75rem 0}
.settings-row input[type=checkbox]{width:auto;accent-color:var(--accent)}
.settings-hint{font-size:.72rem;color:var(--muted);line-height:1.45;margin-top:.5rem}
.voice-lab{margin-top:1rem;padding-top:.85rem;border-top:1px solid var(--border)}
.voice-lab h3{font-size:.92rem;margin:0 0 .45rem;color:var(--text)}
.voice-lab-stats{font-size:.82rem;color:var(--muted);margin:.35rem 0 .6rem}
.voice-lab-actions{display:flex;flex-wrap:wrap;gap:.45rem;margin:.5rem 0}
.voice-lab-actions button{font-size:.82rem;padding:.45rem .7rem;border-radius:8px;border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer}
.voice-lab-actions button.primary{background:linear-gradient(135deg,var(--accent),var(--accent2));border:none;color:#fff}
.voice-lab-actions button:disabled{opacity:.45;cursor:not-allowed}
.voice-lab-status{font-size:.78rem;color:var(--muted);min-height:1.2rem;margin-top:.35rem}
.voice-lab-recording{color:#f87171;font-weight:600}
.settings-actions{display:flex;gap:.5rem;margin-top:1rem}
.settings-actions button{flex:1;padding:.65rem;border:none;border-radius:.6rem;cursor:pointer;font-weight:600}
#settingsSave{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
#settingsClose{background:var(--surface2);color:var(--text);border:1px solid var(--border)}
.bubble img{max-width:100%;border-radius:12px;margin-top:.65rem;display:block}
</style>
</head>
<body>
<div id="pendingScreen" class="hidden">
  <div class="pending-box">
    <div class="pending-icon">⏳</div>
    <h2>Acceso en revisión</h2>
    <p>Tu cuenta fue registrada correctamente. Rafael debe aprobarte antes de acceder a la memoria de empresa.</p>
    <p style="font-size:.82rem;color:var(--muted)">Recibirás acceso en cuanto sea aprobada. Puedes cerrar esta ventana.</p>
    <button type="button" onclick="document.getElementById('pendingScreen').classList.add('hidden')" style="margin-top:.5rem;padding:.6rem 1.2rem;border:none;border-radius:.6rem;cursor:pointer;background:var(--surface2);color:var(--text);border:1px solid var(--border)">Entendido</button>
  </div>
</div>
<div id="loginScreen">
  <div class="login-box">
    <div class="brand-mark">
      <div class="logo">R</div>
      <div><strong style="font-size:1.05rem">Ralphi IA</strong><span>PC Doctor AI · voz.pcdoctor.ai</span></div>
    </div>
    <h2 id="loginTitle" style="font-size:1rem;margin-bottom:.5rem;color:var(--muted);font-weight:500">Iniciar sesión</h2>
    <p id="loginHint">Correo o usuario + contraseña local, <b>o</b> Continuar con Google. Ej: <b>rafagye@gmail.com</b> o <b>rafagye</b>.</p>
    <input id="loginName" type="text" placeholder="Nombre (solo registro)" style="display:none"/>
    <input id="loginUser" type="text" placeholder="Correo o usuario" autocomplete="username"/>
    <input id="loginPass" type="password" placeholder="Contraseña" autocomplete="current-password"/>
    <button id="loginBtn" type="button">Entrar</button>
    <div class="login-divider __GOOGLE_DIVIDER_CLASS__" id="loginDivider">o</div>
    <button id="googleBtn" type="button" class="__GOOGLE_BTN_CLASS__"><svg width="18" height="18" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.611 20.083H42V20H24v8h11.303C33.654 32.657 29.203 36 24 36c-6.627 0-12-5.373-12-12s5.373-12 12-12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C33.64 6.053 28.991 4 24 4 12.955 4 4 12.955 4 24s8.955 20 20 20 20-8.955 20-20c0-1.341-.138-2.65-.389-3.917z"/><path fill="#FF3D00" d="m6.306 14.691 6.571 4.819C14.655 15.108 18.961 12 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C33.64 6.053 28.991 4 24 4 16.318 4 9.656 8.337 6.306 14.691z"/><path fill="#4CAF50" d="M24 44c5.166 0 9.86-1.977 13.409-5.192l-6.19-5.238A11.91 11.91 0 0 1 24 36c-5.202 0-9.619-3.317-11.283-7.946l-6.522 5.025C9.505 39.556 16.227 44 24 44z"/><path fill="#1976D2" d="M43.611 20.083H42V20H24v8h11.303a12.04 12.04 0 0 1-4.087 5.571l.003-.002 6.19 5.238C36.971 39.205 44 34 44 24c0-1.341-.138-2.652-.389-3.917z"/></svg>Continuar con Google</button>
    <button id="registerBtn" type="button" style="margin-top:.5rem;background:var(--surface2);color:var(--text);border:1px solid var(--border)">¿Usuario nuevo? Crear cuenta</button>
    <button id="backLoginBtn" type="button" style="display:none;margin-top:.5rem;background:transparent;color:var(--muted);border:none;font-size:.82rem">← Volver a entrar</button>
    <div class="login-err" id="loginErr"></div>
  </div>
</div>
<div class="app">
  <div id="warn"></div>
  <header class="hdr">
    <div class="orb-wrap" id="orbWrap"><div class="orb-mesh" id="orbMesh"></div><div class="orb" id="orb"><span class="orb-letter">R</span></div><div class="orb-ring"></div>
      <div class="orb-menu" id="orbMenu">
        <button type="button" id="orbMenuNew">＋ Nuevo chat</button>
        <button type="button" id="orbMenuHist">Historial</button>
        <button type="button" id="orbMenuSettings">⚙️ Ajustes</button>
        <button type="button" id="orbMenuLogout">Salir</button>
        <div class="orb-menu-divider"></div>
        <div class="orb-menu-user" id="orbMenuUser"></div>
      </div>
    </div>
    <div class="hdr-text">
      <h1>Ralphi IA</h1>
      <p class="status-line"><span class="status-dot" id="statusDot"></span><span id="statusLabel">Conectando…</span></p>
      <p class="status-meta"><span id="modeBadge" class="mode-badge" style="display:none"></span><span id="histBadge"></span></p>
    </div>
    <div class="hdr-actions">
      <button class="hdr-btn text-btn" id="btnNewChat" type="button" title="Nuevo chat">＋ Nuevo</button>
      <button class="hdr-btn text-btn" id="btnHist" type="button" title="Historial">Historial</button>
      <span class="user-pill" id="userPill"></span>
      <button class="hdr-btn" id="btnSettings" type="button" title="Ajustes" aria-label="Ajustes">⚙️</button>
      <button class="hdr-btn" id="btnLogout" type="button" title="Salir" aria-label="Salir">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
      </button>
    </div>
  </header>
  <div id="adminPanel"></div>
  <main class="chat" id="chat">
    <div class="welcome" id="welcome">
      <h2 id="welcomeTitle">Hola</h2>
      <p id="welcomeSub">Soy <b>Ralphi IA</b>, tu yo del futuro — asistente con memoria de PC Doctor, InnerSpark e InnerChispa. Habla o escribe.</p>
      <div class="chips">
        <button class="chip" data-q="¿Qué tengo pendiente hoy?">📋 Pendientes</button>
        <button class="chip" data-q="Resume mi contexto de InnerSpark">✨ InnerSpark</button>
        <button class="chip" data-q="¿Qué sabes de PC Doctor?">🏥 PC Doctor</button>
      </div>
    </div>
    <div id="chatSpacer" aria-hidden="true"></div>
  </main>
  <footer class="composer">
    <div class="mode-toggle">
      <button type="button" class="mode-btn" id="btnModePtt" title="Toca para grabar (rojo) · toca otra vez para enviar · tercera vez sale del modo">🎤 Pulsar y hablar</button>
      <button type="button" class="mode-btn" id="btnModeFluid" title="Modo conversación — toca para entrar o salir">🔄 Conversación</button>
    </div>
    <div class="composer-inner">
      <textarea id="input" rows="1" placeholder="Mensaje a Ralphi IA…" autocomplete="off"></textarea>
      <input type="file" id="fileInput" accept="image/*,.pdf,.txt,.md,.csv,.json,.doc,.docx" style="display:none"/>
      <button class="btn-icon" id="btnAttach" type="button" title="Adjuntar archivo" aria-label="Adjuntar">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
      </button>
      <button class="btn-icon" id="btnStop" type="button" title="Detener todo" aria-label="Detener">■</button>
      <button class="btn-icon" id="btnSend" type="button" title="Enviar" aria-label="Enviar">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2L15 22 11 13 2 9 22 2z"/></svg>
      </button>
    </div>
    <div class="composer-hint" id="composerHint">🎤 Pulsar y hablar: toca para grabar (rojo) · toca otra vez para enviar · ■ detiene todo</div>
    <div class="composer-brand">Ralphi IA · PC Doctor AI · Ecuador</div>
  </footer>
</div>
<div id="histOverlay"></div>
<aside id="histPanel" aria-label="Historial de conversaciones">
  <h3>Historial <button class="hdr-btn" id="histClose" type="button" aria-label="Cerrar">✕</button></h3>
  <div class="hist-list" id="histList"></div>
</aside>
<div id="settingsOverlay">
  <div class="settings-panel">
    <h2>⚙️ Ajustes <button class="hdr-btn" id="settingsCloseX" type="button" aria-label="Cerrar">✕</button></h2>
    <label for="settingVoice">Voz TTS</label>
    <select id="settingVoice"><option value="">Cargando voces…</option></select>
    <div class="settings-row">
      <input type="checkbox" id="settingSpeak" checked/>
      <label for="settingSpeak" style="margin:0;color:var(--text);font-size:.88rem">Leer respuestas en voz alta</label>
    </div>
    <label for="settingDefaultMode">Modo al abrir</label>
    <select id="settingDefaultMode">
      <option value="fluid">Conversación fluida</option>
      <option value="ptt">Pulsar y hablar</option>
    </select>
    <p class="settings-hint">Imágenes: di <b>«genera una imagen de…»</b> o <b>«crea una foto de…»</b>. Ej: «genera una imagen de un atardecer en Galápagos».</p>
    <section class="voice-lab" id="voiceLab">
      <h3>🎙️ Laboratorio de voz</h3>
      <p class="settings-hint">Graba muestras cortas (15 recomendadas) y clona tu voz con XTTS para usarla en conversación y vídeos.</p>
      <label for="voiceLabLang">Idioma de clonación</label>
      <select id="voiceLabLang">
        <option value="es">Español</option>
        <option value="en">English</option>
        <option value="de">Deutsch</option>
        <option value="fr">Français</option>
        <option value="it">Italiano</option>
        <option value="pt">Português</option>
      </select>
      <div class="voice-lab-stats" id="voiceLabStats">Cargando muestras…</div>
      <div class="voice-lab-actions">
        <button type="button" id="voiceLabRecord">● Grabar muestra</button>
        <button type="button" id="voiceLabClone" class="primary">Clonar voz</button>
        <button type="button" id="voiceLabActivate">Activar en RalfIA</button>
      </div>
      <div class="voice-lab-status" id="voiceLabStatus"></div>
    </section>
    <div class="settings-actions">
      <button type="button" id="settingsClose">Cancelar</button>
      <button type="button" id="settingsSave">Guardar</button>
    </div>
  </div>
</div>
<div id="convScreen" class="conv-screen" aria-hidden="true">
  <div class="conv-top"><button type="button" class="conv-exit" id="convExit">✕ Salir de conversación</button></div>
  <div class="conv-center">
    <div class="conv-orb-wrap" id="convOrbWrap">
      <div class="conv-orb-mesh" id="convOrbMesh"></div>
      <div class="conv-orb" id="convOrb"><span class="orb-letter">R</span></div>
      <div class="conv-orb-ring"></div>
    </div>
    <p class="conv-status" id="convStatus">Te escucho…</p>
    <p class="conv-hint" id="convHint">Habla con naturalidad · «detente» o «paremos» para pausar · ■ corta la respuesta</p>
  </div>
</div>
<script>
const chatEl=document.getElementById('chat'),inputEl=document.getElementById('input'),
  btnSend=document.getElementById('btnSend'),
  orb=document.getElementById('orb'),orbWrap=document.getElementById('orbWrap'),orbMesh=document.getElementById('orbMesh'),
  statusLabel=document.getElementById('statusLabel'),statusDot=document.getElementById('statusDot'),
  warnEl=document.getElementById('warn'),welcomeEl=document.getElementById('welcome');
const isSecure=window.isSecureContext;
const hasMedia=!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia);
let HTTPS_URLS=__HTTPS_URLS__;
window.__GOOGLE_OAUTH__=__GOOGLE_OAUTH_ENABLED__;
let history=[],busy=false,listening=false,rec=null,chunks=[],wakeLock=null,activeStream=null;
let voiceMode='idle',fluidState='off',chatAbort=null,currentAudio=null,recordTimer=null;
let fluidLoopAbort=null,fluidMicStream=null,audioCtx=null,bargeInAbort=null,lastStopClick=0;
let imageGenAbort=false,generatingImage=false,pttRecording=false,pttTranscribeOnStop=true;
let ttsQueue=[],ttsDraining=false,ttsStreamActive=false;
const MAX_RECORD_MS=60000;
let currentUser=null;
const loginScreen=document.getElementById('loginScreen'),loginErr=document.getElementById('loginErr'),
  loginUser=document.getElementById('loginUser'),loginPass=document.getElementById('loginPass'),
  loginBtn=document.getElementById('loginBtn'),registerBtn=document.getElementById('registerBtn'),
  backLoginBtn=document.getElementById('backLoginBtn'),loginTitle=document.getElementById('loginTitle'),
  loginHint=document.getElementById('loginHint'),loginName=document.getElementById('loginName'),
  welcomeTitle=document.getElementById('welcomeTitle'),
  welcomeSub=document.getElementById('welcomeSub'),
  userPill=document.getElementById('userPill'),
  btnLogout=document.getElementById('btnLogout'),
  adminPanel=document.getElementById('adminPanel'),
  pendingScreen=document.getElementById('pendingScreen'),
  googleBtn=document.getElementById('googleBtn'),loginDivider=document.getElementById('loginDivider'),
  histBadge=document.getElementById('histBadge'),fileInput=document.getElementById('fileInput'),
  btnAttach=document.getElementById('btnAttach'),btnStop=document.getElementById('btnStop'),
  btnModePtt=document.getElementById('btnModePtt'),btnModeFluid=document.getElementById('btnModeFluid'),
  composerHint=document.getElementById('composerHint'),
  btnSettings=document.getElementById('btnSettings'),settingsOverlay=document.getElementById('settingsOverlay'),
  settingVoice=document.getElementById('settingVoice'),settingSpeak=document.getElementById('settingSpeak'),
  settingDefaultMode=document.getElementById('settingDefaultMode'),
  composerEl=document.querySelector('.composer'),
  btnNewChat=document.getElementById('btnNewChat'),btnHist=document.getElementById('btnHist'),
  histPanel=document.getElementById('histPanel'),histOverlay=document.getElementById('histOverlay'),
  histList=document.getElementById('histList'),histClose=document.getElementById('histClose'),
  modeBadge=document.getElementById('modeBadge'),
  convScreen=document.getElementById('convScreen'),convOrbWrap=document.getElementById('convOrbWrap'),
  convOrb=document.getElementById('convOrb'),convStatus=document.getElementById('convStatus'),
  convExit=document.getElementById('convExit'),
  orbMenu=document.getElementById('orbMenu'),orbMenuUser=document.getElementById('orbMenuUser');
let registerMode=false,orbMenuOpen=false;
const SETTINGS_KEY='ralfia_settings';
const CONV_KEY='ralfia_voice_conv_id';
const IMAGE_GEN_TIMEOUT_MS=180000;
const WAKE_RE=/\\b(hola|hey|ok)\\s+ralf(i|ia|i\\s*ia)?\\b/i;
const STOP_RE=/\\b(detente|para(mos)?(\\s+la\\s+conversaci[oó]n)?|stop|silencio|basta|ap[aá]gate)\\b/i;
const VAD_THRESHOLD=0.02,VAD_SILENCE_MS=1200,VAD_MIN_UTTERANCE_MS=400,STANDBY_CHUNK_MS=2500;
let settings={voice:'',speak:true,defaultMode:'ptt'};
let conversationId=localStorage.getItem(CONV_KEY)||'';
let conversations=[];
let preserveScroll=false;
let ttsVoices=[];
const fetchOpts={credentials:'include'};

function loadSettings(){
  try{Object.assign(settings,JSON.parse(localStorage.getItem(SETTINGS_KEY)||'{}'))}catch(e){}
  if(settings.defaultMode==='cont')settings.defaultMode='fluid';
  if(settingSpeak)settingSpeak.checked=settings.speak!==false;
  if(settingDefaultMode)settingDefaultMode.value=settings.defaultMode||'ptt';
}
function saveSettingsFromUI(){
  settings.voice=settingVoice?settingVoice.value:'';
  settings.speak=settingSpeak?settingSpeak.checked:true;
  settings.defaultMode=settingDefaultMode?settingDefaultMode.value:'ptt';
  localStorage.setItem(SETTINGS_KEY,JSON.stringify(settings));
}
function chatPayload(extra){
  const p={messages:getHistory(),speak:settings.speak!==false};
  if(settings.voice)p.voice=settings.voice;
  if(conversationId)p.conversation_id=conversationId;
  return Object.assign(p,extra||{});
}
function setConversationId(id){
  conversationId=id||'';
  if(conversationId)localStorage.setItem(CONV_KEY,conversationId);
  else localStorage.removeItem(CONV_KEY);
}
function parseJsonError(r,body){
  if(body&&typeof body==='object'){
    return body.reply||body.detail||body.error||body.message||'Error del servidor';
  }
  return 'No se pudo conectar con el servidor';
}
function showImageStatus(seconds){
  hideTyping();
  const t=document.createElement('div');t.className='typing';t.id='typing';
  const timerText=seconds?` (${seconds}s)`:'';
  t.innerHTML='<div class="msg-av" style="background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff">RI</div><div class="typing-dots img-status"><div class="img-spinner"></div><span id="imgStatusText">Generando imagen…'+timerText+'</span></div>';
  chatEl.appendChild(t);scrollBottom();
}
function updateImageStatusTimer(seconds){
  const el=document.getElementById('imgStatusText');
  if(el)el.textContent='Generando imagen… ('+seconds+'s)';
}
async function generateImage(text,speak){
  showImageStatus(0);
  setStatus('Generando imagen…','thinking');
  if(orb)orb.classList.add('generating');
  generatingImage=true;imageGenAbort=false;
  updateStopBtn();
  const startMs=Date.now();
  let pollTimer=null;
  try{
    const r=await fetch('/api/voice/image/generate',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',
      body:JSON.stringify(chatPayload({text,speak}))});
    if(imageGenAbort){hideTyping();return false;}
    const ct=(r.headers.get('content-type')||'').toLowerCase();
    let c={};
    if(ct.includes('json'))c=await r.json();
    else{
      const raw=await r.text();
      if(raw.includes('<!DOCTYPE')||raw.includes('<html'))throw new Error('El túnel expiró — la imagen tarda más de lo permitido. Intenta de nuevo.');
      try{c=JSON.parse(raw)}catch(e){throw new Error('Respuesta inválida del servidor de imagen');}
    }
    if(!r.ok||!c.ok){
      hideTyping();
      const msg=parseJsonError(r,c);
      addMsg('bot',msg,true);setStatus('Error imagen','off');
      return false;
    }
    if(c.job_id){
      pollTimer=setInterval(()=>updateImageStatusTimer(Math.floor((Date.now()-startMs)/1000)),1000);
      const jobId=c.job_id;
      while(Date.now()-startMs<IMAGE_GEN_TIMEOUT_MS){
        if(imageGenAbort){
          hideTyping();
          addMsg('bot','Generación de imagen cancelada.',true);
          setStatus('Cancelado','off');
          return false;
        }
        await new Promise(res=>setTimeout(res,2000));
        updateImageStatusTimer(Math.floor((Date.now()-startMs)/1000));
        const jr=await fetch('/api/voice/image/job/'+encodeURIComponent(jobId),{credentials:'include'});
        if(!jr.ok)continue;
        const jd=await jr.json();
        if(jd.status==='pending')continue;
        hideTyping();
        if(jd.status==='done'&&jd.ok!==false){
          if(jd.conversation_id)setConversationId(jd.conversation_id);
          const bub=addMsg('bot',jd.reply);
          if(jd.image_url)appendImageToBubble(jd.image_url);
          history.push({role:'assistant',content:jd.reply});
          if(jd.audio_url&&speak){
            await playReplyAudio(jd.audio_url,()=>scheduleNextListen(500),false,bub);
          }else scheduleNextListen(500);
          return true;
        }
        addMsg('bot',jd.reply||jd.error||jd.detail||'Error generando imagen',true);
        setStatus('Error imagen','off');
        return false;
      }
      hideTyping();
      addMsg('bot','Tiempo agotado generando imagen (máx. 3 min). ComfyUI puede estar ocupado.',true);
      setStatus('Tiempo agotado','off');
      return false;
    }
    hideTyping();
    if(c.conversation_id)setConversationId(c.conversation_id);
    const bubImg=addMsg('bot',c.reply);
    if(c.image_url)appendImageToBubble(c.image_url);
    history.push({role:'assistant',content:c.reply});
    if(c.audio_url&&speak){
      await playReplyAudio(c.audio_url,()=>scheduleNextListen(500),false,bubImg);
    }else scheduleNextListen(500);
    return true;
  }catch(e){
    hideTyping();
    addMsg('bot',e.message||'Error generando imagen',true);
    setStatus('Error imagen','off');
    return false;
  }finally{
    if(pollTimer)clearInterval(pollTimer);
    if(orb)orb.classList.remove('generating');
    generatingImage=false;
    updateStopBtn();
  }
}
function shouldSpeak(explicit){return explicit!==undefined?explicit!==false:settings.speak!==false}
function wantsImage(text){
  return /\\b(genera|crea|haz|dibuja|pinta|make|draw)\\w*\\s+(me\\s+)?(una\\s+)?(imagen|foto|picture|image|ilustraci)/i.test(text||'')
    ||/\\b(quiero|necesito|mu[eé]strame)\\s+(una\\s+)?(imagen|foto|ilustraci)/i.test(text||'')
    ||/\\b(genera|crea|haz)\\s+(me\\s+)?(una\\s+)?foto\\b/i.test(text||'');
}
function appendImageToBubble(url){
  if(!url)return;
  const bubble=chatEl.querySelector('.msg.bot:last-child .bubble');
  if(!bubble)return;
  const img=document.createElement('img');
  img.src=url;img.alt='Imagen generada';
  img.loading='lazy';
  bubble.appendChild(img);
  scrollBottom();
}
function updateComposerPadding(){
  if(!composerEl)return;
  document.documentElement.style.setProperty('--composer-h',composerEl.offsetHeight+'px');
}
function updateStopBtn(){
  if(!btnStop)return;
  const fluidOn=voiceMode==='fluid'&&fluidState==='active';
  const show=busy||pttRecording||generatingImage||currentAudio||ttsDraining||ttsQueue.length>0||(fluidOn&&(busy||pttRecording||currentAudio||listening));
  btnStop.style.display=show?'flex':'none';
  btnStop.title='Detener todo (voz, chat, imagen, micrófono)';
}
if(typeof ResizeObserver!=='undefined'&&composerEl){
  new ResizeObserver(updateComposerPadding).observe(composerEl);
}
window.addEventListener('resize',updateComposerPadding);
if(window.visualViewport){
  window.visualViewport.addEventListener('resize',()=>{updateComposerPadding();scrollBottom();});
}

function micErrorMsg(err){
  if(!isSecure)return 'Micrófono requiere HTTPS. Abre: '+HTTPS_URLS.join(' o ');
  if(!hasMedia)return 'Tu navegador no soporta audio.';
  const n=err&&err.name||'';
  if(n==='NotAllowedError'||n==='PermissionDeniedError')return 'Permiso de micrófono denegado.';
  if(n==='NotFoundError')return 'No hay micrófono disponible.';
  if(n==='NotReadableError')return 'Micrófono en uso por otra app.';
  return (err&&err.message)||'Error de micrófono.';
}
function showConvScreen(on){
  if(!convScreen)return;
  convScreen.classList.toggle('open',!!on);
  convScreen.setAttribute('aria-hidden',on?'false':'true');
  document.body.classList.toggle('conv-mode',!!on);
}
function setStatus(label,mode){
  statusLabel.textContent=label;
  statusDot.className='status-dot'+(mode==='busy'?' busy':mode==='off'?' off':'');
  const inConv=convScreen&&convScreen.classList.contains('open');
  const animModes=['listening','thinking','speaking'];
  const shouldAnim=inConv&&animModes.includes(mode);
  if(convStatus)convStatus.textContent=label;
  if(inConv&&convOrb&&convOrbWrap){
    convOrb.className='conv-orb'+(mode==='listening'?' listening':mode==='thinking'?' thinking':mode==='speaking'?' speaking':'');
    convOrbWrap.classList.toggle('active',shouldAnim);
    convOrbWrap.classList.remove('state-listening','state-thinking','state-speaking','state-standby');
    if(mode==='listening')convOrbWrap.classList.add('state-listening');
    else if(mode==='thinking')convOrbWrap.classList.add('state-thinking');
    else if(mode==='speaking')convOrbWrap.classList.add('state-speaking');
  }
  if(!inConv){
    orb.className='orb'+(mode==='listening'?' listening':mode==='thinking'?' thinking':mode==='speaking'?' speaking':'');
    orbWrap.classList.toggle('active',animModes.includes(mode));
    orbWrap.classList.remove('state-listening','state-thinking','state-speaking','state-standby');
  }else{
    orb.className='orb';
    orbWrap.classList.remove('active','state-listening','state-thinking','state-speaking','state-standby');
  }
  updateModeBadge();
}
function updateModeBadge(){
  if(!modeBadge)return;
  if(voiceMode==='fluid'&&fluidState!=='off'){
    modeBadge.style.display='inline-block';
    modeBadge.className='mode-badge '+(fluidState==='active'?'fluid-active':'fluid-standby');
    modeBadge.textContent=fluidState==='active'?'Conversación activa':'Conversación';
    modeBadge.title=fluidState==='active'?'Modo conversación — di «detente» para pausar':'Toca Conversación para entrar';
  }else{modeBadge.style.display='none';modeBadge.className='mode-badge';}
}
function hideWelcome(){if(welcomeEl)welcomeEl.style.display='none'}
function isRafaelUser(u){
  if(!u)return false;
  const un=(u.username||'').toLowerCase().split('@')[0];
  return !!u.is_admin||['rafagye','rlopez','admin','rafael'].includes(un);
}
function setWelcomeTitle(user){
  if(!user)return;
  const name=user.display_name||user.username||'';
  if(userPill)userPill.textContent=name;
  if(orbMenuUser)orbMenuUser.textContent=name;
  if(isRafaelUser(user)){
    if(welcomeTitle)welcomeTitle.textContent='Rafael — Ralphi IA, tu yo del futuro';
    if(welcomeSub)welcomeSub.innerHTML='Soy <b>Ralphi IA</b>, tu yo del futuro — memoria PC Doctor, InnerSpark, MCP y cotizaciones. Habla o escribe.';
    updateChips(['¿Qué tengo pendiente hoy?','Estado del stack','Iniciar cotización','Resume InnerSpark']);
  }else{
    if(welcomeTitle)welcomeTitle.textContent='Hola, '+name;
    if(welcomeSub)welcomeSub.innerHTML='Soy <b>Ralphi IA</b>, el yo del futuro de Rafael — asistente con memoria de empresa. Habla o escribe.';
    updateChips(['¿Qué tengo pendiente?','Buscar en memoria empresa','Ayuda con cotización','Estado del sistema']);
  }
  if(isRafaelUser(user))loadAdminPending();else if(adminPanel)adminPanel.classList.remove('show');
}
function updateChips(queries){
  const chips=document.querySelectorAll('.chip');
  const icons=['📋','⚙️','💼','✨'];
  queries.forEach((q,i)=>{if(chips[i]){chips[i].textContent=(icons[i]||'•')+' '+q;chips[i].dataset.q=q;}});
}
async function loadAdminPending(){
  if(!adminPanel||!currentUser||!isRafaelUser(currentUser))return;
  try{
    const r=await fetch('/api/voice/admin/pending-users',{credentials:'include'});
    if(!r.ok)return;
    const d=await r.json();
    const users=d.users||[];
    if(!users.length){adminPanel.classList.remove('show');return}
    adminPanel.classList.add('show');
    adminPanel.innerHTML='<h3>Solicitudes pendientes ('+users.length+')</h3>'+
      users.map(u=>'<div class="admin-user"><span><b>'+(u.display_name||u.username)+'</b> · '+(u.google_email||u.username)+'</span><button type="button" data-u="'+u.username+'">Aprobar</button></div>').join('');
    adminPanel.querySelectorAll('button[data-u]').forEach(btn=>{
      btn.onclick=async()=>{
        btn.disabled=true;btn.textContent='…';
        const r=await fetch('/api/voice/admin/approve',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:btn.dataset.u})});
        const d=await r.json();
        btn.textContent=d.ok?'✓':'Error';
        if(d.ok)setTimeout(loadAdminPending,800);
      };
    });
  }catch(e){}
}
function scrollBottom(force){
  if(!force&&preserveScroll)return;
  requestAnimationFrame(()=>{chatEl.scrollTop=chatEl.scrollHeight;});
}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}

function addMsg(role,text,isError,opts){
  hideWelcome();
  const div=document.createElement('div');
  div.className='msg '+(role==='user'?'user':'bot');
  const av=document.createElement('div');av.className='msg-av';av.textContent=role==='user'?'R':'RI';
  const bub=document.createElement('div');bub.className='bubble'+(isError?' error':'');
  bub.innerHTML=esc(text);
  if(role==='user'&&opts&&opts.editable!==false){
    const eb=document.createElement('button');eb.className='edit-btn';eb.title='Editar y reenviar';eb.textContent='✎';
    eb.onclick=()=>{inputEl.value=text;inputEl.focus();inputEl.style.height='auto';inputEl.style.height=Math.min(inputEl.scrollHeight,120)+'px';};
    bub.appendChild(eb);
  }
  div.appendChild(av);div.appendChild(bub);chatEl.appendChild(div);scrollBottom();
  if(role==='bot'&&!isError&&text){
    bub.dataset.speakText=text;
    ensureMsgAudioBar(bub);
  }
  return bub;
}
function ensureMsgAudioBar(bubble){
  if(!bubble)return null;
  let bar=bubble.querySelector('.msg-audio-bar');
  if(!bar){
    bar=document.createElement('div');
    bar.className='msg-audio-bar';
    const btn=document.createElement('button');
    btn.type='button';btn.className='speak-btn';btn.title='Escuchar este mensaje';btn.textContent='🔊';
    btn.onclick=()=>replayBubbleAudio(bubble);
    bar.appendChild(btn);
    const mini=document.createElement('audio');
    mini.className='audio-mini';mini.controls=true;mini.preload='metadata';
    bar.appendChild(mini);
    bubble.appendChild(bar);
  }
  return bar;
}
async function fetchTtsUrl(text){
  const r=await fetch('/api/voice/tts/speak',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text,voice:settings.voice||undefined})});
  const d=await r.json();
  return d.ok?d.audio_url:null;
}
async function replayBubbleAudio(bubble){
  if(!bubble)return;
  if(currentAudio){try{currentAudio.pause()}catch(e){}currentAudio=null;}
  const text=bubble.dataset.speakText||bubble.querySelector('.bubble-text')?.textContent||'';
  const bar=ensureMsgAudioBar(bubble);
  let url=bar?.dataset.audioUrl||'';
  if(!url&&text){
    setStatus('Generando voz…','thinking');
    url=await fetchTtsUrl(text);
    if(!url){setStatus('No se pudo generar audio','off');return;}
  }
  await playReplyAudio(url,null,false,bubble);
}
function stopResponse(){
  if(chatAbort){chatAbort.abort();chatAbort=null;}
  if(currentAudio){try{currentAudio.pause()}catch(e){}currentAudio=null;}
  if(bargeInAbort){bargeInAbort();bargeInAbort=null;}
  if(rec&&rec.state==='recording')rec.stop();
  hideTyping();
  ttsQueue=[];
  ttsDraining=false;
  ttsStreamActive=false;
  busy=false;btnSend.disabled=false;inputEl.disabled=false;
  updateStopBtn();
  if(voiceMode==='fluid'&&fluidState==='active'){
    setStatus('Te escucho…','listening');
    setTimeout(()=>{if(voiceMode==='fluid'&&fluidState==='active'&&!busy)vadRecordLoop();},400);
  }else if(voiceMode==='idle'&&!listening)setStatus('En línea · listo','');
}
function abortAll(){
  if(pttRecording){
    stopPttRecording(true);
    return;
  }
  imageGenAbort=true;
  if(chatAbort){chatAbort.abort();chatAbort=null;}
  if(currentAudio){try{currentAudio.pause()}catch(e){}currentAudio=null;}
  if(bargeInAbort){bargeInAbort();bargeInAbort=null;}
  fluidLoopAbort=true;
  pttTranscribeOnStop=false;
  if(rec&&rec.state==='recording')rec.stop();
  stopListening(true);
  hideTyping();
  ttsQueue=[];
  ttsDraining=false;
  ttsStreamActive=false;
  busy=false;generatingImage=false;
  btnSend.disabled=false;inputEl.disabled=false;
  if(voiceMode==='fluid')stopFluidAssistant();
  else if(voiceMode==='ptt')deactivatePttMode();
  else setStatus('En línea · listo','');
  updateStopBtn();
}
function scheduleNextListen(delay){
  setTimeout(()=>{
    if(voiceMode==='fluid'&&fluidState==='active'&&!busy&&!currentAudio)vadRecordLoop();
    else if(!busy&&!listening)setStatus('En línea · listo','');
  },delay||0);
}
function stopFluidAssistant(){
  fluidLoopAbort=true;
  if(bargeInAbort){bargeInAbort();bargeInAbort=null;}
  stopListening();
  releaseFluidMic();
  fluidState='off';
  voiceMode='idle';
  showConvScreen(false);
  updateModeUI();
  setStatus('En línea · listo','');
  updateStopBtn();
}
function deactivatePttMode(){
  pttTranscribeOnStop=false;
  if(rec&&rec.state==='recording')rec.stop();
  stopListening(true);
  voiceMode='idle';
  pttRecording=false;
  updateModeUI();
  if(!busy&&!currentAudio)setStatus('En línea · listo','');
  updateStopBtn();
}
function stripWakePhrase(text){
  return (text||'').replace(WAKE_RE,'').replace(/^[,\\s]+/,'').trim();
}
function matchesWake(text){return WAKE_RE.test(text||'');}
function matchesStop(text){return STOP_RE.test(text||'');}
function playReplyAudio(url,onDone,bargeIn,bubble){
  if(!url)return Promise.resolve();
  if(!bubble){
    const msgs=chatEl.querySelectorAll('.msg.bot .bubble');
    bubble=msgs.length?msgs[msgs.length-1]:null;
  }
  setStatus('RalfIA habla…','speaking');
  const bar=ensureMsgAudioBar(bubble);
  const mini=bar?.querySelector('.audio-mini');
  const speakBtn=bar?.querySelector('.speak-btn');
  if(bar){bar.dataset.audioUrl=url;bar.classList.add('has-url');}
  if(mini){mini.src=url;}
  const a=new Audio(url);
  a.preload='auto';
  currentAudio=a;
  if(speakBtn)speakBtn.classList.add('playing');
  updateStopBtn();
  return new Promise(resolve=>{
    let bargeDone=false;
    if(bargeIn&&fluidMicStream)bargeInMonitor(a,()=>{
      if(bargeDone)return;
      bargeDone=true;
      try{a.pause()}catch(e){}
      currentAudio=null;if(speakBtn)speakBtn.classList.remove('playing');
      updateStopBtn();
      resolve();
      if(onDone)onDone(true);
    });
    const done=(barged)=>{
      if(bargeDone&&barged)return;
      bargeDone=true;
      if(bargeInAbort){bargeInAbort();bargeInAbort=null;}
      currentAudio=null;
      if(speakBtn)speakBtn.classList.remove('playing');
      updateStopBtn();
      resolve();
      if(onDone)onDone(barged);
    };
    a.onended=()=>done(false);
    a.onerror=()=>done(false);
    const startPlay=()=>a.play().catch(()=>{
      if(mini){mini.play().catch(()=>done(false));}
      else done(false);
    });
    if(a.readyState>=2)startPlay();
    else{a.oncanplaythrough=startPlay;a.load();}
  });
}
function getMicLevel(analyser,data){
  analyser.getByteTimeDomainData(data);
  let sum=0;for(let i=0;i<data.length;i++){const v=(data[i]-128)/128;sum+=v*v;}
  return Math.sqrt(sum/data.length);
}
function bargeInMonitor(audioEl,onBarge){
  if(!fluidMicStream||!audioCtx)return;
  const src=audioCtx.createMediaStreamSource(fluidMicStream);
  const analyser=audioCtx.createAnalyser();analyser.fftSize=512;
  src.connect(analyser);
  const data=new Uint8Array(analyser.fftSize);
  let aborted=false;
  bargeInAbort=()=>{aborted=true;try{src.disconnect()}catch(e){}};
  const tick=()=>{
    if(aborted||!currentAudio||audioEl.paused||audioEl.ended)return;
    if(getMicLevel(analyser,data)>VAD_THRESHOLD*1.4){onBarge();return;}
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
async function ensureFluidMic(){
  if(fluidMicStream&&fluidMicStream.active)return fluidMicStream;
  fluidMicStream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
  if(!audioCtx)audioCtx=new (window.AudioContext||window.webkitAudioContext)();
  if(audioCtx.state==='suspended')await audioCtx.resume();
  return fluidMicStream;
}
function releaseFluidMic(){
  if(fluidMicStream){fluidMicStream.getTracks().forEach(t=>t.stop());fluidMicStream=null;}
  if(audioCtx){try{audioCtx.close()}catch(e){}audioCtx=null;}
}
async function vadRecordOnce(maxMs){
  const stream=await ensureFluidMic();
  const mime=pickRecorderMime();
  const recChunks=[];
  const recorder=createMediaRecorder(stream,mime);
  const recMime=recorder.mimeType||mime||'audio/webm';
  return new Promise(resolve=>{
    let speechStart=0,lastSpeech=0,silenceStart=0,started=false;
    const analyser=audioCtx.createAnalyser();analyser.fftSize=512;
    audioCtx.createMediaStreamSource(stream).connect(analyser);
    const data=new Uint8Array(analyser.fftSize);
    const startedAt=Date.now();
    recorder.ondataavailable=e=>{if(e.data.size)recChunks.push(e.data);};
    recorder.onstop=()=>{
      resolve(recChunks.length?new Blob(recChunks,{type:recMime}):null);
    };
    try{recorder.start(100)}catch(e){resolve(null);return;}
    const check=()=>{
      if(fluidState==='off'||voiceMode!=='fluid'){if(recorder.state==='recording')recorder.stop();return;}
      const level=getMicLevel(analyser,data);
      const now=Date.now();
      if(level>VAD_THRESHOLD){
        if(!started){started=true;speechStart=now;}
        lastSpeech=now;silenceStart=0;
        if(fluidState==='active')setStatus('Te escucho…','listening');
      }else if(started){
        if(!silenceStart)silenceStart=now;
        if(now-silenceStart>=VAD_SILENCE_MS){
          if(now-speechStart>=VAD_MIN_UTTERANCE_MS){recorder.stop();return;}
        }
      }
      if(now-startedAt>=(maxMs||15000)){recorder.stop();return;}
      requestAnimationFrame(check);
    };
    requestAnimationFrame(check);
  });
}
async function fluidTurn(text){
  text=(text||'').trim();
  if(!text)return;
  busy=true;updateStopBtn();
  if(matchesStop(text)){
    addMsg('user',text);history.push({role:'user',content:text});
    const farewell='De acuerdo, aquí estaré cuando me necesites.';
    const bubFarewell=addMsg('bot',farewell);history.push({role:'assistant',content:farewell});
    if(settings.speak!==false){
      await playReplyAudio(await fluidTtsUrl(farewell),null,false,bubFarewell);
    }
    busy=false;updateStopBtn();
    stopFluidAssistant();
    return;
  }
  addMsg('user',text);history.push({role:'user',content:text});
  setStatus('RalfIA piensa…','thinking');
  showTyping();
  chatAbort=new AbortController();
  const restartListen=()=>{
    if(voiceMode==='fluid'&&fluidState==='active'&&!busy&&!currentAudio&&!ttsDraining&&!ttsQueue.length)
      setTimeout(()=>vadRecordLoop(),200);
  };
  try{
    const bubble=addMsg('bot','');
    const doSpeak=settings.speak!==false;
    const res=await consumeChatStream(text,doSpeak,bubble,{bargeIn:true,onDone:restartListen});
    if(!res||!res.ok){if(!bubble.textContent)addMsg('bot','Error en conversación',true);setStatus('Error','off');}
  }catch(e){
    hideTyping();
    if(e.name!=='AbortError')addMsg('bot','Error: '+e.message,true);
    setStatus(e.name==='AbortError'?'Detenido':'Error','off');
  }finally{
    chatAbort=null;busy=false;updateStopBtn();
    await waitTtsQueue();
    restartListen();
  }
}
async function fluidTtsUrl(text){
  try{
    const r=await fetch('/api/voice/turn',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',
      body:JSON.stringify({text,speak:true,voice:settings.voice||undefined,_tts_only:true})});
    const c=await r.json();
    return c.audio_url||null;
  }catch(e){return null;}
}
async function processFluidUtterance(blob,mime){
  if(!blob||blob.size<200)return;
  setStatus('Transcribiendo…','thinking');
  const t=await transcribe(blob,mime||'audio/webm');
  const text=(typeof t.text==='string'?t.text:'').trim();
  if(!t.ok||!text){setStatus('Te escucho…','listening');return;}
  if(fluidState==='active')await fluidTurn(text);
}
async function vadRecordLoop(){
  if(voiceMode!=='fluid'||fluidState!=='active'||busy||currentAudio||ttsDraining||ttsQueue.length)return;
  listening=true;updateStopBtn();
  setStatus('Te escucho…','listening');
  const blob=await vadRecordOnce(15000);
  listening=false;updateStopBtn();
  if(voiceMode!=='fluid'||fluidState!=='active')return;
  if(blob)await processFluidUtterance(blob);
  else if(voiceMode==='fluid'&&fluidState==='active'&&!busy)vadRecordLoop();
}
async function standbyLoop(){
  if(voiceMode!=='fluid'||fluidState!=='standby')return;
  setStatus('Di Hola RalfIA','standby');
  try{
    await ensureFluidMic();
    if('wakeLock' in navigator&&!wakeLock){try{wakeLock=await navigator.wakeLock.request('screen')}catch(e){}}
  }catch(e){
    warnEl.textContent='⚠️ '+micErrorMsg(e);warnEl.classList.add('show');return;
  }
  while(voiceMode==='fluid'&&fluidState==='standby'){
    const blob=await vadRecordOnce(STANDBY_CHUNK_MS);
    if(voiceMode!=='fluid'||fluidState!=='standby')break;
    if(blob&&blob.size>200){
      const t=await transcribe(blob,'audio/webm');
      const text=(typeof t.text==='string'?t.text:'').trim();
      if(t.ok&&text&&matchesWake(text)){
        fluidState='active';
        updateModeBadge();
        const cmd=stripWakePhrase(text);
        if(cmd)await fluidTurn(cmd);
        else{
          const greet='Hola Rafael, ¿en qué te ayudo?';
          addMsg('bot',greet);history.push({role:'assistant',content:greet});
          setStatus('Te escucho…','listening');
          if(settings.speak!==false){
            const url=await fluidTtsUrl(greet);
            if(url)await playReplyAudio(url,()=>{if(fluidState==='active')vadRecordLoop();},true);
            else vadRecordLoop();
          }else vadRecordLoop();
        }
        break;
      }
    }
    await new Promise(r=>setTimeout(r,200));
  }
}
async function startFluidAssistant(){
  if(!isSecure||!hasMedia){warnEl.textContent='⚠️ '+micErrorMsg({});warnEl.classList.add('show');return;}
  voiceMode='fluid';
  fluidState='active';
  updateModeUI();
  showConvScreen(true);
  setStatus('Te escucho…','listening');
  try{
    await ensureFluidMic();
    if('wakeLock' in navigator&&!wakeLock){try{wakeLock=await navigator.wakeLock.request('screen')}catch(e){}}
    vadRecordLoop();
  }catch(e){
    warnEl.textContent='⚠️ '+micErrorMsg(e);warnEl.classList.add('show');
    stopFluidAssistant();
  }
}
function showTyping(){
  hideWelcome();
  const t=document.createElement('div');t.className='typing';t.id='typing';
  t.innerHTML='<div class="msg-av" style="background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff">RI</div><div class="typing-dots"><span></span><span></span><span></span></div>';
  chatEl.appendChild(t);scrollBottom();
}
function hideTyping(){document.getElementById('typing')?.remove()}

function getHistory(){return history.map(m=>({role:m.role,content:m.content}))}

async function sendText(text,speak){
  text=(text||'').trim();
  if(!text)return;
  if(busy){
    if(chatAbort){chatAbort.abort();chatAbort=null;}
    hideTyping();
    busy=false;
    btnSend.disabled=false;
    inputEl.disabled=false;
  }
  const doSpeak=shouldSpeak(speak);
  busy=true;btnSend.disabled=true;inputEl.disabled=true;
  updateStopBtn();
  addMsg('user',text);
  history.push({role:'user',content:text});
  if(wantsImage(text)){
    try{
      await generateImage(text,doSpeak);
    }catch(e){}
    finally{
      busy=false;btnSend.disabled=false;inputEl.disabled=false;
      updateStopBtn();inputEl.focus();
    }
    return;
  }
  setStatus('RalfIA piensa…','thinking');
  showTyping();
  chatAbort=new AbortController();
  let listenScheduled=false;
  try{
    const useStream=doSpeak&&voiceMode!=='fluid';
    if(useStream){
      const streamed=await sendTextStream(text,doSpeak);
      if(streamed){listenScheduled=false;return;}
    }
    hideTyping();
    const r=await fetch('/api/voice/chat',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',
      body:JSON.stringify(chatPayload({text,speak:doSpeak})),signal:chatAbort.signal});
    const ct=(r.headers.get('content-type')||'').toLowerCase();
    if(!r.ok||!ct.includes('json')){
      let errBody='No se pudo conectar con el servidor de chat';
      try{if(ct.includes('json'))errBody=parseJsonError(r,await r.json());}catch(e){}
      addMsg('bot',String(errBody),true);setStatus('Error','off');
      return;
    }
    const c=await r.json();
        if(!c.ok){
      addMsg('bot',c.reply||c.detail||c.error||'No pude responder.',true);setStatus('Error','off');
      return;
    }
    if(c.conversation_id)setConversationId(c.conversation_id);
    const bubble=addMsg('bot',c.reply);
    if(c.image_url)appendImageToBubble(c.image_url);
    history.push({role:'assistant',content:c.reply});
    if(c.audio_url&&doSpeak){
      await playReplyAudio(c.audio_url,null,false,bubble);
    }
  }catch(e){
    hideTyping();
    if(e.name!=='AbortError')addMsg('bot','Error: '+e.message,true);
    setStatus(e.name==='AbortError'?'Detenido':'Sin conexión',e.name==='AbortError'?'':'off');
  }finally{
    chatAbort=null;busy=false;btnSend.disabled=false;inputEl.disabled=false;
    updateStopBtn();
    inputEl.focus();
  }
}

async function waitTtsQueue(){
  while(ttsDraining||ttsQueue.length)await new Promise(r=>setTimeout(r,60));
}
async function enqueueTtsChunk(url,bubble,opts){
  if(!url)return;
  ttsQueue.push({url,bubble,opts:opts||{}});
  if(!ttsDraining)drainTtsQueue();
}
async function drainTtsQueue(){
  ttsDraining=true;
  while(ttsQueue.length){
    const {url,bubble,opts}=ttsQueue.shift();
    await playReplyAudio(url,opts.onDone,opts.bargeIn,bubble);
  }
  ttsDraining=false;
  if(ttsQueue.length)drainTtsQueue();
  else updateStopBtn();
}
async function consumeChatStream(text,speak,bubble,opts){
  opts=opts||{};
  ttsStreamActive=false;
  const r=await fetch('/api/voice/chat/stream',{method:'POST',credentials:'include',signal:(chatAbort&&chatAbort.signal),
    headers:{'Content-Type':'application/json','Accept':'text/event-stream'},
    body:JSON.stringify(chatPayload({text,speak}))});
  if(!r.ok||!(r.headers.get('content-type')||'').includes('text/event-stream'))return false;
  hideTyping();
  if(!bubble)bubble=addMsg('bot','');
  let full='';
  const reader=r.body.getReader();
  const dec=new TextDecoder();
  let buf='';
  const bargeIn=!!opts.bargeIn;
  while(true){
    const {done,value}=await reader.read();
    if(done)break;
    buf+=dec.decode(value,{stream:true});
    const events=buf.split('\\n\\n');
    buf=events.pop()||'';
    for(const ev of events){
      if(!ev.startsWith('data: '))continue;
      const d=JSON.parse(ev.slice(6));
      if(d.token){full+=d.token;bubble.textContent=full;scrollBottom();}
      if(d.tts_chunk&&d.audio_url&&speak!==false){
        ttsStreamActive=true;
        bubble.dataset.speakText=full;
        ensureMsgAudioBar(bubble);
        setStatus('RalfIA habla…','speaking');
        enqueueTtsChunk(d.audio_url,bubble,{bargeIn,onDone:opts.onChunkDone});
      }
      if(d.text_done){
        history.push({role:'assistant',content:d.reply||full});
        if(d.conversation_id)setConversationId(d.conversation_id);
        bubble.dataset.speakText=d.reply||full;
        ensureMsgAudioBar(bubble);
        if(speak!==false&&!ttsStreamActive)setStatus('Preparando voz…','thinking');
      }
      if(d.done){
        if(!d.ok){bubble.classList.add('error');bubble.textContent=d.error||d.detail||'Error';return {ok:false};}
        if(!d.text_done){
          history.push({role:'assistant',content:d.reply||full});
          if(d.conversation_id)setConversationId(d.conversation_id);
        }
        bubble.dataset.speakText=d.reply||full;
        if(d.image_url)appendImageToBubble(d.image_url);
        if(d.audio_url&&speak!==false&&!ttsStreamActive){
          await playReplyAudio(d.audio_url,opts.onDone,bargeIn,bubble);
        }else{
          await waitTtsQueue();
          if(opts.onDone)opts.onDone();
        }
        return {ok:true,reply:d.reply||full};
      }
      if(d.error){bubble.classList.add('error');bubble.textContent=d.error;return {ok:false};}
    }
  }
  if(full){history.push({role:'assistant',content:full});return {ok:true,reply:full};}
  return {ok:false};
}
async function sendTextStream(text,speak){
  if(wantsImage(text))return false;
  try{
    const bubble=addMsg('bot','');
    const res=await consumeChatStream(text,speak,bubble,{onDone:()=>scheduleNextListen(500)});
    return !!(res&&res.ok);
  }catch(e){
    if(e.name==='AbortError')throw e;
    return false;
  }
}

function mimeToExt(mime){
  const m=(mime||'').toLowerCase();
  if(m.includes('mp4')||m.includes('m4a'))return '.m4a';
  if(m.includes('aac'))return '.aac';
  if(m.includes('ogg'))return '.ogg';
  if(m.includes('webm'))return '.webm';
  return '.webm';
}
function pickRecorderMime(){
  if(typeof MediaRecorder==='undefined')return '';
  for(const m of ['audio/webm;codecs=opus','audio/webm','audio/mp4','audio/aac']){
    try{if(MediaRecorder.isTypeSupported(m))return m}catch(e){}
  }
  return '';
}
function createMediaRecorder(stream,mime){
  if(typeof MediaRecorder==='undefined')throw new Error('MediaRecorder no soportado');
  const opts=mime?{mimeType:mime}:{};
  try{return new MediaRecorder(stream,opts)}
  catch(e){try{return new MediaRecorder(stream)}catch(e2){throw e2}}
}
function updateModeUI(){
  const isFluid=voiceMode==='fluid';
  const isPtt=voiceMode==='ptt';
  if(btnModePtt){
    btnModePtt.classList.toggle('active',isPtt);
    btnModePtt.classList.toggle('listening',pttRecording);
  }
  if(btnModeFluid)btnModeFluid.classList.toggle('active',isFluid);
  if(composerEl){
    composerEl.classList.toggle('fluid-mode',isFluid);
    composerEl.classList.toggle('ptt-mode',isPtt);
  }
  if(composerHint){
    if(isFluid){
      composerHint.textContent='Conversación activa · habla con naturalidad · «detente» para pausar · ■ detiene todo';
    }else if(isPtt){
      composerHint.textContent=pttRecording
        ?'🔴 Grabando — toca 🎤 o ■ para enviar lo dicho'
        :busy
          ?'Procesando respuesta… ■ para cancelar · 🎤 otra vez para salir del modo'
          :'Modo PTT · toca 🎤 para grabar otra vez · toca 🎤 sin grabar para salir';
    }else{
      composerHint.textContent='🎤 Pulsar y hablar: toca para grabar (rojo) · toca otra vez para enviar · ■ detiene todo';
    }
  }
  updateModeBadge();
  updateComposerPadding();
  updateStopBtn();
}
async function togglePttMode(){
  if(voiceMode==='fluid')stopFluidAssistant();
  if(voiceMode==='idle'){
    voiceMode='ptt';
    updateModeUI();
    await startPttRecording();
    return;
  }
  if(voiceMode==='ptt'){
    if(pttRecording){
      stopPttRecording(true);
      return;
    }
    if(busy||currentAudio){
      stopResponse();
      deactivatePttMode();
      return;
    }
    deactivatePttMode();
  }
}
function stopPttRecording(transcribe){
  if(!pttRecording&&!(rec&&rec.state==='recording'))return;
  pttTranscribeOnStop=!!transcribe;
  if(rec&&rec.state==='recording')rec.stop();
  else finishPttRecording();
}
async function toggleFluidMode(){
  if(voiceMode==='fluid'){
    stopFluidAssistant();
    return;
  }
  if(voiceMode==='ptt')deactivatePttMode();
  await startFluidAssistant();
}
async function startPttRecording(){
  if(pttRecording||busy)return;
  if(!isSecure||!hasMedia){warnEl.textContent='⚠️ '+micErrorMsg({});warnEl.classList.add('show');return}
  pttTranscribeOnStop=true;
  listening=true;
  pttRecording=true;
  updateModeUI();
  try{if('wakeLock' in navigator&&!wakeLock)wakeLock=await navigator.wakeLock.request('screen')}catch(e){}
  await recordOnce();
}
async function transcribe(blob,mime){
  const ext=mimeToExt(mime||blob.type);
  const fd=new FormData();fd.append('audio',blob,'voice'+ext);
  const r=await fetch('/api/voice/transcribe',{method:'POST',body:fd,credentials:'include'});
  const ct=(r.headers.get('content-type')||'').toLowerCase();
  if(!r.ok){
    let err='Error STT ('+r.status+')';
    try{
      if(ct.includes('json'))err=(await r.json()).error||err;
      else{const t=await r.text();if(t.includes('<!DOCTYPE'))err='Servidor STT no disponible (proxy/timeout)';}
    }catch(e){}
    return {ok:false,error:err};
  }
  if(!ct.includes('json'))return {ok:false,error:'Respuesta STT inválida (no JSON)'};
  return r.json();
}

function stopActiveStream(){if(activeStream){activeStream.getTracks().forEach(t=>t.stop());activeStream=null}}
function stopListening(skipProcess){
  listening=false;
  pttRecording=false;
  updateModeUI();
  if(recordTimer){clearTimeout(recordTimer);recordTimer=null;}
  if(rec&&rec.state==='recording'){
    if(skipProcess)pttTranscribeOnStop=false;
    rec.stop();
  }
  stopActiveStream();
  if(wakeLock){wakeLock.release();wakeLock=null}
  if(!busy&&voiceMode==='idle')setStatus('En línea · listo','');
}
async function finishPttRecording(){
  pttRecording=false;
  listening=false;
  updateModeUI();
}
async function processPttChunks(recMime){
  if(!chunks.length){
    setStatus('No capté audio — intenta de nuevo','');
    if(voiceMode==='ptt')setStatus('Modo PTT · toca 🎤 para grabar','');
    return;
  }
  setStatus('Transcribiendo…','thinking');
  try{
    const t=await transcribe(new Blob(chunks,{type:recMime}),recMime);
    const text=(typeof t.text==='string'?t.text:'').trim();
    if(!t.ok){
      setStatus(t.error||'Servicio STT no disponible','off');
      warnEl.textContent='⚠️ '+(t.error||'No se pudo transcribir');
      warnEl.classList.add('show');
      return;
    }
    if(!text){
      setStatus('No te entendí — habla más cerca del micrófono','');
      return;
    }
    await sendText(text,shouldSpeak(true));
  }catch(e){
    setStatus('Error STT','off');
    warnEl.textContent='⚠️ '+(e.message||'Error transcribiendo');
    warnEl.classList.add('show');
  }finally{
    chunks=[];
    if(voiceMode==='ptt'&&!busy)setStatus('Modo PTT · toca 🎤 para grabar otra vez','');
    updateModeUI();
  }
}

async function recordOnce(){
  if(!pttRecording&&!listening)return;
  if(typeof MediaRecorder==='undefined'){
    warnEl.textContent='⚠️ Tu navegador no soporta grabación de audio.';
    warnEl.classList.add('show');stopListening(true);return;
  }
  chunks=[];
  let stream;
  try{
    stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
    activeStream=stream;
  }catch(e){setStatus(micErrorMsg(e),'off');stopListening(true);return}
  let mime=pickRecorderMime();
  const maxMs=MAX_RECORD_MS;
  setStatus('🔴 Grabando… toca 🎤 o ■ para enviar','listening');
  try{
    rec=createMediaRecorder(stream,mime);
    if(rec.mimeType)mime=rec.mimeType;
  }catch(e){
    setStatus('Grabación no disponible','off');
    warnEl.textContent='⚠️ '+(e.message||'MediaRecorder no soportado');
    warnEl.classList.add('show');
    stream.getTracks().forEach(t=>t.stop());activeStream=null;
    stopListening(true);return;
  }
  const recMime=rec.mimeType||mime||'audio/webm';
  rec.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
  rec.onstop=async()=>{
    stream.getTracks().forEach(t=>t.stop());activeStream=null;
    if(recordTimer){clearTimeout(recordTimer);recordTimer=null;}
    const doTranscribe=pttTranscribeOnStop;
    pttTranscribeOnStop=true;
    await finishPttRecording();
    if(!doTranscribe){chunks=[];return;}
    await processPttChunks(recMime);
  };
  try{rec.start(250)}
  catch(e){
    setStatus('Error al grabar','off');
    warnEl.textContent='⚠️ '+(e.message||'No se pudo iniciar grabación');
    warnEl.classList.add('show');
    stopListening(true);return;
  }
  recordTimer=setTimeout(()=>{if(rec&&rec.state==='recording')rec.stop()},maxMs);
}

btnModePtt.onclick=()=>togglePttMode();
btnModeFluid.onclick=()=>toggleFluidMode();
if(btnStop)btnStop.onclick=()=>abortAll();
if(convExit)convExit.onclick=()=>stopFluidAssistant();
updateModeUI();
updateStopBtn();

btnSend.onclick=()=>{const t=inputEl.value;inputEl.value='';inputEl.style.height='auto';sendText(t,false)};
inputEl.addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();btnSend.click()}
});
inputEl.addEventListener('input',()=>{
  inputEl.style.height='auto';
  inputEl.style.height=Math.min(inputEl.scrollHeight,120)+'px';
  updateComposerPadding();
  scrollBottom();
});
inputEl.addEventListener('focus',()=>{setTimeout(()=>{updateComposerPadding();scrollBottom();},300);});

async function loadTtsVoices(){
  try{
    const r=await fetch('/api/voice/tts/voices',{credentials:'include'});
    if(!r.ok)return;
    const d=await r.json();
    ttsVoices=d.voices||[];
    if(!settingVoice)return;
    settingVoice.innerHTML=ttsVoices.map(v=>'<option value="'+esc(v.id)+'">'+esc(v.label)+'</option>').join('');
    const def=d.default||'';
    const preferred=settings.voice||def||(ttsVoices.find(v=>v.id&&v.id.startsWith('xtts:'))&&ttsVoices.find(v=>v.id.startsWith('xtts:')).id)||(ttsVoices[0]&&ttsVoices[0].id)||'';
    settingVoice.value=preferred;
    if(!settings.voice&&preferred){settings.voice=preferred;saveSettings();}
  }catch(e){}
}
let voiceLabRecorder=null,voiceLabChunks=[],voiceLabRecording=false,voiceLabPoll=null;
const voiceLabStats=document.getElementById('voiceLabStats'),voiceLabStatus=document.getElementById('voiceLabStatus'),
  voiceLabRecord=document.getElementById('voiceLabRecord'),voiceLabClone=document.getElementById('voiceLabClone'),
  voiceLabActivate=document.getElementById('voiceLabActivate'),voiceLabLang=document.getElementById('voiceLabLang');
async function refreshVoiceLab(){
  if(!voiceLabStats)return;
  try{
    const r=await fetch('/api/voice/tts/lab/status',{credentials:'include'});
    if(!r.ok){voiceLabStats.textContent='Inicia sesión para ver el laboratorio.';return;}
    const d=await r.json();
    const min=d.min_samples||15;
    voiceLabStats.textContent='Muestras: '+d.sample_count+' / '+min+' · '+(d.cloned?'Clonada ✓':'Sin clonar')+(d.active_in_ralfia?' · Activa en RalfIA':'');
    if(voiceLabClone)voiceLabClone.disabled=!d.ready_for_clone||d.status==='preparing'||d.status==='loading_model'||d.status==='synthesizing'||d.status==='queued';
    if(voiceLabActivate)voiceLabActivate.disabled=!d.cloned||!!d.active_in_ralfia;
    if(d.message&&voiceLabStatus)voiceLabStatus.textContent=d.message;
    if(d.status&&['preparing','loading_model','synthesizing','queued'].includes(d.status)){
      if(!voiceLabPoll)voiceLabPoll=setInterval(refreshVoiceLab,4000);
    }else if(voiceLabPoll){clearInterval(voiceLabPoll);voiceLabPoll=null;}
  }catch(e){voiceLabStats.textContent='No se pudo cargar el laboratorio.';}
}
async function toggleVoiceLabRecord(){
  if(!isSecure||!hasMedia){if(voiceLabStatus)voiceLabStatus.textContent=micErrorMsg({});return;}
  if(voiceLabRecording){
    voiceLabRecorder.stop();
    return;
  }
  try{
    const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
    const mime=pickRecorderMime();
    voiceLabChunks=[];
    voiceLabRecorder=createMediaRecorder(stream,mime);
    const recMime=voiceLabRecorder.mimeType||mime||'audio/webm';
    voiceLabRecorder.ondataavailable=e=>{if(e.data.size)voiceLabChunks.push(e.data);};
    voiceLabRecorder.onstop=async()=>{
      stream.getTracks().forEach(t=>t.stop());
      voiceLabRecording=false;
      if(voiceLabRecord){voiceLabRecord.textContent='● Grabar muestra';voiceLabRecord.classList.remove('voice-lab-recording');}
      const blob=voiceLabChunks.length?new Blob(voiceLabChunks,{type:recMime}):null;
      voiceLabChunks=[];
      if(!blob||blob.size<500){if(voiceLabStatus)voiceLabStatus.textContent='Muestra demasiado corta.';return;}
      if(voiceLabStatus)voiceLabStatus.textContent='Subiendo muestra…';
      const fd=new FormData();
      fd.append('audio',blob,'sample'+mimeToExt(recMime));
      const r=await fetch('/api/voice/tts/sample',{method:'POST',credentials:'include',body:fd});
      const d=await r.json();
      if(!r.ok||!d.ok){if(voiceLabStatus)voiceLabStatus.textContent=d.error||'Error al guardar muestra';return;}
      if(voiceLabStatus)voiceLabStatus.textContent='Muestra guardada ('+d.count+' total).';
      refreshVoiceLab();
    };
    voiceLabRecorder.start(250);
    voiceLabRecording=true;
    if(voiceLabRecord){voiceLabRecord.textContent='■ Detener grabación';voiceLabRecord.classList.add('voice-lab-recording');}
    if(voiceLabStatus)voiceLabStatus.textContent='Grabando… habla 5–15 segundos y pulsa de nuevo.';
  }catch(e){if(voiceLabStatus)voiceLabStatus.textContent=micErrorMsg(e);}
}
async function startVoiceClone(){
  if(voiceLabStatus)voiceLabStatus.textContent='Iniciando clonación XTTS…';
  const lang=voiceLabLang?voiceLabLang.value:'es';
  const r=await fetch('/api/voice/tts/lab/clone',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({language:lang})});
  const d=await r.json();
  if(voiceLabStatus)voiceLabStatus.textContent=d.message||d.detail||d.error||'Clonación solicitada.';
  refreshVoiceLab();
}
async function activateVoiceClone(){
  if(voiceLabStatus)voiceLabStatus.textContent='Activando voz…';
  const r=await fetch('/api/voice/tts/lab/activate',{method:'POST',credentials:'include'});
  const d=await r.json();
  if(voiceLabStatus)voiceLabStatus.textContent=d.message||d.detail||d.error||'Voz activada.';
  await loadTtsVoices();
  refreshVoiceLab();
}
if(voiceLabRecord)voiceLabRecord.onclick=toggleVoiceLabRecord;
if(voiceLabClone)voiceLabClone.onclick=startVoiceClone;
if(voiceLabActivate)voiceLabActivate.onclick=activateVoiceClone;
setInterval(()=>{
  const active=busy||ttsDraining||currentAudio||generatingImage||(listening&&voiceMode==='fluid');
  if(!active){window.__busySince=0;return;}
  if(!window.__busySince)window.__busySince=Date.now();
  else if(Date.now()-window.__busySince>120000){
    console.warn('RalfIA: watchdog liberó estado pegado');
    abortAll();
    window.__busySince=0;
  }
},5000);
function openSettings(){
  loadSettings();
  loadTtsVoices().then(()=>{
    if(settingVoice&&settings.voice)settingVoice.value=settings.voice;
  });
  refreshVoiceLab();
  if(settingsOverlay)settingsOverlay.classList.add('show');
}
function closeSettings(){if(settingsOverlay)settingsOverlay.classList.remove('show')}
if(btnSettings)btnSettings.onclick=openSettings;
document.getElementById('settingsClose')?.addEventListener('click',closeSettings);
document.getElementById('settingsCloseX')?.addEventListener('click',closeSettings);
document.getElementById('settingsSave')?.addEventListener('click',()=>{saveSettingsFromUI();closeSettings();});
settingsOverlay?.addEventListener('click',e=>{if(e.target===settingsOverlay)closeSettings();});

document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>sendText(c.dataset.q,false));

function renderHistory(msgs){
  chatEl.querySelectorAll('.msg:not(.welcome)').forEach(el=>el.remove());
  history=[];
  for(const m of msgs||[]){
    if(!m.content)continue;
    history.push({role:m.role,content:m.content});
    addMsg(m.role==='user'?'user':'bot',m.content);
  }
  if(welcomeEl&&(!msgs||!msgs.length))welcomeEl.style.display='';
}
function formatConvDate(iso){
  if(!iso)return '';
  try{
    const d=new Date(iso);
    return d.toLocaleDateString('es',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
  }catch(e){return ''}
}
function renderConvList(){
  if(!histList)return;
  if(!conversations.length){
    histList.innerHTML='<p style="padding:.75rem;color:var(--muted);font-size:.82rem">Sin conversaciones guardadas.</p>';
    return;
  }
  histList.innerHTML=conversations.map(c=>{
    const active=c.conversation_id===conversationId?' active':'';
    return '<button type="button" class="hist-item'+active+'" data-id="'+esc(c.conversation_id)+'">'+
      esc(c.title||'Sin título')+'<small>'+formatConvDate(c.updated_at||c.created_at)+'</small></button>';
  }).join('');
  histList.querySelectorAll('.hist-item').forEach(btn=>{
    btn.onclick=()=>switchConversation(btn.dataset.id);
  });
}
function openHistPanel(){
  if(histPanel)histPanel.classList.add('open');
  if(histOverlay)histOverlay.classList.add('show');
  loadConversations();
}
function closeHistPanel(){
  if(histPanel)histPanel.classList.remove('open');
  if(histOverlay)histOverlay.classList.remove('show');
}
async function loadConversations(){
  try{
    const r=await fetch('/api/voice/conversations',{credentials:'include'});
    if(!r.ok)return;
    const d=await r.json();
    conversations=d.conversations||[];
    if(d.active_conversation_id&&!conversationId)setConversationId(d.active_conversation_id);
    renderConvList();
  }catch(e){}
}
async function createNewChat(){
  try{
    const r=await fetch('/api/voice/conversations',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'Nueva conversación'})});
    if(!r.ok)return;
    const d=await r.json();
    setConversationId(d.conversation_id);
    renderHistory([]);
    if(welcomeEl)welcomeEl.style.display='';
    if(histBadge)histBadge.textContent='';
    closeHistPanel();
    await loadConversations();
    inputEl.focus();
  }catch(e){}
}
async function switchConversation(convId){
  if(!convId||convId===conversationId){closeHistPanel();return}
  try{
    const r=await fetch('/api/voice/conversations/'+encodeURIComponent(convId)+'/switch',{method:'POST',credentials:'include'});
    if(!r.ok)return;
    const d=await r.json();
    setConversationId(d.conversation_id);
    renderHistory(d.messages||[]);
    if(histBadge)histBadge.textContent=d.count?'· '+d.count+' msgs':'';
    closeHistPanel();
    renderConvList();
  }catch(e){}
}
async function loadHistory(){
  try{
    const url=conversationId?'/api/voice/history?conversation_id='+encodeURIComponent(conversationId):'/api/voice/history';
    const r=await fetch(url,{credentials:'include'});
    if(!r.ok)return;
    const d=await r.json();
    if(d.conversation_id)setConversationId(d.conversation_id);
    if(d.messages&&d.messages.length){
      renderHistory(d.messages);
      if(histBadge)histBadge.textContent='· '+d.count+' msgs';
    }
  }catch(e){}
}
if(btnNewChat)btnNewChat.onclick=createNewChat;
if(btnHist)btnHist.onclick=openHistPanel;
if(histClose)histClose.onclick=closeHistPanel;
if(histOverlay)histOverlay.onclick=closeHistPanel;
if(orbWrap)orbWrap.onclick=(e)=>{e.stopPropagation();orbMenuOpen=!orbMenuOpen;if(orbMenu)orbMenu.classList.toggle('open',orbMenuOpen);};
document.addEventListener('click',()=>{orbMenuOpen=false;if(orbMenu)orbMenu.classList.remove('open');});
document.getElementById('orbMenuNew')?.addEventListener('click',(e)=>{e.stopPropagation();orbMenuOpen=false;if(orbMenu)orbMenu.classList.remove('open');createNewChat();});
document.getElementById('orbMenuHist')?.addEventListener('click',(e)=>{e.stopPropagation();orbMenuOpen=false;if(orbMenu)orbMenu.classList.remove('open');openHistPanel();});
document.getElementById('orbMenuSettings')?.addEventListener('click',(e)=>{e.stopPropagation();orbMenuOpen=false;if(orbMenu)orbMenu.classList.remove('open');openSettings();});
document.getElementById('orbMenuLogout')?.addEventListener('click',async(e)=>{e.stopPropagation();orbMenuOpen=false;if(orbMenu)orbMenu.classList.remove('open');if(btnLogout)btnLogout.click();});
btnAttach.onclick=()=>fileInput.click();
fileInput.onchange=async()=>{
  const f=fileInput.files&&fileInput.files[0];
  if(!f)return;
  setStatus('Subiendo…','busy');
  const fd=new FormData();fd.append('file',f);
  try{
    const r=await fetch('/api/voice/upload',{method:'POST',credentials:'include',body:fd});
    const d=await r.json();
    if(!r.ok||!d.ok){addMsg('bot','Error adjunto: '+(d.error||'falló'),true);return}
    addMsg('user','📎 '+d.filename);
    input.value='Analiza el archivo adjunto: '+d.filename+(d.note?' — '+d.note:'');
    await sendText(input.value,false);
  }catch(e){addMsg('bot',e.message,true)}
  finally{fileInput.value='';setStatus('Listo','');}
};
async function checkSession(){
  try{
    const r=await fetch('/api/voice/me',{credentials:'include'});
    if(!r.ok){loginScreen.classList.remove('hidden');return false}
    const d=await r.json();
    currentUser=d.user;
    setWelcomeTitle(currentUser);
    loginScreen.classList.add('hidden');
    await loadConversations();
    await loadHistory();
    return true;
  }catch(e){loginScreen.classList.remove('hidden');return false}
}

loginBtn.onclick=async()=>{
  loginErr.classList.remove('show');
  loginBtn.disabled=true;
  const prevLabel=loginBtn.textContent;
  loginBtn.textContent=registerMode?'Enviando…':'Entrando…';
  const url=registerMode?'/api/voice/register':'/api/voice/login';
  const body=registerMode?{username:loginUser.value,password:loginPass.value,display_name:loginName.value}:{username:loginUser.value,password:loginPass.value};
  try{
    const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify(body)});
    const raw=await r.text();
    let d={};
    try{d=JSON.parse(raw)}catch(_){throw new Error(r.ok?'Respuesta inválida del servidor':'No se pudo conectar (¿red o Cloudflare?). Prueba WiFi casa: http://192.168.1.5:8200');}
    if(registerMode){
      if(!r.ok||!d.ok){loginErr.textContent=d.message||d.error||'Error';loginErr.classList.add('show');return}
      loginErr.style.color='#86efac';loginErr.textContent=d.message||'Cuenta creada — espera aprobación de Rafael.';loginErr.classList.add('show');
      registerMode=false;loginName.style.display='none';backLoginBtn.style.display='none';
      loginTitle.textContent='Entrar a RalfIA';loginBtn.textContent='Entrar';registerBtn.style.display='block';
      return;
    }
    if(!r.ok||!d.ok){
      loginErr.style.color='#fecaca';
      loginErr.textContent=d.message||(d.error==='invalid_credentials'?'Usuario o contraseña incorrectos.':d.error)||'No se pudo entrar';
      loginErr.classList.add('show');return;
    }
    currentUser=d.user;
    setWelcomeTitle(currentUser);
    loginScreen.classList.add('hidden');
    loginPass.value='';
  }catch(e){loginErr.style.color='#fecaca';loginErr.textContent=e.message;loginErr.classList.add('show')}
  finally{loginBtn.disabled=false;loginBtn.textContent=prevLabel}
};
loginPass.onkeydown=(e)=>{if(e.key==='Enter')loginBtn.click()};
loginUser.onkeydown=(e)=>{if(e.key==='Enter')loginPass.focus()};
registerBtn.onclick=()=>{
  registerMode=true;loginErr.classList.remove('show');loginErr.style.color='#fecaca';
  loginTitle.textContent='Crear cuenta RalfIA';
  loginHint.textContent='Elige un usuario y contraseña. Rafael debe aprobarte para acceder a memoria de empresa.';
  loginName.style.display='block';backLoginBtn.style.display='block';
  loginBtn.textContent='Solicitar acceso';registerBtn.style.display='none';
  googleBtn.classList.remove('show');loginDivider.classList.remove('show');
};
backLoginBtn.onclick=()=>{
  registerMode=false;loginName.style.display='none';backLoginBtn.style.display='none';
  loginTitle.textContent='Entrar a RalfIA';
  loginHint.innerHTML='Correo o usuario + contraseña local, <b>o</b> Google. Ej: <b>rafagye@gmail.com</b> o <b>rafagye</b>.';
  loginBtn.textContent='Entrar';registerBtn.style.display='block';
  if(window.__GOOGLE_OAUTH__)googleBtn.classList.add('show');
  loginDivider.classList.toggle('show',!!window.__GOOGLE_OAUTH__);
};

googleBtn.onclick=()=>{window.location.href='/api/voice/auth/google'};
if(btnLogout)btnLogout.onclick=async()=>{
  await fetch('/api/voice/logout',{method:'POST',credentials:'include'});
  currentUser=null;
  loginScreen.classList.remove('hidden');
  if(userPill)userPill.textContent='';
  if(adminPanel)adminPanel.classList.remove('show');
  history.replaceState(null,'',window.location.pathname);
};

function showAuthMessage(){
  const p=new URLSearchParams(window.location.search);
  const auth=p.get('auth');
  if(auth==='pending'){
    if(pendingScreen)pendingScreen.classList.remove('hidden');
    loginScreen.classList.add('hidden');
    history.replaceState(null,'',window.location.pathname);
  }else if(auth==='error'){
    loginScreen.classList.remove('hidden');
    loginErr.style.color='#fecaca';
    loginErr.textContent=decodeURIComponent(p.get('msg')||'Error al iniciar con Google');
    loginErr.classList.add('show');
    history.replaceState(null,'',window.location.pathname);
  }
}

(async function init(){
  showAuthMessage();
  setStatus('En línea · listo','');
  loadSettings();
  updateModeUI();
  updateComposerPadding();
  if(!isSecure||!hasMedia){
    warnEl.textContent='⚠️ '+micErrorMsg({});
    warnEl.classList.add('show');
  }
  window.__GOOGLE_OAUTH__=!!window.__GOOGLE_OAUTH__;
  if(window.__GOOGLE_OAUTH__&&!registerMode){
    googleBtn.classList.add('show');
    loginDivider.classList.add('show');
  }
  try{
    const h=await fetch('/api/voice/health').then(r=>r.json());
    window.__GOOGLE_OAUTH__=!!(h.google_oauth||window.__GOOGLE_OAUTH__);
    if(window.__GOOGLE_OAUTH__&&!registerMode){
      googleBtn.classList.add('show');
      loginDivider.classList.add('show');
    }
    if(h.auth_required) await checkSession();
    else loginScreen.classList.add('hidden');
    setStatus(h.ok?'En línea · listo':'Parcial','');
    await loadTtsVoices();
  }catch(e){
    if(window.__GOOGLE_OAUTH__&&!registerMode){
      googleBtn.classList.add('show');
      loginDivider.classList.add('show');
    }
    setStatus('Sin conexión al servidor','off');
  }
})();
</script>
</body>
</html>"""


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, timeout: float = 120.0) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _extract_whisper_text(data: Any) -> str:
    """Normaliza respuesta Whisper (json, txt o json anidado en text)."""
    if isinstance(data, str):
        s = data.strip()
        if s.startswith("{"):
            try:
                return _extract_whisper_text(json.loads(s))
            except json.JSONDecodeError:
                return s
        return s
    if isinstance(data, dict):
        text = str(data.get("text") or data.get("transcription") or "").strip()
        if text.startswith("{"):
            try:
                return _extract_whisper_text(json.loads(text))
            except json.JSONDecodeError:
                pass
        if text:
            return text
        segments = data.get("segments") or []
        if segments:
            return " ".join(str(s.get("text", "")).strip() for s in segments if s.get("text")).strip()
    return ""


def _mime_to_voice_ext(mime: str) -> str:
    m = (mime or "audio/webm").lower()
    if "mp4" in m or "m4a" in m:
        return ".m4a"
    if "aac" in m:
        return ".aac"
    if "ogg" in m:
        return ".ogg"
    return ".webm"


def _whisper_transcribe(raw: bytes, *, mime: str = "audio/webm") -> dict[str, Any]:
    import httpx

    url = f"{WHISPER}/asr"
    params = {"task": "transcribe", "language": "es", "output": "json"}
    ext = _mime_to_voice_ext(mime)
    files = {"audio_file": (f"voice{ext}", raw, mime)}
    try:
        r = httpx.post(url, params=params, files=files, timeout=120.0)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        raw_text = r.text if not ctype.startswith("application/json") else ""
        if raw_text.strip().lower().startswith("<!doctype") or raw_text.strip().lower().startswith("<html"):
            return {"ok": False, "error": "whisper_unavailable_html_response"}
        if ctype.startswith("application/json"):
            data = r.json()
        else:
            data = {"text": r.text}
        text = _extract_whisper_text(data)
        return {"ok": bool(text), "text": text, "raw": data if isinstance(data, dict) else {"text": str(data)}}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _voice_username(user: dict[str, Any]) -> str:
    return str(user.get("username") or user.get("owner_id") or "anon").lower()


def _voice_conversation_id(user: dict[str, Any], conv_id: str | None = None) -> str:
    uname = _voice_username(user)
    if conv_id:
        cid = str(conv_id).strip()
        prefix = f"voice:{uname}:"
        if cid.startswith(prefix):
            return cid
        if cid.startswith("voice:") and cid.count(":") >= 2:
            return cid
        if ":" not in cid:
            return f"{prefix}{cid}"
        return cid
    return f"voice:{uname}"


def _resolve_conv_id(
    user: dict[str, Any],
    *,
    payload: dict[str, Any] | None = None,
    request: Request | None = None,
    create_if_missing: bool = True,
) -> str:
    uname = _voice_username(user)
    raw = ""
    if payload:
        raw = str(payload.get("conversation_id") or payload.get("conv_id") or "").strip()
    if not raw and request:
        raw = (request.headers.get("X-Voice-Conversation-Id") or request.cookies.get("voice_conv_id") or "").strip()
    if raw:
        return _voice_conversation_id(user, raw)
    try:
        db = mongo_store.get_db()
        latest = db[COL_VOICE_CONVERSATIONS].find_one(
            {"username": uname},
            sort=[("updated_at", -1)],
        )
        if latest and latest.get("conversation_id"):
            return str(latest["conversation_id"])
        legacy = f"voice:{uname}"
        if db[COL_VOICE_MESSAGES].find_one({"conversation_id": legacy}):
            _ensure_voice_conversation(user, legacy, title="Conversación anterior")
            return legacy
    except Exception:
        pass
    if create_if_missing:
        return _create_voice_conversation(user)
    return f"voice:{uname}"


def _ensure_voice_conversation(user: dict[str, Any], conv_id: str, *, title: str | None = None) -> None:
    from datetime import datetime, timezone

    try:
        db = mongo_store.get_db()
        uname = _voice_username(user)
        now = datetime.now(timezone.utc).isoformat()
        existing = db[COL_VOICE_CONVERSATIONS].find_one({"conversation_id": conv_id})
        if existing:
            return
        db[COL_VOICE_CONVERSATIONS].insert_one(
            {
                "conversation_id": conv_id,
                "username": uname,
                "owner_id": user.get("owner_id"),
                "title": (title or "Nueva conversación")[:120],
                "created_at": now,
                "updated_at": now,
            }
        )
    except Exception:
        pass


def _create_voice_conversation(user: dict[str, Any], *, title: str | None = None) -> str:
    from datetime import datetime, timezone

    uname = _voice_username(user)
    conv_id = f"voice:{uname}:{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    try:
        db = mongo_store.get_db()
        db[COL_VOICE_CONVERSATIONS].insert_one(
            {
                "conversation_id": conv_id,
                "username": uname,
                "owner_id": user.get("owner_id"),
                "title": (title or "Nueva conversación")[:120],
                "created_at": now,
                "updated_at": now,
            }
        )
    except Exception:
        pass
    return conv_id


def _touch_voice_conversation(user: dict[str, Any], conv_id: str, *, content: str = "", role: str = "") -> None:
    from datetime import datetime, timezone

    try:
        db = mongo_store.get_db()
        uname = _voice_username(user)
        now = datetime.now(timezone.utc).isoformat()
        _ensure_voice_conversation(user, conv_id)
        update: dict[str, Any] = {"updated_at": now}
        doc = db[COL_VOICE_CONVERSATIONS].find_one({"conversation_id": conv_id}) or {}
        title = str(doc.get("title") or "")
        if role == "user" and content.strip() and title in ("", "Nueva conversación"):
            update["title"] = content.strip()[:80]
        db[COL_VOICE_CONVERSATIONS].update_one(
            {"conversation_id": conv_id, "username": uname},
            {"$set": update},
            upsert=True,
        )
    except Exception:
        pass


def _list_voice_conversations(user: dict[str, Any], *, limit: int = 40) -> list[dict[str, Any]]:
    try:
        db = mongo_store.get_db()
        uname = _voice_username(user)
        rows = list(
            db[COL_VOICE_CONVERSATIONS]
            .find({"username": uname}, {"_id": 0})
            .sort("updated_at", -1)
            .limit(limit)
        )
        if rows:
            return rows
        legacy = f"voice:{uname}"
        if db[COL_VOICE_MESSAGES].find_one({"conversation_id": legacy}):
            _ensure_voice_conversation(user, legacy, title="Conversación anterior")
            return _list_voice_conversations(user, limit=limit)
        return []
    except Exception:
        return []


def _save_voice_message(*, user: dict[str, Any], role: str, content: str, conv_id: str | None = None) -> None:
    if not content.strip():
        return
    try:
        from datetime import datetime, timezone

        db = mongo_store.get_db()
        cid = conv_id or _resolve_conv_id(user)
        now = datetime.now(timezone.utc).isoformat()
        db[COL_VOICE_MESSAGES].insert_one(
            {
                "conversation_id": cid,
                "username": user.get("username"),
                "owner_id": user.get("owner_id"),
                "role": role,
                "content": content[:16000],
                "created_at": now,
            }
        )
        _touch_voice_conversation(user, cid, content=content, role=role)
    except Exception:
        pass


def _load_voice_history(user: dict[str, Any], *, limit: int | None = None, conv_id: str | None = None) -> list[dict[str, str]]:
    lim = limit or VOICE_HISTORY_LIMIT
    try:
        db = mongo_store.get_db()
        cid = conv_id or _resolve_conv_id(user, create_if_missing=False)
        rows = list(
            db[COL_VOICE_MESSAGES]
            .find({"conversation_id": cid}, {"_id": 0, "role": 1, "content": 1})
            .sort("created_at", -1)
            .limit(lim)
        )
        rows.reverse()
        return [{"role": str(r.get("role")), "content": str(r.get("content"))} for r in rows if r.get("content")]
    except Exception:
        return []


def _resolve_chat_backend() -> str:
    mode = VOICE_CHAT_BACKEND
    if mode in ("ollama", "vllm", "gemini"):
        return mode
    if mode == "auto":
        from raphiia_openai import config_store

        if VOICE_LOCAL_FIRST:
            if USE_VLLM and _vllm_ok():
                return "vllm"
            if _ollama_reachable():
                return "ollama"
        if config_store.get_google_api_key() or GOOGLE_API_KEY:
            return "gemini"
        if USE_VLLM:
            return "vllm"
        return "ollama"
    return mode


def _vllm_ok() -> bool:
    if not USE_VLLM:
        return False
    try:
        r = _http_json(f"{VLLM_URL}/v1/models", timeout=3.0)
        return bool(r.get("data") or r.get("models"))
    except Exception:
        return False


def _ollama_reachable() -> bool:
    for base in (OLLAMA_DIRECT, OLLAMA_CHAT):
        try:
            if base.endswith(":11435") or "/11435" in base:
                _http_json(f"{base}/health", timeout=3.0)
            else:
                _http_json(f"{base}/api/tags", timeout=3.0)
            return True
        except Exception:
            continue
    return False


def _pick_ollama_model(user_text: str, *, heavy: bool = False) -> str:
    if heavy:
        return VOICE_HEAVY_MODEL
    low = user_text.lower()
    if any(k in low for k in ("código", "programa", "python", "script", "implementa", "refactor", "bug", "api ")):
        return VOICE_HEAVY_MODEL
    return VOICE_MODEL


def _build_chat_messages(
    *,
    user: dict[str, Any],
    user_text: str,
    history: list[dict[str, str]] | None,
    entity_id: str | None,
    with_context: bool,
    min_ctx_chars: int = 0,
    speaker_hint: str | None = None,
) -> tuple[str, list[dict[str, str]], str]:
    hist = history or []
    query = user_text.strip()
    if not query and hist:
        for m in reversed(hist):
            if m.get("role") == "user" and m.get("content"):
                query = str(m["content"])
                break
    ctx_block = ""
    backend = _resolve_chat_backend()
    vllm_active = backend == "vllm" and USE_VLLM and _vllm_ok()
    ctx_max = VLLM_CONTEXT_CHARS if vllm_active else 9000
    if min_ctx_chars:
        ctx_max = max(ctx_max, min_ctx_chars)
    system_max = 4500 if vllm_active else 12000
    msg_max = 800 if vllm_active else 8000
    mcp_block = voice_mcp_bridge.mcp_context_for_message(user, query or user_text)
    if speaker_hint:
        mcp_block = (mcp_block + "\n\n=== Hablante detectado (voz) ===\n" + speaker_hint).strip()
    mcp_ran = "Resultados herramientas MCP" in mcp_block
    if vllm_active and mcp_ran:
        ctx_max = min(ctx_max, 800)
    if with_context and query and not (vllm_active and mcp_ran):
        ctx = get_user_context(query=query, user=user, entity_id=entity_id, max_chars=ctx_max)
        ctx_block = ctx.get("context") or ""
    model = VLLM_MODEL if vllm_active else (
        GEMINI_TEXT_MODEL if backend == "gemini" else VOICE_MODEL
    )
    system = voice_identity.build_system_prompt(
        user=user,
        ctx_block=ctx_block,
        user_text=query or user_text,
        chat_backend=backend,
        chat_model=model,
        vllm_ok=_vllm_ok(),
        mcp_block=mcp_block,
    )
    msgs: list[dict[str, str]] = []
    hist_slice = hist[-VLLM_HISTORY_LIMIT:] if vllm_active and hist else hist
    if hist_slice:
        for m in hist_slice:
            role = str(m.get("role") or "").strip()
            content = str(m.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                msgs.append({"role": role, "content": content[:msg_max]})
    elif query:
        msgs.append({"role": "user", "content": query[:msg_max]})
    return system[:system_max], msgs, query


def _gemini_reply(system: str, msgs: list[dict[str, str]]) -> dict[str, Any]:
    from raphiia_openai import config_store

    key = config_store.get_google_api_key() or GOOGLE_API_KEY
    if not key:
        return {"ok": False, "error": "gemini_not_configured"}
    contents: list[dict[str, Any]] = []
    for m in msgs:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    if not contents:
        return {"ok": False, "error": "empty_messages"}
    body: dict[str, Any] = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TEXT_MODEL}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180.0) as resp:
            parsed = json.loads(resp.read().decode())
        parts = (((parsed.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
        reply = " ".join(str(p.get("text", "")).strip() for p in parts if p.get("text")).strip()
        if reply:
            return {"ok": True, "reply": reply, "model": GEMINI_TEXT_MODEL, "backend": "gemini"}
        return {"ok": False, "error": "gemini_empty_reply", "raw": parsed}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:400]
        return {"ok": False, "error": f"gemini_http_{exc.code}", "detail": err_body}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _vllm_trim_messages(msgs: list[dict[str, str]]) -> list[dict[str, str]]:
    if len(msgs) <= 5:
        return msgs
    return [msgs[0], *msgs[-4:]]


def _vllm_reply(ollama_msgs: list[dict[str, str]], *, model: str | None = None) -> dict[str, Any]:
    if not USE_VLLM:
        return {"ok": False, "error": "vllm_disabled"}
    msgs = ollama_msgs
    max_tokens = VLLM_MAX_TOKENS
    for attempt in range(2):
        body = {
            "model": model or VLLM_MODEL,
            "messages": msgs,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        try:
            data = _http_json(f"{VLLM_URL}/v1/chat/completions", method="POST", body=body, timeout=180.0)
            reply = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if reply.strip():
                return {"ok": True, "reply": reply.strip(), "model": body["model"], "backend": "vllm"}
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            if attempt == 0 and exc.code == 400 and "maximum context length" in err_body:
                msgs = _vllm_trim_messages(msgs)
                max_tokens = min(max_tokens, 256)
                continue
            return {"ok": False, "error": f"HTTP Error {exc.code}: {err_body[:200]}", "backend": "vllm"}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "backend": "vllm"}
        break
    return {"ok": False, "error": "vllm_empty_reply", "backend": "vllm"}


def _ollama_reply(
    user_text: str,
    *,
    user: dict[str, Any],
    entity_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    with_context: bool = True,
    speaker_hint: str | None = None,
) -> dict[str, Any]:
    hist = history or []
    query = user_text.strip()
    if not query and hist:
        for m in reversed(hist):
            if m.get("role") == "user" and m.get("content"):
                query = str(m["content"])
                break
    system, msgs, _query = _build_chat_messages(
        user=user,
        user_text=user_text,
        history=hist,
        entity_id=entity_id,
        with_context=with_context,
        speaker_hint=speaker_hint,
    )
    ollama_msgs: list[dict[str, str]] = [{"role": "system", "content": system}]
    ollama_msgs.extend(msgs)
    vllm_failed = False
    if USE_VLLM:
        vllm = _vllm_reply(ollama_msgs)
        if vllm.get("ok"):
            return vllm
        vllm_failed = True
    body = {"model": _pick_ollama_model(query or user_text, heavy=False), "messages": ollama_msgs, "stream": False}
    timeout = 300.0 if VOICE_HEAVY_MODEL in body["model"] else 180.0
    try:
        data = _http_json(f"{OLLAMA_CHAT}/api/chat", method="POST", body=body, timeout=timeout)
        reply = (data.get("message") or {}).get("content") or ""
        if reply.strip():
            result: dict[str, Any] = {
                "ok": True,
                "reply": reply.strip(),
                "model": body["model"],
                "backend": "ollama",
            }
            if vllm_failed:
                result["fallback_from"] = "vllm"
            return result
        return {"ok": False, "error": "ollama_empty_reply"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _chat_reply(
    user_text: str,
    *,
    user: dict[str, Any],
    entity_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    with_context: bool = True,
    speaker_hint: str | None = None,
) -> dict[str, Any]:
    backend = _resolve_chat_backend()
    system, msgs, _query = _build_chat_messages(
        user=user,
        user_text=user_text,
        history=history,
        entity_id=entity_id,
        with_context=with_context,
        speaker_hint=speaker_hint,
    )
    if backend in ("ollama", "vllm"):
        result = _ollama_reply(user_text, user=user, entity_id=entity_id, history=history, with_context=with_context, speaker_hint=speaker_hint)
        if result.get("ok"):
            return result
        if VOICE_LOCAL_FIRST and (GOOGLE_API_KEY or backend != "gemini"):
            from raphiia_openai import config_store

            if config_store.get_google_api_key() or GOOGLE_API_KEY:
                gem = _gemini_reply(system, msgs)
                if gem.get("ok"):
                    gem["fallback_from"] = backend
                    return gem
        return result
    if backend == "gemini":
        result = _gemini_reply(system, msgs)
        if result.get("ok"):
            return result
        if VOICE_CHAT_BACKEND == "gemini":
            if VOICE_LOCAL_FIRST and _ollama_reachable():
                local = _ollama_reply(user_text, user=user, entity_id=entity_id, history=history, with_context=with_context)
                if local.get("ok"):
                    local["fallback_from"] = "gemini"
                    return local
            return result
    return _ollama_reply(user_text, user=user, entity_id=entity_id, history=history, with_context=with_context)


def _matches_wake(text: str) -> bool:
    return bool(WAKE_RE.search(text or ""))


def _matches_stop(text: str) -> bool:
    return bool(STOP_RE.search(text or ""))


def _strip_wake_phrase(text: str) -> str:
    return WAKE_RE.sub("", text or "").strip(" ,.")


def _has_business_keywords(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in _BUSINESS_KEYWORDS)


def _is_short_conversational(text: str) -> bool:
    """True = omitir contexto Qdrant (solo charla muy corta)."""
    t = (text or "").strip()
    if not t:
        return True
    if _has_business_keywords(t):
        return False
    if len(t.split()) > 15:
        return False
    low = t.lower()
    if any(k in low for k in ("busca", "recuerda", "contexto", "documento", "archivo", "cotiz", "qdrant", "mongo", "servidor", "fleet", "stack", "gpu", "ssh")):
        return False
    return len(t) < 80 and len(t.split()) < 12


def _fluid_ollama_reply(
    user_text: str,
    *,
    user: dict[str, Any],
    entity_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    speaker_hint: str | None = None,
) -> dict[str, Any]:
    """Respuesta rápida para turnos fluidos — modelo 7B, max 256 tokens."""
    with_context = not _is_short_conversational(user_text)
    min_ctx = 1500 if _has_business_keywords(user_text) else 0
    system, msgs, query = _build_chat_messages(
        user=user,
        user_text=user_text,
        history=history,
        entity_id=entity_id,
        with_context=with_context,
        min_ctx_chars=min_ctx,
        speaker_hint=speaker_hint,
    )
    ollama_msgs: list[dict[str, str]] = [{"role": "system", "content": system}]
    ollama_msgs.extend(msgs)
    model = VOICE_FLUID_MODEL if VOICE_FLUID_FAST else _pick_ollama_model(query or user_text, heavy=False)
    body: dict[str, Any] = {
        "model": model,
        "messages": ollama_msgs,
        "stream": False,
        "options": {"num_predict": VOICE_FLUID_MAX_TOKENS, "temperature": 0.7},
    }
    timeout = 90.0
    try:
        data = _http_json(f"{OLLAMA_CHAT}/api/chat", method="POST", body=body, timeout=timeout)
        reply = (data.get("message") or {}).get("content") or ""
        if reply.strip():
            return {"ok": True, "reply": reply.strip(), "model": model, "backend": "ollama_fluid"}
        return {"ok": False, "error": "ollama_empty_reply"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _fluid_chat_reply(
    user_text: str,
    *,
    user: dict[str, Any],
    entity_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    speaker_hint: str | None = None,
) -> dict[str, Any]:
    if VOICE_FLUID_FAST and _ollama_reachable():
        result = _fluid_ollama_reply(user_text, user=user, entity_id=entity_id, history=history, speaker_hint=speaker_hint)
        if result.get("ok"):
            return result
    return _chat_reply(user_text, user=user, entity_id=entity_id, history=history, with_context=not _is_short_conversational(user_text), speaker_hint=speaker_hint)


def _process_voice_turn(
    payload: dict[str, Any],
    user: dict[str, Any],
    *,
    raw_text: str | None = None,
) -> dict[str, Any]:
    text = (raw_text if raw_text is not None else str(payload.get("text") or "")).strip()
    speak = bool(payload.get("speak", True))
    voice = payload.get("voice")
    tts_only = bool(payload.get("_tts_only"))
    conv_id = _resolve_conv_id(user, payload=payload)
    entity_id = payload.get("entity_id")
    hist_list: list[dict[str, str]] | None = None
    history = payload.get("messages")
    if isinstance(history, list):
        hist_list = [
            {"role": str(m.get("role", "")), "content": str(m.get("content", ""))}
            for m in history
            if isinstance(m, dict)
        ]

    if tts_only and text:
        audio_url, _ = _synthesize_reply(text, voice=str(voice) if voice else None)
        return {"ok": True, "reply": text, "audio_url": audio_url, "session_action": "continue", "conversation_id": conv_id}

    session_action = "continue"
    if text and _matches_stop(text):
        reply = "De acuerdo, aquí estaré cuando me necesites."
        _save_voice_message(user=user, role="user", content=text, conv_id=conv_id)
        _save_voice_message(user=user, role="assistant", content=reply, conv_id=conv_id)
        out: dict[str, Any] = {"ok": True, "reply": reply, "session_action": "stop", "conversation_id": conv_id}
        if speak:
            audio_url, _ = _synthesize_reply(reply, voice=str(voice) if voice else None)
            if audio_url:
                out["audio_url"] = audio_url
        return out

    if text and _matches_wake(text):
        text = _strip_wake_phrase(text)
        if not text:
            reply = "Hola Rafael, ¿en qué te ayudo?"
            _save_voice_message(user=user, role="user", content="Hola RalfIA", conv_id=conv_id)
            _save_voice_message(user=user, role="assistant", content=reply, conv_id=conv_id)
            out = {"ok": True, "reply": reply, "session_action": "continue", "conversation_id": conv_id}
            if speak:
                audio_url, _ = _synthesize_reply(reply, voice=str(voice) if voice else None)
                if audio_url:
                    out["audio_url"] = audio_url
            return out

    if not text:
        return {"ok": False, "error": "text vacío"}

    voice_user_profile.touch_profile(user)
    voice_user_profile.learn_from_message(user, text)
    _save_voice_message(user=user, role="user", content=text, conv_id=conv_id)

    if _wants_image(text):
        img = _generate_voice_image(user, text)
        if img.get("ok"):
            _save_voice_message(user=user, role="assistant", content=img["reply"], conv_id=conv_id)
            if speak:
                audio_url, _ = _synthesize_reply(img["reply"], voice=str(voice) if voice else None)
                if audio_url:
                    img["audio_url"] = audio_url
            img["conversation_id"] = conv_id
            img["session_action"] = session_action
            return img
        return {"ok": False, "error": img.get("error", "image_failed"), "reply": img.get("reply") or _voice_image_error_message(img.get("error", ""))}

    chat = _fluid_chat_reply(
        text,
        user=user,
        entity_id=entity_id,
        history=hist_list,
        speaker_hint=payload.get("speaker_hint"),
    )
    if not chat.get("ok"):
        return chat
    reply = chat["reply"]
    _save_voice_message(user=user, role="assistant", content=reply, conv_id=conv_id)
    chat["audio_url"] = None
    chat["conversation_id"] = conv_id
    chat["session_action"] = session_action
    if speak:
        audio_url, _ = _synthesize_reply(reply, voice=str(voice) if voice else None)
        if audio_url:
            chat["audio_url"] = audio_url
    return chat


async def _stream_chat_tokens(
    user_text: str,
    *,
    user: dict[str, Any],
    entity_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    with_context: bool = True,
):
    """Genera tokens de respuesta (vLLM u Ollama streaming)."""
    import httpx

    system, msgs, query = _build_chat_messages(
        user=user,
        user_text=user_text,
        history=history,
        entity_id=entity_id,
        with_context=with_context,
    )
    ollama_msgs: list[dict[str, str]] = [{"role": "system", "content": system}]
    ollama_msgs.extend(msgs)
    model = _pick_ollama_model(query or user_text, heavy=False)

    if USE_VLLM and _vllm_ok():
        vllm_msgs = ollama_msgs
        vllm_max_tokens = VLLM_MAX_TOKENS
        for attempt in range(2):
            body = {
                "model": VLLM_MODEL,
                "messages": vllm_msgs,
                "stream": True,
                "max_tokens": vllm_max_tokens,
                "temperature": 0.7,
            }
            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    async with client.stream("POST", f"{VLLM_URL}/v1/chat/completions", json=body) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                break
                            data = json.loads(payload)
                            delta = ((data.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                            if delta:
                                yield delta
                return
            except httpx.HTTPStatusError as exc:
                err_body = exc.response.text if exc.response is not None else ""
                if attempt == 0 and exc.response is not None and exc.response.status_code == 400 and "maximum context length" in err_body:
                    vllm_msgs = _vllm_trim_messages(vllm_msgs)
                    vllm_max_tokens = min(vllm_max_tokens, 256)
                    continue
                break

    body = {"model": model, "messages": ollama_msgs, "stream": True}
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("POST", f"{OLLAMA_CHAT}/api/chat", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                chunk = (data.get("message") or {}).get("content") or ""
                if chunk:
                    yield chunk


def _wants_image(text: str) -> bool:
    return bool(
        re.search(
            r"\b(genera(me)?|crea(me)?|haz(me)?|dibuja(me)?|pinta(me)?|make|draw)\s+(me\s+)?(una\s+)?(imagen|foto|picture|image|ilustraci)",
            text,
            re.I,
        )
        or re.search(r"\b(quiero|necesito|mu[eé]strame)\s+(una\s+)?(imagen|foto|ilustraci)", text, re.I)
        or re.search(r"\b(genera|crea|haz)\s+(me\s+)?(una\s+)?foto\b", text, re.I)
    )


def _list_tts_voices() -> list[dict[str, str]]:
    voices: list[dict[str, str]] = []
    try:
        from raphiia_openai import voice_xtts

        voices.extend(voice_xtts.list_cloned_voices())
    except Exception:
        pass
    piper_dir = Path(os.getenv("PIPER_VOICES_DIR", "/home/rlopez/data/piper/voices"))
    if piper_dir.is_dir():
        for onnx in sorted(piper_dir.glob("*.onnx")):
            label = onnx.stem.replace("_", " ").replace("-", " ")
            voices.append({"id": str(onnx.resolve()), "label": label, "provider": "piper"})
    if not voices and tts.PIPER_MODEL.is_file():
        voices.append(
            {
                "id": str(tts.PIPER_MODEL.resolve()),
                "label": tts.PIPER_MODEL.stem.replace("_", " ").replace("-", " "),
                "provider": "piper",
            }
        )
    health = tts.tts_health()
    if health.get("espeak_fallback"):
        voices.append({"id": "espeak", "label": "Espeak (fallback sistema)", "provider": "espeak"})
    return voices


def _resolve_tts_voice(voice: str | None) -> str | None:
    if not voice or voice == "espeak":
        return None
    path = Path(voice)
    return str(path) if path.is_file() else None


def _synthesize_reply(text: str, *, voice: str | None = None) -> tuple[str | None, str | None]:
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    os.close(tmp_fd)
    tmp = Path(tmp_path)
    try:
        from raphiia_openai import voice_xtts

        kind, speaker = voice_xtts.resolve_voice_id(voice)
        if not kind and not voice:
            jobs = voice_xtts._load_jobs()
            for sp, job in jobs.items():
                if job.get("status") == "ready" and job.get("active"):
                    kind, speaker = "xtts", sp
                    break
        if kind == "xtts" and speaker:
            syn = voice_xtts.synthesize(text[:2000], tmp, speaker=speaker)
            if syn.get("ok") and tmp.is_file():
                return f"/api/voice/audio/{tmp.name}", str(tmp)
    except Exception:
        pass
    model = _resolve_tts_voice(voice)
    syn = tts.synthesize(text[:2000], tmp, voice=model)
    if syn.get("ok") and tmp.is_file():
        return f"/api/voice/audio/{tmp.name}", str(tmp)
    return None, None


def _comfy_ui_up() -> bool:
    from raphiia_openai.settings import COMFYUI_URL
    from urllib.parse import urlparse

    parsed = urlparse(COMFYUI_URL or "http://127.0.0.1:8188")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8188
    from raphiia_openai import portal_bridge

    return portal_bridge._tcp_open(port, host=host)


def _resolve_voice_image_provider() -> str:
    from raphiia_openai import config_store
    from raphiia_openai.settings import IMAGE_GEN_PROVIDER

    provider = (IMAGE_GEN_PROVIDER or "google").strip().lower()
    if provider == "google" and not (config_store.get_google_api_key() or GOOGLE_API_KEY):
        if _comfy_ui_up():
            return "local_comfy"
    return provider


def _voice_image_error_message(err: str, detail: str = "") -> str:
    err = (err or "").strip()
    detail = (detail or "").strip()
    known = {
        "gemini_not_configured": "Google Imagen no está configurado (falta GOOGLE_API_KEY en el panel).",
        "image_generation_failed": "No se pudo generar la imagen.",
        "image_file_missing": "La imagen no se guardó en el servidor.",
        "comfyui_unreachable": "ComfyUI no responde en :8188 — ¿está activo ralfia-comfyui?",
        "comfyui_timeout": "ComfyUI tardó demasiado — la GPU puede estar ocupada con vLLM.",
    }
    msg = known.get(err, err.replace("_", " "))
    if detail and detail not in msg:
        msg = f"{msg} ({detail[:180]})"
    if not _comfy_ui_up() and "GOOGLE" not in msg.upper():
        msg += " ComfyUI local tampoco está disponible."
    return msg


def _generate_voice_image(user: dict[str, Any], text: str) -> dict[str, Any]:
    from datetime import datetime, timezone

    from raphiia_openai import config_store, image_gen, local_image_runtime
    from raphiia_openai.settings import IMAGE_GEN_PROVIDER

    prompt = re.sub(
        r"^.*?(imagen|foto|picture|image|ilustraci[oó]n)\s*(de|para|:|-)?\s*",
        "",
        text,
        flags=re.I,
    ).strip() or text
    draft_id = f"voice-{user.get('username', 'user')}"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    media = Path(EDITORIAL_MEDIA_ROOT) / f"draft_{draft_id}_{ts}.png"
    media.parent.mkdir(parents=True, exist_ok=True)

    visual = f"{prompt}. High quality, detailed, cinematic lighting, photorealistic."
    provider = _resolve_voice_image_provider()
    result: dict[str, Any] = {"ok": False, "error": "image_generation_failed"}
    tried: list[str] = []

    def _try_comfy() -> dict[str, Any]:
        tried.append("local_comfy")
        return local_image_runtime.generate(visual, media)

    def _try_google() -> dict[str, Any]:
        if not (config_store.get_google_api_key() or GOOGLE_API_KEY):
            return {"ok": False, "error": "gemini_not_configured"}
        tried.append("google")
        return image_gen.generate_for_draft(
            draft_id=draft_id,
            title=prompt[:120],
            markdown=visual,
            include_ai_text=True,
        )

    if provider in {"local_comfy", "comfyui"}:
        result = _try_comfy()
        if not result.get("ok") and (config_store.get_google_api_key() or GOOGLE_API_KEY):
            result = _try_google()
    elif provider == "google":
        result = _try_google()
        if not result.get("ok") and _comfy_ui_up():
            comfy = _try_comfy()
            if comfy.get("ok"):
                result = comfy
    else:
        result = image_gen.generate_for_draft(
            draft_id=draft_id,
            title=prompt[:120],
            markdown=visual,
            include_ai_text=True,
        )
        if not result.get("ok") and _comfy_ui_up():
            result = _try_comfy()

    if result.get("media_path"):
        media = Path(str(result["media_path"]))

    media_path = Path(str(result.get("media_path") or media))
    if not result.get("ok") and not media_path.is_file():
        err = str(result.get("error") or "image_generation_failed")
        warnings = result.get("warnings") or []
        detail = "; ".join(warnings) if isinstance(warnings, list) else str(warnings or "")
        if err == "image_generation_failed" and not detail:
            detail = f"Proveedores probados: {', '.join(tried) or provider}"
        friendly = _voice_image_error_message(err, detail)
        return {
            "ok": False,
            "error": err,
            "reply": friendly,
            "detail": detail,
            "warnings": warnings,
        }
    if not media_path.is_file():
        friendly = _voice_image_error_message("image_file_missing")
        return {"ok": False, "error": "image_file_missing", "reply": friendly, "warnings": result.get("warnings")}
    img_provider = result.get("provider") or result.get("backend") or provider or IMAGE_GEN_PROVIDER
    reply = f"Listo — generé la imagen con {img_provider}.\n\nPrompt: {prompt[:200]}"
    return {
        "ok": True,
        "reply": reply,
        "image_url": f"/api/voice/media/{media_path.name}",
        "image_provider": img_provider,
        "backend": "image_gen",
    }


def _is_lan_sync_request(request: Request) -> bool:
    if request.query_params.get("sync") != "1":
        return False
    host = (request.client.host if request.client else "") or ""
    return host.startswith("127.") or host.startswith("192.168.") or host.startswith("10.") or host == "::1"


def _run_image_job(
    job_id: str,
    *,
    user: dict[str, Any],
    text: str,
    conv_id: str,
    speak: bool,
    voice: str | None,
) -> None:
    try:
        img = _generate_voice_image(user, text)
        if img.get("ok"):
            _save_voice_message(user=user, role="assistant", content=img["reply"], conv_id=conv_id)
            if speak:
                audio_url, _path = _synthesize_reply(img["reply"], voice=str(voice) if voice else None)
                if audio_url:
                    img["audio_url"] = audio_url
            img["conversation_id"] = conv_id
            payload = {"status": "done", **img}
        else:
            err = str(img.get("error") or "image_failed")
            detail = str(img.get("detail") or img.get("reply") or "")
            payload = {
                "status": "error",
                "ok": False,
                "error": err,
                "reply": img.get("reply") or _voice_image_error_message(err, detail),
                "detail": detail,
            }
    except Exception as exc:
        payload = {
            "status": "error",
            "ok": False,
            "error": str(exc),
            "reply": _voice_image_error_message(str(exc)),
        }
    payload["finished_at"] = time.time()
    with _IMAGE_JOBS_LOCK:
        IMAGE_JOBS[job_id] = payload


@app.get("/link", response_class=HTMLResponse)
def voice_link():
    urls = _public_https_urls()
    primary = urls[0] if urls else ""
    body = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"/>
<meta http-equiv="refresh" content="0;url={primary}"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>RalfIA — enlace</title></head><body style="font-family:system-ui;background:#070b14;color:#e8edf7;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0">
<p>Redirigiendo a <a href="{primary}" style="color:#38bdf8">{primary}</a>…</p></body></html>"""
    return body


@app.head("/")
def voice_pwa_head():
    return Response(status_code=200, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/", response_class=HTMLResponse)
def voice_pwa():
    urls = _public_https_urls()
    oauth = voice_auth.google_oauth_configured()
    html = PWA_HTML.replace("__HTTPS_URLS__", json.dumps(urls, ensure_ascii=False))
    html = html.replace(
        "__GOOGLE_OAUTH_ENABLED__",
        "true" if oauth else "false",
    )
    html = html.replace("__GOOGLE_BTN_CLASS__", "show" if oauth else "")
    html = html.replace("__GOOGLE_DIVIDER_CLASS__", "show" if oauth else "")
    return html


PWA_MANIFEST = {
    "name": "Ralphi IA — PC Doctor AI",
    "short_name": "Ralphi IA",
    "description": "Asistente de voz y chat con memoria de empresa",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#070b14",
    "theme_color": "#070b14",
    "lang": "es",
    "icons": [
        {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"},
    ],
}

PWA_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#38bdf8"/><stop offset="100%" stop-color="#818cf8"/></linearGradient></defs>
<rect width="512" height="512" rx="108" fill="#070b14"/>
<rect x="32" y="32" width="448" height="448" rx="88" fill="url(#g)"/>
<text x="256" y="310" font-family="system-ui,sans-serif" font-size="220" font-weight="700"
  fill="#fff" text-anchor="middle">R</text></svg>"""


@app.head("/manifest.json")
def voice_manifest_head():
    return Response(status_code=200, media_type="application/json", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/manifest.json")
def voice_manifest():
    return JSONResponse(PWA_MANIFEST)


LEGAL_DIR = Path(__file__).resolve().parent / "static" / "legal"


@app.get("/privacy", response_class=HTMLResponse)
def voice_privacy():
    return HTMLResponse((LEGAL_DIR / "privacy.html").read_text(encoding="utf-8"))


@app.get("/terms", response_class=HTMLResponse)
def voice_terms():
    return HTMLResponse((LEGAL_DIR / "terms.html").read_text(encoding="utf-8"))


@app.get("/icon.svg", response_class=Response)
def voice_icon():
    return Response(PWA_ICON_SVG, media_type="image/svg+xml")


@app.get("/api/voice/public-url")
def voice_public_url():
    urls = _public_https_urls()
    return {"ok": bool(urls), "urls": urls, "primary": urls[0] if urls else None}


@app.get("/media/videos/{filename}")
def serve_published_video(filename: str):
    """Artifact Delivery — vídeos publicados en staging web (Cloudflare → voz.pcdoctor.ai)."""
    from raphiia_openai import artifact_delivery

    try:
        safe = artifact_delivery._safe_filename(filename)
    except ValueError:
        return JSONResponse({"ok": False, "error": "invalid_filename"}, status_code=400)
    path = artifact_delivery.MEDIA_VIDEOS_DIR / safe
    if not path.is_file():
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    return FileResponse(path, media_type="video/mp4", filename=safe)


@app.head("/api/voice/health")
def voice_health_head():
    return Response(status_code=200, media_type="application/json", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/api/voice/health")
def voice_health():
    vllm_ok = _vllm_ok() if USE_VLLM else False
    backend = _resolve_chat_backend()
    chat_model = GEMINI_TEXT_MODEL if backend == "gemini" else (VLLM_MODEL if backend == "vllm" and vllm_ok else VOICE_MODEL)
    qh = qdrant_health()
    return {
        "ok": True,
        "whisper": WHISPER,
        "ollama": OLLAMA_CHAT,
        "ollama_direct": OLLAMA_DIRECT,
        "ollama_reachable": _ollama_reachable(),
        "local_first": VOICE_LOCAL_FIRST,
        "vllm": {"url": VLLM_URL, "enabled": USE_VLLM, "ok": vllm_ok, "model": VLLM_MODEL},
        "model": chat_model,
        "heavy_model": VOICE_HEAVY_MODEL,
        "mongo": mongo_store.mongo_connection_info(),
        "qdrant": qh,
        "qdrant_ok": bool(qh.get("ok")),
        "qdrant_collection": qh.get("collections"),
        "qdrant_points": qh.get("points_count"),
        "tts": tts.tts_health(),
        "comfyui": {"ok": _comfy_ui_up(), "url": os.getenv("COMFYUI_URL", "http://127.0.0.1:8188")},
        "public_urls": _public_https_urls(),
        "auth_required": voice_auth.AUTH_REQUIRED,
        "google_oauth": voice_auth.google_oauth_configured(),
        "chat_backend": backend,
        "chat_model": chat_model,
        "fluid_model": VOICE_FLUID_MODEL,
        "fluid_fast": VOICE_FLUID_FAST,
        "gpu_policy": {
            "vllm_primary": VLLM_PRIMARY,
            "ollama_router": OLLAMA_CHAT,
            "fallback_chain": ["vllm", "ollama_router_intel", "gemini"],
        },
    }


@app.get("/api/voice/tts/voices")
def voice_tts_voices():
    voices = _list_tts_voices()
    default = _default_tts_voice_id()
    return {"ok": True, "voices": voices, "default": default, "health": tts.tts_health()}


@app.get("/api/voice/tts/lab/status")
def voice_tts_lab_status(user: dict[str, Any] = Depends(voice_auth.require_user)):
    from raphiia_openai import voice_xtts

    speaker = _speaker_for_user(user)
    return voice_xtts.clone_status(speaker)


@app.post("/api/voice/tts/lab/clone")
def voice_tts_lab_clone(payload: dict[str, Any], user: dict[str, Any] = Depends(voice_auth.require_user)):
    from raphiia_openai import voice_xtts

    speaker = _speaker_for_user(user)
    language = str(payload.get("language") or "es")
    langs = payload.get("output_languages")
    if isinstance(langs, list):
        langs = [str(x) for x in langs]
    else:
        langs = None
    return voice_xtts.start_clone(speaker, language=language, output_languages=langs)


@app.post("/api/voice/tts/lab/activate")
def voice_tts_lab_activate(user: dict[str, Any] = Depends(voice_auth.require_user)):
    from raphiia_openai import voice_xtts

    speaker = _speaker_for_user(user)
    return voice_xtts.activate_speaker(speaker)


@app.post("/api/voice/tts/speak")
def voice_tts_speak(payload: dict[str, Any], user: dict[str, Any] = Depends(voice_auth.require_user)):
    """Genera TTS bajo demanda — para reescuchar mensajes anteriores."""
    text = str(payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "text vacío"}, status_code=400)
    voice = payload.get("voice")
    audio_url, _path = _synthesize_reply(text, voice=str(voice) if voice else None)
    if not audio_url:
        return JSONResponse({"ok": False, "error": "tts_failed"}, status_code=503)
    return {"ok": True, "audio_url": audio_url}


@app.get("/api/voice/tts/samples")
def voice_tts_samples_status(user: dict[str, Any] = Depends(voice_auth.require_user)):
    """Cuenta muestras de voz guardadas para clonación (XTTS)."""
    speaker = _speaker_for_user(user)
    folder = VOICE_SAMPLES_ROOT / speaker
    files = sorted(folder.glob("*.*")) if folder.is_dir() else []
    total_sec = 0.0
    for f in files:
        try:
            if f.suffix.lower() in (".wav",):
                import wave

                with wave.open(str(f), "rb") as wf:
                    total_sec += wf.getnframes() / float(wf.getframerate())
            else:
                total_sec += max(f.stat().st_size / 32000.0, 1.0)
        except Exception:
            pass
    return {
        "ok": True,
        "speaker": speaker,
        "count": len(files),
        "estimated_minutes": round(total_sec / 60.0, 1),
        "target_minutes": 15,
        "ready_for_clone": len(files) >= int(os.getenv("VOICE_CLONE_MIN_SAMPLES", "15")),
        "folder": str(folder),
    }


@app.post("/api/voice/tts/sample")
async def voice_tts_sample_upload(
    audio: UploadFile = File(...),
    user: dict[str, Any] = Depends(voice_auth.require_user),
):
    """Guarda muestra de voz del usuario para entrenamiento/clonación XTTS."""
    speaker = _speaker_for_user(user)
    folder = VOICE_SAMPLES_ROOT / speaker
    folder.mkdir(parents=True, exist_ok=True)
    ext = Path(audio.filename or "sample.webm").suffix.lower() or ".webm"
    if ext not in (".wav", ".webm", ".mp3", ".m4a", ".ogg"):
        ext = ".webm"
    name = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    dest = folder / name
    data = await audio.read()
    if len(data) < 500:
        return JSONResponse({"ok": False, "error": "audio_too_short"}, status_code=400)
    dest.write_bytes(data)
    status = voice_tts_samples_status(user)
    return {"ok": True, "file": name, **status}


@app.post("/api/voice/login")
def voice_login(payload: dict[str, Any], response: Response):
    username = str(payload.get("username") or payload.get("email") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        return JSONResponse({"ok": False, "error": "credentials_required"}, status_code=400)
    portal = voice_auth.verify_portal_credentials(username, password)
    if not portal:
        return JSONResponse({"ok": False, "error": "invalid_credentials", "message": "Usuario o contraseña incorrectos."}, status_code=401)
    resolved = voice_auth.resolve_username(username)
    profile = voice_auth.get_voice_profile(resolved)
    if profile.get("status") == "pending":
        return JSONResponse(
            {"ok": False, "error": "pending_approval", "message": "Cuenta creada. Rafael debe aprobarte antes de entrar."},
            status_code=403,
        )
    token = voice_auth.create_session(resolved)
    response.set_cookie(
        voice_auth.SESSION_COOKIE,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=voice_auth.SESSION_TTL,
        path="/",
    )
    profile["is_admin"] = profile.get("role") == "admin" or profile.get("owner_id") == RALFIA_OWNER_ID
    return {"ok": True, "user": voice_auth.user_public(profile)}


@app.post("/api/voice/register")
def voice_register(payload: dict[str, Any]):
    username = str(payload.get("username") or payload.get("email") or "").strip()
    password = str(payload.get("password") or "")
    display_name = str(payload.get("display_name") or payload.get("name") or "").strip() or None
    if not username or not password:
        return JSONResponse({"ok": False, "error": "credentials_required"}, status_code=400)
    try:
        doc = voice_auth.request_access(username=username, password=password, display_name=display_name)
    except ValueError as exc:
        err = str(exc)
        msgs = {
            "username_exists": "Ese usuario ya existe. Prueba Entrar.",
            "username_too_short": "Usuario muy corto (mínimo 3 caracteres).",
            "password_too_short": "Contraseña muy corta (mínimo 4).",
            "use_login": "Eres administrador — usa Entrar.",
        }
        return JSONResponse({"ok": False, "error": err, "message": msgs.get(err, err)}, status_code=400)
    return {
        "ok": True,
        "status": "pending",
        "message": "Cuenta creada. Rafael te aprobará pronto para acceder a memoria de empresa.",
        "username": doc.get("username"),
    }


@app.post("/api/voice/logout")
def voice_logout(response: Response):
    response.delete_cookie(voice_auth.SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/voice/auth/google")
def voice_google_start():
    if not voice_auth.google_oauth_configured():
        return JSONResponse({"ok": False, "error": "google_oauth_not_configured"}, status_code=503)
    state = voice_auth.new_oauth_state()
    redirect = RedirectResponse(voice_auth.google_authorize_url(state), status_code=302)
    redirect.set_cookie(
        "ralfia_oauth_state",
        state,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return redirect


@app.get("/api/voice/auth/google/callback")
def voice_google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
):
    from urllib.parse import quote

    if error:
        return RedirectResponse(f"/?auth=error&msg={quote(error)}", status_code=302)
    cookie_state = request.cookies.get("ralfia_oauth_state") or ""
    if not code or not state or not voice_auth.verify_oauth_state(state) or state != cookie_state:
        return RedirectResponse("/?auth=error&msg=invalid_oauth_state", status_code=302)
    try:
        g_user = voice_auth.exchange_google_code(code)
        profile, _notify = voice_auth.ensure_google_access(
            email=g_user["email"],
            display_name=g_user["display_name"],
            google_sub=g_user["google_sub"],
        )
    except Exception as exc:
        msg = getattr(exc, "detail", str(exc))
        return RedirectResponse(f"/?auth=error&msg={quote(str(msg))}", status_code=302)

    if profile.get("status") != "approved":
        return RedirectResponse("/?auth=pending", status_code=302)

    token = voice_auth.create_session(str(profile.get("username")))
    redirect = RedirectResponse("/", status_code=302)
    redirect.set_cookie(
        voice_auth.SESSION_COOKIE,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=voice_auth.SESSION_TTL,
        path="/",
    )
    redirect.delete_cookie("ralfia_oauth_state", path="/")
    return redirect


@app.post("/api/voice/set-password")
def voice_set_password(payload: dict[str, Any], user: dict[str, Any] = Depends(voice_auth.require_user)):
    password = str(payload.get("password") or payload.get("new_password") or "")
    username = str(payload.get("username") or user.get("username") or "").strip()
    if str(user.get("username") or "").lower() not in (username.lower(), "rafagye", "rlopez") and not user.get("is_admin"):
        if username.lower() != str(user.get("username") or "").lower():
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    try:
        voice_auth.set_local_password(username, password)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True, "message": "Contraseña local actualizada. Puedes entrar con correo/usuario + contraseña o con Google."}


@app.post("/api/voice/bootstrap-password")
def voice_bootstrap_password(payload: dict[str, Any], request: Request):
    """Una vez: fija contraseña local de admin (requiere MCP_API_KEY)."""
    from raphiia_openai.settings import MCP_API_KEY

    key = request.headers.get("X-RalfIA-Admin-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if not MCP_API_KEY or not key or key != MCP_API_KEY:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=403)
    username = str(payload.get("username") or "rafagye").strip()
    password = str(payload.get("password") or "")
    if len(password) < 4:
        return JSONResponse({"ok": False, "error": "password_too_short"}, status_code=400)
    try:
        voice_auth.set_local_password(username, password, allow_admin_bootstrap=True)
        voice_auth.approve_user(voice_auth.resolve_username(username), approved_by="bootstrap", role="admin")
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True, "username": voice_auth.resolve_username(username), "message": "Contraseña local configurada."}


@app.get("/api/voice/me")
def voice_me(user: dict[str, Any] = Depends(voice_auth.require_user)):
    return {"ok": True, "user": voice_auth.user_public(user)}


@app.get("/api/voice/profile")
def voice_profile(user: dict[str, Any] = Depends(voice_auth.require_user)):
    uname = str(user.get("username") or "").lower()
    prof = voice_user_profile.get_profile(uname)
    return {
        "ok": True,
        "username": uname,
        "display_name": prof.get("display_name"),
        "facts": prof.get("facts") or [],
        "interaction_count": prof.get("interaction_count") or 0,
        "is_rafael": voice_user_profile.is_rafael(user),
    }


@app.get("/api/voice/mcp/tools")
def voice_mcp_tools(user: dict[str, Any] = Depends(voice_auth.require_user)):
    return {"ok": True, "tools": voice_mcp_executor.tools_summary_for_user(user)}


@app.get("/api/voice/admin/pending-users")
def voice_admin_pending(user: dict[str, Any] = Depends(voice_auth.require_user)):
    if not user.get("is_admin"):
        return JSONResponse({"ok": False, "error": "admin_required"}, status_code=403)
    return {"ok": True, "users": voice_auth.list_pending_users()}


@app.post("/api/voice/admin/approve")
def voice_admin_approve(payload: dict[str, Any], user: dict[str, Any] = Depends(voice_auth.require_user)):
    if not user.get("is_admin"):
        return JSONResponse({"ok": False, "error": "admin_required"}, status_code=403)
    username = str(payload.get("username") or "").strip()
    if not username:
        return JSONResponse({"ok": False, "error": "username_required"}, status_code=400)
    profile = voice_auth.approve_user(username, approved_by=str(user.get("username")))
    return {"ok": True, "profile": profile}


_APPROVE_HTML_OK = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>RalfIA — Usuario aprobado</title><style>body{{font-family:system-ui,sans-serif;background:#070b14;color:#e8edf7;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:1rem}}
.box{{max-width:420px;background:#0f1628;border:1px solid #1e2d4a;border-radius:1rem;padding:2rem;text-align:center}}
h1{{color:#38bdf8;font-size:1.25rem}}p{{color:#8b9cb8;line-height:1.5}}a{{color:#38bdf8}}</style></head>
<body><div class="box"><h1>✅ Usuario aprobado</h1><p><b>{who}</b> ({username}) ya puede entrar a RalfIA voz.</p>
<p><a href="{url}">Abrir voz.pcdoctor.ai</a></p></div></body></html>"""

_APPROVE_HTML_ERR = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>RalfIA — Error</title><style>body{{font-family:system-ui,sans-serif;background:#070b14;color:#fecaca;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:1rem}}
.box{{max-width:420px;background:#450a0a;border:1px solid #7f1d1d;border-radius:1rem;padding:2rem;text-align:center}}</style></head>
<body><div class="box"><h1>No se pudo aprobar</h1><p>{msg}</p></div></body></html>"""


@app.get("/api/voice/approve")
def voice_approve_by_token(token: str | None = None):
    """Aprobación 1-clic desde WhatsApp/email — sin login admin."""
    username = voice_auth.verify_approval_token(token or "")
    if not username:
        return HTMLResponse(
            _APPROVE_HTML_ERR.format(msg="Enlace inválido o expirado. Pide una nueva solicitud."),
            status_code=400,
        )
    try:
        profile = voice_auth.approve_user(username, approved_by="whatsapp_link")
    except Exception as exc:
        return HTMLResponse(_APPROVE_HTML_ERR.format(msg=str(exc)[:200]), status_code=400)
    who = profile.get("display_name") or username
    url = os.getenv("VOICE_PUBLIC_URL", "https://voz.pcdoctor.ai")
    return HTMLResponse(_APPROVE_HTML_OK.format(who=who, username=username, url=url))


@app.post("/api/voice/upload")
async def voice_upload(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(voice_auth.require_user),
):
    """Guarda adjunto en disco para referencia y futuro OCR/visión."""
    raw = await file.read()
    if len(raw) < 1:
        return JSONResponse({"ok": False, "error": "archivo vacío"}, status_code=400)
    if len(raw) > 25 * 1024 * 1024:
        return JSONResponse({"ok": False, "error": "max 25MB"}, status_code=400)
    uname = str(user.get("username") or "user").replace("/", "_")
    dest_dir = Path(f"/home/rlopez/data/ralfia/uploads/{uname}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]", "_", file.filename or "upload.bin")[:120]
    path = dest_dir / safe
    path.write_bytes(raw)
    note = ""
    ct = (file.content_type or "").lower()
    if ct.startswith("text/") or safe.endswith((".txt", ".md", ".csv", ".json")):
        try:
            note = raw.decode("utf-8", errors="replace")[:2000]
        except Exception:
            note = ""
    _save_voice_message(user=user, role="user", content=f"[adjunto] {safe}")
    return {
        "ok": True,
        "filename": safe,
        "path": str(path),
        "size": len(raw),
        "content_type": file.content_type,
        "note": note[:500] if note else "Guardado en servidor — análisis visión/OCR en expansión.",
    }


@app.post("/api/voice/transcribe")
async def voice_transcribe(
    audio: UploadFile = File(...),
    user: dict[str, Any] = Depends(voice_auth.require_user),
):
    raw = await audio.read()
    if len(raw) < 100:
        return JSONResponse({"ok": False, "error": "audio vacío"}, status_code=400)
    if len(raw) > 15 * 1024 * 1024:
        return JSONResponse({"ok": False, "error": "audio_too_large_max_15mb"}, status_code=413)
    result = _whisper_transcribe(raw, mime=audio.content_type or "audio/webm")
    if not result.get("ok"):
        return JSONResponse(result, status_code=503)
    try:
        from raphiia_openai import voice_speaker_id

        spk = voice_speaker_id.identify(raw, audio.content_type or "audio/webm")
        result["speaker_id"] = spk
    except Exception:
        pass
    return result


@app.get("/api/voice/conversations")
def voice_list_conversations(user: dict[str, Any] = Depends(voice_auth.require_user)):
    convs = _list_voice_conversations(user)
    active = _resolve_conv_id(user, create_if_missing=False)
    return {"ok": True, "conversations": convs, "active_conversation_id": active}


@app.post("/api/voice/conversations")
def voice_create_conversation(
    payload: dict[str, Any] = None,
    user: dict[str, Any] = Depends(voice_auth.require_user),
):
    payload = payload if isinstance(payload, dict) else {}
    title = str(payload.get("title") or "Nueva conversación").strip() or "Nueva conversación"
    conv_id = _create_voice_conversation(user, title=title)
    return {"ok": True, "conversation_id": conv_id, "title": title}


@app.post("/api/voice/conversations/{conv_id}/switch")
def voice_switch_conversation(
    conv_id: str,
    user: dict[str, Any] = Depends(voice_auth.require_user),
):
    cid = _voice_conversation_id(user, conv_id)
    _ensure_voice_conversation(user, cid)
    messages = _load_voice_history(user, conv_id=cid)
    return {
        "ok": True,
        "conversation_id": cid,
        "messages": messages,
        "count": len(messages),
    }


@app.post("/api/voice/image/generate")
async def voice_image_generate(
    request: Request,
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(voice_auth.require_user),
):
    """Generación de imagen — async por defecto; ?sync=1 en LAN para respuesta inmediata."""
    import asyncio

    text = str(payload.get("text") or payload.get("prompt") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "text vacío", "detail": "Indica qué imagen quieres generar."}, status_code=400)
    conv_id = _resolve_conv_id(user, payload=payload)
    speak = bool(payload.get("speak", False))
    voice = payload.get("voice")
    voice_user_profile.touch_profile(user)
    voice_user_profile.learn_from_message(user, text)
    _save_voice_message(user=user, role="user", content=text, conv_id=conv_id)

    if not _is_lan_sync_request(request):
        job_id = uuid.uuid4().hex[:16]
        with _IMAGE_JOBS_LOCK:
            IMAGE_JOBS[job_id] = {"status": "pending", "created_at": time.time()}
        threading.Thread(
            target=_run_image_job,
            kwargs={
                "job_id": job_id,
                "user": user,
                "text": text,
                "conv_id": conv_id,
                "speak": speak,
                "voice": str(voice) if voice else None,
            },
            daemon=True,
        ).start()
        return {"ok": True, "job_id": job_id, "status": "pending"}

    try:
        img = await asyncio.wait_for(
            asyncio.to_thread(_generate_voice_image, user, text),
            timeout=VOICE_IMAGE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        friendly = _voice_image_error_message("comfyui_timeout")
        return JSONResponse(
            {"ok": False, "error": "comfyui_timeout", "reply": friendly, "detail": "La generación superó el tiempo límite."},
            status_code=504,
        )
    if img.get("ok"):
        _save_voice_message(user=user, role="assistant", content=img["reply"], conv_id=conv_id)
        if speak:
            audio_url, _path = _synthesize_reply(img["reply"], voice=str(voice) if voice else None)
            if audio_url:
                img["audio_url"] = audio_url
        img["conversation_id"] = conv_id
        return img
    err = str(img.get("error") or "image_failed")
    detail = str(img.get("detail") or img.get("reply") or "")
    return JSONResponse(
        {
            "ok": False,
            "error": err,
            "reply": img.get("reply") or _voice_image_error_message(err, detail),
            "detail": detail,
        },
        status_code=503,
    )


@app.get("/api/voice/image/job/{job_id}")
def voice_image_job_status(
    job_id: str,
    user: dict[str, Any] = Depends(voice_auth.require_user),
):
    del user
    with _IMAGE_JOBS_LOCK:
        job = IMAGE_JOBS.get(job_id)
    if not job:
        return JSONResponse({"ok": False, "error": "job_not_found", "status": "error"}, status_code=404)
    return {"ok": True, **job}


@app.get("/api/voice/history")
def voice_history(
    request: Request,
    conversation_id: str | None = None,
    user: dict[str, Any] = Depends(voice_auth.require_user),
):
    payload = {"conversation_id": conversation_id} if conversation_id else None
    conv_id = _resolve_conv_id(user, payload=payload, request=request)
    messages = _load_voice_history(user, conv_id=conv_id)
    return {
        "ok": True,
        "conversation_id": conv_id,
        "messages": messages,
        "count": len(messages),
    }


@app.post("/api/voice/chat")
async def voice_chat(payload: dict[str, Any], user: dict[str, Any] = Depends(voice_auth.require_user)):
    text = str(payload.get("text") or "").strip()
    history = payload.get("messages")
    if not text and not history:
        return JSONResponse({"ok": False, "error": "text vacío"}, status_code=400)
    conv_id = _resolve_conv_id(user, payload=payload)
    entity_id = payload.get("entity_id")
    speak = bool(payload.get("speak", True))
    voice = payload.get("voice")
    hist_list: list[dict[str, str]] | None = None
    if isinstance(history, list):
        hist_list = [
            {"role": str(m.get("role", "")), "content": str(m.get("content", ""))}
            for m in history
            if isinstance(m, dict)
        ]
    elif not text:
        hist_list = _load_voice_history(user, conv_id=conv_id)
    if text:
        voice_user_profile.touch_profile(user)
        voice_user_profile.learn_from_message(user, text)
        _save_voice_message(user=user, role="user", content=text, conv_id=conv_id)
    if text and _wants_image(text):
        img = _generate_voice_image(user, text)
        if img.get("ok"):
            _save_voice_message(user=user, role="assistant", content=img["reply"], conv_id=conv_id)
            if speak:
                audio_url, _path = _synthesize_reply(img["reply"], voice=str(voice) if voice else None)
                if audio_url:
                    img["audio_url"] = audio_url
            img["conversation_id"] = conv_id
            return img
        chat = {"ok": False, "error": img.get("error", "image_failed"), "detail": img.get("detail") or img.get("warnings")}
        if img.get("reply"):
            return {"ok": False, "error": img.get("error", "image_failed"), "reply": img["reply"], "detail": img.get("detail")}
        return JSONResponse(chat, status_code=503)
    chat = _chat_reply(text or "", user=user, entity_id=entity_id, history=hist_list)
    if not chat.get("ok"):
        return chat
    reply = chat["reply"]
    _save_voice_message(user=user, role="assistant", content=reply, conv_id=conv_id)
    chat["audio_url"] = None
    chat["conversation_id"] = conv_id
    if speak:
        audio_url, tmp_path = _synthesize_reply(reply, voice=str(voice) if voice else None)
        if audio_url:
            chat["audio_url"] = audio_url
            chat["audio_path"] = tmp_path
    return chat


@app.post("/api/voice/chat/stream")
async def voice_chat_stream(payload: dict[str, Any], user: dict[str, Any] = Depends(voice_auth.require_user)):
    """Chat con streaming SSE — texto token a token; TTS al final si speak=true."""
    text = str(payload.get("text") or "").strip()
    history = payload.get("messages")
    if not text:
        return JSONResponse({"ok": False, "error": "text vacío"}, status_code=400)
    conv_id = _resolve_conv_id(user, payload=payload)
    entity_id = payload.get("entity_id")
    speak = bool(payload.get("speak", True))
    voice = payload.get("voice")
    hist_list: list[dict[str, str]] | None = None
    if isinstance(history, list):
        hist_list = [
            {"role": str(m.get("role", "")), "content": str(m.get("content", ""))}
            for m in history
            if isinstance(m, dict)
        ]
    voice_user_profile.touch_profile(user)
    voice_user_profile.learn_from_message(user, text)
    _save_voice_message(user=user, role="user", content=text, conv_id=conv_id)

    async def event_gen():
        parts: list[str] = []
        try:
            if _wants_image(text):
                img = _generate_voice_image(user, text)
                if not img.get("ok"):
                    yield f"data: {json.dumps({'done': True, 'ok': False, 'error': img.get('error') or 'image_failed', 'detail': img.get('detail')}, ensure_ascii=False)}\n\n"
                    return
                _save_voice_message(user=user, role="assistant", content=img["reply"], conv_id=conv_id)
                audio_url = None
                if speak:
                    audio_url, _ = _synthesize_reply(img["reply"], voice=str(voice) if voice else None)
                yield f"data: {json.dumps({'done': True, 'ok': True, 'reply': img['reply'], 'image_url': img.get('image_url'), 'audio_url': audio_url, 'conversation_id': conv_id}, ensure_ascii=False)}\n\n"
                return
            sentence_buf = ""
            tts_idx = 0
            voice_str = str(voice) if voice else None
            async for token in _stream_chat_tokens(
                text, user=user, entity_id=entity_id, history=hist_list, with_context=True
            ):
                parts.append(token)
                sentence_buf += token
                yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
                s = sentence_buf.strip()
                if speak and len(s) >= 22 and re.search(r'[.!?…]["\']?\s*$', s):
                    audio_url, _ = _synthesize_reply(s, voice=voice_str)
                    sentence_buf = ""
                    if audio_url:
                        tts_idx += 1
                        yield f"data: {json.dumps({'tts_chunk': True, 'audio_url': audio_url, 'index': tts_idx}, ensure_ascii=False)}\n\n"
            reply = "".join(parts).strip()
            if not reply:
                yield f"data: {json.dumps({'ok': False, 'error': 'empty_reply'})}\n\n"
                return
            _save_voice_message(user=user, role="assistant", content=reply, conv_id=conv_id)
            yield f"data: {json.dumps({'text_done': True, 'ok': True, 'reply': reply, 'conversation_id': conv_id}, ensure_ascii=False)}\n\n"
            if speak and sentence_buf.strip():
                tail = sentence_buf.strip()
                audio_url, _ = _synthesize_reply(tail, voice=voice_str)
                if audio_url:
                    tts_idx += 1
                    yield f"data: {json.dumps({'tts_chunk': True, 'audio_url': audio_url, 'index': tts_idx, 'final': True}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'ok': True, 'reply': reply, 'audio_url': None, 'tts_streamed': tts_idx > 0, 'conversation_id': conv_id}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'ok': False, 'error': str(exc)[:300]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/api/voice/turn")
async def voice_turn(payload: dict[str, Any], user: dict[str, Any] = Depends(voice_auth.require_user)):
    """Turno fluido v4 — texto ya transcrito, respuesta rápida + TTS."""
    result = _process_voice_turn(payload, user)
    if not result.get("ok") and result.get("error") and not result.get("reply"):
        status = 503 if result.get("error") not in ("text vacío",) else 400
        return JSONResponse(result, status_code=status)
    return result


@app.post("/api/voice/turn/audio")
async def voice_turn_audio(
    audio: UploadFile = File(...),
    conversation_id: str | None = Form(None),
    speak: str | None = Form("true"),
    voice: str | None = Form(None),
    user: dict[str, Any] = Depends(voice_auth.require_user),
):
    """Whisper + turno fluido en una sola llamada."""
    raw = await audio.read()
    if len(raw) < 100:
        return JSONResponse({"ok": False, "error": "audio vacío"}, status_code=400)
    if len(raw) > 15 * 1024 * 1024:
        return JSONResponse({"ok": False, "error": "audio_too_large_max_15mb"}, status_code=413)
    from raphiia_openai import voice_speaker_id

    spk = voice_speaker_id.identify(raw, audio.content_type or "audio/webm")
    stt = _whisper_transcribe(raw, mime=audio.content_type or "audio/webm")
    if not stt.get("ok"):
        return JSONResponse(stt, status_code=503)
    payload: dict[str, Any] = {
        "speak": str(speak or "true").lower() not in ("0", "false", "no"),
    }
    if spk.get("matched") and spk.get("speaker_label"):
        payload["speaker_hint"] = (
            f"Hablante identificado por voz: {spk['speaker_label']} "
            f"(confianza {int(float(spk.get('confidence', 0)) * 100)}%). "
            "Trátalo por su nombre si es coherente con el contexto."
        )
        payload["detected_speaker"] = spk.get("speaker")
        payload["detected_speaker_label"] = spk.get("speaker_label")
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if voice:
        payload["voice"] = voice
    result = _process_voice_turn(payload, user, raw_text=stt.get("text") or "")
    result["transcript"] = stt.get("text") or ""
    result["speaker_id"] = spk
    if not result.get("ok") and result.get("error") and not result.get("reply"):
        return JSONResponse(result, status_code=503)
    return result


@app.get("/api/voice/audio/{filename}")
def voice_audio(filename: str):
    path = Path(tempfile.gettempdir()) / filename
    if not path.is_file() or ".." in filename:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/voice/media/{filename}")
def voice_media(filename: str):
    safe = Path(filename).name
    path = Path(EDITORIAL_MEDIA_ROOT) / safe
    if not path.is_file() or safe != filename:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    mt = "image/png" if safe.lower().endswith(".png") else "image/jpeg"
    return FileResponse(path, media_type=mt)


@app.get("/api/voice/rag-preview")
def voice_rag_preview(
    q: str | None = None,
    limit: int = 8,
    user: dict[str, Any] = Depends(voice_auth.require_user),
):
    """Debug owner-only: RAG híbrido + herramientas MCP detectadas (voz.pcdoctor.ai)."""
    if not (voice_user_profile.is_rafael(user) or user.get("is_admin")):
        return JSONResponse({"ok": False, "error": "owner_required"}, status_code=403)
    query = (q or "").strip()
    if not query:
        return JSONResponse({"ok": False, "error": "q_required"}, status_code=400)
    limit = max(1, min(int(limit), 20))
    return voice_mcp_bridge.rag_preview(user, query, limit=limit)


@app.get("/api/voice/context")
def voice_context(
    query: str | None = None,
    entity_id: str | None = None,
    user: dict[str, Any] = Depends(voice_auth.require_user),
):
    return get_user_context(query=query, user=user, entity_id=entity_id)


@app.post("/api/voice/search")
def voice_search(payload: dict[str, Any], user: dict[str, Any] = Depends(voice_auth.require_user)):
    return user_search(
        user=user,
        query=str(payload.get("query") or ""),
        limit=int(payload.get("limit") or 10),
        entity_id=payload.get("entity_id"),
    )

@app.head("/favicon.ico")
def voice_favicon_head():
    return Response(status_code=200, media_type="image/svg+xml", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/favicon.ico", response_class=Response)
def voice_favicon():
    return Response(PWA_ICON_SVG, media_type="image/svg+xml")


@app.head("/{legacy_path:path}")
def voice_pwa_fallback_head(legacy_path: str):
    blocked_prefixes = ("api/", "cdn-cgi/", "docs", "openapi.json")
    if legacy_path and legacy_path.startswith(blocked_prefixes):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return Response(status_code=200, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/{legacy_path:path}", response_class=HTMLResponse)
def voice_pwa_fallback(legacy_path: str):
    blocked_prefixes = ("api/", "cdn-cgi/", "docs", "openapi.json")
    if legacy_path and legacy_path.startswith(blocked_prefixes):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return voice_pwa()

