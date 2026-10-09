# AG-60 Guardian de red: operación local

## Implementado en esta rama (no desplegado)
- `network.guardian.scan.v1` en el broker de capacidades, sin expandir el catálogo MCP Small.
- Sondeos ICMP y TCP con límites estrictos de CIDR autorizado, hosts y concurrencia.
- Estado `UNKNOWN` cuando un host no responde, no `OFFLINE` inventado.
- Inventario HA deja de marcar todos los dispositivos como `ONLINE` por defecto.
- Lectura de la entidad `State` de AP UniFi a través de HA, con timestamp y MAC disponibles.
- Mongo local: `network_device_state`, `network_device_samples`, `network_device_events`. Transiciones solo con evidencia, dos comprobaciones sin respuesta para marcar pérdida de monitorización.
- Pruebas: `platform/tests/test_ag60_home_inventory_truth.py` y `platform/tests/test_ag60_network_guardian.py`.

## Verificación previa al despliegue
```bash
cd platform
python3 -m pytest tests/test_ag60_home_inventory_truth.py tests/test_ag60_network_guardian.py -q
python3 -m inneros_core_runtime.network_guardian --site home_pcdoctor_lab --limit-hosts 12
```
**No habilitar el servicio antes de pasar las pruebas y comparar sus IP con la topología real.** Para evitar escaneos continuos de 254 hosts, el primer piloto será de una muestra limitada.

## Activación local controlada
Programar desde systemd timer o scheduler interno SOLO después de la verificación, como unidad de usuario bajo un usuario sin privilegios y con acceso limitado a Mongo, y comando:
```bash
python3 -m inneros_core_runtime.network_guardian --site home_pcdoctor_lab --limit-hosts 254 --save
```
Cadencia inicial recomendada: cada 60-120 s; reducir después de medir carga/ruido. No ejecutar sobre redes ajenas. El inventario activo omite hosts no receptivos y solo reclama detección de pérdida de monitorización, NO comprobación de fallo físico. Mantener colección temporal con retención apropiada y índices `site_id`/`ip`/`observed_at`.

## Pendiente para calidad de técnico experto
1. Integración autenticada **read-only** con API local UniFi: switch ports, PoE, link-flap, AP adoption/restart, radios, canales, channel-utilization, RSSI, retries, clientes/roaming, eventos 24-72h.
2. Enriquecimiento SSH/SNMP en switches compatibles, con credenciales en vault, sin cambios de configuración.
3. Tailscale por peer: rutas aceptadas y anunciadas, DNS/exit-node, netcheck y logs.
4. Escaneo ARP pasivo/vecinos con mapeo L2 LLDP y correlación por puerto y dominio de broadcast.
5. Identificación del videoportero Dahua por MAC/IP real, y comprobación de asociación/SSID/roaming.
6. Correlación multi-origen WAN/gateway/switch/AP/Wi-Fi/IoT/servidor; informe con pruebas y causas graduadas.
7. Baseline de ruido en 2.4 GHz y plano por piso antes de optimizar canales, potencias o ancho.
8. Dashboard, retención, alertas deduplicadas y pruebas reales de falla inducida con autorización.

## Política
Solo lectura a dispositivos: no reinicios, cambios Wi-Fi, firmware, VLAN, DHCP ni PoE sin aprobación.
Modelos locales para interpretar evidencia, nunca para inventarla. No afirmar `ONLINE` solo por presencia en registro HA.
