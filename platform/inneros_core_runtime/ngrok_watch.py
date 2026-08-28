"""Vigilancia ngrok + gateway público — health para registry y AG-31."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any

NGROK_PUBLIC_HOST = os.getenv(
    "NGROK_PUBLIC_HOST",
    "sworn-profusely-alongside.ngrok-free.dev",
)
NGROK_PROBE_PATH = os.getenv("NGROK_PROBE_PATH", "/uipath/dashboard")
PUBLIC_GATEWAY_PORT = int(os.getenv("PUBLIC_GATEWAY_PORT", "5188"))


def _http_code(url: str, *, headers: dict[str, str] | None = None, timeout: float = 12.0) -> tuple[int, str]:
    hdrs = {"User-Agent": "RalfIA-NgrokWatch/1.0", **(headers or {})}
    try:
        req = urllib.request.Request(url, headers=hdrs, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), ""
    except urllib.error.HTTPError as exc:
        err_hdr = exc.headers.get("ngrok-error-code", "") if exc.headers else ""
        return int(exc.code), err_hdr or str(exc.reason)[:120]
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc)[:200]


def _local_ngrok_api() -> dict[str, Any]:
    for port in (4040, 4041):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/tunnels", timeout=3
            ) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            continue
    return {}


def _systemd_active(unit: str, scope: str = "system") -> str:
    cmd = ["systemctl", "is-active", unit] if scope == "system" else ["systemctl", "--user", "is-active", unit]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return (proc.stdout or proc.stderr or "").strip()


def check_public_gateway() -> dict[str, Any]:
    code, err = _http_code(f"http://127.0.0.1:{PUBLIC_GATEWAY_PORT}/")
    status = "up" if 200 <= code < 400 else "down"
    systemd = _systemd_active("swarm-public-gateway.service")
    zombie = systemd == "active" and status == "down"
    return {
        "service_id": "public-gateway",
        "name": "Public Gateway ngrok",
        "status": status,
        "port": PUBLIC_GATEWAY_PORT,
        "last_error": (
            f"zombie systemd=active sin HTTP ({err or f'HTTP {code}'})"
            if zombie
            else (err or ("" if status == "up" else f"HTTP {code}"))
        ),
        "systemd": systemd,
        "zombie": zombie,
    }


def check_ngrok_tunnel() -> dict[str, Any]:
    """Estado del túnel HTTPS público (ngrok → :5188)."""
    api = _local_ngrok_api()
    tunnels = api.get("tunnels") or []
    public_url = ""
    for t in tunnels:
        u = t.get("public_url") or ""
        if NGROK_PUBLIC_HOST in u:
            public_url = u
            break

    systemd = _systemd_active("swarm-ngrok.service")
    local_ok = bool(public_url)

    ext_url = f"https://{NGROK_PUBLIC_HOST}{NGROK_PROBE_PATH}"
    ext_code, ext_err = _http_code(
        ext_url,
        headers={"ngrok-skip-browser-warning": "true"},
        timeout=15,
    )
    external_ok = 200 <= ext_code < 400

    if external_ok:
        status = "up"
        last_error = ""
    elif local_ok and ext_code == 404 and "ERR_NGROK_3200" in (ext_err or ""):
        status = "degraded"
        last_error = "API local OK pero endpoint público offline (ERR_NGROK_3200)"
    elif local_ok:
        status = "degraded"
        gw = check_public_gateway()
        if gw.get("status") != "up":
            last_error = (
                f"túnel ngrok OK pero gateway :{PUBLIC_GATEWAY_PORT} caído "
                f"(systemd={gw.get('systemd')}; {gw.get('last_error') or f'HTTP externo {ext_code} {ext_err}'})"
            ).strip()
        else:
            last_error = f"ngrok local activo pero externo HTTP {ext_code} {ext_err}".strip()
    elif systemd == "active":
        status = "degraded"
        last_error = "systemd active pero sin túnel en API :4040"
    else:
        status = "down"
        parts = [f"systemd={systemd}"]
        if ext_err:
            parts.append(ext_err)
        elif ext_code:
            parts.append(f"HTTP {ext_code}")
        last_error = "; ".join(parts)

    return {
        "service_id": "ngrok-public-tunnel",
        "name": "ngrok HTTPS público",
        "status": status,
        "port": 4040,
        "risk_level": "critical",
        "public_url": public_url or f"https://{NGROK_PUBLIC_HOST}",
        "probe_url": ext_url,
        "external_http": ext_code,
        "systemd": systemd,
        "last_error": last_error,
        "local_tunnel": local_ok,
    }


def check_uipath_copilot() -> dict[str, Any]:
    code, err = _http_code("http://127.0.0.1:8097/dashboard")
    status = "up" if 200 <= code < 400 else "down"
    return {
        "service_id": "uipath-copilot",
        "name": "UiPath Copilot",
        "status": status,
        "port": 8097,
        "last_error": err or ("" if status == "up" else f"HTTP {code}"),
        "systemd": _systemd_active("swarm-uipath-copilot.service"),
    }


def run_infra_checks() -> list[dict[str, Any]]:
    return [check_public_gateway(), check_ngrok_tunnel(), check_uipath_copilot()]


def _restart_unit(unit: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["sudo", "-n", "systemctl", "restart", unit],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return 0, f"sudo systemctl restart {unit}"
    err = (proc.stderr or proc.stdout or "")[:200]
    return proc.returncode, f"sudo restart {unit} exit={proc.returncode}: {err}"


def try_recover_public_gateway() -> dict[str, Any]:
    """Si :5188 no responde (aunque systemd diga active/zombie), reinicia el gateway."""
    import time
    from pathlib import Path

    before = check_public_gateway()
    if before.get("status") == "up":
        return {"ok": True, "action": "none", "before": before}

    actions: list[str] = []
    # Proceso zombie: systemd active + connection refused → reiniciar unit
    code, msg = _restart_unit("swarm-public-gateway.service")
    actions.append(msg)
    if code != 0:
        # Fallback user: fuser + script
        subprocess.run(
            ["fuser", "-k", f"{PUBLIC_GATEWAY_PORT}/tcp"],
            capture_output=True,
            text=True,
        )
        actions.append(f"fuser -k {PUBLIC_GATEWAY_PORT}/tcp")
        gw = Path("/home/rlopez/projects/innerspark-swarm-os-cursor-local/run_public_gateway.sh")
        if gw.is_file():
            subprocess.Popen(
                ["/usr/bin/bash", str(gw)],
                cwd=str(gw.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            actions.append("run_public_gateway.sh background")
    time.sleep(5)
    after = check_public_gateway()
    return {"ok": after.get("status") == "up", "action": "; ".join(actions), "before": before, "after": after}


def try_recover_ngrok() -> dict[str, Any]:
    """Recupera cadena pública: primero gateway :5188, luego ngrok si el túnel falta."""
    before = check_ngrok_tunnel()
    gw_before = check_public_gateway()
    if before.get("status") == "up" and gw_before.get("status") == "up":
        return {"ok": True, "action": "none", "before": before, "gateway": gw_before}

    import time
    from pathlib import Path

    actions: list[str] = []

    # Causa habitual del 502 ERR_NGROK_8012: túnel vivo + backend :5188 muerto/zombie.
    # Ante cualquier degraded/down: forzar gateway primero (barato y suele bastar).
    if gw_before.get("status") != "up" or before.get("status") != "up":
        gw_rec = try_recover_public_gateway()
        # Si gateway ya estaba "up" local pero externo 502, reiniciar igual (estado inconsistente)
        if gw_before.get("status") == "up" and before.get("status") != "up":
            code, msg = _restart_unit("swarm-public-gateway.service")
            actions.append(f"gateway-force:{msg}")
            time.sleep(5)
            gw_rec = {"ok": check_public_gateway().get("status") == "up", "action": msg, "forced": True}
        else:
            actions.append(f"gateway:{gw_rec.get('action')}")
        time.sleep(2)
        after_gw = check_ngrok_tunnel()
        if after_gw.get("status") == "up":
            return {
                "ok": True,
                "action": "; ".join(actions),
                "before": before,
                "after": after_gw,
                "gateway_recover": gw_rec,
            }

    sync = Path("/home/rlopez/projects/raphiia-openai/scripts/sync_ngrok_authtoken.sh")
    if sync.is_file():
        subprocess.run([str(sync)], capture_output=True, text=True, timeout=30)
        actions.append("sync_ngrok_authtoken")

    script = Path("/home/rlopez/projects/innerspark-swarm-os-cursor-local/run_ngrok_all.sh")
    systemd = before.get("systemd") or _systemd_active("swarm-ngrok.service")
    tunnel_missing = not before.get("local_tunnel")
    still_bad = check_ngrok_tunnel().get("status") != "up"

    # Solo lanzar script / reiniciar ngrok si el túnel falta o sigue mal tras gateway
    if tunnel_missing and script.is_file() and systemd != "active":
        subprocess.Popen(
            ["/usr/bin/bash", str(script)],
            cwd=str(script.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        actions.append("run_ngrok_all.sh background")
        time.sleep(8)
        after = check_ngrok_tunnel()
        if after.get("status") == "up":
            return {"ok": True, "action": "; ".join(actions), "before": before, "after": after}

    proc_code, proc_msg = 0, "ngrok restart skipped (túnel local OK)"
    if tunnel_missing or before.get("status") == "down" or still_bad:
        proc_code, proc_msg = _restart_unit("swarm-ngrok.service")
    actions.append(proc_msg)
    time.sleep(6)
    after = check_ngrok_tunnel()
    return {
        "ok": after.get("status") == "up",
        "action": "; ".join(actions),
        "stderr": "" if proc_code == 0 else proc_msg,
        "before": before,
        "after": after,
    }
