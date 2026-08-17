"""Typed, allowlisted multi-node service operations for WhatsApp maintenance."""

from __future__ import annotations

import hashlib
import json
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from raphiia_openai.notifications import settings as notification_settings

UP_STATES = frozenset({"active", "up", "open", "unauthorized_alive"})
NODE_HOSTS = {"primary": "192.168.1.4", "amd": "192.168.1.5"}
NODE_LABELS = {"primary": ".4", "amd": ".5"}
SSH_TARGETS = {"primary": "rlopez@192.168.1.4", "amd": "ralfiia-amd"}
SSH_IDENTITY_FILE = "/home/rlopez/.ssh/ralfia_peer_ops_ed25519"
_SECRET_RE = re.compile(r"(?i)(token|password|secret|apikey|api_key|authorization|cookie)\s*[=:]\s*\S+")


@dataclass(frozen=True)
class ServiceSpec:
    service_id: str
    label: str
    aliases: tuple[str, ...]
    kind: str
    unit_primary: str | None = None
    unit_amd: str | None = None
    container_primary: str | None = None
    container_amd: str | None = None
    port: int | None = None
    health_path: str | None = None

    def unit(self, node: str) -> str | None:
        return self.unit_amd if node == "amd" else self.unit_primary

    def container(self, node: str) -> str | None:
        return self.container_amd if node == "amd" else self.container_primary


SERVICES: tuple[ServiceSpec, ...] = (
    ServiceSpec("portal", "Panel de Control", ("portal", "panel", "panel de control"), "user", "ralfia-portal.service", "ralfia-portal.service", port=2002, health_path="/api/ops/health"),
    ServiceSpec("mcp", "Conector MCP", ("mcp", "conector", "conector mcp"), "user", "ralfia-mcp.service", "ralfia-mcp.service", port=8102),
    ServiceSpec("app", "RalfIA App", ("app", "ralfia app", "aplicacion", "aplicación"), "user", "ralfia-app.service", "ralfia-app.service", port=8101, health_path="/status"),
    ServiceSpec("coordination", "Coordinación", ("coordinacion", "coordinación", "ag-25"), "user", "ralfia-coordination-daemon.service", "ralfia-coordination-daemon.service"),
    ServiceSpec("whatsapp", "Worker WhatsApp", ("whatsapp", "worker whatsapp", "ralfia whatsapp"), "user", "whatsapp-automation.service", None),
    ServiceSpec("evolution", "Evolution API", ("evolution", "evolution api", "linea whatsapp", "línea whatsapp"), "docker", container_primary="evolution_api", container_amd="evolution_api_amd", port=8082),
)

SERVICE_BY_ID = {service.service_id: service for service in SERVICES}


