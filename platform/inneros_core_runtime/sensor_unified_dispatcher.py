#!/usr/bin/env python3
"""
Sensor Unified Dispatcher · InnerOS
Monitorea en tiempo real cambios de estado en:
1. Sensores de Alarma Intelbras (zonas magnéticas y detectores de movimiento).
2. Panel de Alarma Intelbras (armado, desarmado, disparada).
3. Sensores Hubitat (SMagnetico01 contacto, Multisensor 6 movimiento).

Despacha notificaciones instantáneas DUALES a:
- NTFY (Push directo al celular vía http://127.0.0.1:2586/ralfia-owner-ops)
- Telegram (InnerSparkOS_Bot al chat_id 1502049267)
"""

from __future__ import annotations

import json
import os
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

# Configurar PYTHONPATH seguro sin colisionar con el módulo estándar 'platform'
PLATFORM_DIR = Path("/home/rlopez/inneros/inneros_core/platform")
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

RAPHIIA_DIR = Path("/home/rlopez/projects/raphiia-openai")
if str(RAPHIIA_DIR) not in sys.path:
    sys.path.insert(0, str(RAPHIIA_DIR))

HA_URL = (os.getenv("HOME_ASSISTANT_URL") or "http://192.168.1.4:8123").rstrip("/")
HA_TOKEN = os.getenv("HOME_ASSISTANT_TOKEN", "")
if not HA_TOKEN:
    env_file = Path("/home/rlopez/projects/raphiia-openai/.env")
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("HOME_ASSISTANT_TOKEN="):
                HA_TOKEN = line.split("=", 1)[1].strip().strip("\"'")

NTFY_URL = (os.getenv("INNEROS_NTFY_URL") or "http://127.0.0.1:2586").rstrip("/")
NTFY_TOPIC = (os.getenv("INNEROS_NTFY_TOPIC") or "ralfia-owner-ops").strip().lstrip("/")
STATE_FILE = Path(os.getenv("UNIFIED_SENSOR_STATE_FILE", "/home/rlopez/data/ralfia/unified_sensor_state.json"))
OWNER_TZ = ZoneInfo(os.getenv("INNEROS_OWNER_TZ", "America/Guayaquil"))

# Cargar cliente Telegram
try:
    from inneros_core_runtime.notifications import telegram_client as tg
    TG_AVAILABLE = True
except Exception as _e:
    TG_AVAILABLE = False
    tg = None

# Cargar cliente Hubitat
try:
    from raphiia_openai import hubitat_client as hub
    HUB_AVAILABLE = True
except Exception as _e:
    HUB_AVAILABLE = False
    hub = None


