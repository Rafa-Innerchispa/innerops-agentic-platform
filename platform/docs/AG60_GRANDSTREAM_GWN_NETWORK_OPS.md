# AG-60 Grandstream GWN Network Operations

Integración al estilo **UniFi ops** (`observe → diagnose → governed action → verify`) para **GWN Cloud**, inventario Mongo/local y sonda del gateway GCC en sitio.

## MCP tools

| Tool | Uso |
|------|-----|
| `grandstream_gwn_network_ops` | Diagnóstico completo (APs, SSIDs, switches, clientes cloud cuando hay credenciales) |
| `grandstream_gwn_api_capabilities` | Qué está soportado vs UniFi/HA (gaps honestos) |
| `grandstream_gwn_ssid_update` | Cambios SSID en cloud (dry-run por defecto; requiere `owner_approval_ref`) |
| `device_fabric_inventory` con `live=true` | Inventario Mongo + snapshot GWN Cloud |
| `run_home_ops_cycle(message=...)` | Enruta mensajes GWN/Bellini/GCC antes del digest genérico |

## Credenciales GWN Cloud

1. En [GWN Cloud](https://www.gwn.cloud) → **API Developer** → activar modo desarrollador → copiar **APP ID** y **Secret Key**.
2. Configurar en el runtime (AMD `:8112`):

```bash
export GWN_CLOUD_APP_ID="..."
export GWN_CLOUD_SECRET_KEY="..."
export GWN_CLOUD_NETWORK_ID_BELLINI="..."   # opcional si hay varias redes
export GWN_CLOUD_NETWORK_ID_HOME="..."      # lab casa
```

Alternativa: `owner_vault` categoría `gwn_cloud` con claves `app_id` y `secret_key`.

## Paridad vs UniFi en casa

| Capacidad | UniFi (HA) | Grandstream GWN (InnerOS) |
|-----------|------------|---------------------------|
| APs / estado | Sí (integración HA) | Sí (`ap/list` cloud) |
| SSIDs / clientes WLAN | Conteos vía HA | Sí (`ssid/list`, `client/list`) |
| Switches / puertos | Parcial vía HA | Inventario switch cloud; detalle puerto según payload API |
| Router GCC local | N/A | Sonda read-only (`device_fabric_probe` 192.168.3.1) |
| Cambios RF/canal | Fail-closed | Fail-closed + vía SSID gobernado |
| Multi-sitio | Un controller | Redes GWN Cloud + tenants Mongo |

## Validación

```bash
cd /home/rlopez/inneros/inneros_core/platform
PYTHONPATH=. pytest tests/test_ag32_grandstream_gwn_network_ops.py tests/test_device_fabric_fresh.py tests/test_ag32_unifi_network_ops.py -q
```
