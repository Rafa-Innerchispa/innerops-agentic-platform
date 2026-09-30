"""Bellini I-II Network Guardian — Monitoreo Continuo, Detección de Incidentes y Control Gobernado.

Alcance: Bellini I-II exclusivamente (192.168.3.0/24).
Modo de Operación: READ-ONLY y Detección Automática de Causa Raíz.
"""

from __future__ import annotations

import datetime
import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import pymongo

GUARDIAN_VERSION = "2026.09.29"
SITE_ID = "bellini-i-ii"
CLIENT_ID = "bellini"
NETWORK_CIDR = "192.168.3.0/24"
PEER_TAILSCALE_IP = "100.103.151.40"
PEER_HOSTNAME = "DESKTOP-T2JLE71"

MUTATION_POLICY = {
    "mode": "read_only",
    "allowed": [
        "icmp_ping",
        "tcp_syn_probe",
        "http_get_status",
        "tailscale_status_read",
        "tailscale_ping",
        "home_assistant_state_publish",
        "mongo_telemetry_write",
        "governed_action_dry_run",
    ],
    "forbidden": [
        "live_ap_reboot_without_owner_approval",
        "live_router_reboot_without_owner_approval",
        "live_radio_change_without_owner_approval",
        "live_vlan_change",
        "live_dhcp_change",
        "live_firewall_change",
        "live_firmware_update",
        "live_poe_cycle_without_owner_approval",
    ],
}

TARGETS = [
    {"ip": "192.168.3.1", "asset_id": "bellini_gw_gcc6010", "name": "GCC6010 Gateway", "segment": "core", "device_type": "gateway", "ports": [80, 443, 8443, 22]},
    {"ip": "192.168.3.2", "asset_id": "bellini_pbx_ucm", "name": "UCM IP-PBX Core", "segment": "core", "device_type": "pbx", "ports": [80, 443, 5060]},
    {"ip": "192.168.3.100", "asset_id": "bellini_nvr_dahua", "name": "Dahua NVR", "segment": "cctv", "device_type": "nvr", "ports": [80, 37777, 554]},
    {"ip": "192.168.3.185", "asset_id": "bellini_switch_185", "name": "Switch Administración", "segment": "admin", "device_type": "switch", "ports": [80, 443, 8000]},
    {"ip": "192.168.3.188", "asset_id": "bellini_ap_188", "name": "GWN Wi-Fi AP 188", "segment": "admin", "device_type": "ap", "ports": [80, 443]},
    {"ip": "192.168.3.207", "asset_id": "bellini_ap_207_gwn7052f", "name": "GWN7052F Router/AP", "segment": "wifi", "device_type": "ap", "ports": [80, 443]},
    {"ip": "192.168.3.212", "asset_id": "bellini_ap_212", "name": "GWN Wi-Fi AP 212", "segment": "wifi", "device_type": "ap", "ports": [80, 443]},
    {"ip": "192.168.3.213", "asset_id": "bellini_ap_213", "name": "GWN Wi-Fi AP 213", "segment": "wifi", "device_type": "ap", "ports": [80, 443]},
    {"ip": "192.168.3.216", "asset_id": "bellini_ap_216", "name": "GWN Wi-Fi AP 216", "segment": "wifi", "device_type": "ap", "ports": [80, 443]},
    {"ip": "192.168.3.227", "asset_id": "bellini_ap_227", "name": "GWN Wi-Fi AP 227", "segment": "wifi", "device_type": "ap", "ports": [80, 443]},
    {"ip": "192.168.3.180", "asset_id": "bellini_host_180", "name": "Documented Host 180", "segment": "other", "device_type": "host", "ports": [80, 443]},
    {"ip": "192.168.3.220", "asset_id": "bellini_host_220", "name": "Documented Host 220", "segment": "other", "device_type": "host", "ports": [80, 443]},
    {"ip": "192.168.3.232", "asset_id": "bellini_host_232", "name": "Documented Host 232", "segment": "other", "device_type": "host", "ports": [80, 443]},
    {"ip": "192.168.3.234", "asset_id": "bellini_host_234", "name": "Documented Host 234", "segment": "other", "device_type": "host", "ports": [80, 443]},
]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def get_mongo_db() -> pymongo.database.Database | None:
    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
    try:
        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=1500)
        return client["pcdoctor_swarm"]
    except Exception:
        return None


