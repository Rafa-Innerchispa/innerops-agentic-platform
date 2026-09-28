"""AG-41 Peer Ops Executor — mutaciones allowlisted en nodos .4/.5 vía MCP."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from raphiia_openai.agent_auto_log import record_agent_run
from raphiia_openai.notifications import whatsapp_service_ops

AGENT_ID = "AG-41_PEER_OPS_EXECUTOR"

ALLOWLIST_SERVICES = tuple(sorted(whatsapp_service_ops.SERVICE_BY_ID.keys()))
ALLOWLIST_ACTIONS = frozenset({"start", "restart", "recover"})
# Servicios que normalmente corren solo en Intel — down en AMD no es incidente
INTEL_ONLY_SERVICES = frozenset({"portal", "app", "whatsapp"})
WIFI_SECRET_DIR = "/home/rlopez/inneros/inneros_core/var/peer_wifi_credentials"
NODE_HELPER = "/home/rlopez/bin/ralfia-peer-node-helper"
WIFI_HELPER = NODE_HELPER
WIFI_APPLY_ENV = "RALFIA_PEER_WIFI_APPLY_ENABLED"
WIFI_MUTATION_TOOLS = frozenset({"connect", "disconnect", "forget", "secret_store"})
DENIED_INTERFACE_PREFIXES = ("en", "eth", "br", "docker", "veth", "tun", "tap", "wg", "tailscale", "zt", "lo")
PACKAGE_MUTATION_TOOLS = frozenset({"peer_package_install", "peer_package_remove"})
ALLOWED_PEER_PACKAGES = (
    "network-manager",
    "iw",
    "wireless-tools",
    "wpasupplicant",
    "rfkill",
    "python3-venv",
    "python3-pip",
    "python3-dev",
    "build-essential",
    "git",
)


def _node_registry() -> dict[str, Any]:
    return {
        "primary": {"node": "primary", "role": "primary/intel", "host": "192.168.1.4", "peer_ops": "operative"},
        "amd": {"node": "amd", "role": "secondary/amd", "host": "192.168.1.5", "peer_ops": "operative"},
    }


def _redact(text: str) -> str:
    return re.sub(r"(?i)(psk|password|secret|token|key)\s*[:=]\s*\S+", r"\1=[REDACTED]", text or "")


def _run_node(node: str, args: list[str], *, timeout: int = 30, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    node = whatsapp_service_ops.normalize_node(node)
    if node == whatsapp_service_ops._local_node():
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
            whatsapp_service_ops.SSH_IDENTITY_FILE,
            whatsapp_service_ops.SSH_TARGETS[node],
            *args,
        ]
    return subprocess.run(command, input=input_text, capture_output=True, text=True, timeout=timeout, check=False)


def _safe_proc(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": _redact((proc.stdout or "")[:12000]),
        "stderr": _redact((proc.stderr or "")[:12000]),
    }


def _helper(node: str, action: str, payload: dict[str, Any] | None = None, timeout: int = 45) -> dict[str, Any]:
    proc = _run_node(node, [NODE_HELPER, action], timeout=timeout, input_text=json.dumps(payload or {}))
    try:
        result = json.loads(proc.stdout or "{}")
    except Exception:
        result = {"ok": False, "error": "helper_invalid_json", "raw": _safe_proc(proc)}
    if "raw" in result and isinstance(result["raw"], dict):
        result["raw"]["stdout"] = _redact(result["raw"].get("stdout", ""))
        result["raw"]["stderr"] = _redact(result["raw"].get("stderr", ""))
    result.setdefault("helper_returncode", proc.returncode)
    if proc.returncode != 0 and result.get("ok"):
        result["ok"] = False
    return result


def _require_approval(approval_id: str) -> None:
    if not (approval_id or "").strip():
        raise ValueError("approval_id_required")


def _iface_safe(name: str) -> bool:
    value = (name or "").strip()
    if not re.match(r"^[A-Za-z0-9_.:-]{1,64}$", value):
        return False
    lowered = value.lower()
    return not lowered.startswith(DENIED_INTERFACE_PREFIXES)


def _wireless_ifaces_from_sys(node: str) -> set[str]:
    result = _helper(node, "interfaces", timeout=20)
    meta = result.get("meta") if isinstance(result, dict) else {}
    return set((meta or {}).get("wireless_sys") or [])


def _interfaces_raw(node: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = _helper(node, "interfaces", timeout=25)
    return list(result.get("interfaces") or []), dict(result.get("meta") or {"helper": result})


def _assert_wifi_interface(node: str, interface: str) -> dict[str, Any]:
    items, _meta = _interfaces_raw(node)
    for item in items:
        if item.get("interface") == interface:
            if not item.get("wifi_capable") or not item.get("mutation_allowed"):
                raise PermissionError("interface_not_dedicated_wifi_allowlisted")
            return item
    raise PermissionError("wifi_interface_not_found")


def _audit(action: str, payload: dict[str, Any]) -> None:
    clean = {k: v for k, v in payload.items() if k not in {"secret", "psk", "password"}}
    record_agent_run(
        AGENT_ID,
        action=f"peer_wifi_{action}",
        summary=f"peer_wifi_{action} node={clean.get('node')} ok={clean.get('ok')}",
        project="ralfia-peer-ops",
        metadata=clean,
    )


def _audit_peer(action: str, payload: dict[str, Any]) -> None:
    clean = {k: v for k, v in payload.items() if k not in {"secret", "psk", "password", "unit_content"}}
    record_agent_run(
        AGENT_ID,
        action=action,
        summary=f"{action} node={clean.get('node')} ok={clean.get('ok')}",
        project="ralfia-peer-ops",
        metadata=clean,
    )


def _annotate_warm_standby(snap: dict[str, Any]) -> dict[str, Any]:
    notes: list[str] = []
    for item in snap.get("items") or []:
        if item.get("node") == "amd" and item.get("service_id") in INTEL_ONLY_SERVICES and not item.get("healthy"):
            item["warm_standby"] = True
            item["note"] = "Intel-only en warm-standby; down en AMD es esperado"
            notes.append(item.get("service_id", ""))
    if notes:
        snap["warm_standby_amd"] = {
            "intel_only_down_expected": notes,
            "note": "Failover --execute levantaría estos servicios en .5",
        }
    return snap


def list_peer_ops_services() -> dict[str, Any]:
    services = []
    for sid, spec in whatsapp_service_ops.SERVICE_BY_ID.items():
        services.append({
            "service_id": sid,
            "label": spec.label,
            "kind": spec.kind,
            "aliases": list(spec.aliases),
        })
    return {"ok": True, "agent_id": AGENT_ID, "nodes": _node_registry(), "services": services}


def peer_ops_snapshot(node: str | None = None) -> dict[str, Any]:
    snap = whatsapp_service_ops.status_snapshot(node)
    snap = _annotate_warm_standby(snap)
    unhealthy = [
        i for i in (snap.get("items") or [])
        if i.get("ok") and not i.get("healthy") and not i.get("warm_standby")
    ]
    snap["ok"] = len(unhealthy) == 0
    record_agent_run(AGENT_ID, action="peer_ops_snapshot", summary=f"nodes={snap.get('nodes')} ok={snap['ok']}", project="ralfia-ops")
    return {"ok": snap["ok"], "agent_id": AGENT_ID, "node_registry": _node_registry(), **snap}


def peer_ops_status(service_id: str, node: str = "primary") -> dict[str, Any]:
    result = whatsapp_service_ops.service_status(service_id, node)
    return {"ok": bool(result.get("ok", True)), "agent_id": AGENT_ID, **result}


def peer_ops_action(
    service_id: str,
    node: str = "primary",
    action: str = "restart",
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    action = (action or "restart").strip().lower()
    if action not in ALLOWLIST_ACTIONS:
        return {"ok": False, "error": "action_not_allowlisted", "allowed": sorted(ALLOWLIST_ACTIONS)}
    if service_id not in whatsapp_service_ops.SERVICE_BY_ID:
        return {"ok": False, "error": "service_not_allowlisted", "allowed": ALLOWLIST_SERVICES}
    if dry_run:
        before = whatsapp_service_ops.service_status(service_id, node)
        return {
            "ok": True,
            "dry_run": True,
            "agent_id": AGENT_ID,
            "would_execute": {"service_id": service_id, "node": node, "action": action},
            "current": before,
        }
    result = whatsapp_service_ops.execute_service_action(service_id, node, action)
    record_agent_run(
        AGENT_ID,
        action="peer_ops_action",
        summary=f"{service_id}@{node} {action} ok={result.get('ok')}",
        project="ralfia-ops",
        metadata={"service_id": service_id, "node": node, "action": action},
    )
    return {"ok": bool(result.get("ok")), "agent_id": AGENT_ID, **result}


def peer_ops_logs(service_id: str, node: str = "primary", lines: int = 30) -> dict[str, Any]:
    result = whatsapp_service_ops.recent_logs(service_id, node, lines=max(1, min(lines, 50)))
    return {"ok": bool(result.get("ok", True)), "agent_id": AGENT_ID, **result}


def peer_net_interfaces(node: str = "amd") -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    items, meta = _interfaces_raw(node)
    route = peer_route_check(node)
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "node": node,
        "node_registry": _node_registry(),
        "interfaces": items,
        "route_check": route,
        "meta": meta,
        "security": {
            "ethernet_mutation": "denied",
            "wifi_mutation_requires": ["approval_id", "dedicated wifi interface", "dry_run=false gated"],
        },
    }


def peer_route_check(node: str = "amd") -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    result = _helper(node, "route_check", timeout=20)
    return {
        "ok": bool(result.get("ok")),
        "agent_id": AGENT_ID,
        "node": node,
        "lan_default_route_intact": bool(result.get("lan_default_route_intact")),
        "default_routes": result.get("default_routes") or [],
        "raw": result.get("raw") or result,
    }



def _validate_network_probe_target(target: str, networks: list[ipaddress._BaseNetwork]) -> str:
    raw = (target or "").strip()
    if not raw:
        raise ValueError("empty_network_probe_target")
    try:
        address = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise ValueError("network_probe_requires_ip_literal") from exc
    if address.version != 4:
        raise ValueError("network_probe_ipv4_only")
    if not any(address in network for network in networks):
        raise PermissionError("network_probe_target_out_of_scope")
    return str(address)


def _network_probe_scope(
    project_id: str,
    node: str,
) -> tuple[list[ipaddress._BaseNetwork], tuple[str, ...], dict[str, Any]]:
    """Load read-only network scope from the private project runtime config."""
    project_key = (project_id or "").strip()
    if not project_key:
        raise ValueError("project_id_required_for_network_probe")

    from raphiia_openai import project_runtime_registry as prr

    resolved = prr.resolve_project(project_id=project_key, node=node)
    project_path = Path(str(resolved.get("project_path") or "")).expanduser().resolve()
    if not str(project_path):
        raise FileNotFoundError("network_probe_project_path_missing")

    config_path = (project_path / "config" / "site.json").resolve()
    if project_path != config_path and project_path not in config_path.parents:
        raise PermissionError("network_probe_config_path_outside_project")
    if not config_path.is_file():
        raise FileNotFoundError("network_probe_site_config_missing")

    try:
        spec = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("network_probe_site_config_invalid") from exc

    cidrs = list(spec.get("authorized_subnets") or [])
    if not cidrs:
        raise PermissionError("network_probe_no_authorized_subnets")

    networks: list[ipaddress._BaseNetwork] = []
    for cidr in cidrs:
        try:
            network = ipaddress.ip_network(str(cidr), strict=True)
        except ValueError as exc:
            raise ValueError("network_probe_invalid_authorized_subnet") from exc
        if network.version != 4:
            raise ValueError("network_probe_ipv4_only")
        if not network.is_private or network.prefixlen < 16:
            raise PermissionError("network_probe_subnet_not_private_or_too_broad")
        networks.append(network)

    raw_sentinels = spec.get("diagnostic_sentinels") or {}
    sentinels: list[str] = []
    if isinstance(raw_sentinels, dict):
        for values in raw_sentinels.values():
            if isinstance(values, str):
                sentinels.append(values)
            elif isinstance(values, list):
                sentinels.extend(str(item) for item in values)
    elif isinstance(raw_sentinels, list):
        sentinels.extend(str(item) for item in raw_sentinels)

    normalized_sentinels = tuple(
        _validate_network_probe_target(item, networks)
        for item in sentinels
    )
    return networks, normalized_sentinels, {
        "project_id": project_key,
        "project_path": str(project_path),
        "site_id": spec.get("site_id") or project_key,
    }


def _parse_ping_output(stdout: str) -> dict[str, Any]:
    text = stdout or ""
    packet = re.search(
        r"(\d+) packets transmitted,\s*(\d+) (?:packets )?received,.*?([\d.]+)% packet loss",
        text,
        re.S,
    )
    rtt = re.search(
        r"(?:rtt|round-trip) min/avg/max/(?:mdev|stddev) = "
        r"([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms",
        text,
    )
    result: dict[str, Any] = {
        "transmitted": 0,
        "received": 0,
        "packet_loss_percent": 100.0,
        "rtt_ms": None,
    }
    if packet:
        result.update(
            {
                "transmitted": int(packet.group(1)),
                "received": int(packet.group(2)),
                "packet_loss_percent": float(packet.group(3)),
            }
        )
    if rtt:
        result["rtt_ms"] = {
            "min": float(rtt.group(1)),
            "avg": float(rtt.group(2)),
            "max": float(rtt.group(3)),
            "mdev": float(rtt.group(4)),
        }
    return result


def peer_network_path_probe(
    project_id: str,
    targets: list[str] | str | None = None,
    node: str = "primary",
    count: int = 3,
    timeout_seconds: int = 1,
) -> dict[str, Any]:
    """Read-only ICMP/route probe constrained by a private project's site config."""
    node = whatsapp_service_ops.normalize_node(node)
    networks, default_sentinels, project_meta = _network_probe_scope(project_id, node)
    requested = targets if targets is not None else list(default_sentinels)
    if isinstance(requested, str):
        requested = [part.strip() for part in requested.split(",") if part.strip()]
    requested = list(requested or [])
    if not requested:
        return {
            "ok": False,
            "error": "network_probe_targets_required",
            "project_id": project_meta["project_id"],
        }
    if len(requested) > 32:
        return {"ok": False, "error": "network_probe_target_limit", "max_targets": 32}

    count = max(1, min(int(count or 3), 10))
    timeout_seconds = max(1, min(int(timeout_seconds or 1), 5))
    validated = [_validate_network_probe_target(item, networks) for item in requested]

    results: list[dict[str, Any]] = []
    for target in validated:
        route_proc = _run_node(node, ["ip", "route", "get", target], timeout=10)
        ping_proc = _run_node(
            node,
            ["ping", "-n", "-c", str(count), "-W", str(timeout_seconds), target],
            timeout=max(10, count * timeout_seconds + 5),
        )
        parsed = _parse_ping_output(ping_proc.stdout or "")
        reachable = parsed["received"] > 0
        results.append(
            {
                "target": target,
                "reachable": reachable,
                "packet_loss_percent": parsed["packet_loss_percent"],
                "transmitted": parsed["transmitted"],
                "received": parsed["received"],
                "rtt_ms": parsed["rtt_ms"],
                "route": _redact((route_proc.stdout or "").strip())[:1000],
                "route_ok": route_proc.returncode == 0,
                "icmp_returncode": ping_proc.returncode,
                "icmp_error": _redact((ping_proc.stderr or "").strip())[:500] or None,
            }
        )

    reachable_count = sum(1 for item in results if item["reachable"])
    lossy = [item["target"] for item in results if 0 < item["packet_loss_percent"] < 100]
    down = [item["target"] for item in results if not item["reachable"]]
    payload = {
        "ok": True,
        "agent_id": AGENT_ID,
        "project_id": project_meta["project_id"],
        "site_id": project_meta["site_id"],
        "node": node,
        "scope": [str(network) for network in networks],
        "count_per_target": count,
        "timeout_seconds": timeout_seconds,
        "results": results,
        "summary": {
            "targets": len(results),
            "reachable": reachable_count,
            "unreachable": len(results) - reachable_count,
            "lossy_targets": lossy,
            "down_targets": down,
        },
        "security": {
            "read_only": True,
            "ip_literals_only": True,
            "project_runtime_scope_enforced": True,
            "private_subnets_only": True,
            "shell": "not_exposed",
            "mutation": "denied",
        },
    }
    _audit_peer(
        "peer_network_path_probe",
        {
            "ok": True,
            "node": node,
            "project_id": project_meta["project_id"],
            "targets": len(results),
            "reachable": reachable_count,
            "unreachable": len(results) - reachable_count,
        },
    )
    return payload


