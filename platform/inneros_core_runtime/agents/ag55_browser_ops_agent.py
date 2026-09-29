"""AG-55 Browser Ops Agent — Playwright local, sin créditos Cursor.

Tareas puntuales: navegar, captura, rellenar formularios allowlisted, extraer texto.
Evidencia en data/ralfia/browser_ops/evidence/.
Subred autorizada para dispositivos: 192.168.3.0/24 (Bellini I-II read-only).
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from raphiia_openai.agent_auto_log import record_agent_run

AGENT_ID = "AG-55_BROWSER_OPS"

DEFAULT_ALLOWLIST = (
    "linkedin.com",
    "www.linkedin.com",
    "brightdata.com",
    "brightdata.io",
    "devpost.com",
    "lablab.ai",
    "cloud.google.com",
    "console.cloud.google.com",
    "aws.amazon.com",
    "developer.amazon.com",
    "amazon.com",
    "portal.azure.com",
    "notion.so",
    "docs.google.com",
    "github.com",
    "pcdoctor.ai",
    "mcp.pcdoctor.ai",
    "google.com",
    "accounts.google.com",
    "myaccount.google.com",
    "gmail.com",
    "mail.google.com",
    "microsoft.com",
    "login.microsoftonline.com",
    "login.live.com",
    "outlook.live.com",
    "gwn.cloud",
    "www.gwn.cloud",
    "grandstream.com",
    "www.grandstream.com",
)

BELLINI_SUBNET = ipaddress.ip_network("192.168.3.0/24")

EVIDENCE_ROOT = Path(os.getenv(
    "BROWSER_OPS_EVIDENCE",
    "/home/rlopez/data/ralfia/browser_ops/evidence",
))
USER_DATA_ROOT = Path(os.getenv(
    "BROWSER_OPS_USER_DATA",
    "/home/rlopez/data/ralfia/browser_ops/profiles",
))


def _profile_dir(profile: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", (profile or "default")[:40])
    path = USER_DATA_ROOT / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _allowlist() -> tuple[str, ...]:
    raw = os.getenv("BROWSER_OPS_ALLOWLIST", "")
    if raw.strip():
        return tuple(d.strip().lower() for d in raw.split(",") if d.strip())
    return DEFAULT_ALLOWLIST


def _url_allowed_result(
    url: str,
    *,
    local_preview: bool = False,
    loopback_ports: list[int] | None = None,
) -> dict[str, Any]:
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "missing_url"}
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return {"ok": False, "error": "invalid_url", "url": url}

    if not host:
        return {"ok": False, "error": "missing_host", "url": url}

    # 1. Check Bellini Subnet 192.168.3.0/24 (Scope Bellini I-II read-only)
    try:
        ip = ipaddress.ip_address(host)
        if ip in BELLINI_SUBNET:
            return {
                "ok": True,
                "host": host,
                "scope": "bellini_read_only",
                "subnet": "192.168.3.0/24",
                "mutation_policy": "read_only",
            }
        # Other private IPs are forbidden unless explicit loopback preview
        if ip.is_private or ip.is_loopback:
            if local_preview and host in ("127.0.0.1", "localhost") and loopback_ports and port in loopback_ports:
                return {"ok": True, "host": host, "scope": "loopback_preview", "port": port}
            return {
                "ok": False,
                "error": "private_network_forbidden",
                "host": host,
                "allowed_subnet": "192.168.3.0/24",
                "reason": "Private IP is outside authorized Bellini 192.168.3.0/24 subnet",
            }
    except ValueError:
        pass

    # 2. Check Domain Allowlist
    for allowed in _allowlist():
        if host == allowed or host.endswith(f".{allowed}"):
            return {"ok": True, "host": host, "scope": "domain_allowlisted"}

    # 3. Local preview check for named localhost
    if local_preview and host in ("127.0.0.1", "localhost"):
        if loopback_ports and port in loopback_ports:
            return {"ok": True, "host": host, "scope": "loopback_preview", "port": port}
        return {"ok": False, "error": "loopback_port_not_allowlisted", "host": host, "port": port}

    return {
        "ok": False,
        "error": "domain_not_allowlisted",
        "host": host,
        "allowlist": list(_allowlist()),
        "allowed_subnets": ["192.168.3.0/24"],
    }


def _host_allowed(url: str, local_preview: bool = False, loopback_ports: list[int] | None = None) -> bool:
    res = _url_allowed_result(url, local_preview=local_preview, loopback_ports=loopback_ports)
    return res.get("ok", False)


def _playwright_available() -> dict[str, Any]:
    try:
        import playwright  # noqa: F401
        return {"ok": True, "package": "playwright"}
    except ImportError:
        return {"ok": False, "error": "playwright_not_installed", "fix": "pip install playwright && playwright install chromium"}


def agent_browser_status() -> dict[str, Any]:
    pw = _playwright_available()
    evidence: list[dict[str, Any]] = []
    if EVIDENCE_ROOT.is_dir():
        for p in sorted(EVIDENCE_ROOT.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                evidence.append({
                    "file": p.name,
                    "task": data.get("task"),
                    "url": data.get("url"),
                    "at": data.get("at"),
                    "ok": data.get("ok"),
                })
            except (OSError, json.JSONDecodeError):
                continue
    return {
        "ok": pw.get("ok", False),
        "agent_id": AGENT_ID,
        "playwright": pw,
        "headless": os.getenv("BROWSER_OPS_HEADLESS", "1") != "0",
        "allowlist": list(_allowlist()),
        "allowed_subnets": ["192.168.3.0/24"],
        "evidence_dir": str(EVIDENCE_ROOT),
        "recent_runs": evidence,
        "mission": "Automatización puntual en navegador (formularios, capturas) — local, sin cloud",
        "entry_tools": ["agent_browser_run_task", "browser_session_start", "dispatch_local_agent task_kind=browser"],
    }


def _save_evidence(payload: dict[str, Any]) -> str:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", (payload.get("task") or "run")[:40])
    path = EVIDENCE_ROOT / f"{ts}_{safe}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return str(path)


def agent_browser_run_task(
    task: str,
    url: str = "",
    *,
    selectors: dict[str, str] | None = None,
    values: dict[str, str] | None = None,
    click_selector: str = "",
    extract_selector: str = "",
    profile: str = "",
    dry_run: bool = True,
    timeout_ms: int = 30000,
    local_preview: bool = False,
    loopback_ports: list[int] | None = None,
) -> dict[str, Any]:
    """Ejecuta tarea browser allowlisted: navigate | screenshot | fill_form | click | extract."""
    task = (task or "navigate").strip().lower()

    pw_check = _playwright_available()
    if not pw_check.get("ok"):
        return {"ok": False, "agent_id": AGENT_ID, **pw_check}

    if task != "status" and not url:
        return {"ok": False, "error": "url_required", "agent_id": AGENT_ID}

    guard = _url_allowed_result(url, local_preview=local_preview, loopback_ports=loopback_ports)
    if url and not guard.get("ok"):
        return {
            "ok": False,
            "error": "domain_or_ip_not_allowlisted",
            "url": url,
            "url_guard": guard,
            "allowlist": list(_allowlist()),
            "allowed_subnets": ["192.168.3.0/24"],
            "agent_id": AGENT_ID,
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "agent_id": AGENT_ID,
            "url_guard": guard,
            "would_run": {
                "task": task,
                "url": url,
                "selectors": selectors or {},
                "values": values or {},
                "click_selector": click_selector,
                "extract_selector": extract_selector,
                "profile": profile or "",
            },
        }

    from playwright.sync_api import sync_playwright

    headless = os.getenv("BROWSER_OPS_HEADLESS", "1") != "0"
    result: dict[str, Any] = {
        "ok": True,
        "agent_id": AGENT_ID,
        "task": task,
        "url": url,
        "profile": profile or "",
        "at": _now_iso(),
        "dry_run": False,
        "url_guard": guard,
    }
    screenshot_path = ""
    context = None
    browser = None

    try:
        with sync_playwright() as p:
            if profile:
                context = p.chromium.launch_persistent_context(
                    str(_profile_dir(profile)),
                    headless=headless,
                    channel=None,
                )
                page = context.pages[0] if context.pages else context.new_page()
            else:
                browser = p.chromium.launch(headless=headless)
                page = browser.new_page()
            page.set_default_timeout(timeout_ms)

            if task in ("navigate", "screenshot", "fill_form", "click", "extract"):
                page.goto(url, wait_until="domcontentloaded")

            if task == "screenshot" or task == "navigate":
                EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                screenshot_path = str(EVIDENCE_ROOT / f"{ts}_screenshot.png")
                page.screenshot(path=screenshot_path, full_page=True)
                result["screenshot"] = screenshot_path
                result["title"] = page.title()

            if task == "fill_form" and values:
                filled: list[str] = []
                for field, value in values.items():
                    sel = (selectors or {}).get(field, field)
                    page.fill(sel, value)
                    filled.append(sel)
                result["filled"] = filled

            if task == "click" and click_selector:
                page.click(click_selector)
                result["clicked"] = click_selector

            if task == "extract":
                sel = extract_selector or "body"
                result["text"] = (page.locator(sel).first.inner_text(timeout=timeout_ms))[:8000]

            if context:
                context.close()
            elif browser:
                browser.close()
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)[:500]

    evidence_file = _save_evidence(result)
    result["evidence_file"] = evidence_file
    record_agent_run(AGENT_ID, action=f"browser_{task}", summary=f"ok={result['ok']} url={url[:60]}", project="browser-ops")
    return result
