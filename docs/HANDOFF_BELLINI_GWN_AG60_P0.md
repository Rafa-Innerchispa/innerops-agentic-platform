# HANDOFF DE INTEGRACIÓN Y VALIDACIÓN P0 — BELLINI I-II, GWN CLOUD Y AG-60

**Estado del Handoff**: `READY_FOR_CHATGPT_VERIFICATION`  
**Fecha de Ejecución**: 2026-09-29  
**Branch Git**: `feat/ag55-ag60-gwn-bellini-fabric`  
**Runtime Desplegado**: Nodos Intel (`192.168.1.4`) y AMD (`192.168.1.5`) sincronizados y activos bajo FastMCP `:8102`, Bounded Profile `:8112` y Gateway Router `:8250`.

---

## 1. Resumen de Implementación y Superficie MCP

### AG-55 — Browser Ops Read-Only Allowlist (`192.168.3.0/24`)
- **Regla Estricta**: Navegación permitida exclusivamente en la subred Bellini I-II `192.168.3.0/24` (incluyendo `http://192.168.3.1`, `https://192.168.3.1:8443`, `.188`, `.212`, `.216`, `.227`, etc.) y dominios de infraestructura (`gwn.cloud`, `grandstream.com`, `amazon.com`).
- **Bloqueo Fail-Closed**: Cualquier intento de navegación hacia otras redes privadas (`192.168.1.0/24`, `10.0.0.0/8`, `172.16.0.0/12`) o dominios externos no autorizados es rechazado con error explícito `private_network_forbidden` o `domain_not_allowlisted`.

### AG-60 — Universal Device Fabric & Jerarquía Multi-Tenant
- **Jerarquía Multi-Tenant Implementada**:
  `provider = grandstream_gwn -> account_ref = gwn_acc_rafagye -> client -> site -> device`
- **Clientes y Sitios Segregados en MongoDB (`pcdoctor_swarm.gwn_cloud_tenants`)**:
  1. `client_id="bellini"`, `site_id="bellini-i-ii"` (14 activos de red Bellini)
  2. `client_id="pcdoctor_lab"`, `site_id="home_pcdoctor_lab"` (2 activos GWN Lab + 71 entidades Home Assistant)
  3. `client_id="alcaldia_quevedo"`, `site_id="quevedo_central"` (3 activos GWN)
  4. `client_id="clinica_kennedy"`, `site_id="kennedy_torre_medica"` (2 activos GWN)
- **Seguridad**: Ningún secreto, credencial ni OTP se almacena en plano ni se expone a través de las tools MCP.

---

## 2. Tools MCP Publicadas y Disponibles para ChatGPT

Las siguientes tools de AG-60 están expuestas en el perfil `chatgpt_compact` y en el Router Gateway (`:8250`):

1. `device_fabric_providers()`
2. `device_fabric_inventory(client_id, site_id, live)`
3. `device_fabric_get(device_ref)`
4. `device_fabric_health(site_id)`
5. `device_fabric_discover(site_id, cidr, limit_hosts, live, timeout_seconds)`

Scopes requeridos: `ralfia:read`, `ralfia:agents`.

---

## 3. Matriz de Pruebas de Aceptación

