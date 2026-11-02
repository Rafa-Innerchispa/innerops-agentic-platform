"""Alertas WhatsApp por coordinación RalfIA — directo Evolution, sin n8n."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from raphiia_openai import ralfia_time
from raphiia_openai.notifications.evolution_client import send_alert_whatsapp
from raphiia_openai.notifications.settings import NOTIFY_COOLDOWN_SEC, NOTIFY_MODULE_DOWN

COORD = Path("/home/rlopez/data/ai_coordination")
STATE_FILE = COORD / ".notify_state.json"
FEED_JSONL = COORD / "HUB" / "feed.jsonl"

HIGH_PRIORITY_FILES = {
    "TASKS.md",
    "cursor/INBOX.md",
    "chatgpt/INBOX.md",
    "codex/INBOX.md",
    "antigravity/INBOX.md",
}

INBOX_HIGH_RE = re.compile(r"\*\*Priority:\*\*\s*high", re.I)


def _load_state() -> dict:
    default = {"sent_hashes": [], "cooldowns": {}, "modules_down": []}
    if not STATE_FILE.is_file():
        return default
    raw = STATE_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Estado corrupto (p. ej. escrituras concurrentes) — conservar primer objeto válido
        decoder = json.JSONDecoder()
        try:
            obj, _end = decoder.raw_decode(raw)
            if isinstance(obj, dict):
                backup = STATE_FILE.with_suffix(".json.bak")
                backup.write_text(raw, encoding="utf-8")
                _save_state({**default, **obj})
                return {**default, **obj}
        except json.JSONDecodeError:
            pass
        backup = STATE_FILE.with_suffix(".json.bak")
        backup.write_text(raw, encoding="utf-8")
        _save_state(default)
        return default


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _dedupe_key(kind: str, payload: str) -> str:
    return hashlib.sha256(f"{kind}:{payload}".encode()).hexdigest()[:16]


def _can_send(state: dict, kind: str, key: str) -> bool:
    now = time.time()
    cd = state.setdefault("cooldowns", {})
    last = cd.get(f"{kind}:{key}", 0)
    if now - last < NOTIFY_COOLDOWN_SEC:
        return False
    sent = set(state.get("sent_hashes", []))
    if key in sent:
        return False
    return True


def _mark_sent(state: dict, kind: str, key: str) -> None:
    state.setdefault("cooldowns", {})[f"{kind}:{key}"] = time.time()
    hashes = state.setdefault("sent_hashes", [])
    hashes.append(key)
    state["sent_hashes"] = hashes[-200:]


def _notify(text: str, state: dict, kind: str, key: str) -> bool:
    if not _can_send(state, kind, key):
        return False
    res = send_alert_whatsapp(text)
    if res.get("ok"):
        _mark_sent(state, kind, key)
        return True
    return False


def check_high_priority_inboxes() -> list[str]:
    alerts: list[str] = []
    for rel in HIGH_PRIORITY_FILES:
        if rel.endswith("INBOX.md"):
            path = COORD / rel
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            sections = text.split("\n## ")
            for sec in sections[-3:]:
                if INBOX_HIGH_RE.search(sec):
                    agent = rel.split("/")[0]
                    title_m = re.search(r"\*\*(.+?)\*\*", sec)
                    title = title_m.group(1) if title_m else sec[:80]
                    alerts.append(f"📬 {agent.upper()}: {title[:120]}")
    return alerts


def check_tasks_blocked() -> list[str]:
    tasks = COORD / "TASKS.md"
    if not tasks.is_file():
        return []
    text = tasks.read_text(encoding="utf-8", errors="replace")
    alerts = []
    for line in text.splitlines():
        if "| **T-" in line and ("BLOCKED" in line or "IN_PROGRESS" in line and "T-035" in line):
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 4:
                alerts.append(f"📋 {parts[0]} {parts[1][:40]} — {parts[3]}")
    return alerts[:5]


def check_modules_down(modules: list[dict] | None) -> list[str]:
    if not modules or not NOTIFY_MODULE_DOWN:
        return []
    return [f"🔴 Servicio caído: {m['id']} ({m.get('owner', '?')})" for m in modules if not m.get("ok")]


def check_feed_important(since_line: int = 0) -> list[str]:
    if not FEED_JSONL.is_file():
        return []
    lines = FEED_JSONL.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines = lines[since_line:]
    alerts = []
    for ln in new_lines[-10:]:
        if any(x in ln for x in ("chatgpt/INBOX", "TASKS.md", "BLOCKED", "Priority")):
            alerts.append(f"🔄 {ln[:180]}")
    return alerts


def check_registry_critical_down() -> list[str]:
    """Servicios critical/high en estado down o timeout."""
    try:
        from raphiia_openai import service_registry

        listed = service_registry.list_services(visible_only=False, limit=200)
        alerts = []
        for s in listed.get("services", []):
            st = s.get("status")
            risk = s.get("risk_level", "")
            sid = str(s.get("service_id") or "")
            bad = st in ("down", "timeout") or (st == "degraded" and risk in ("critical", "high"))
            if not bad:
                continue
            if risk not in ("critical", "high") and not sid.startswith("discovered-"):
                continue
            if s.get("status") == "pending_review":
                continue
            alerts.append(
                f"🔴 {s.get('name', s.get('service_id'))} :{s.get('port', '?')} — {s.get('status')}"
                + (f" ({s.get('last_error', '')[:80]})" if s.get("last_error") else "")
            )
        return alerts[:8]
    except Exception:
        return []


def check_missing_handoffs() -> list[str]:
    try:
        from raphiia_openai import handoff_detector

        res = handoff_detector.detect_missing_handoff(hours=48)
        alerts = []
        for f in res.get("flags", []):
            if f.get("severity") != "high" and f.get("kind") != "orchestration_task":
                continue
            alerts.append(
                f"⚠️ Handoff {f.get('agent', '?')}: {(f.get('title') or f.get('summary') or f.get('kind', ''))[:100]}"
            )
        return alerts[:5]
    except Exception:
        return []


def run_coordination_alerts(modules_health: list[dict] | None = None) -> dict[str, Any]:
    state = _load_state()
    messages: list[str] = []
    sent = 0

    for msg in check_high_priority_inboxes():
        key = _dedupe_key("inbox", msg)
        if _notify(f"🧠 Ralphi IA\n{msg}\n{ralfia_time.format_log()}", state, "inbox", key):
            sent += 1
        messages.append(msg)

    blocked = check_tasks_blocked()
    if blocked:
        body = "🧠 Ralphi IA — tareas activas\n" + "\n".join(blocked[:5])
        key = _dedupe_key("tasks", "|".join(blocked))
        if _notify(body, state, "tasks", key):
            sent += 1

    down = check_modules_down(modules_health)
    prev_down = set(state.get("modules_down", []))
    curr_down = {d.split(":")[1].split()[0] if ":" in d else d for d in down}
    for d in down:
        mod_id = d.split(":")[1].split()[0] if "Servicio" in d else d
        if mod_id not in prev_down:
            key = _dedupe_key("down", mod_id)
            if _notify(f"🧠 Ralphi IA\n{d}\n{ralfia_time.format_log()}", state, "down", key):
                sent += 1
    state["modules_down"] = list(curr_down)

    registry_down = check_registry_critical_down()
    for d in registry_down:
        key = _dedupe_key("registry_down", d)
        if _notify(f"🧠 Ralphi IA\n{d}\n{ralfia_time.format_log()}", state, "registry_down", key):
            sent += 1

    handoffs = check_missing_handoffs()
    if handoffs:
        body = "🤖 RalfIA — handoffs pendientes\n" + "\n".join(handoffs[:5])
        key = _dedupe_key("handoff", "|".join(handoffs))
        if _notify(body, state, "handoff", key):
            sent += 1

    _save_state(state)
    return {
        "alerts_found": len(messages) + len(blocked) + len(down) + len(registry_down) + len(handoffs),
        "whatsapp_sent": sent,
        "messages": messages,
    }