def peer_wifi_scan(node: str = "amd", interface: str = "") -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    if interface:
        _assert_wifi_interface(node, interface)
    result = _helper(node, "scan", {"interface": interface}, timeout=45)
    return {"ok": bool(result.get("ok")), "agent_id": AGENT_ID, "node": node, "interface": interface or None, "networks": result.get("networks") or [], "raw": result.get("raw") or result}


def peer_wifi_status(node: str = "amd", interface: str = "") -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    if interface:
        _assert_wifi_interface(node, interface)
    result = _helper(node, "status", {"interface": interface}, timeout=25)
    return {"ok": bool(result.get("ok")), "agent_id": AGENT_ID, "node": node, "interface": interface or None, "route_check": result.get("route_check") or peer_route_check(node), "raw": result.get("raw") or result}


def peer_secret_store_wifi(node: str, ssid: str, secret: str, approval_id: str) -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    _require_approval(approval_id)
    if not ssid or not secret:
        return {"ok": False, "error": "ssid_and_secret_required"}
    ref_hash = hashlib.sha256(f"{node}:{ssid}:{approval_id}".encode()).hexdigest()[:16]
    credential_ref = f"wifi:{node}:{ref_hash}"
    payload = json.dumps({"base": WIFI_SECRET_DIR, "credential_ref": credential_ref, "ssid": ssid, "secret": secret})
    result = _helper(node, "secret_store", json.loads(payload), timeout=25)
    ok = bool(result.get("ok"))
    _audit("secret_store", {"ok": ok, "node": node, "ssid_hash": hashlib.sha256(ssid.encode()).hexdigest()[:12], "credential_ref": credential_ref, "approval_id": approval_id})
    return {"ok": ok, "agent_id": AGENT_ID, "node": node, "credential_ref": credential_ref, "ssid": ssid, "secret_stored": ok, "raw": {k: v for k, v in result.items() if k not in {"secret"}}}


