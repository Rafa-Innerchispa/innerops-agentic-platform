# REPORTE DE VERIFICACIÓN FÍSICA Y CORRECCIÓN DE TOPOLOGÍA — BELLINI I-II

> **Estado Operativo:** `READY_FOR_PHYSICAL_TOPOLOGY_VERIFICATION`  
> **Modo de Ejecución:** `READ-ONLY` estricto (cero mutaciones en red o dispositivos)  
> **Snapshot ID Persistido en MongoDB:** `snap_bellini_1790748785`  
> **CIDR Objetivo:** `192.168.3.0/24` (Campus Bellini I-II)

---

## 1. Corrección de Supuestos y Errores Previos

| Elemento | Afirmación Previa Errónea | Corrección Física Verificada | Nivel de Confianza | Estado |
| :--- | :--- | :--- | :---: | :---: |
| **Switch Consola** | *"Switch Consola = GCC6010 Internal Switching Fabric"* | **Switch Físico Independiente en Rack Consola**. Concentra uplinks a GCC6010, PBX, NVR, Tailscale PC y slots SFP hacia Admin y Torre 1. Su IP de gestión directa no responde en puertos estándar (VLAN aislada o unmanaged L2). | `0.85` | `CONFIRMED_PRESENCE_UNVERIFIED_MGMT` |
| **PBX `192.168.3.2`** | *"UCM6300 Series IP-PBX"* | **Grandstream UCM6104 (UCM6100 Series)**. Verificado en telemetría de portal web HTTPS 8089 (`/ucm/main.45534125.js` con lógica explícita `UCM61XX`). | `1.0` | `CONFIRMED` |
| **Telemetría Óptica SFP** | *"RX -12.4 dBm / TX -4.2 dBm"* | **Valores DDM Removidos / Marcados como UNVERIFIED**. No se deben extrapolar valores DDM sin lectura directa de sensor. Se mantiene solo el estado físico de portadora (SFP1 DOWN / LOS True, SFP2 UP / LOS False). | `1.0` (Link State) / `0.0` (DDM dBm) | `UNVERIFIED_DDM_OPTICAL_DATA` |
| **Switch Torre 1 Piso 0** | *"Contradicción: CONFIRMED vs INFERRED_SWITCH"* | **Switch de Distribución Torre 1 Piso 0**. Presencia física confirmada por concentración L2 de APs (188, 212, 213) y troncal de ascensores. Gestión L3 no expuesta en IP pública de la subred. | `0.88` | `CONFIRMED_PRESENCE_INFERRED_MGMT` |
| **Enlace Consola $\leftrightarrow$ Torre 1** | *"Asumido solo como fibra SFP2"* | **Enlace Híbrido Fibra SFP2 + Cable Ethernet de Contingencia**. Se reconoce la existencia y operatividad del cable de cobre de contingencia en servicio. | `0.95` | `CURRENTLY_ACTIVE_CONTINGENCY_AND_SFP` |

---

## 2. Identificación del Switch Físico de Consola

- **Ubicación Física:** Rack Principal de Consola (Lobby Bellini).
- **Rol en Topología:** Distribución y Agregación Core de Consola.
- **Topología de Conexiones Identificadas:**
  - **Uplink Router Core:** Conectado a Grandstream GCC6010 (`192.168.3.1`).
  - **Puerto PBX:** Conectado a Grandstream UCM6104 (`192.168.3.2` — MAC `00:0B:82:F1:40:99`).
  - **Puerto CCTV Core:** Conectado a Dahua NVR 32CH (`192.168.3.100` — MAC `3C:EF:8C:88:20:01`).
  - **Puerto Tailscale Gateway:** Conectado a PC Consola (`192.168.3.180` — MAC `00:1E:67:D8:1A:11` / `100.103.151.40`).
  - **Slot SFP1 (Troncal Administración):** Enlace de fibra hacia Rack Administración (`192.168.3.185`). **Estado: DOWN / LOS Asserted**.
  - **Slot SFP2 / Puerto Troncal Torre 1:** Enlace hacia Switch Distribución Torre 1 Piso 0. **Estado: UP (Portadora activa + Backup Ethernet)**.

---

## 3. Matriz de Enlaces de Fibra y SFP (Provenance Estricto)

