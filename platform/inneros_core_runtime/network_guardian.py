"""AG-60 local-first bounded network guardian.

Read-only monitoring of allowlisted IPv4 LANs. No device reconfiguration,
external inference, credential probing, HTTP POST, or destructive actions.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import time
from typing import Any


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def authorized_network(site_id: str) -> ipaddress.IPv4Network:
    from inneros_core_runtime.device_fabric import _site
    site = _site(site_id)
    if not site or not site.get("authorized_cidr"):
        raise ValueError("unregistered_or_unscoped_site")
    network = ipaddress.ip_network(site["authorized_cidr"], strict=False)
    if not isinstance(network, ipaddress.IPv4Network) or network.num_addresses > 1024:
        raise ValueError("site_range_too_large")
    return network


def icmp_probe(host: str, timeout: float = 0.8) -> dict[str, Any]:
    """Invoke system ping with an absolute deadline; failure is not proof of offline."""
    if not shutil.which("ping"):
        return {"status": "UNKNOWN", "error": "ping_unavailable"}
    try:
        result = subprocess.run(
            ["ping", "-n", "-c", "1", "-W", "1", host],
            capture_output=True, text=True, timeout=max(1.5, timeout + 1),
            check=False,
        )
        return {"status": "REACHABLE" if result.returncode == 0 else "NO_REPLY",
                "latency_ms": _latency(result.stdout) if result.returncode == 0 else None,
                "exit_code": result.returncode}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "UNKNOWN", "error": type(exc).__name__}


def _latency(output: str) -> float | None:
    import re
    found = re.search(r"time[=<]([0-9.]+)\s*ms", output)
    return float(found.group(1)) if found else None


def tcp_probe(host: str, ports: tuple[int, ...], timeout: float = 0.3) -> list[int]:
    open_ports: list[int] = []
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                open_ports.append(port)
        except (OSError, TimeoutError):
            continue
    return open_ports


def probe_host(host: str, site_id: str, ports: tuple[int, ...] = (80, 443, 554, 22),
               timeout: float = 0.3) -> dict[str, Any]:
    net = authorized_network(site_id)
    ip = ipaddress.ip_address(host)
    if ip not in net:
        raise ValueError("target_outside_authorized_cidr")
    ping = icmp_probe(host)
    opened = tcp_probe(host, ports, timeout)
    reached = ping["status"] == "REACHABLE" or bool(opened)
    # An unresponsive host may block ICMP and TCP; classify UNKNOWN, not OFFLINE.
    return {"ip": host, "site_id": site_id, "health": "ONLINE" if reached else "UNKNOWN",
            "reachable": True if reached else None, "icmp": ping, "tcp_open": opened,
            "observed_at": utcnow(), "evidence_source": "local_icmp_tcp",
            "verified": reached}


def scan_site(site_id: str = "home_pcdoctor_lab", limit_hosts: int = 254,
              workers: int = 16, timeout: float = 0.25) -> dict[str, Any]:
    net = authorized_network(site_id)
    if not 1 <= limit_hosts <= 254 or not 1 <= workers <= 24:
        raise ValueError("scan_limits_exceeded")
    targets = [str(ip) for ip in net.hosts()][:limit_hosts]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(
            lambda ip: probe_host(ip, site_id, timeout=timeout), targets
        ))
    found = [row for row in results if row["verified"]]
    return {"site_id": site_id, "cidr": str(net), "observed_at": utcnow(),
            "tested_hosts": len(results), "responsive_count": len(found),
            "responsive": found, "unverified_count": len(results) - len(found),
            "read_only": True, "scan_complete": len(results) == len(targets)}


def correlate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark co-occurring loss; no invented root cause."""
    findings: list[dict[str, Any]] = []
    lost = [e for e in events if e.get("new_state") == "UNKNOWN"
            and e.get("previous_state") == "ONLINE"]
    if len(lost) >= 3:
        findings.append({"code": "multiple_hosts_lost",
                         "affected": [e.get("ip") for e in lost],
                         "cause": "UNDETERMINED",
                         "next_checks": ["gateway", "switch_uplink", "poe", "lan_loop"]})
    return findings


def persist_snapshot(snapshot: dict[str, Any], *, mongo_uri: str | None = None) -> dict[str, Any]:
    """Optional local Mongo persistence; do not turn unavailable DB into success."""
    try:
        from pymongo import MongoClient
        with MongoClient(mongo_uri or os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017"),
                         serverSelectionTimeoutMS=1200) as client:
            db = client["pcdoctor_swarm"]
            existing = {r["ip"]: r for r in db.network_device_state.find(
                {"site_id": snapshot["site_id"]}, {"_id": 0})}
            events = []
            for record in snapshot["responsive"]:
                ip = record["ip"]
                prev = existing.get(ip, {})
                if prev.get("health") != record["health"]:
                    events.append({"site_id": snapshot["site_id"], "ip": ip,
                                   "previous_state": prev.get("health", "UNKNOWN"),
                                   "new_state": record["health"], "observed_at": snapshot["observed_at"]})
                db.network_device_state.update_one(
                    {"site_id": snapshot["site_id"], "ip": ip},
                    {"$set": {"site_id": snapshot["site_id"], **record}}, upsert=True)
            # Absence on one scan is insufficient to mark an existing device offline.
            db.network_device_samples.insert_one(snapshot)
            if events:
                db.network_device_events.insert_many(events)
            return {"ok": True, "transitions": events,
                    "findings": correlate_events(events)}
    except (ImportError, Exception) as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:140]}


def main() -> None:
    parser = argparse.ArgumentParser(description="AG-60 bounded read-only LAN monitoring")
    parser.add_argument("--site", default="home_pcdoctor_lab")
    parser.add_argument("--limit-hosts", type=int, default=254)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    snapshot = scan_site(args.site, args.limit_hosts)
    result = {"snapshot": snapshot,
              "persistence": persist_snapshot(snapshot) if args.save else "disabled"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
