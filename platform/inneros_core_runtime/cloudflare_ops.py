"""Cloudflare DNS + túnel + WAF para subdominios pcdoctor.ai (AG-44)."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from raphiia_openai.settings import (
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_TUNNEL_CONFIG,
    CLOUDFLARE_TUNNEL_HOST,
    CLOUDFLARE_TUNNEL_ID,
    CLOUDFLARE_TUNNEL_SERVICE,
    CLOUDFLARE_ZONE_ID,
    CLOUDFLARE_ZONE_NAME,
    RALFIA_INTEL_HOST,
)

DEFAULT_TUNNEL_CNAME = f"{CLOUDFLARE_TUNNEL_ID}.cfargotunnel.com"
CERT_PEM = Path.home() / ".cloudflared" / "cert.pem"
TOKEN_FILE = Path.home() / ".config" / "ralfia" / "cloudflare.env"


def _read_cert_pem_text(host: str | None = None) -> str | None:
    if CERT_PEM.is_file():
        return CERT_PEM.read_text(encoding="utf-8", errors="replace")
    remote_host = (host or CLOUDFLARE_TUNNEL_HOST or "").strip()
    if not remote_host or remote_host in {"127.0.0.1", "localhost"}:
        return None
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            f"rlopez@{remote_host}",
            f"cat {CERT_PEM}",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if proc.returncode == 0 and "ARGO TUNNEL TOKEN" in (proc.stdout or ""):
        return proc.stdout
    return None


def _decode_tunnel_cert_token(host: str | None = None) -> dict[str, str] | None:
    text = _read_cert_pem_text(host)
    if not text:
        return None
    match = re.search(
        r"-----BEGIN ARGO TUNNEL TOKEN-----\n(.+?)\n-----END ARGO TUNNEL TOKEN-----",
        text,
        re.S,
    )
    if not match:
        return None
    compact = re.sub(r"\s+", "", match.group(1))
    compact += "=" * (-len(compact) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(compact))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


@dataclass
class CloudflareCredentials:
    api_token: str
    zone_id: str
    source: str
    dns: bool = True
    waf: bool = False


def load_credentials() -> CloudflareCredentials | None:
    token = (CLOUDFLARE_API_TOKEN or "").strip()
    zone_id = (CLOUDFLARE_ZONE_ID or "").strip()
    source = "env"
    waf_capable = False

    if not token and TOKEN_FILE.is_file():
        for line in TOKEN_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "CLOUDFLARE_API_TOKEN" and value.strip():
                token = value.strip().strip('"').strip("'")
                source = str(TOKEN_FILE)
            elif key.strip() == "CLOUDFLARE_ZONE_ID" and value.strip() and not zone_id:
                zone_id = value.strip().strip('"').strip("'")

    if not token:
        payload = _decode_tunnel_cert_token(CLOUDFLARE_TUNNEL_HOST)
        if payload and payload.get("apiToken"):
            token = str(payload["apiToken"])
            zone_id = zone_id or str(payload.get("zoneID") or "")
            source = "cloudflared_cert_dns_only"

    if not token:
        return None

    if token and not waf_capable:
        waf_capable = _token_can_waf(token, zone_id)

    if token and not zone_id:
        zone_id = _resolve_zone_id(token, CLOUDFLARE_ZONE_NAME) or ""

    if not zone_id:
        return None

    return CloudflareCredentials(
        api_token=token,
        zone_id=zone_id,
        source=source,
        dns=True,
        waf=waf_capable,
    )


def _cf_request(
    creds: CloudflareCredentials,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {creds.api_token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"errors": [{"message": raw[:300]}]}
        parsed["ok"] = False
        parsed["http_status"] = exc.code
        return parsed


def _resolve_zone_id(token: str, zone_name: str) -> str | None:
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/zones?name={zone_name}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    results = data.get("result") or []
    return results[0]["id"] if results else None


def _token_can_waf(token: str, zone_id: str) -> bool:
    if not zone_id:
        return False
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        return bool(data.get("success"))
    except urllib.error.HTTPError:
        return False


def cloudflare_status() -> dict[str, Any]:
    creds = load_credentials()
    if not creds:
        return {
            "ok": False,
            "error": "credentials_missing",
            "hint": "Configura CLOUDFLARE_API_TOKEN en platform/.env o ~/.config/ralfia/cloudflare.env",
            "zone": CLOUDFLARE_ZONE_NAME,
            "tunnel_id": CLOUDFLARE_TUNNEL_ID,
            "tunnel_host": CLOUDFLARE_TUNNEL_HOST,
        }

    verify = _cf_request(creds, "GET", "/user/tokens/verify")
    zones = _cf_request(creds, "GET", f"/zones/{creds.zone_id}")
    return {
        "ok": bool(verify.get("success")),
        "credentials_source": creds.source,
        "token_active": verify.get("result", {}).get("status") == "active",
        "zone_name": zones.get("result", {}).get("name", CLOUDFLARE_ZONE_NAME),
        "zone_id_prefix": creds.zone_id[:8],
        "capabilities": {"dns": creds.dns, "waf": creds.waf},
        "tunnel_id": CLOUDFLARE_TUNNEL_ID,
        "tunnel_host": CLOUDFLARE_TUNNEL_HOST,
        "tunnel_config": CLOUDFLARE_TUNNEL_CONFIG,
        "mcp_tool": "cloudflare_provision_subdomain(subdomain, service, ...)",
    }


def _normalize_hostname(subdomain: str, zone: str = CLOUDFLARE_ZONE_NAME) -> str:
    host = (subdomain or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("subdomain_required")
    if host.endswith(f".{zone}"):
        return host
    if "." in host:
        return host
    return f"{host}.{zone}"


def _dns_record(creds: CloudflareCredentials, hostname: str) -> dict[str, Any] | None:
    out = _cf_request(creds, "GET", f"/zones/{creds.zone_id}/dns_records?name={hostname}")
    rows = out.get("result") or []
    return rows[0] if rows else None


def ensure_dns_cname(
    hostname: str,
    *,
    tunnel_id: str = CLOUDFLARE_TUNNEL_ID,
    proxied: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    creds = load_credentials()
    if not creds:
        return {"ok": False, "error": "credentials_missing"}
    hostname = _normalize_hostname(hostname)
    target = f"{tunnel_id}.cfargotunnel.com"
    existing = _dns_record(creds, hostname)
    body = {
        "type": "CNAME",
        "name": hostname.split(f".{CLOUDFLARE_ZONE_NAME}")[0],
        "content": target,
        "proxied": proxied,
        "ttl": 1,
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "action": "upsert_dns", "hostname": hostname, "content": target}
    if existing:
        updated = _cf_request(
            creds,
            "PUT",
            f"/zones/{creds.zone_id}/dns_records/{existing['id']}",
            body,
        )
        return {
            "ok": bool(updated.get("success")),
            "action": "updated",
            "hostname": hostname,
            "content": target,
            "proxied": proxied,
            "errors": updated.get("errors"),
        }
    created = _cf_request(creds, "POST", f"/zones/{creds.zone_id}/dns_records", body)
    return {
        "ok": bool(created.get("success")),
        "action": "created",
        "hostname": hostname,
        "content": target,
        "proxied": proxied,
        "errors": created.get("errors"),
    }


def ensure_waf_skip(hostname: str, *, dry_run: bool = False) -> dict[str, Any]:
    creds = load_credentials()
    if not creds:
        return {"ok": False, "error": "credentials_missing"}
    if not creds.waf:
        return {
            "ok": False,
            "error": "waf_token_required",
            "hint": "CLOUDFLARE_API_TOKEN necesita permiso Zone.WAF Edit (el token del túnel solo sirve DNS)",
        }
    hostname = _normalize_hostname(hostname)
    expression = f'(http.host eq "{hostname}")'
    if dry_run:
        return {"ok": True, "dry_run": True, "action": "waf_skip", "expression": expression}

    entry = _cf_request(
        creds,
        "GET",
        f"/zones/{creds.zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint",
    )
    ruleset_id = (entry.get("result") or {}).get("id")
    if not ruleset_id:
        return {"ok": False, "error": "ruleset_entrypoint_missing", "response": entry}

    rules = (entry.get("result") or {}).get("rules") or []
    for rule in rules:
        if rule.get("expression") == expression and rule.get("action") == "skip":
            return {"ok": True, "action": "exists", "hostname": hostname}

    added = _cf_request(
        creds,
        "POST",
        f"/zones/{creds.zone_id}/rulesets/{ruleset_id}/rules",
        {
            "action": "skip",
            "action_parameters": {"ruleset": "current"},
            "expression": expression,
            "description": f"Auto skip WAF for {hostname}",
            "enabled": True,
        },
    )
    return {
        "ok": bool(added.get("success")),
        "action": "created",
        "hostname": hostname,
        "errors": added.get("errors"),
    }


def ensure_tunnel_ingress(
    hostname: str,
    service: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    hostname = _normalize_hostname(hostname)
    service = (service or "").strip()
    if not service:
        return {"ok": False, "error": "service_required"}

    remote_host = CLOUDFLARE_TUNNEL_HOST
    config_path = CLOUDFLARE_TUNNEL_CONFIG
    snippet = f"  - hostname: {hostname}\n    service: {service}\n"

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "action": "tunnel_ingress",
            "hostname": hostname,
            "service": service,
            "host": remote_host,
            "config": config_path,
        }

    py = f"""