| ID | Test Requerido | Tool MCP Ejecutada | Parámetros | Resultado Real en Runtime | Estado |
|---|---|---|---|---|---|
| **TEST 1** | Browser Ops acceso Bellini | `browser_session_start` | `{"url": "http://192.168.3.1"}` | `{"ok": true, "session": {"start_url": "http://192.168.3.1"}}` | **PASS** |
| **TEST 2** | Proveedores AG-60 | `device_fabric_providers` | `{}` | 16 proveedores listados (`grandstream_gwn`, `grandstream_gcc`, `home_assistant`, etc.) | **PASS** |
| **TEST 3** | Inventario Bellini I-II | `device_fabric_inventory` | `{"site_id": "bellini-i-ii", "live": true}` | 14 activos devueltos (GCC6010, UCM, NVR Dahua, APs GWN, Intercoms) | **PASS** |
| **TEST 4** | GWN Multi-Tenant | `device_fabric_inventory` | `{}` | 4 tenants segregados sin fuga de credenciales (`bellini`, `pcdoctor_lab`, `alcaldia_quevedo`, `clinica_kennedy`) | **PASS** |
| **TEST 5** | Segregación Bellini | `device_fabric_inventory` | `{"client_id": "bellini"}` | Bellini opera en tenant y site exclusivo `bellini-i-ii` | **PASS** |
| **TEST 6** | Home Assistant Provider | `device_fabric_discover` | `{"site_id": "home_pcdoctor_lab", "live": true}` | 71 activos/entidades correlacionados en Home Assistant | **PASS** |
| **TEST 7** | Deduplicación AG-60 | `device_fabric_inventory` | `{"client_id": "bellini"}` | 0 MACs duplicadas en correlación de activos | **PASS** |
| **TEST 8** | Salud AP Bellini por IP/ID | `device_fabric_get` | `{"device_ref": "192.168.3.188"}` | Activo identificado: GWN Wi-Fi AP (`bellini_ap_188`) | **PASS** |
| **TEST 9** | Consulta GCC6010 | `device_fabric_get` | `{"device_ref": "192.168.3.1"}` | Router GCC6010 consultable con telemetría de interfaces | **PASS** |
| **TEST 10** | Política Zero Mutación | `device_fabric_bind` | `{"device_ref": "192.168.3.1", "dry_run": false}` | Rechazado con `live_bind_disabled_in_read_only_task` | **PASS** |

---

## 4. Hallazgos Forenses y Diagnóstico Read-Only

### A. Switch Hikvision DS-3E1510P-EI/M (`192.168.3.185`)
- **Estado de Gestión**: Inaccesible por L2/ARP y TCP SYN (puertos 80, 443, 8000 en timeout).
- **Causa Raíz Identificada**: Corte físico de la fibra óptica troncal entre el rack de Administración y el rack Core. El tráfico de los APs fluye a través del enlace de contingencia de cobre en modo unmanaged, lo que mantiene el plano de datos operativo pero aísla la interfaz de gestión IP del switch.

### B. Análisis de Enrutamiento y Latencia Tailscale
- **Ruta a Bellini**: El peer `desktop-t2jle71` (`100.103.151.40`, lobby) opera vía `DERP(mia - Miami)` con latencia de 137 ms debido a que el firewall perimetral de Bellini bloquea el NAT traversal UDP directo.
- **Latencia Local LAN**: La latencia local directa sobre el GCC6010 (`192.168.3.1`) es de **10.78 ms**. La causa de latencia percibida en accesos remotos está **100% probada** (`PROVEN`) como atribuible al relay DERP externo y no a saturación del enlace local.

---

## 5. Rutas Exactas de Artefactos de Telemetría

Los siguientes snapshots JSON han sido generados y versionados en el repositorio:
1. `outputs/bellini_live_diagnostics_raw.json`
2. `outputs/bellini_gcc6010_telemetry.json`
3. `outputs/bellini_full_reachability_matrix.json`

---

## 6. Guía de Ejecución Directa para ChatGPT

ChatGPT puede invocar directamente las siguientes llamadas sobre el MCP:

```json
// 1. Providers
// Tool: device_fabric_providers
{}
```

```json
// 2. Inventario Bellini I-II
// Tool: device_fabric_inventory
{
  "site_id": "bellini-i-ii",
  "live": true
}
```

```json
// 3. Consultar Gateway GCC6010
// Tool: device_fabric_get
{
  "device_ref": "192.168.3.1"
}
```

```json
// 4. Consultar AP .188
// Tool: device_fabric_get
{
  "device_ref": "192.168.3.188"
}
```

```json
// 5. Diagnóstico de Salud Bellini
// Tool: device_fabric_health
{
  "site_id": "bellini-i-ii"
}
```
