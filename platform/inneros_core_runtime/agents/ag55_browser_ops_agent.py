"""AG-55 Browser Ops Agent — Playwright local, sin créditos Cursor.

Tareas puntuales: navegar, captura, rellenar formularios allowlisted, extraer texto.
Evidencia en data/ralfia/browser_ops/evidence/.
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
    "creatorcore.ai",
    "alpaca.markets",
)
DEFAULT_LOOPBACK_PORTS = (8088,)
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
METADATA_HOSTS = {"169.254.169.254"}

EVIDENCE_ROOT = Path(
    os.getenv("BROWSER_OPS_EVIDENCE", "/home/rlopez/data/ralfia/browser_ops/evidence")
)
USER_DATA_ROOT = Path(
    os.getenv("BROWSER_OPS_USER_DATA", "/home/rlopez/data/ralfia/browser_ops/profiles")
)


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


def _loopback_ports(extra_ports: list[int] | tuple[int, ...] | None = None) -> tuple[int, ...]:
    raw = os.getenv("BROWSER_OPS_LOOPBACK_PORTS", "")
    ports: set[int] = set(DEFAULT_LOOPBACK_PORTS)
    for value in [*raw.split(","), *(extra_ports or [])]:
        try:
            port = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535:
            ports.add(port)
    return tuple(sorted(ports))


def _is_private_or_metadata_host(host: str) -> bool:
    if host in METADATA_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _host_allowed(
    url: str,
    *,
    local_preview: bool = False,
    loopback_ports: list[int] | tuple[int, ...] | None = None,
) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in LOOPBACK_HOSTS:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return bool(port in _loopback_ports(loopback_ports))
    if _is_private_or_metadata_host(host):
        return False
    for allowed in _allowlist():
        if host == allowed or host.endswith(f".{allowed}"):
            return True
    return False


def _url_allowed_result(
    url: str,
    *,
    local_preview: bool = False,
    loopback_ports: list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return {"ok": False, "error": "invalid_url"}
    if parsed.scheme not in {"http", "https"} or not host:
        return {"ok": False, "error": "invalid_url"}
    if host in LOOPBACK_HOSTS:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        ports = _loopback_ports(loopback_ports)
        if port in ports:
            return {
                "ok": True,
                "mode": "local_preview" if local_preview else "loopback_allowlist",
                "host": host,
                "port": port,
                "loopback_ports": list(ports),
            }
        return {
            "ok": False,
            "error": "loopback_not_allowlisted",
            "host": host,
            "port": port,
            "loopback_ports": list(ports),
        }
    if _is_private_or_metadata_host(host):
        return {"ok": False, "error": "private_or_metadata_host_blocked", "host": host}
    if _host_allowed(url):
        return {"ok": True, "mode": "domain_allowlist", "host": host}
    return {
        "ok": False,
        "error": "domain_not_allowlisted",
        "host": host,
        "allowlist": list(_allowlist()),
    }


def _playwright_available() -> dict[str, Any]:
    try:
        import playwright  # noqa: F401

        return {"ok": True, "package": "playwright"}
    except ImportError:
        return {
            "ok": False,
            "error": "playwright_not_installed",
            "fix": "pip install playwright && playwright install chromium",
        }


def agent_browser_status() -> dict[str, Any]:
    pw = _playwright_available()
    evidence: list[dict[str, Any]] = []
    if EVIDENCE_ROOT.is_dir():
        for p in sorted(EVIDENCE_ROOT.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                evidence.append(
                    {
                        "file": p.name,
                        "task": data.get("task"),
                        "url": data.get("url"),
                        "at": data.get("at"),
                        "ok": data.get("ok"),
                    }
                )
            except (OSError, json.JSONDecodeError):
                continue
    return {
        "ok": pw.get("ok", False),
        "agent_id": AGENT_ID,
        "playwright": pw,
        "headless": os.getenv("BROWSER_OPS_HEADLESS", "1") != "0",
        "allowlist": list(_allowlist()),
        "loopback_hosts": sorted(LOOPBACK_HOSTS),
        "loopback_ports": list(_loopback_ports()),
        "evidence_dir": str(EVIDENCE_ROOT),
        "recent_runs": evidence,
        "mission": "Automatización puntual en navegador (formularios, capturas) — local, sin cloud",
        "entry_tools": ["agent_browser_run_task", "dispatch_local_agent task_kind=browser"],
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

    url_guard = (
        _url_allowed_result(url, local_preview=local_preview, loopback_ports=loopback_ports)
        if url
        else {"ok": True}
    )
    if url and not url_guard.get("ok"):
        return {"ok": False, **url_guard, "url": url, "agent_id": AGENT_ID}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "agent_id": AGENT_ID,
            "would_run": {
                "task": task,
                "url": url,
                "selectors": selectors or {},
                "values": values or {},
                "click_selector": click_selector,
                "extract_selector": extract_selector,
                "profile": profile or "",
                "local_preview": local_preview,
                "url_guard": url_guard,
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
    }
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
                final_guard = _url_allowed_result(
                    page.url,
                    local_preview=local_preview,
                    loopback_ports=loopback_ports,
                )
                if not final_guard.get("ok"):
                    result["ok"] = False
                    result["error"] = "redirect_target_not_allowlisted"
                    result["final_url"] = page.url
                    result["url_guard"] = final_guard
                    raise RuntimeError("redirect_target_not_allowlisted")
                result["final_url"] = page.url

            if task in ("screenshot", "navigate"):
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
                result["text"] = page.locator(sel).first.inner_text(timeout=timeout_ms)[:8000]

            if context:
                context.close()
            elif browser:
                browser.close()
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)[:500]

    evidence_file = _save_evidence(result)
    result["evidence_file"] = evidence_file
    record_agent_run(
        AGENT_ID,
        action=f"browser_{task}",
        summary=f"ok={result['ok']} url={url[:60]}",
        project="browser-ops",
    )
    return result