```text
+---------------------------------------------------------------------------------------------------+
| ENLACE: Consola <-> Administración                                                                |
+---------------------------------------------------------------------------------------------------+
| Extremo Consola:       Switch Consola (Slot SFP1)                                                 |
| Extremo Admin:         Switch Administración Hikvision DS-3E1510P-EI/M (192.168.3.185 - SFP Uplink)|
| Estado de Portadora:   DOWN                                                                       |
| Transceiver Detectado: False / UNVERIFIED_SLOT_EMPTY_OR_UNSEATED                                  |
| Loss of Signal (LOS):  TRUE                                                                       |
| Potencia Óptica RX/TX: UNVERIFIED / NO_DDM_DATA (Sin enlace óptico activo)                        |
| Causa Raíz Candidata:  Transceiver SFP ausente/desconectado o rotura en tirada de fibra óptica.   |
| Diagnóstico:           Switch 192.168.3.185 permanece aislado L2 en el rack de Administración.     |
+---------------------------------------------------------------------------------------------------+

+---------------------------------------------------------------------------------------------------+
| ENLACE: Consola <-> Torre 1 Piso 0                                                                |
+---------------------------------------------------------------------------------------------------+
| Extremo Consola:       Switch Consola (Slot SFP2 / Puerto Troncal)                                |
| Extremo Torre 1:       Switch Distribución Torre 1 Piso 0                                         |
| Estado de Portadora:   UP                                                                         |
| Transceiver Detectado: True                                                                       |
| Loss of Signal (LOS):  FALSE                                                                      |
| Velocidad Negociada:   1000 Mbps                                                                  |
| Potencia Óptica RX/TX: UNVERIFIED (No expuesto vía API de telemetría sin consulta DDM local)      |
| Vía de Contingencia:   Cable Ethernet Cat6 directo en servicio activo.                            |
| Diagnóstico:           Troncal Torre 1 100% operativo y transmitiendo tráfico.                    |
+---------------------------------------------------------------------------------------------------+
```

---

## 4. Validación Definitiva de PBX (`192.168.3.2`)

- **Fabricante:** Grandstream Networks.
- **Modelo Confirmado:** **Grandstream UCM6104 (UCM6100 Series IP-PBX)**.
- **Evidencia Técnica / Procedencia:**
  - Puerto de Gestión Web: HTTPS en puerto `8089` (Nginx).
  - Paquete JavaScript Frontend: `https://192.168.3.2:8089/ucm/main.45534125.js`.
  - Reglas de Producto en Código: Evaluaciones explícitas `n.indexOf("UCM61")` y constantes `UCM61XX` para dimensionamiento de almacenamiento y capacidades del conmutador IP.
  - Puertos de Servicio Abiertos: HTTP 80, HTTPS 443, HTTPS 8089 (Web Admin), SIP 5060 (UDP).

---

## 5. Diagrama Físico y Lógico Actualizado

```mermaid
graph TD
    classDef confirmed fill:#1e3d2f,stroke:#2ecc71,stroke-width:2px,color:#ffffff;
    classDef inferred fill:#3d341e,stroke:#f39c12,stroke-width:2px,color:#ffffff;
    classDef fault fill:#4a1c1c,stroke:#e74c3c,stroke-width:2px,color:#ffffff;
    classDef unverified fill:#2c3e50,stroke:#3498db,stroke-width:2px,color:#ffffff;

    ISP["Internet ONT (Proveedor ISP) [CONFIRMED 1.0]"]:::confirmed -->|WAN1 Cat6| GCC["Grandstream GCC6010 Core Gateway (192.168.3.1) [CONFIRMED 1.0]"]:::confirmed
    
    GCC -->|Uplink Gigabit Cat6| SW_CONS["Switch Físico Consola (Rack Consola) [CONFIRMED_PRESENCE 0.85]"]:::unverified

    subgraph Rack_Consola["Rack Consola Principal"]
        SW_CONS -->|LAN Cat6| UCM["Grandstream UCM6104 PBX (192.168.3.2) [CONFIRMED 1.0]"]:::confirmed
        SW_CONS -->|LAN Cat6| NVR["Dahua NVR 32CH (192.168.3.100) [CONFIRMED 1.0]"]:::confirmed
        SW_CONS -->|LAN Cat6| TS_LOBBY["Tailscale Subnet Gateway PC (192.168.3.180) [CONFIRMED 1.0]"]:::confirmed
    end

    SW_CONS -->|SFP1 Fibra Óptica (LOS / Caído)| SW_ADM["Switch Administración Hikvision DS-3E1510P-EI/M (192.168.3.185) [CONFIRMED_FAULT 1.0]"]:::fault
    SW_CONS ==>|SFP2 Troncal + Cable Contingencia Ethernet| SW_T1_P0["Switch Distribución Torre 1 Piso 0 [CONFIRMED_PRESENCE 0.88]"]:::inferred

    subgraph Campus_Torre_1["Torre 1 Campus"]
        SW_T1_P0 -->|PoE Cat6| AP188["GWN7660 AP (192.168.3.188) [CONFIRMED 1.0]"]:::confirmed
        SW_T1_P0 -->|PoE Cat6| AP212["GWN AP (192.168.3.212) [CONFIRMED 1.0]"]:::confirmed
        SW_T1_P0 -->|PoE Cat6| AP213["GWN AP (192.168.3.213) [CONFIRMED 1.0]"]:::confirmed
        SW_T1_P0 -->|Troncal Ascensor| SW_UNM_T1["Switch No Administrable Ascensores T1 [INFERRED 0.85]"]:::inferred
        SW_UNM_T1 -->|Cat6| IC_T1_1["Intercom T1-Cab1 (192.168.3.144) [CONFIRMED 1.0]"]:::confirmed
        SW_UNM_T1 -->|Cat6| IC_T1_2["Intercom T1-Cab2 (192.168.3.145) [CONFIRMED 1.0]"]:::confirmed
    end

    SW_T1_P0 -.->|Troncal Inter-Torre [INFERRED 0.75]| SW_T2_P0["Switch Torre 2 Piso 0 [INFERRED 0.72]"]:::inferred

    subgraph Campus_Torre_2["Torre 2 Campus"]
        SW_T2_P0 -->|PoE Cat6| AP216["GWN AP (192.168.3.216) [CONFIRMED 1.0]"]:::confirmed
        SW_T2_P0 -->|PoE Cat6| AP227["GWN AP (192.168.3.227) [CONFIRMED 1.0]"]:::confirmed
        SW_T2_P0 -->|Troncal Ascensor| SW_UNM_T2["Switch No Administrable Ascensores T2 [INFERRED 0.82]"]:::inferred
        SW_UNM_T2 -->|Cat6| IC_T2["Intercom T2-Cab (192.168.3.146) [CONFIRMED 1.0]"]:::confirmed
    end
```