from pathlib import Path
import re
p = Path({config_path!r})
text = p.read_text()
hostname = {hostname!r}
service = {service!r}
snippet = f"  - hostname: {{hostname}}\\n    service: {{service}}\\n"
pattern = rf"  - hostname: {{re.escape(hostname)}}\\n    service: [^\\n]+\\n"
if re.search(pattern, text):
    text = re.sub(pattern, snippet, text, count=1)
    action = "updated"
elif f"  - hostname: {{hostname}}\\n" in text:
    text = text.replace(f"  - hostname: {{hostname}}\\n", snippet, 1)
    action = "updated"
else:
    marker = "  - service: http_status:404\\n"
    if marker not in text:
        raise SystemExit("catch_all_missing")
    text = text.replace(marker, snippet + marker, 1)
    action = "inserted"
backup = p.with_suffix(".yml.bak-auto")
backup.write_text(p.read_text())
p.write_text(text)
print(action)
"""
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        f"rlopez@{remote_host}",
        f"python3 - <<'PY'\n{py}\nPY",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ssh_timeout", "host": remote_host}
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": "tunnel_config_update_failed",
            "stderr": (proc.stderr or proc.stdout or "")[:500],
        }

    restart = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            f"rlopez@{remote_host}",
            f"systemctl --user restart {CLOUDFLARE_TUNNEL_SERVICE} && systemctl --user is-active {CLOUDFLARE_TUNNEL_SERVICE}",
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    return {
        "ok": restart.returncode == 0,
        "action": (proc.stdout or "").strip() or "updated",
        "hostname": hostname,
        "service": service,
        "tunnel_service": CLOUDFLARE_TUNNEL_SERVICE,
        "tunnel_active": restart.stdout.strip() if restart.returncode == 0 else "",
        "stderr": (restart.stderr or "")[:300] if restart.returncode != 0 else "",
    }


def verify_subdomain(hostname: str) -> dict[str, Any]:
    hostname = _normalize_hostname(hostname)
    dns_cmd = subprocess.run(
        ["dig", "+short", hostname, "@1.1.1.1"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    ips = [line.strip() for line in (dns_cmd.stdout or "").splitlines() if line.strip()]
    curl = subprocess.run(
        ["curl", "-sI", "--max-time", "25", f"https://{hostname}/"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    status_line = ""
    headers: dict[str, str] = {}
    for line in (curl.stdout or "").splitlines():
        if line.startswith("HTTP/"):
            status_line = line.strip()
        elif ":" in line:
            key, _, val = line.partition(":")
            headers[key.strip().lower()] = val.strip()
    http_code = 0
    if status_line:
        parts = status_line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            http_code = int(parts[1])
    tls_ok = bool(ips) and http_code > 0
    return {
        "hostname": hostname,
        "dns": "PASS" if ips else "FAIL",
        "dns_ips": ips[:4],
        "tls": "PASS" if tls_ok else "FAIL",
        "http_status": http_code,
        "http": "PASS" if http_code == 200 else "FAIL",
        "cf_mitigated": headers.get("cf-mitigated", ""),
        "server": headers.get("server", ""),
        "x_powered_by": headers.get("x-powered-by", ""),
    }


def provision_subdomain(
    subdomain: str,
    service: str,
    *,
    waf_skip: bool = True,
    proxied: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Crea/actualiza subdominio pcdoctor.ai: DNS + túnel + WAF skip + verificación."""
    hostname = _normalize_hostname(subdomain)
    steps: list[dict[str, Any]] = []

    dns = ensure_dns_cname(hostname, proxied=proxied, dry_run=dry_run)
    steps.append({"step": "dns", **dns})
    if not dns.get("ok"):
        return {"ok": False, "hostname": hostname, "steps": steps}

    tunnel = ensure_tunnel_ingress(hostname, service, dry_run=dry_run)
    steps.append({"step": "tunnel_ingress", **tunnel})
    if not tunnel.get("ok"):
        return {"ok": False, "hostname": hostname, "steps": steps}

    if waf_skip:
        waf = ensure_waf_skip(hostname, dry_run=dry_run)
        steps.append({"step": "waf_skip", **waf})
        if not waf.get("ok") and waf.get("error") != "waf_token_required":
            return {"ok": False, "hostname": hostname, "steps": steps}

    verify: dict[str, Any] = {"step": "verify", "skipped": dry_run}
    if not dry_run:
        verify = {"step": "verify", **verify_subdomain(hostname)}
        steps.append(verify)

    http_ok = verify.get("http") == "PASS" or verify.get("skipped")
    waf_step = next((s for s in steps if s.get("step") == "waf_skip"), {})
    waf_ok = waf_step.get("ok", True) or waf_step.get("error") == "waf_token_required"
    ok = bool(http_ok and all(s.get("ok", False) for s in steps if s.get("step") in ("dns", "tunnel_ingress")))

    next_hint = None
    if not http_ok and verify.get("cf_mitigated") == "challenge":
        next_hint = (
            "Configura CLOUDFLARE_API_TOKEN con WAF Edit en "
            "~/.config/ralfia/cloudflare.env y reintenta cloudflare_provision_subdomain"
        )
    elif not ok:
        next_hint = "Revisa steps[] para el fallo concreto"

    return {
        "ok": ok and http_ok,
        "hostname": hostname,
        "url": f"https://{hostname}/",
        "service": service,
        "steps": steps,
        "next": next_hint,
    }
