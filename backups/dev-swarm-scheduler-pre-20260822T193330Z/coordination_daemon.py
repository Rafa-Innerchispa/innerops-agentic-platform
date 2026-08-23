#!/usr/bin/env python3
"""AG-25 — RalfIA Coordination Orchestrator (daemon loop).

Corre permanentemente (systemd). No reemplaza Cursor/Codex/Antigravity — automatiza:
  - watcher → HUB/feed
  - heartbeat Mongo
  - health módulos InnerOS
  - router Ollama opcional (sin créditos cloud)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

COORD = Path("/home/rlopez/data/ai_coordination")
SCRIPTS = COORD / "scripts"
WATCHER = SCRIPTS / "coordination_watcher.py"
MAPA = COORD / "MAPA_CENTRAL.md"
ROUTER_OUT = COORD / "HUB" / "router_decision.md"
STATE = COORD / ".daemon_state.json"

ROOT = Path("/home/rlopez/projects/raphiia-openai")
sys.path.insert(0, str(ROOT))

from raphiia_openai import ralfia_time  # noqa: E402

INTERVAL_SEC = int(os.environ.get("COORD_DAEMON_INTERVAL", "120"))
OLLAMA_ENABLED = os.environ.get("COORD_OLLAMA_ROUTER", "0") == "1"
OLLAMA_MODEL = os.environ.get("OLLAMA_ORCHESTRATOR_MODEL", "qwen2.5:14b-instruct")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

# Módulos InnerOS / RalfIA — health HTTP (modular, ampliar aquí)
MODULE_HEALTH = [
    {"id": "raphiia-health", "url": "http://127.0.0.1:8101/status", "owner": "CURSOR"},
    {"id": "funding-hub", "url": "http://127.0.0.1:8099/api/opportunities", "owner": "ANTIGRAVITY"},
    {"id": "portal", "url": "http://127.0.0.1:2002/api/ops/health", "owner": "CURSOR"},
]


def _now() -> str:
    return ralfia_time.format_log()


def _load_state() -> dict:
    if STATE.is_file():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"cycles": 0, "last_router": ""}


def _save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _run_watcher() -> str:
    r = subprocess.run(
        [sys.executable, str(WATCHER)],
        capture_output=True,
        text=True,
        check=False,
    )
    out = (r.stdout or "").strip() or (r.stderr or "").strip() or "ok"
    return out[:500]


def _patch_mapa_sync() -> None:
    if not MAPA.is_file():
        return
    text = MAPA.read_text(encoding="utf-8")
    marker = "**Última sync:**"
    line = f"{marker} {_now()} · daemon AG-25"
    if marker in text:
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith(marker):
                lines[i] = line
                break
        MAPA.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        MAPA.write_text(line + "\n\n" + text, encoding="utf-8")


def _check_modules() -> list[dict]:
    results = []
    for mod in MODULE_HEALTH:
        ok = False
        try:
            req = urllib.request.Request(mod["url"], method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                ok = 200 <= resp.status < 400
        except (urllib.error.URLError, OSError, TimeoutError):
            ok = False
        results.append({**mod, "ok": ok, "ts": _now()})
    return results


def _log_mongo(summary: str, event: str = "daemon_tick", metadata: dict | None = None) -> None:
    try:
        from raphiia_openai.agent_auto_log import record_agent_run  # noqa: WPS433

        record_agent_run(
            "AG-25",
            action=event,
            summary=summary,
            project="ralfia-coordination",
            tool_used="coordination_daemon",
            metadata=metadata or {},
        )
    except Exception as exc:
        print(f"auto log skip: {exc}")
        try:
            from raphiia_openai import mongo_store  # noqa: WPS433

            mongo_store.log_coordination(
                agent="AG-25",
                summary=summary,
                event=event,
                project="ralfia-coordination",
                tool_used="coordination_daemon",
                metadata=metadata or {},
            )
        except Exception as exc2:
            print(f"mongo log skip: {exc2}")


def _ollama_router(watcher_output: str) -> None:
    if not OLLAMA_ENABLED or "No changes" in watcher_output:
        return
    prompt_path = COORD / "scripts" / "ollama_orchestrator_prompt.txt"
    if not prompt_path.is_file():
        return
    system = prompt_path.read_text(encoding="utf-8")[:4000]
    user = f"Cambios detectados: {watcher_output}\nResume y propón next action en español."
    body = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data.get("message", {}).get("content", "")
        if content:
            ROUTER_OUT.parent.mkdir(parents=True, exist_ok=True)
            ROUTER_OUT.write_text(f"# Router Ollama — {_now()}\n\n{content}\n", encoding="utf-8")
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"ollama router skip: {exc}")


def tick() -> None:
    state = _load_state()
    watcher_out = _run_watcher()
    modules = _check_modules()
    try:
        sync_path = SCRIPTS / "coordination_mailbox_sync.py"
        if sync_path.is_file():
            r = subprocess.run(
                [sys.executable, str(sync_path)],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "MODULES_HEALTH_JSON": json.dumps(modules)},
            )
            sync_out = (r.stdout or "").strip()
            if sync_out and "Synced:" in sync_out:
                watcher_out += f"; {sync_out}"
    except Exception as exc:
        print(f"mailbox sync skip: {exc}")
    _patch_mapa_sync()
    try:
        from raphiia_openai import service_registry  # noqa: WPS433

        wd = service_registry.run_all_checks()
        watcher_out += f"; watchdog={wd.get('summary', {})}"
    except Exception as exc:
        print(f"watchdog skip: {exc}")
    cycles = state.get("cycles", 0)
    if cycles % 6 == 0:
        try:
            from raphiia_openai import handoff_detector  # noqa: WPS433

            hd = handoff_detector.detect_missing_handoff(hours=72)
            if hd.get("count", 0):
                watcher_out += f"; missing_handoff={hd['count']}"
        except Exception as exc:
            print(f"handoff scan skip: {exc}")
    down = [m["id"] for m in modules if not m["ok"]]
    summary = f"AG-25 tick: {watcher_out}"
    if down:
        summary += f"; modules down: {', '.join(down)}"
    _log_mongo(summary, metadata={"modules": modules, "watcher": watcher_out})
    _ollama_router(watcher_out)
    # Notificaciones WhatsApp cada ~5 min (cada 2-3 ciclos de 120s)
    if cycles % 3 == 0:
        try:
            import subprocess as _sp

            notify_script = ROOT / "scripts" / "ralfia_notify.py"
            if notify_script.is_file():
                env = {**os.environ, "MODULES_HEALTH_JSON": json.dumps(modules)}
                _sp.run(
                    [sys.executable, str(notify_script)],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=env,
                    check=False,
                )
        except Exception as exc:
            print(f"notify skip: {exc}")
    if cycles % 12 == 0:
        try:
            from raphiia_openai.memory.agent_messages import compact_agent_mailbox  # noqa: WPS433

            for ag in ("chatgpt", "codex", "antigravity", "cursor", "notion", "gemini"):
                compact_agent_mailbox(ag, max_open=10)
            watcher_out += "; inboxes_compacted"
        except Exception as exc:
            print(f"compact skip: {exc}")
    state["cycles"] = state.get("cycles", 0) + 1
    state["last_tick"] = _now()
    _save_state(state)
    try:
        from raphiia_openai.coordination_live import refresh_estado_vivo  # noqa: WPS433

        refresh_estado_vivo()
    except Exception as exc:
        print(f"estado_vivo skip: {exc}")
    print(summary)


def main() -> None:
    print(f"AG-25 coordination daemon — interval {INTERVAL_SEC}s ollama={OLLAMA_ENABLED}")
    while True:
        try:
            tick()
        except Exception as exc:
            print(f"tick error: {exc}")
            _log_mongo(f"AG-25 error: {exc}", event="daemon_error")
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