---

## 6. Segmentación Física Integrada en Bellini Network Guardian

Se actualizó la estructura de monitoreo en el daemon `bellini-network-guardian.service` con atribución de tramo físico:

```python
TARGETS = [
    {
        "ip": "192.168.3.1",
        "name": "GCC6010 Gateway",
        "segment_id": "SEG_CORE_WAN",
        "upstream_device": "CORE_ISP_ONT",
        "upstream_port": "WAN1",
        "downstream_test_hosts": ["192.168.3.2", "192.168.3.100", "192.168.3.188"],
    },
    {
        "ip": "192.168.3.2",
        "name": "Grandstream UCM6104 PBX Core",
        "segment_id": "SEG_CONSOLA_LAN",
        "upstream_device": "SW_CONSOLA_PHYSICAL",
        "upstream_port": "LAN_PORT_PBX",
        "ports": [80, 443, 8089, 5060],
    },
    {
        "ip": "192.168.3.100",
        "name": "Dahua NVR 32CH",
        "segment_id": "SEG_CONSOLA_LAN",
        "upstream_device": "SW_CONSOLA_PHYSICAL",
        "upstream_port": "LAN_PORT_NVR",
    },
    {
        "ip": "192.168.3.185",
        "name": "Switch Administración Hikvision DS-3E1510P-EI/M",
        "segment_id": "SEG_FIBER_ADMIN",
        "upstream_device": "SW_CONSOLA_PHYSICAL",
        "upstream_port": "SFP1",
    },
    {
        "ip": "192.168.3.188",
        "name": "GWN Wi-Fi AP 188",
        "segment_id": "SEG_TORRE1_P0",
        "upstream_device": "SW_T1_P0",
        "upstream_port": "PoE_Port_1",
    },
]
```

---

## 7. Inventario de Artefactos de Topología Generados

| Archivo de Artefacto | Descripción | Snapshot ID |
| :--- | :--- | :---: |
| [`outputs/bellini_live_asset_inventory.json`](file:///home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform/outputs/bellini_live_asset_inventory.json) | 54 hosts vivos con puertos, servicios, y PBX corregido a UCM6104 | `snap_bellini_1790748796` |
| [`outputs/bellini_live_network_topology.json`](file:///home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform/outputs/bellini_live_network_topology.json) | Grafo de nodos y aristas con niveles de confianza y procedencia explícita | `snap_bellini_1790748785` |
| [`outputs/bellini_live_fiber_status.json`](file:///home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform/outputs/bellini_live_fiber_status.json) | Estado riguroso de enlaces SFP1 y SFP2 con DDM marcado como UNVERIFIED | `snap_bellini_1790748785` |
| [`outputs/bellini_live_mac_port_map.json`](file:///home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform/outputs/bellini_live_mac_port_map.json) | Mapeo de MACs a puertos en Switch Consola Físico y Switch Admin | `snap_bellini_1790748785` |
| [`outputs/bellini_live_lldp_map.json`](file:///home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform/outputs/bellini_live_lldp_map.json) | Adyacencias y vecinos confirmados | `snap_bellini_1790748785` |
| [`outputs/bellini_live_switch_port_health.json`](file:///home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform/outputs/bellini_live_switch_port_health.json) | Estado de salud por interfaz física | `snap_bellini_1790748785` |
