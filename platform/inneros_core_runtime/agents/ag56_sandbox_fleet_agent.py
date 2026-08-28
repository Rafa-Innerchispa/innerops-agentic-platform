"""AG-56 Sandbox Fleet — modelos uncensored, WebUI sandbox, ops locales (cero créditos cloud)."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-56_SANDBOX_FLEET"
PROJECT = Path("/home/rlopez/projects/ai-research-sandbox")
SANDBOX_OLLAMA_AMD = os.getenv("SANDBOX_OLLAMA_AMD", "127.0.0.1:11436")
SANDBOX_OLLAMA_INTEL = os.getenv("SANDBOX_OLLAMA_INTEL", "192.168.1.4:11435")
WEBUI_AMD = "open_webui_sandbox_amd"

CATALOG_HINTS = [
    "huihui_ai/qwen3-abliterated:8b → uncensored-qwen3-8b",
    "huihui_ai/dolphin3-abliterated:8b → uncensored-dolphin3-8b",
    "mannix/llama3.1-8b-abliterated:q5_K_M → uncensored-llama31-8b",
    "huihui_ai/deepseek-r1-abliterated:8b → uncensored-deepseek-r1-8b",
]


def _host(node: str) -> str:
    return SANDBOX_OLLAMA_INTEL if node == "intel" else SANDBOX_OLLAMA_AMD


def _run(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 600) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, check=False)
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-2000:],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def agent_sandbox_status(*, node: str = "amd") -> dict[str, Any]:
    from raphiia_openai import sandbox_steward

    host = _host(node)
    ollama = sandbox_steward.list_sandbox_models(node=node)
    webui = _run(["docker", "inspect", "-f", "{{.State.Health.Status}}", WEBUI_AMD], timeout=15)
    svc = _run(["systemctl", "--user", "is-active", "ollama-sandbox-amd"], timeout=10)
    out = {
        "ok": True,
        "agent_id": AGENT_ID,
        "node": node,
        "ollama_host": host,
        "ollama": ollama,
        "ollama_service": svc.get("stdout", "").strip(),
        "webui_container": WEBUI_AMD,
        "webui_health": webui.get("stdout", "").strip() or "unknown",
        "webui_url": "http://192.168.1.5:3004" if node == "amd" else "http://192.168.1.4:3002",
        "portal_url": "http://192.168.1.5:3005" if node == "amd" else "http://192.168.1.4:3003",
        "runtime": "local — Ollama CPU/GPU en LAN, sin créditos Cursor/ChatGPT",
        "catalog_installed": CATALOG_HINTS,
    }
    record_agent_run(AGENT_ID, action="sandbox_status", summary=f"node={node}", metadata=out)
    return out


def agent_sandbox_search_models(query: str, *, limit: int = 10) -> dict[str, Any]:
    """Busca en librería pública Ollama (HTTP) + modelos locales sandbox."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "empty_query"}
    local: list[str] = []
    try:
        from raphiia_openai import sandbox_steward

        listing = sandbox_steward.list_sandbox_models(node="amd")
        local = [m["name"] for m in listing.get("models") or [] if q.lower() in m["name"].lower()]
    except Exception:
        pass
    remote: list[dict[str, str]] = []
    url = f"https://ollama.com/api/search?q={urllib.parse.quote(q)}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in (data.get("models") or data if isinstance(data, list) else [])[:limit]:
            if isinstance(item, dict):
                remote.append({"name": str(item.get("name", "")), "tag": str(item.get("tag", ""))})
            else:
                remote.append({"name": str(item), "tag": ""})
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        remote = [{"error": str(exc)[:120]}]
    result = {
        "ok": True,
        "agent_id": AGENT_ID,
        "query": q,
        "local_matches": local,
        "remote_matches": remote[:limit],
        "catalog_hints": [h for h in CATALOG_HINTS if q.lower() in h.lower()],
        "runtime": "local search + ollama.com API",
    }
    record_agent_run(AGENT_ID, action="sandbox_search", summary=q, metadata=result)
    return result


