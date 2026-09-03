# AG-32 Ambient Intelligence & Home Assistant Orchestrator

**Numeración:** AG-32 · **ID:** `AG-32_home_assistant_bridge`
**Categoría:** Ecosistema Domótico y Control Escénico Integral

Puente y orquestador físico/ambiental entre InnerOS (MCP, voz, IA) y la infraestructura domótica unificada en el servidor Home Assistant (`http://192.168.1.4:8123`).

---

## Áreas y Protocolos Bajo Control de AG-32

1. **Home Assistant Master Hub (`192.168.1.4:8123`):**
   - Entidades (`light`, `switch`, `climate`, `scene`, `sensor`, `cover`, `media_player`).
   - Automatizaciones, scripts y grupos inteligentes.

2. **Hubitat Elevation Hub:**
   - Redes de malla Zigbee y Z-Wave para cerraduras, sensores de presencia, pulsadores y contactos de puerta integrados transparentemente en Home Assistant.

3. **Broadlink Universal Remotes:**
   - Transmisores IR y RF (433MHz / 315MHz) para climatización (A/C), pantallas, proyectores y motores de cortinas.

4. **DMX512 & Art-Net Engine (`inneros-dmx-engine`):**
   - Nodo físico: **Pknight CR011R** (`192.168.1.10:6454`, Universo 0).
   - Control de 9 dispositivos escénicos:
     * 2x Moving Heads Spider RGBW (Eurolite EL-LMH1240WB, 19 canales c/u).
     * 2x Pinspot Beams 12W RGBW (6 canales c/u).
     * 4x Tachos PAR LED RGB/RGBW (Escalera, Peces, Central, Plantas).
     * 1x Crystal Magic Ball Disco (Motor + RGBW + Estrobo).
   - Módulo satélite en: `/home/rlopez/projects/inneros-dmx-engine` (GitHub: `Rafa-Innerchispa/inneros-dmx-engine`).

---

## Capacidades y Flujos de IA

- **Síntesis de Ambientes:** AG-32 coordina simultáneamente el aire acondicionado (Broadlink), el clima/iluminación ambiental (Hubitat/Zigbee) y la escenografía DMX (Art-Net).
- **Control por Voz y MCP:** `ha_ping`, `ha_list_entities`, `ha_get_entity`, `ha_turn_on_light`, `ha_turn_off_light`, `ha_call_service`, `run_home_ops_cycle`.
- **Snapshot Cache:** `/home/rlopez/data/ralfia/ha_state.json`.

---

## Variables de Entorno

```bash
export HOME_ASSISTANT_URL=http://192.168.1.4:8123
export HOME_ASSISTANT_TOKEN=...
export DMX_ARTNET_NODE_IP=192.168.1.10
export DMX_ARTNET_UNIVERSE=0
```
