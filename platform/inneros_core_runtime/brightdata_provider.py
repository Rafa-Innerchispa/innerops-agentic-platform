"""Bright Data provider for InnerOS web-data tasks.

Tokens live in owner_vault. Public functions redact secrets and default to
low-volume calls so agents can use the expiring credit without open-ended spend.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from inneros_core_runtime import owner_vault
from raphiia_openai import mongo_store

PROVIDER_ID = "brightdata-webdata"
VAULT_CATEGORY = "brightdata"
VAULT_KEY = "api_token"
AUDIT_COLLECTION = "ralfia_brightdata_audit"
API_BASE = "https://api.brightdata.com"
MCP_BASE = "https://mcp.brightdata.com/mcp"
DEFAULT_RATE_LIMIT = "80/day"
DEFAULT_GROUPS = "web_data,serp"
ALLOWED_DIRECT_TOOLS = {"ask_brightdata_assistant", "search_engine", "scrape_as_markdown", "search_engine_batch"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("<redacted>" if re.search(r"(?i)(token|secret|password|authorization|api[_-]?key)", str(k)) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str) and re.search(r"(?i)(bearer\\s+|api[_-]?key|token=|[0-9a-f]{8}-[0-9a-f-]{27,})", value):
        return "<redacted>"
    return value


def _audit(action: str, evidence: dict[str, Any]) -> None:
    try:
        mongo_store.get_db()[AUDIT_COLLECTION].insert_one(
            {"ts": _now(), "provider": PROVIDER_ID, "action": action, "evidence": _redact(evidence)}
        )
    except Exception:
        pass


def _token() -> str:
    cred = owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=True)
    if not cred.get("ok"):
        return ""
    return str(cred.get("secret") or "").strip()


def _request(method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 45) -> dict[str, Any]:
    token = _token()
    if not token:
        return {"ok": False, "error": "brightdata_token_missing", "secret_location": f"owner_vault:{VAULT_CATEGORY}/{VAULT_KEY}"}
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method.upper(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(text) if text else {}
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "data": parsed}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text) if text else {}
        except Exception:
            parsed = {"raw": text[:2000]}
        return {"ok": False, "status": exc.code, "error": "brightdata_http_error", "data": _redact(parsed)}
    except Exception as exc:
        return {"ok": False, "error": "brightdata_request_failed", "detail": str(exc)[:300]}


def _parse_sse(text: str) -> dict[str, Any]:
    payloads = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                payloads.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                payloads.append({"raw": line[6:][:2000]})
    if payloads:
        return payloads[-1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text[:4000]}


def _mcp_post(payload: dict[str, Any], session_id: str = "", timeout: int = 60) -> tuple[dict[str, Any], str]:
    token = _token()
    if not token:
        return {"ok": False, "error": "brightdata_token_missing", "secret_location": f"owner_vault:{VAULT_CATEGORY}/{VAULT_KEY}"}, ""
    url = f"{MCP_BASE}?token={urllib.parse.quote(token)}"
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session_id:
        headers["mcp-session-id"] = session_id
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "data": _parse_sse(text)}, str(resp.headers.get("mcp-session-id") or session_id)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status": exc.code, "error": "brightdata_mcp_http_error", "data": _redact(_parse_sse(text))}, session_id
    except Exception as exc:
        return {"ok": False, "error": "brightdata_mcp_request_failed", "detail": str(exc)[:300]}, session_id


def _mcp_session() -> tuple[dict[str, Any], str]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "inneros-brightdata-provider", "version": "0.1"},
        },
    }
    init, session_id = _mcp_post(payload)
    if session_id:
        _mcp_post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, session_id=session_id, timeout=20)
    return init, session_id


def store_api_token_server_side(secret: str, label: str = "Bright Data API token", actor: str = "RAFAEL") -> dict[str, Any]:
    if not secret or len(secret.strip()) < 20:
        return {"ok": False, "error": "secret_required"}
    result = owner_vault.save_owner_credential(
        key=VAULT_KEY,
        secret=secret.strip(),
        category=VAULT_CATEGORY,
        label=label,
        metadata={"provider": PROVIDER_ID, "stored_at": _now(), "default_rate_limit": DEFAULT_RATE_LIMIT},
        actor=actor,
    )
    _audit("store_api_token_server_side", {"ok": result.get("ok"), "vault_id": result.get("vault_id")})
    return {"ok": bool(result.get("ok")), "vault_id": result.get("vault_id"), "category": VAULT_CATEGORY, "key": VAULT_KEY, "secret_returned": False}


def balance() -> dict[str, Any]:
    result = _request("GET", "/customer/balance", timeout=30)
    out = {"ok": bool(result.get("ok")), "provider": PROVIDER_ID, "balance": (result.get("data") or {}) if result.get("ok") else None, "raw_status": result.get("status"), "error": result.get("error")}
    _audit("balance", out)
    return out


def status() -> dict[str, Any]:
    token_present = bool(_token())
    bal = balance() if token_present else {"ok": False, "error": "brightdata_token_missing"}
    return {
        "ok": True,
        "provider": PROVIDER_ID,
        "token_present": token_present,
        "account_reachable": bool(bal.get("ok")),
        "balance": bal.get("balance"),
        "secret_location": f"owner_vault:{VAULT_CATEGORY}/{VAULT_KEY}",
        "remote_mcp": {"ok": token_present, "url": f"{MCP_BASE}?token=<redacted>", "groups": DEFAULT_GROUPS},
        "default_rate_limit": DEFAULT_RATE_LIMIT,
        "recommended_immediate_uses": ["seo_serp_checks", "public_page_research", "blocked_page_fetch", "competitive_research"],
    }


def mcp_list_tools(limit: int = 80) -> dict[str, Any]:
    init, session_id = _mcp_session()
    if not init.get("ok") or not session_id:
        return {"ok": False, "provider": PROVIDER_ID, "init": _redact(init)}
    result, _ = _mcp_post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, session_id=session_id)
    tools = (((result.get("data") or {}).get("result") or {}).get("tools") or []) if result.get("ok") else []
    trimmed = [
        {"name": t.get("name"), "description": str(t.get("description") or "")[:500], "inputSchema": t.get("inputSchema")}
        for t in tools[: max(1, min(int(limit or 80), 120))]
    ]
    _audit("mcp_list_tools", {"ok": result.get("ok"), "count": len(tools)})
    return {"ok": bool(result.get("ok")), "provider": PROVIDER_ID, "tools_count": len(tools), "tools": trimmed}


def mcp_call_tool(tool_name: str, arguments: dict[str, Any] | None = None, dry_run: bool = True) -> dict[str, Any]:
    name = (tool_name or "").strip()
    if name not in ALLOWED_DIRECT_TOOLS:
        return {"ok": False, "error": "brightdata_tool_not_allowlisted", "allowed": sorted(ALLOWED_DIRECT_TOOLS)}
    args = arguments or {}
    if dry_run:
        return {"ok": True, "dry_run": True, "provider": PROVIDER_ID, "tool_name": name, "arguments": _redact(args), "will_consume_credit": True}
    init, session_id = _mcp_session()
    if not init.get("ok") or not session_id:
        return {"ok": False, "provider": PROVIDER_ID, "init": _redact(init)}
    payload = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": args}}
    result, _ = _mcp_post(payload, session_id=session_id, timeout=90)
    _audit("mcp_call_tool", {"ok": result.get("ok"), "tool_name": name, "args": _redact(args)})
    return {"ok": bool(result.get("ok")), "provider": PROVIDER_ID, "tool_name": name, "result": _redact(result.get("data"))}


def search_engine(query: str, engine: str = "google", geo_location: str = "us", dry_run: bool = True) -> dict[str, Any]:
    return mcp_call_tool(
        "search_engine",
        {"query": query, "engine": engine, "geo_location": geo_location},
        dry_run=dry_run,
    )


def scrape_as_markdown(url: str, dry_run: bool = True) -> dict[str, Any]:
    if not re.fullmatch(r"https?://[^\\s]+", (url or "").strip()):
        return {"ok": False, "error": "url_invalid"}
    return mcp_call_tool("scrape_as_markdown", {"url": url.strip()}, dry_run=dry_run)