def get_ha_config() -> tuple[str, str]:
    ha_url = os.getenv("HOME_ASSISTANT_URL", "http://192.168.1.4:8123")
    ha_token = os.getenv("HOME_ASSISTANT_TOKEN", "")
    if not ha_token and os.path.exists("/home/rlopez/inneros/inneros_core/platform/.env"):
        try:
            with open("/home/rlopez/inneros/inneros_core/platform/.env") as f:
                for l in f:
                    if l.startswith("HOME_ASSISTANT_TOKEN="):
                        ha_token = l.strip().split("=", 1)[1]
        except Exception:
            pass
    return ha_url, ha_token


def probe_icmp(ip: str, count: int = 2, timeout_s: int = 1) -> dict[str, Any]:
    try:
        res = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout_s), ip],
            capture_output=True,
            text=True,
            timeout=timeout_s * count + 2,
        )
        loss = 100.0
        rtt_min = None
        rtt_avg = None
        rtt_max = None
        for line in res.stdout.splitlines():
            if "packet loss" in line:
                for part in line.split(","):
                    if "packet loss" in part:
                        try:
                            loss = float(part.strip().replace("% packet loss", "").strip())
                        except ValueError:
                            pass
            if "rtt min/avg/max" in line or "round-trip min/avg/max" in line:
                try:
                    stats = line.split("=")[1].strip().split("/")
                    rtt_min = float(stats[0])
                    rtt_avg = float(stats[1])
                    rtt_max = float(stats[2])
                except (ValueError, IndexError):
                    pass
        return {
            "online": res.returncode == 0,
            "loss_pct": loss,
            "rtt_min_ms": rtt_min,
            "rtt_avg_ms": rtt_avg,
            "rtt_max_ms": rtt_max,
        }
    except Exception as e:
        return {"online": False, "loss_pct": 100.0, "rtt_min_ms": None, "rtt_avg_ms": None, "rtt_max_ms": None, "error": str(e)}


def probe_tcp(ip: str, port: int, timeout_s: float = 0.8) -> dict[str, Any]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout_s)
    t0 = time.time()
    try:
        s.connect((ip, port))
        rtt = (time.time() - t0) * 1000.0
        return {"open": True, "rtt_ms": round(rtt, 2), "port": port}
    except Exception as e:
        return {"open": False, "rtt_ms": None, "port": port, "error": str(e)}
    finally:
        s.close()


def probe_tailscale() -> dict[str, Any]:
    telemetry = {
        "peer_ip": PEER_TAILSCALE_IP,
        "peer_hostname": PEER_HOSTNAME,
        "direct": False,
        "derp": True,
        "relay_region": "mia",
        "endpoint": "",
        "rtt_ms": None,
        "active": False,
        "route_available": True,
    }
    try:
        res = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            peers = data.get("Peer", {})
            for _, p in peers.items():
                ips = p.get("TailscaleIPs", [])
                if PEER_TAILSCALE_IP in ips or PEER_HOSTNAME.lower() in p.get("HostName", "").lower():
                    telemetry["active"] = p.get("Active", False)
                    telemetry["endpoint"] = p.get("CurAddr", "")
                    telemetry["relay_region"] = p.get("Relay") or "mia"
                    telemetry["direct"] = not bool(p.get("Relay"))
                    telemetry["derp"] = bool(p.get("Relay"))
                    break
    except Exception:
        pass

    try:
        ping_res = subprocess.run(["tailscale", "ping", "--c", "2", PEER_TAILSCALE_IP], capture_output=True, text=True, timeout=5)
        if ping_res.returncode == 0:
            for line in ping_res.stdout.splitlines():
                if "pong from" in line and "in " in line:
                    try:
                        ms_part = line.split("in ")[-1].strip().replace("ms", "")
                        telemetry["rtt_ms"] = float(ms_part)
                        if "via" in line and "DERP" not in line:
                            telemetry["direct"] = True
                            telemetry["derp"] = False
                    except (ValueError, IndexError):
                        pass
    except Exception:
        pass

    return telemetry