def agent_sandbox_install_model(
    pull_name: str,
    alias: str | None = None,
    *,
    node: str = "amd",
    notify: bool = True,
) -> dict[str, Any]:
    """Pull + alias uncensored (SYSTEM vacío, think=false). Notifica WhatsApp."""
    from raphiia_openai import sandbox_steward

    pull = pull_name.strip()
    if not pull:
        return {"ok": False, "error": "empty_pull_name"}
    host = _host(node)
    env = {**os.environ, "OLLAMA_HOST": host}
    pull_r = _run(["ollama", "pull", pull], env=env, timeout=3600)
    if not pull_r.get("ok"):
        return {"ok": False, "step": "pull", **pull_r}

    alias_name = (alias or pull.split("/")[-1].replace(":", "-")).strip()
    if not alias_name.startswith("uncensored-"):
        alias_name = f"uncensored-{alias_name}"

    mod.write_text(
        f"FROM {pull}\nSYSTEM \"\"\nPARAMETER temperature 1.0\nPARAMETER top_p 0.95\n"
        f"PARAMETER repeat_penalty 1.05\nPARAMETER num_ctx 8192\nPARAMETER num_predict 4096\n",
        encoding="utf-8",
    )
    create_r = _run(["ollama", "create", alias_name, "-f", str(mod)], env=env, timeout=300)
    listing = sandbox_steward.list_sandbox_models(node=node)
    result = {
        "ok": create_r.get("ok", False),
        "agent_id": AGENT_ID,
        "pull": pull,
        "alias": alias_name,
        "node": node,
        "host": host,
        "models": listing.get("models"),
        "runtime": "local ollama pull — cero créditos cloud",
    }
    if notify:
        sandbox_steward.notify_owner(
            f"AG-56 instaló modelo sandbox\n• pull: `{pull}`\n• alias: `{alias_name}`\n• nodo: {node}",
            severity="info" if result["ok"] else "warn",
        )
    record_agent_run(AGENT_ID, action="sandbox_install", summary=pull, metadata=result)
    return result


def agent_sandbox_fix_webui(*, node: str = "amd") -> dict[str, Any]:
    """Reaplica fix WebUI (historial ON, think=false, modelos pinned) sin borrar chats."""
    if node != "amd":
        return {"ok": False, "error": "only_amd_implemented"}
    env_file = PROJECT / "sandbox.env.amd"
    model = "uncensored-qwen3-8b:latest"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("SANDBOX_MODEL="):
                model = line.split("=", 1)[1].strip()
    cp = _run(["docker", "cp", str(PROJECT / "fix_webui_sandbox.py"), f"{WEBUI_AMD}:/tmp/fix.py"])
    if not cp.get("ok"):
        return {"ok": False, "step": "docker_cp", **cp}
    fix = _run(
        [
            "docker", "exec",
            "-e", f"SANDBOX_MODEL={model}",
            "-e", "SANDBOX_OLLAMA_URL=http://host.docker.internal:11436",
            "-e", "SANDBOX_RESET_CHATS=0",
            WEBUI_AMD, "python3", "/tmp/fix.py",
        ],
        timeout=60,
    )
    result = {"ok": fix.get("ok", False), "agent_id": AGENT_ID, "model": model, "fix": fix}
    record_agent_run(AGENT_ID, action="sandbox_fix_webui", summary=model, metadata=result)
    return result


def agent_sandbox_dispatch(message: str = "", *, node: str = "amd") -> dict[str, Any]:
    """Router NL local para ops sandbox."""
    msg = (message or "").strip().lower()
    if not msg or msg in ("estado", "status", "help"):
        return agent_sandbox_status(node=node)
    if msg.startswith("buscar ") or msg.startswith("search "):
        q = message.split(" ", 1)[1]
        return agent_sandbox_search_models(q)
    if msg.startswith("instalar ") or msg.startswith("install "):
        parts = message.split()
        pull = parts[1] if len(parts) > 1 else ""
        alias = parts[2] if len(parts) > 2 else None
        return agent_sandbox_install_model(pull, alias, node=node)
    if "fix" in msg or "webui" in msg or "reparar" in msg:
        return agent_sandbox_fix_webui(node=node)
    if msg.startswith("borrar ") or msg.startswith("delete "):
        from raphiia_openai import sandbox_steward

        model = message.split(" ", 1)[1].strip()
        return sandbox_steward.propose_delete_model(model, node=node, requested_by=AGENT_ID)
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "hint": "Comandos: estado | buscar <query> | instalar <pull> [alias] | fix webui | borrar <modelo>",
        "status": agent_sandbox_status(node=node),
    }