def peer_wifi_connect(
    node: str = "amd",
    interface: str = "",
    ssid: str = "",
    credential_ref: str = "",
    approval_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    _require_approval(approval_id)
    iface = _assert_wifi_interface(node, interface)
    before = peer_route_check(node)
    plan = {"node": node, "interface": interface, "ssid": ssid, "credential_ref": credential_ref, "route_before": before}
    if dry_run:
        return {"ok": True, "dry_run": True, "agent_id": AGENT_ID, "would_execute": "nmcli wifi connect on dedicated wifi only", "plan": plan}
    if os.getenv(WIFI_APPLY_ENV, "").lower() not in {"1", "true", "yes"}:
        return {"ok": False, "agent_id": AGENT_ID, "error": "peer_wifi_apply_disabled", "requires_env": WIFI_APPLY_ENV, "plan": plan}
    if not credential_ref.startswith(f"wifi:{node}:"):
        return {"ok": False, "error": "credential_ref_invalid_for_node"}
    result = _helper(node, "connect", {"credential_ref": credential_ref, "ssid": ssid, "interface": interface}, timeout=70)
    after = peer_route_check(node)
    ok = bool(result.get("ok")) and after.get("lan_default_route_intact")
    _audit("connect", {"ok": ok, **plan, "route_after": after, "approval_id": approval_id})
    return {"ok": ok, "agent_id": AGENT_ID, "node": node, "interface": iface, "route_before": before, "route_after": after, "raw": result.get("raw") or result}


def peer_wifi_disconnect(node: str = "amd", interface: str = "", approval_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    _require_approval(approval_id)
    iface = _assert_wifi_interface(node, interface)
    before = peer_route_check(node)
    if dry_run:
        return {"ok": True, "dry_run": True, "agent_id": AGENT_ID, "would_execute": ["nmcli", "device", "disconnect", interface], "interface": iface, "route_before": before}
    if os.getenv(WIFI_APPLY_ENV, "").lower() not in {"1", "true", "yes"}:
        return {"ok": False, "agent_id": AGENT_ID, "error": "peer_wifi_apply_disabled", "requires_env": WIFI_APPLY_ENV}
    result = _helper(node, "disconnect", {"interface": interface}, timeout=45)
    after = peer_route_check(node)
    ok = bool(result.get("ok")) and after.get("lan_default_route_intact")
    _audit("disconnect", {"ok": ok, "node": node, "interface": interface, "approval_id": approval_id, "route_after": after})
    return {"ok": ok, "agent_id": AGENT_ID, "node": node, "interface": iface, "route_before": before, "route_after": after, "raw": result.get("raw") or result}


def peer_wifi_forget(node: str = "amd", connection_id: str = "", approval_id: str = "", dry_run: bool = True) -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    _require_approval(approval_id)
    if not re.match(r"^[A-Za-z0-9_.:@ -]{1,96}$", connection_id or ""):
        return {"ok": False, "error": "invalid_connection_id"}
    before = peer_route_check(node)
    if dry_run:
        return {"ok": True, "dry_run": True, "agent_id": AGENT_ID, "would_execute": ["nmcli", "connection", "delete", connection_id], "route_before": before}
    if os.getenv(WIFI_APPLY_ENV, "").lower() not in {"1", "true", "yes"}:
        return {"ok": False, "agent_id": AGENT_ID, "error": "peer_wifi_apply_disabled", "requires_env": WIFI_APPLY_ENV}
    result = _helper(node, "forget", {"connection_id": connection_id}, timeout=45)
    after = peer_route_check(node)
    ok = bool(result.get("ok")) and after.get("lan_default_route_intact")
    _audit("forget", {"ok": ok, "node": node, "connection_id": connection_id, "approval_id": approval_id, "route_after": after})
    return {"ok": ok, "agent_id": AGENT_ID, "node": node, "route_before": before, "route_after": after, "raw": result.get("raw") or result}


def peer_package_status(node: str = "primary", packages: list[str] | str | None = None) -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    requested = packages or list(ALLOWED_PEER_PACKAGES)
    result = _helper(node, "package_status", {"packages": requested}, timeout=35)
    return {
        "ok": bool(result.get("ok")),
        "agent_id": AGENT_ID,
        "node": node,
        "packages": result.get("packages") or [],
        "allowlist": result.get("allowlist") or list(ALLOWED_PEER_PACKAGES),
        "raw": result.get("raw") or result,
    }


def peer_package_install(
    node: str = "primary",
    packages: list[str] | str | None = None,
    approval_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    _require_approval(approval_id)
    before = peer_route_check(node)
    result = _helper(node, "package_install", {"packages": packages or [], "dry_run": dry_run}, timeout=420)
    after = peer_route_check(node)
    ok = bool(result.get("ok")) and bool(after.get("lan_default_route_intact"))
    _audit_peer("peer_package_install", {"ok": ok, "node": node, "packages": packages, "dry_run": dry_run, "approval_id": approval_id, "route_after": after})
    return {
        "ok": ok,
        "agent_id": AGENT_ID,
        "node": node,
        "dry_run": dry_run,
        "route_before": before,
        "route_after": after,
        "result": result,
        "security": {"apt_arbitrary": "denied", "packages": "allowlist_only", "approval_id_required": True},
    }


def peer_package_remove(
    node: str = "primary",
    packages: list[str] | str | None = None,
    approval_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    _require_approval(approval_id)
    before = peer_route_check(node)
    result = _helper(node, "package_remove", {"packages": packages or [], "dry_run": dry_run}, timeout=420)
    after = peer_route_check(node)
    ok = bool(result.get("ok")) and bool(after.get("lan_default_route_intact"))
    _audit_peer("peer_package_remove", {"ok": ok, "node": node, "packages": packages, "dry_run": dry_run, "approval_id": approval_id, "route_after": after})
    return {
        "ok": ok,
        "agent_id": AGENT_ID,
        "node": node,
        "dry_run": dry_run,
        "route_before": before,
        "route_after": after,
        "result": result,
        "security": {"apt_arbitrary": "denied", "packages": "allowlist_only", "approval_id_required": True},
    }


def peer_hardware_discovery(node: str = "primary") -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    result = _helper(node, "hardware", timeout=45)
    return {"ok": bool(result.get("ok")), "agent_id": AGENT_ID, "node": node, "hardware": result}


def peer_python_runtime(
    node: str = "primary",
    project_path: str = "",
    project_id: str = "",
    repo: str = "",
    action: str = "status",
    requirements: str = "requirements.txt",
    target: str = ".",
    approval_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    resolved_project: dict[str, Any] | None = None
    if project_id or repo:
        from raphiia_openai import project_runtime_registry as prr

        resolved_project = prr.resolve_project(project_id=project_id or repo, repo=repo, node=node)
        project_path = resolved_project["project_path"]
    action = (action or "status").strip().lower()
    if action in {"venv", "pip_install"}:
        _require_approval(approval_id)
    payload = {
        "project_path": project_path,
        "action": action,
        "requirements": requirements,
        "target": target,
        "dry_run": dry_run,
    }
    result = _helper(node, "python_runtime", payload, timeout=700 if action in {"pip_install", "pytest"} else 220)
    _audit_peer("peer_python_runtime", {"ok": bool(result.get("ok")), "node": node, "project_path": project_path, "action": action, "dry_run": dry_run, "approval_id": approval_id or None})
    return {
        "ok": bool(result.get("ok")),
        "agent_id": AGENT_ID,
        "node": node,
        "project_path": project_path,
        "project": resolved_project.get("project") if resolved_project else None,
        "action": action,
        "result": result,
        "security": {"system_python_mutation": "denied", "project_path": "allowlisted_roots_only"},
    }


def peer_user_service(
    node: str = "primary",
    action: str = "status",
    service_name: str = "",
    project_path: str = "",
    project_id: str = "",
    repo: str = "",
    unit_content: str = "",
    approval_id: str = "",
    dry_run: bool = True,
    lines: int = 50,
) -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    resolved_project: dict[str, Any] | None = None
    if project_id or repo:
        from raphiia_openai import project_runtime_registry as prr

        resolved_project = prr.resolve_project(project_id=project_id or repo, repo=repo, node=node)
        project_path = resolved_project["project_path"]
    action = (action or "status").strip().lower()
    if action in {"write", "start", "restart", "stop", "enable", "disable"}:
        _require_approval(approval_id)
    payload = {
        "action": action,
        "service_name": service_name,
        "project_path": project_path,
        "unit_content": unit_content,
        "dry_run": dry_run,
        "lines": max(1, min(int(lines or 50), 200)),
    }
    result = _helper(node, "user_service", payload, timeout=120)
    _audit_peer("peer_user_service", {"ok": bool(result.get("ok")), "node": node, "service_name": service_name, "action": action, "dry_run": dry_run, "approval_id": approval_id or None})
    return {
        "ok": bool(result.get("ok")),
        "agent_id": AGENT_ID,
        "node": node,
        "service_name": service_name,
        "project_path": project_path,
        "project": resolved_project.get("project") if resolved_project else None,
        "action": action,
        "result": result,
        "security": {"system_scope": "user", "unit_path": "~/.config/systemd/user", "project_path_required_for_write": True},
    }


def peer_node_capability_matrix() -> dict[str, Any]:
    nodes = _node_registry()
    matrix: dict[str, Any] = {}
    for node in nodes:
        route = peer_route_check(node)
        interfaces = peer_net_interfaces(node)
        packages = peer_package_status(node, ["network-manager", "iw", "python3-venv", "python3-pip", "git"])
        hardware = peer_hardware_discovery(node)
        matrix[node] = {
            "node": node,
            "role": nodes[node]["role"],
            "host": nodes[node]["host"],
            "route": {"ok": route.get("ok"), "lan_default_route_intact": route.get("lan_default_route_intact"), "default_routes": route.get("default_routes")},
            "wifi_interfaces": [i for i in interfaces.get("interfaces", []) if i.get("wifi_capable")],
            "packages": packages.get("packages", []),
            "hardware": {
                "wireless_sys": ((hardware.get("hardware") or {}).get("wireless_sys") or []),
                "gpu_raw": (((hardware.get("hardware") or {}).get("gpu") or {}).get("stdout") or "")[:1000],
            },
            "control_plane": ["packages", "python_runtime", "user_systemd", "hardware_discovery", "network_readonly", "wifi_if_present", "project_filesystem", "observability"],
        }
    return {"ok": True, "agent_id": AGENT_ID, "nodes": nodes, "matrix": matrix, "future_nodes": "registry accepts additive node aliases without changing tool contracts"}


def peer_host_ops_policy() -> dict[str, Any]:
    return {
        "ok": True,
        "agent_id": AGENT_ID,
        "capability": "host_ops",
        "nodes": _node_registry(),
        "normal_without_new_permission": [
            "read/list/stat/write_text/mkdir/copy/move/chmod/quarantine inside trusted project roots",
            "Git/GitHub through Local Execution primitives on owner-approved repos",
            "package status and allowlisted package install/remove with existing approval_id flow",
            "Python venv/pip/compileall/pytest inside registered project paths",
            "systemd --user status/logs/write/start/restart/stop/enable/disable for project services",
            "hardware and observability read-only discovery",
            "Wi-Fi dedicated-interface connect/disconnect/forget through peer_wifi_*",
            "cloud status/auth/dry-run and apply-window primitives where provider is configured",
        ],
        "high_impact_requires_approval": [
            "package install/remove",
            "Wi-Fi apply",
            "systemd --user mutations",
            "cloud apply",
            "filesystem writes/moves/quarantine outside an already bootstrapped routine",
            "firewall/default-route/management-plane changes only with snapshot and rollback primitives",
        ],
        "destructive_denied": [
            "rm -rf/wipe/format/partition/kernel/bootloader mutations",
            "raw secret reads or secret values in logs",
            "unrestricted shell/root",
            "Ethernet/default route mutation without explicit recovery primitive",
            "force-push protected branches",
            "writes outside trusted project roots",
            "irreversible data deletion",
        ],
        "trusted_project_roots": [
            "/home/rlopez/inneros/inneros_core/workspaces",
            "/home/rlopez/inneros/inneros_core/var/local_execution/repos",
            "/home/rlopez/inneros/inneros_core/var/local_execution/worktrees",
            "/home/rlopez/projects",
        ],
        "evidence_policy": "Every mutation returns dry_run/result/audit metadata and keeps secrets redacted.",
    }


def peer_observability_snapshot(node: str = "primary") -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    result = _helper(node, "observability", timeout=45)
    return {"ok": bool(result.get("ok")), "agent_id": AGENT_ID, "node": node, "snapshot": result}


def peer_project_fs(
    node: str = "primary",
    project_path: str = "",
    project_id: str = "",
    repo: str = "",
    action: str = "stat",
    relative_path: str = ".",
    dest_relative_path: str = "",
    content: str = "",
    mode: str = "",
    approval_id: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    node = whatsapp_service_ops.normalize_node(node)
    resolved_project: dict[str, Any] | None = None
    if project_id or repo:
        from raphiia_openai import project_runtime_registry as prr

        resolved_project = prr.resolve_project(project_id=project_id or repo, repo=repo, node=node)
        project_path = resolved_project["project_path"]
    mutating = (action or "stat").strip().lower() in {"mkdir", "write_text", "copy", "move", "chmod", "quarantine"}
    if mutating:
        _require_approval(approval_id)
    payload = {
        "project_path": project_path,
        "action": action,
        "relative_path": relative_path,
        "dest_relative_path": dest_relative_path,
        "content": content,
        "mode": mode,
        "dry_run": dry_run,
    }
    result = _helper(node, "project_fs", payload, timeout=90)
    _audit_peer("peer_project_fs", {"ok": bool(result.get("ok")), "node": node, "project_path": project_path, "action": action, "relative_path": relative_path, "dry_run": dry_run, "approval_id": approval_id or None})
    return {
        "ok": bool(result.get("ok")),
        "agent_id": AGENT_ID,
        "node": node,
        "project_path": project_path,
        "project": resolved_project.get("project") if resolved_project else None,
        "action": action,
        "result": result,
        "security": {"trusted_roots_only": True, "path_traversal": "denied", "destructive_delete": "denied"},
    }