def normalize_node(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text in {"amd", "backup", "5", ".5", "1.5", "192.168.1.5"}:
        return "amd"
    return "primary"


def node_from_text(text: str, default: str = "primary") -> str:
    lowered = (text or "").lower()
    if re.search(r"(?:servidor\s*(?:5|\.5|1\.5)\b|(?:\.5|1\.5|192\.168\.1\.5|amd|backup)\b)", lowered):
        return "amd"
    if re.search(r"(?:servidor\s*(?:4|\.4|1\.4)\b|(?:\.4|1\.4|192\.168\.1\.4|principal)\b)", lowered):
        return "primary"
    return normalize_node(default)


def service_from_text(text: str) -> ServiceSpec | None:
    lowered = re.sub(r"\s+", " ", (text or "").lower()).strip()
    matches: list[tuple[int, ServiceSpec]] = []
    for service in SERVICES:
        for alias in service.aliases:
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                matches.append((len(alias), service))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def _local_node() -> str:
    hostname = socket.gethostname().lower()
    return "amd" if "amd" in hostname else "primary"


def _run_node(node: str, args: list[str], *, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    node = normalize_node(node)
    if node == _local_node():
        command = args
    else:
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "IdentitiesOnly=yes",
            "-i",
            SSH_IDENTITY_FILE,
            SSH_TARGETS[node],
            *args,
        ]
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def _tcp_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_state(node: str, port: int, path: str) -> str:
    try:
        request = urllib.request.Request(
            f"http://{NODE_HOSTS[node]}:{port}{path}",
            headers={"User-Agent": "RalfIA-SafeOps/1.0"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return "up" if 200 <= response.status < 400 else "degraded"
    except urllib.error.HTTPError as exc:
        return "unauthorized_alive" if exc.code in {401, 403, 406} else "down"
    except Exception:
        return "down"


def node_reachable(node: str) -> bool:
    return _tcp_open(NODE_HOSTS[normalize_node(node)], 22, timeout=2.5)


def _evolution_health(node: str) -> str:
    """Probe the canonical node address, independent from each host's localhost config."""
    node = normalize_node(node)
    instance = (
        notification_settings.EVOLUTION_AMD_INSTANCE
        if node == "amd"
        else notification_settings.EVOLUTION_INSTANCE
    )
    api_key = notification_settings.EVOLUTION_API_KEY
    if not instance or not api_key:
        try:
            response = httpx.get(f"http://{NODE_HOSTS[node]}:8082/", timeout=5.0)
            return "unauthorized_alive" if response.status_code < 500 else "down"
        except Exception:
            return "down"
    try:
        response = httpx.get(
            f"http://{NODE_HOSTS[node]}:8082/instance/connectionState/{instance}",
            headers={"apikey": api_key},
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
        inst = payload.get("instance") if isinstance(payload.get("instance"), dict) else payload
        state = str(
            (inst or {}).get("state")
            or (inst or {}).get("connectionStatus")
            or payload.get("state")
            or payload.get("connectionStatus")
            or ""
        ).lower()
        return "up" if state == "open" else "down"
    except Exception:
        return "down"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_ref(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"health:{hashlib.sha256(encoded).hexdigest()[:24]}"


def service_status(
    service_id: str,
    node: str,
    *,
    checked_at: str | None = None,
    evidence_ref: str | None = None,
) -> dict[str, Any]:
    node = normalize_node(node)
    spec = SERVICE_BY_ID.get(service_id)
    if not spec:
        return {"ok": False, "error": "service_not_allowlisted"}
    if spec.kind == "user":
        unit = spec.unit(node)
        if not unit:
            return {"ok": False, "error": "service_not_available_on_node", "service_id": service_id, "node": node}
        proc = _run_node(node, ["systemctl", "--user", "is-active", unit], timeout=15)
        system_state = (proc.stdout or proc.stderr or "unknown").strip().splitlines()[0][:40]
    else:
        container = spec.container(node)
        if not container:
            return {"ok": False, "error": "service_not_available_on_node", "service_id": service_id, "node": node}
        proc = _run_node(node, ["docker", "inspect", "-f", "{{.State.Running}}", container], timeout=15)
        system_state = "active" if proc.returncode == 0 and proc.stdout.strip() == "true" else "inactive"
    remote_telemetry_unavailable = node != _local_node() and proc.returncode != 0
    if remote_telemetry_unavailable:
        system_state = "unknown"
    if service_id == "evolution":
        health = _evolution_health(node)
    elif spec.port and spec.health_path:
        health = _http_state(node, spec.port, spec.health_path)
    elif spec.port:
        health = "up" if _tcp_open(NODE_HOSTS[node], spec.port) else "down"
    elif remote_telemetry_unavailable:
        health = "unknown"
    else:
        health = "up" if system_state == "active" else "down"
    externally_healthy = health in UP_STATES and (system_state == "active" or remote_telemetry_unavailable)
    confidence = "low" if health == "unknown" else (
        "medium" if health == "unauthorized_alive" or remote_telemetry_unavailable else "high"
    )
    health_basis = (
        "http_root_no_connection_auth"
        if service_id == "evolution" and health == "unauthorized_alive"
        else ("external_probe" if remote_telemetry_unavailable else "system_and_health_probe")
    )
    checked_at = checked_at or _now()
    result = {
        "ok": not (remote_telemetry_unavailable and health == "unknown"),
        "node": node,
        "node_label": NODE_LABELS[node],
        "target_host": NODE_HOSTS[node],
        "service_id": service_id,
        "label": spec.label,
        "system_state": system_state,
        "health": health,
        "healthy": externally_healthy,
        "telemetry": "remote_unavailable" if remote_telemetry_unavailable else "full",
        "confidence": confidence,
        "health_basis": health_basis,
        "checked_at": checked_at,
        "source": "whatsapp_service_ops.service_status",
    }
    result["evidence_ref"] = evidence_ref or _evidence_ref(
        {
            key: result.get(key)
            for key in (
                "target_host", "service_id", "system_state", "health", "confidence",
                "health_basis", "checked_at", "source",
            )
        }
    )
    return result


def status_snapshot(node: str | None = None) -> dict[str, Any]:
    nodes = [normalize_node(node)] if node else ["primary", "amd"]
    checked_at = _now()
    items: list[dict[str, Any]] = []
    for current in nodes:
        for spec in SERVICES:
            if not spec.unit(current) and not spec.container(current):
                continue
            items.append(service_status(spec.service_id, current, checked_at=checked_at))
    hosts = [
        {
            "node": current,
            "node_label": NODE_LABELS[current],
            "target_host": NODE_HOSTS[current],
            "reachable": node_reachable(current),
            "checked_at": checked_at,
            "source": "whatsapp_service_ops.node_reachable",
        }
        for current in nodes
    ]
    evidence_ref = _evidence_ref(
        {
            "checked_at": checked_at,
            "nodes": nodes,
            "hosts": [{"node": x["node"], "reachable": x["reachable"]} for x in hosts],
            "items": [
                {
                    key: item.get(key)
                    for key in (
                        "node", "target_host", "service_id", "system_state", "health",
                        "healthy", "confidence", "health_basis",
                    )
                }
                for item in items
            ],
        }
    )
    for item in items:
        item["evidence_ref"] = evidence_ref
    for host in hosts:
        host["evidence_ref"] = evidence_ref
    return {
        "ok": all(item.get("healthy") for item in items if item.get("ok")),
        "nodes": nodes,
        "hosts": hosts,
        "items": items,
        "checked_at": checked_at,
        "source": "whatsapp_service_ops.status_snapshot",
        "evidence_ref": evidence_ref,
        "tool_call_id": f"health_{evidence_ref.split(':', 1)[1]}",
        "canonical": True,
    }


def format_status_text(node: str | None = None, *, snapshot: dict[str, Any] | None = None) -> str:
    snapshot = snapshot or status_snapshot(node)
    wa_conn: dict[str, bool] = {}
    try:
        from raphiia_openai.notifications.evolution_client import dual_whatsapp_status

        for node_key, info in (dual_whatsapp_status() or {}).items():
            wa_conn[node_key] = bool(info.get("connected"))
    except Exception:
        pass
    lines = ["*RalfIA · Estado verificado de servidores*", ""]
    for current in snapshot["nodes"]:
        host = next((item for item in snapshot.get("hosts", []) if item.get("node") == current), {})
        reachable = bool(host.get("reachable"))
        lines.append(f"*Servidor {NODE_LABELS[current]}* — {'🟢 alcanzable' if reachable else '🔴 no alcanzable'}")
        for item in snapshot["items"]:
            if item.get("node") != current:
                continue
            icon = "🟢" if item.get("healthy") else "🔴"
            extra = ""
            if item.get("service_id") == "evolution":
                conn = wa_conn.get(current)
                if conn is True:
                    extra = " · WhatsApp conectado"
                elif conn is False:
                    extra = " · WhatsApp desconectado"
            lines.append(
                f"{icon} {item.get('label')}: {item.get('system_state')} / {item.get('health')}{extra}"
            )
        lines.append("")
    lines.append(f"Verificado: {snapshot.get('checked_at', '?')} · evidencia {snapshot.get('evidence_ref', '?')}")
    unhealthy = [item for item in snapshot.get("items", []) if item.get("ok") and not item.get("healthy")]
    if unhealthy:
        target = unhealthy[0]
        label = str(target.get("label") or target.get("service_id") or "servicio")
        node_label = str(target.get("node_label") or NODE_LABELS.get(target.get("node"), ".4"))
        lines.append(
            f"Siguiente paso seguro: “diagnostica {label} en {node_label}”. "
            f"Solo si luego quieres intervenir: “recupera {label} en {node_label}” (pedirá confirmación)."
        )
    else:
        lines.append("No se recomienda reiniciar ni recuperar ningún servicio con esta comprobación.")
    return "\n".join(lines).strip()


def sanitize_log(text: str) -> str:
    cleaned = _SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text or "")
    return cleaned[-3000:]


def recent_logs(service_id: str, node: str, lines: int = 20) -> dict[str, Any]:
    node = normalize_node(node)
    spec = SERVICE_BY_ID.get(service_id)
    if not spec:
        return {"ok": False, "error": "service_not_allowlisted"}
    limit = max(5, min(int(lines), 50))
    if spec.kind == "user" and spec.unit(node):
        args = ["journalctl", "--user", "-u", spec.unit(node) or "", "-n", str(limit), "--no-pager"]
    elif spec.kind == "docker" and spec.container(node):
        args = ["docker", "logs", "--tail", str(limit), spec.container(node) or ""]
    else:
        return {"ok": False, "error": "service_not_available_on_node"}
    proc = _run_node(node, args, timeout=20)
    return {
        "ok": proc.returncode == 0,
        "service_id": service_id,
        "node": node,
        "logs": sanitize_log((proc.stdout or "") + "\n" + (proc.stderr or "")),
    }


def execute_service_action(service_id: str, node: str, action: str) -> dict[str, Any]:
    node = normalize_node(node)
    action = (action or "").strip().lower()
    if action not in {"start", "restart", "recover"}:
        return {"ok": False, "error": "action_not_allowlisted"}
    spec = SERVICE_BY_ID.get(service_id)
    if not spec:
        return {"ok": False, "error": "service_not_allowlisted"}
    before = service_status(service_id, node)
    if action in {"start", "recover"} and before.get("healthy"):
        return {"ok": True, "skipped": True, "reason": "already_healthy", "before": before, "after": before}
    effective_action = "start" if action == "start" or before.get("system_state") != "active" else "restart"
    if spec.kind == "user":
        unit = spec.unit(node)
        if not unit:
            return {"ok": False, "error": "service_not_available_on_node"}
        args = ["systemctl", "--user", effective_action, unit]
    else:
        container = spec.container(node)
        if not container:
            return {"ok": False, "error": "service_not_available_on_node"}
        # Docker has no idempotent start+restart abstraction; both remain fixed allowlisted calls.
        args = ["docker", "start" if effective_action == "start" else "restart", container]
    proc = _run_node(node, args, timeout=45)
    time.sleep(2.0)
    after = service_status(service_id, node)
    return {
        "ok": proc.returncode == 0 and bool(after.get("healthy")),
        "service_id": service_id,
        "node": node,
        "requested_action": action,
        "effective_action": effective_action,
        "before": before,
        "after": after,
        "returncode": proc.returncode,
        "stderr": sanitize_log(proc.stderr or "")[:500],
    }