def publish_home_assistant(states: dict[str, tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    url, token = get_ha_config()
    if not token:
        return {"ok": False, "error": "missing_ha_token"}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    results = {}
    for entity_id, (state, attrs) in states.items():
        payload = {"state": state, "attributes": attrs}
        req = urllib.request.Request(
            f"{url}/api/states/{entity_id}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results[entity_id] = {"ok": True, "state": data.get("state")}
        except Exception as e:
            results[entity_id] = {"ok": False, "error": str(e)}
    return {"ok": True, "results": results}


class BelliniNetworkGuardian:
    def __init__(self) -> None:
        self.running = False
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.last_sample: dict[str, Any] = {}
        self.active_incident: dict[str, Any] | None = None
        self.baseline_rtt = 15.0
        self.consecutive_gateway_drops = 0

    def capture_single_sweep(self) -> dict[str, Any]:
        sweep_time = _now()
        target_results = []
        
        for t in TARGETS:
            ip = t["ip"]
            icmp_res = probe_icmp(ip, count=2, timeout_s=1)
            tcp_res = {}
            for port in t["ports"][:2]:
                tcp_res[str(port)] = probe_tcp(ip, port, timeout_s=0.6)
            
            # An IP is considered responsive if ICMP or any primary TCP port responds
            tcp_open = any(v.get("open", False) for v in tcp_res.values())
            is_online = icmp_res.get("online", False) or tcp_open
            
            target_results.append({
                "ip": ip,
                "asset_id": t["asset_id"],
                "name": t["name"],
                "segment": t["segment"],
                "device_type": t["device_type"],
                "online": is_online,
                "icmp": icmp_res,
                "tcp": tcp_res,
            })

        ts_res = probe_tailscale()

        gw_stat = next((r for r in target_results if r["ip"] == "192.168.3.1"), {})
        gw_online = gw_stat.get("online", False)
        gw_rtt = (
            gw_stat.get("tcp", {}).get("80", {}).get("rtt_ms")
            or gw_stat.get("tcp", {}).get("443", {}).get("rtt_ms")
            or gw_stat.get("icmp", {}).get("rtt_avg_ms")
            or 0.0
        )

        sample = {
            "timestamp": sweep_time,
            "site_id": SITE_ID,
            "client_id": CLIENT_ID,
            "gateway_online": gw_online,
            "gateway_rtt_ms": gw_rtt,
            "tailscale": ts_res,
            "targets": target_results,
            "summary": {
                "total_targets": len(target_results),
                "online_count": sum(1 for r in target_results if r["online"]),
                "offline_count": sum(1 for r in target_results if not r["online"]),
                "admin_switch_185_online": next((r["online"] for r in target_results if r["ip"] == "192.168.3.185"), False),
                "ap_188_online": next((r["online"] for r in target_results if r["ip"] == "192.168.3.188"), False),
            },
            "mutation_policy": MUTATION_POLICY,
        }

        # Analyze incident triggers
        self._analyze_incidents(sample)

        # Store in Mongo
        db = get_mongo_db()
        if db is not None:
            try:
                db.bellini_guardian_state.update_one(
                    {"site_id": SITE_ID},
                    {"$set": sample},
                    upsert=True,
                )
                db.bellini_telemetry.insert_one({**sample, "created_at": datetime.datetime.now(datetime.timezone.utc)})
            except Exception:
                pass

        # Sync to Home Assistant
        self._sync_to_home_assistant(sample)

        with self.lock:
            self.last_sample = sample

        return sample

    def _analyze_incidents(self, sample: dict[str, Any]) -> None:
        gw_online = sample["gateway_online"]
        gw_rtt = sample["gateway_rtt_ms"]
        ts = sample["tailscale"]
        targets = sample["targets"]
        
        sw185 = next((r for r in targets if r["ip"] == "192.168.3.185"), {})
        ap188 = next((r for r in targets if r["ip"] == "192.168.3.188"), {})
        
        ap_targets = [r for r in targets if r["device_type"] == "ap"]
        offline_aps = [r for r in ap_targets if not r["online"]]

        incident_trigger = None
        root_cause = "NORMAL_OPERATION"
        confidence = 1.0

        if not gw_online:
            incident_trigger = "GATEWAY_UNREACHABLE"
            root_cause = "CORE_ROUTER_OR_POWER_OUTAGE"
            confidence = 0.98
        elif gw_rtt > 100.0 and ts.get("derp"):
            incident_trigger = "TAILSCALE_DERP_HIGH_LATENCY"
            root_cause = "REMOTE_ACCESS_TAILSCALE_DERP_DEGRADATION"
            confidence = 0.95
        elif not sw185.get("online") and not ap188.get("online") and gw_online:
            incident_trigger = "ADMIN_SEGMENT_DROP"
            root_cause = "ADMIN_SEGMENT_PHYSICAL_FAILURE"
            confidence = 0.92
        elif len(offline_aps) >= 2 and gw_online:
            incident_trigger = "MULTIPLE_AP_OUTAGE"
            root_cause = "WIFI_DISTRIBUTION_SWITCH_OR_POE_DROP"
            confidence = 0.88
        elif len(offline_aps) == 1:
            incident_trigger = f"SINGLE_AP_OUTAGE_{offline_aps[0]['asset_id']}"
            root_cause = "SINGLE_AP_OR_POE_DROP"
            confidence = 0.90

        if incident_trigger:
            if not self.active_incident:
                inc_id = f"inc_{int(time.time())}_{incident_trigger.lower()}"
                self.active_incident = {
                    "incident_id": inc_id,
                    "site_id": SITE_ID,
                    "client_id": CLIENT_ID,
                    "started_at": sample["timestamp"],
                    "recovered_at": None,
                    "trigger": incident_trigger,
                    "root_cause_candidate": root_cause,
                    "confidence": confidence,
                    "affected_devices": [r["asset_id"] for r in targets if not r["online"]],
                    "first_failed_component": targets[0]["asset_id"] if not gw_online else (offline_aps[0]["asset_id"] if offline_aps else "unknown"),
                    "timeline": [{"timestamp": sample["timestamp"], "event": f"Triggered: {incident_trigger}"}],
                    "raw_snapshot": {
                        "tailscale": ts,
                        "gateway_rtt_ms": gw_rtt,
                        "offline_count": sample["summary"]["offline_count"],
                    },
                }
                db = get_mongo_db()
                if db is not None:
                    try:
                        db.bellini_incidents.insert_one(self.active_incident)
                    except Exception:
                        pass
        else:
            if self.active_incident:
                self.active_incident["recovered_at"] = sample["timestamp"]
                self.active_incident["timeline"].append({"timestamp": sample["timestamp"], "event": "Recovered to normal"})
                db = get_mongo_db()
                if db is not None:
                    try:
                        db.bellini_incidents.update_one(
                            {"incident_id": self.active_incident["incident_id"]},
                            {"$set": {"recovered_at": sample["timestamp"], "timeline": self.active_incident["timeline"]}},
                        )
                    except Exception:
                        pass
                self.active_incident = None

    def _sync_to_home_assistant(self, sample: dict[str, Any]) -> None:
        ts = sample.get("tailscale", {})
        targets = sample.get("targets", [])
        
        ap188 = next((r["online"] for r in targets if r["ip"] == "192.168.3.188"), False)
        ap212 = next((r["online"] for r in targets if r["ip"] == "192.168.3.212"), False)
        ap216 = next((r["online"] for r in targets if r["ip"] == "192.168.3.216"), False)
        ap227 = next((r["online"] for r in targets if r["ip"] == "192.168.3.227"), False)
        sw185 = next((r["online"] for r in targets if r["ip"] == "192.168.3.185"), False)

        ts_path_str = f"DERP({ts.get('relay_region')})" if ts.get("derp") else "direct"
        ts_latency_str = str(ts.get("rtt_ms") or 0.0)
        gw_lat_str = str(sample.get("gateway_rtt_ms") or 0.0)

        incident_name = self.active_incident.get("trigger", "none") if self.active_incident else "none"

        states = {
            "sensor.bellini_gateway_latency": (gw_lat_str, {"unit_of_measurement": "ms", "friendly_name": "Bellini Gateway Latency", "device_class": "duration"}),
            "binary_sensor.bellini_gateway_online": ("on" if sample.get("gateway_online") else "off", {"friendly_name": "Bellini Gateway Online", "device_class": "connectivity"}),
            "sensor.bellini_tailscale_latency": (ts_latency_str, {"unit_of_measurement": "ms", "friendly_name": "Bellini Tailscale Latency", "device_class": "duration"}),
            "sensor.bellini_tailscale_path": (ts_path_str, {"friendly_name": "Bellini Tailscale Path", "endpoint": ts.get("endpoint", "")}),
            "binary_sensor.bellini_ap_188_online": ("on" if ap188 else "off", {"friendly_name": "Bellini AP 188 Online", "device_class": "connectivity"}),
            "binary_sensor.bellini_ap_212_online": ("on" if ap212 else "off", {"friendly_name": "Bellini AP 212 Online", "device_class": "connectivity"}),
            "binary_sensor.bellini_ap_216_online": ("on" if ap216 else "off", {"friendly_name": "Bellini AP 216 Online", "device_class": "connectivity"}),
            "binary_sensor.bellini_ap_227_online": ("on" if ap227 else "off", {"friendly_name": "Bellini AP 227 Online", "device_class": "connectivity"}),
            "binary_sensor.bellini_switch_185_online": ("on" if sw185 else "off", {"friendly_name": "Bellini Switch 185 Online", "device_class": "connectivity"}),
            "sensor.bellini_active_incident": (incident_name, {"friendly_name": "Bellini Active Incident", "active": bool(self.active_incident)}),
        }
        publish_home_assistant(states)

    def loop(self, interval_s: int = 10) -> None:
        self.running = True
        while self.running:
            try:
                self.capture_single_sweep()
            except Exception:
                pass
            time.sleep(interval_s)

    def start_background(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False


# Governed Control Plane Functions (Stage / Dry-Run / Read-Only Guarded)

def execute_governed_action(
    action: str,
    device_ref: str,
    params: dict[str, Any] | None = None,
    *,
    dry_run: bool = True,
    approval_token: str | None = None,
) -> dict[str, Any]:
    """Funciones de control operativo gobernado sobre la red Bellini I-II.
    
    Por política de seguridad P0, toda acción en vivo (dry_run=False) requiere
    autorización explícita del owner.
    """
    params = params or {}
    plan = {
        "action": action,
        "device_ref": device_ref,
        "site_id": SITE_ID,
        "client_id": CLIENT_ID,
        "params": params,
        "dry_run": dry_run,
        "requires_approval": True,
        "mutation_policy": MUTATION_POLICY,
        "created_at": _now(),
    }

    if dry_run:
        return {
            "ok": True,
            "status": "STAGED_DRY_RUN",
            "message": f"Acción gobernada '{action}' validada en modo simulación para {device_ref}.",
            "plan": plan,
            "mutation_applied": False,
        }

    # Live execution check
    return {
        "ok": False,
        "error": "governed_action_requires_explicit_owner_approval",
        "message": f"La mutación '{action}' sobre {device_ref} está bloqueada por la política READ-ONLY de Bellini.",
        "plan": plan,
        "mutation_applied": False,
    }


def reboot_ap(device_ref: str, dry_run: bool = True, approval_token: str | None = None) -> dict[str, Any]:
    return execute_governed_action("reboot_ap", device_ref, dry_run=dry_run, approval_token=approval_token)


def toggle_radio(device_ref: str, radio: str = "2.4ghz", enabled: bool = True, dry_run: bool = True, approval_token: str | None = None) -> dict[str, Any]:
    return execute_governed_action("toggle_radio", device_ref, {"radio": radio, "enabled": enabled}, dry_run=dry_run, approval_token=approval_token)


def change_channel(device_ref: str, radio: str = "2.4ghz", channel: int = 6, dry_run: bool = True, approval_token: str | None = None) -> dict[str, Any]:
    return execute_governed_action("change_channel", device_ref, {"radio": radio, "channel": channel}, dry_run=dry_run, approval_token=approval_token)


def change_tx_power(device_ref: str, radio: str = "2.4ghz", power: str = "medium", dry_run: bool = True, approval_token: str | None = None) -> dict[str, Any]:
    return execute_governed_action("change_tx_power", device_ref, {"radio": radio, "power": power}, dry_run=dry_run, approval_token=approval_token)


def restart_interface(device_ref: str, interface: str = "wan1", dry_run: bool = True, approval_token: str | None = None) -> dict[str, Any]:
    return execute_governed_action("restart_interface", device_ref, {"interface": interface}, dry_run=dry_run, approval_token=approval_token)


def reboot_router(device_ref: str, dry_run: bool = True, approval_token: str | None = None) -> dict[str, Any]:
    return execute_governed_action("reboot_router", device_ref, dry_run=dry_run, approval_token=approval_token)


def port_control(switch_ref: str, port: int = 1, enabled: bool = True, dry_run: bool = True, approval_token: str | None = None) -> dict[str, Any]:
    return execute_governed_action("port_control", switch_ref, {"port": port, "enabled": enabled}, dry_run=dry_run, approval_token=approval_token)


def poe_cycle(switch_ref: str, port: int = 1, dry_run: bool = True, approval_token: str | None = None) -> dict[str, Any]:
    return execute_governed_action("poe_cycle", switch_ref, {"port": port}, dry_run=dry_run, approval_token=approval_token)


# Singleton Guardian instance
_guardian_instance: BelliniNetworkGuardian | None = None

def get_guardian() -> BelliniNetworkGuardian:
    global _guardian_instance
    if _guardian_instance is None:
        _guardian_instance = BelliniNetworkGuardian()
    return _guardian_instance


def bellini_guardian_status() -> dict[str, Any]:
    """Retorna el estado operativo en vivo y telemetría de Bellini Network Guardian."""
    db = get_mongo_db()
    if db is not None:
        state = db.bellini_guardian_state.find_one({"site_id": SITE_ID}, {"_id": 0})
        if state:
            return {"ok": True, "source": "mongodb_guardian_state", **state}
    g = get_guardian()
    return {"ok": True, "source": "live_sweep", **g.capture_single_sweep()}


def bellini_guardian_dashboard() -> dict[str, Any]:
    """Retorna el panel operativo de Bellini I-II con métricas, incidentes y telemetría."""
    status = bellini_guardian_status()
    db = get_mongo_db()
    recent_incidents = []
    if db is not None:
        try:
            cursor = db.bellini_incidents.find({"site_id": SITE_ID}, {"_id": 0}).sort("started_at", -1).limit(5)
            recent_incidents = list(cursor)
        except Exception:
            pass

    return {
        "ok": True,
        "site_id": SITE_ID,
        "client_id": CLIENT_ID,
        "guardian_version": GUARDIAN_VERSION,
        "mode": "read_only",
        "gateway": {
            "ip": "192.168.3.1",
            "model": "GCC6010",
            "online": status.get("gateway_online", False),
            "rtt_ms": status.get("gateway_rtt_ms", 0.0),
        },
        "tailscale": status.get("tailscale", {}),
        "summary": status.get("summary", {}),
        "device_matrix": status.get("targets", []),
        "recent_incidents": recent_incidents,
        "mutation_policy": MUTATION_POLICY,
        "generated_at": _now(),
    }

if __name__ == "__main__":
    import signal
    print(f"[{_now()}] Starting Bellini Network Guardian daemon v{GUARDIAN_VERSION} on {SITE_ID}...")
    g = get_guardian()
    
    def handle_sig(sig, frame):
        print(f"[{_now()}] Stopping Bellini Network Guardian...")
        g.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)
    
    # Run loop
    g.loop(interval_s=10)