def _parse_instant(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def fmt_owner_tz(dt: datetime | None) -> str:
    if dt is None:
        return ""
    local = dt.astimezone(OWNER_TZ)
    return local.strftime("%d/%m/%Y %H:%M:%S") + " (Guayaquil)"


def sanitize_header(text: str) -> str:
    """Elimina acentos y emojis para encabezados HTTP ASCII seguros (urllib latin-1 safe)."""
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(norm.split()).strip() or "Alerta InnerOS"


def send_ntfy(title: str, message: str, tags: str = "bell,shield", priority: str = "default") -> bool:
    try:
        url = f"{NTFY_URL}/{NTFY_TOPIC}"
        headers = {
            "Title": sanitize_header(title),
            "Priority": priority,
            "Tags": tags,
        }
        req = urllib.request.Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[NTFY Error] {e}", file=sys.stderr)
        return False


def send_telegram(message: str) -> bool:
    if not TG_AVAILABLE or tg is None:
        return False
    try:
        res = tg.send_message(message, chat_id=tg.owner_chat_id(), parse_mode="")
        return bool(res.get("ok"))
    except Exception as e:
        print(f"[Telegram Error] {e}", file=sys.stderr)
        return False


def dispatch_alert(
    title: str,
    text: str,
    tags: str = "bell",
    priority: str = "default",
    *,
    detected_at: object = None,
) -> None:
    sent_at = datetime.now(timezone.utc)
    det = _parse_instant(detected_at) or sent_at
    body_lines = [
        text.strip(),
        "",
        "──────────────────────",
        f"🕐 Detección · {fmt_owner_tz(det)}",
        f"📲 Notificación · {fmt_owner_tz(sent_at)}",
    ]
    body = "\n".join(body_lines)
    formatted_msg = f"{title}\n{body}"

    ntfy_ok = send_ntfy(title, body, tags=tags, priority=priority)
    tg_ok = send_telegram(formatted_msg)

    stamp = fmt_owner_tz(sent_at)
    print(f"[{stamp}] DISPATCH '{title}': NTFY={'OK' if ntfy_ok else 'FAIL'}, Telegram={'OK' if tg_ok else 'FAIL'}")


def load_saved_state() -> dict:
    if not STATE_FILE.is_file():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[Save State Error] {e}", file=sys.stderr)


def get_ha_states() -> dict[str, dict]:
    try:
        req = urllib.request.Request(f"{HA_URL}/api/states", headers={"Authorization": f"Bearer {HA_TOKEN}"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
            return {s["entity_id"]: s for s in data}
    except Exception as e:
        print(f"[HA Poll Error] {e}", file=sys.stderr)
        return {}


def main_loop():
    print("=" * 60)
    print("🚀 Iniciando Sensor Unified Dispatcher (InnerOS Sentinel)")
    print(f"HA: {HA_URL} | NTFY: {NTFY_URL}/{NTFY_TOPIC} | Telegram: {'Activo' if TG_AVAILABLE else 'No'}")
    print("=" * 60)

    saved_state = load_saved_state()
    ha_states_history: dict[str, str] = saved_state.get("ha", {})
    hubitat_states_history: dict[str, dict] = saved_state.get("hubitat", {})

    zone_friendly_names = {
        "binary_sensor.panel_home_ralphi_zona_01": "Zona 01",
        "binary_sensor.panel_home_ralphi_zona_02": "Zona 02",
        "binary_sensor.panel_home_ralphi_zona_03": "Zona 03",
        "binary_sensor.panel_home_ralphi_zona_04": "Zona 04",
        "binary_sensor.panel_home_ralphi_zona_05": "Puerta Oficina (POficina)",
        "binary_sensor.panel_home_ralphi_zona_06": "Puerta Entrada (PEntrada)",
        "binary_sensor.panel_home_ralphi_zona_07": "Puerta Balcón (PBalcon)",
        "binary_sensor.panel_home_ralphi_zona_08": "Puerta Cuarto (PCuarto)",
        "binary_sensor.panel_home_ralphi_zona_09": "Sensor Movimiento Entrada (SEntrada)",
        "binary_sensor.panel_home_ralphi_zona_10": "Sensor Movimiento Disco (SDisco)",
        "binary_sensor.panel_home_ralphi_zona_11": "Sensor Movimiento Cuarto (SCuarto)",
        "binary_sensor.panel_home_ralphi_zona_12": "Cuarto Paneles (CMPaneles)",
    }
    for i in range(13, 25):
        zid = f"binary_sensor.panel_home_ralphi_zona_{i:02d}"
        if zid not in zone_friendly_names:
            zone_friendly_names[zid] = f"Zona {i:02d}"

    # Bootstrap inicial de estados si no hay historial guardado
    first_run = len(ha_states_history) == 0
    current_ha = get_ha_states()
    for eid, s in current_ha.items():
        if eid in zone_friendly_names or eid == "alarm_control_panel.panel_home_ralphi_panel_home_ralphi":
            if eid not in ha_states_history:
                ha_states_history[eid] = s.get("state")

    if HUB_AVAILABLE and hub and hub.configured():
        for dev_id in ["2", "4"]:
            if dev_id not in hubitat_states_history:
                dev = hub.get_device(dev_id)
                if dev.get("ok"):
                    hubitat_states_history[dev_id] = dev.get("attributes", {})

    # Guardar snapshot inicial
    save_state({"ha": ha_states_history, "hubitat": hubitat_states_history})

    # Notificar inicio del servicio
    dispatch_alert(
        "🛡️ InnerOS Sentinel Conectado",
        "Monitoreo dual de Alarma Intelbras y Sensores Hubitat en línea.\nNotificaciones activas en NTFY y Telegram.",
        tags="white_check_mark,shield",
        priority="default"
    )

    loop_count = 0
    while True:
        try:
            loop_count += 1
            # 1. Monitoreo de Alarma Intelbras (Home Assistant)
            ha_live = get_ha_states()
            state_changed_any = False

            for eid, name in zone_friendly_names.items():
                ent = ha_live.get(eid)
                if not ent:
                    continue
                curr_state = ent.get("state")
                prev_state = ha_states_history.get(eid)

                if prev_state and curr_state != prev_state:
                    state_changed_any = True
                    if curr_state == "on":
                        # Apertura o detección de movimiento
                        dispatch_alert(
                            f"🚨 ALERTA: {name}",
                            f"Estado: ABIERTO / DETECCIÓN\n📍 {name}",
                            tags="door,warning" if "Puerta" in name else "walking,warning",
                            priority="high",
                            detected_at=ent.get("last_changed") or ent.get("last_updated"),
                        )
                    elif curr_state == "off":
                        # Cierre o normalización
                        dispatch_alert(
                            f"✅ NORMAL: {name}",
                            f"Estado: CERRADO / NORMAL\n📍 {name}",
                            tags="heavy_check_mark",
                            priority="default",
                            detected_at=ent.get("last_changed") or ent.get("last_updated"),
                        )
                    elif curr_state in ("unavailable", "unknown") and prev_state not in ("unavailable", "unknown"):
                        dispatch_alert(
                            f"⚠️ SENSOR INDISPONIBLE: {name}",
                            f"El sensor pasó a estado {curr_state.upper()}.",
                            tags="grey_question",
                            priority="low"
                        )
                    ha_states_history[eid] = curr_state

            # Panel de Alarma
            panel_eid = "alarm_control_panel.panel_home_ralphi_panel_home_ralphi"
            panel_ent = ha_live.get(panel_eid)
            if panel_ent:
                curr_panel_state = panel_ent.get("state")
                prev_panel_state = ha_states_history.get(panel_eid)
                if prev_panel_state and curr_panel_state != prev_panel_state:
                    state_changed_any = True
                    dispatch_alert(
                        f"🛡️ PANEL DE ALARMA INTELBRAS",
                        f"Estado del panel cambió: {prev_panel_state} ➡️ {curr_panel_state}",
                        tags="lock" if curr_panel_state != "disarmed" else "unlock",
                        priority="high" if curr_panel_state == "triggered" else "default"
                    )
                    ha_states_history[panel_eid] = curr_panel_state

            # 2. Monitoreo de Sensores Hubitat (cada ciclo o cada 2 ciclos)
            if HUB_AVAILABLE and hub and hub.configured():
                try:
                    for dev_id, dev_name in [("2", "SMagnetico01 (Puerta/Contacto)"), ("4", "Multisensor 6 (Disco/Movimiento)")]:
                        dev = hub.get_device(dev_id)
                        if not dev.get("ok"):
                            continue
                        attrs = dev.get("attributes", {})
                        prev_attrs = hubitat_states_history.get(dev_id, {})

                        # Contacto
                        if "contact" in attrs:
                            c_curr = attrs["contact"]
                            c_prev = prev_attrs.get("contact")
                            if c_prev and c_curr != c_prev:
                                state_changed_any = True
                                is_open = c_curr == "open"
                                hub_ts = attrs.get("Last Activity") or attrs.get("lastActivity")
                                dispatch_alert(
                                    f"{'🚨' if is_open else '✅'} HUBITAT CONTACTO: {dev_name}",
                                    f"Estado: {c_curr.upper()}\n📍 Hubitat · {dev_name}",
                                    tags="door,open" if is_open else "door,closed",
                                    priority="high" if is_open else "default",
                                    detected_at=hub_ts,
                                )

                        # Movimiento
                        if "motion" in attrs:
                            m_curr = attrs["motion"]
                            m_prev = prev_attrs.get("motion")
                            if m_prev and m_curr != m_prev:
                                state_changed_any = True
                                is_active = m_curr == "active"
                                hub_ts = attrs.get("Last Activity") or attrs.get("lastActivity")
                                dispatch_alert(
                                    f"{'🏃' if is_active else '✅'} HUBITAT MOVIMIENTO: {dev_name}",
                                    f"Detección: {m_curr.upper()}\n📍 Hubitat · {dev_name}",
                                    tags="walking,warning" if is_active else "white_check_mark",
                                    priority="high" if is_active else "default",
                                    detected_at=hub_ts,
                                )

                        hubitat_states_history[dev_id] = attrs
                except Exception as he:
                    if loop_count % 30 == 0:
                        print(f"[Hubitat Poll Error] {he}", file=sys.stderr)

            if state_changed_any or loop_count % 50 == 0:
                save_state({"ha": ha_states_history, "hubitat": hubitat_states_history})

        except Exception as exc:
            print(f"[Poll Loop Error] {exc}", file=sys.stderr)

        time.sleep(2.5)


if __name__ == "__main__":
    main_loop()
