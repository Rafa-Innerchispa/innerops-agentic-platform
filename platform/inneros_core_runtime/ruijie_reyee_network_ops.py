"""Ruijie / Reyee network observe → diagnose (cloud + local probe)."""

from __future__ import annotations

from typing import Any

from inneros_core_runtime import device_fabric, ruijie_reyee_client as rj

_RUIJIE_KEYWORDS = (
    "ruijie", "reyee", "ruggie", "锐捷", "easy-smart", "easy smart", "rg-ap", "rg-es",
    "eg205", "eap", "rap",
)


def is_ruijie_reyee_request(message: str) -> bool:
    text = (message or "").strip().lower()
    return any(k in text for k in _RUIJIE_KEYWORDS)


def _infer_site(message: str, client_id: str, site_id: str) -> tuple[str, str]:
    c = (client_id or "").strip().lower()
    s = (site_id or "").strip().lower()
    if c or s:
        if not c and "bellini" in s:
            c = "bellini"
        if not s and c == "bellini":
            s = "bellini-i-ii"
        return c or "bellini", s or "bellini-i-ii"
    if "casa" in (message or "").lower() or "lab" in (message or "").lower():
        return "pcdoctor_lab", "home_pcdoctor_lab"
    return "bellini", "bellini-i-ii"


def _norm_dev(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row.get("aliasName") or row.get("name"),
        "serial": row.get("serialNumber"),
        "model": row.get("productClass"),
        "type": row.get("commonType") or row.get("productType"),
        "online": str(row.get("onlineStatus") or "").upper() == "ON",
        "status": row.get("onlineStatus"),
        "mac": row.get("mac"),
        "local_ip": row.get("localIp"),
        "software": row.get("softwareVersion"),
        "group_name": row.get("groupName"),
    }


def ruijie_reyee_network_ops(
    message: str = "",
    *,
    client_id: str = "",
    site_id: str = "",
    group_id: int = 0,
) -> dict[str, Any]:
    client_id, site_id = _infer_site(message, client_id, site_id)
    creds, cred_err = rj.load_ruijie_credentials()
    gid = rj.resolve_group_id(client_id=client_id, site_id=site_id, group_id=group_id or None)
    findings: list[dict[str, Any]] = []
    limitations: list[str] = []
    cloud: dict[str, Any] | None = None
    local_probe = None

    if client_id == "bellini":
        try:
            local_probe = device_fabric.device_fabric_probe("192.168.3.172", site_id="bellini-i-ii")
        except Exception as exc:
            local_probe = {"ok": False, "error": str(exc)[:160]}

    if not creds:
        limitations.extend(
            [
                "Ruijie Cloud API requiere appid+secret (email service_rj@ruijienetworks.com) y cuenta cloud.",
                "Variables: RUIJIE_CLOUD_APP_ID, RUIJIE_CLOUD_SECRET, RUIJIE_CLOUD_ACCOUNT, RUIJIE_CLOUD_PASSWORD.",
                "Sin credenciales cloud: solo probe LAN (p.ej. 192.168.3.172 Easy-Smart Switch).",
            ]
        )
    else:
        if not gid:
            hint = "bellini" if client_id == "bellini" else client_id
            gid, pick = rj.pick_group_id_from_cloud(creds, hint=hint)
            if not gid:
                findings.append({"severity": "medium", "code": "ruijie_group_unresolved", "detail": pick})
        if gid:
            cloud = rj.fetch_full_network_snapshot(group_id=int(gid), creds=creds)

    aps: list[dict[str, Any]] = []
    switches: list[dict[str, Any]] = []
    gateways: list[dict[str, Any]] = []
    clients: list[dict[str, Any]] = []

    if cloud and cloud.get("ok"):
        block = (cloud.get("devices") or {}).get("devices") or {}
        aps = [_norm_dev(r) for r in block.get("AP") or [] if isinstance(r, dict)]
        switches = [_norm_dev(r) for r in block.get("Switch") or [] if isinstance(r, dict)]
        gateways = [_norm_dev(r) for r in block.get("Gateway") or [] if isinstance(r, dict)]
        clients = list((cloud.get("clients") or {}).get("items") or [])

    offline_aps = [d for d in aps if not d.get("online")]
    offline_sw = [d for d in switches if not d.get("online")]
    if offline_aps:
        findings.append({"severity": "high", "code": "reyee_ap_offline", "detail": [d.get("name") or d.get("serial") for d in offline_aps]})
    if offline_sw:
        findings.append({"severity": "high", "code": "reyee_switch_offline", "detail": [d.get("name") or d.get("serial") for d in offline_sw]})

    summary = (
        f"Ruijie/Reyee {client_id}/{site_id}: "
        f"{len(gateways)} gateway(s), {len(aps)} AP(s), {len(switches)} switch(es), "
        f"{len(clients)} client(s) cloud"
        + ("; creds missing — cloud pending" if not creds else "")
    )

    return {
        "ok": True,
        "mode": "ruijie_reyee_network_ops",
        "client_id": client_id,
        "site_id": site_id,
        "group_id": gid,
        "summary": summary,
        "findings": findings,
        "evidence": {
            "cloud_snapshot": cloud,
            "local_probe_192_168_3_172": local_probe,
            "gateways": gateways,
            "access_points": aps,
            "switches": switches,
            "clients_sample": clients[:100],
        },
        "limitations": limitations,
        "api_capabilities": rj.reyee_api_capabilities(),
        "credential_error": cred_err,
    }
