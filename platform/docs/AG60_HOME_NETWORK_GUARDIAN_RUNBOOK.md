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


## Arquitectura extensible universal (9 octubre 2026)

El monitor no está ligado a marcas: `protocol_catalog.py` registra familias y fuentes,
`communication_observer.py` interpreta estados vivos de HA con degradación explícita,
`physical_bus_observer.py` enumera NIC, USB, tty/serial, Bluetooth y estado Tailscale
solo **en el host donde corre**, `unifi_readonly.py` utiliza la API oficial GET-only
y `communication_history.py` registra eventos históricos y correlacionados.

- **IP/Ethernet:** ICMP/TCP, carrier, cambios y errores en NIC; detección por HTTP,
  HTTPS, RTSP, servicios Dahua/Hikvision y MQTT/Modbus TCP solo como indicios.
- **UniFi:** API local GET /integration/v1/sites, devices, clients, device details,
  uplink, PoE, puerto y canal (si versión/clave de API lo permiten). Se requiere
  `UNIFI_LOCAL_API_KEY` y, si hace falta, `UNIFI_LOCAL_CA_BUNDLE`. Nunca desactivar
  verificación TLS sin autorización. Fuente: https://developer.ui.com/network/
- **CCTV / porteros:** Dahua, Hikvision, Imou, EZVIZ, Axis y fabricantes futuros.
  ONVIF/RTSP/HTTP solo detectan disponibilidad de servicio, no garantizan video ni
  autenticación del dispositivo. Imou no dispone aún de adaptador nativo validado.
- **IoT inalámbrico:** Zigbee/ZHA/Zigbee2MQTT, Matter, Thread, Z-Wave, BLE, RF 315/433/868/915,
  LoRa y gateways. Un sensor sin heartbeat o protocolo sin ACK no puede declararse
  desconectado solo porque su estado no cambie. Registrar disponibilidad del gateway
  y las señales de calidad del proveedor cuando existan.
- **Buses e industria:** RS232/422/485, Modbus RTU/TCP, USB HID/CDC, UART,
  CAN, CANopen, KNX, BACnet, DMX, DALI, OSDP, Wiegand, GPIO, I2C, SPI. La presencia
  de un adaptador no implica que su bus ni los dispositivos detrás estén comunicándose.
  Implementar colectores específicos para cada protocolo/caso.
- **Energía:** Pi01 (192.168.1.97) conectado a Xmart vía USB HID 0665:5161,
  datos publicados a HA por integración solar. AG-32 es propietario del dominio
  domótico/energético; AG-60 supervisa LAN/USB y frescura de las fuentes. El USB del
  inversor solo se verifica ejecutando colector **en Pi01**, no en AMD remoto.
- **Tailscale:** lectura de backend/status del nodo local, no configuración de rutas
  ni DNS del teléfono remoto sin agente y permisos en ese dispositivo.
- **Marcas futuras:** si no existe adaptador validado, el equipo entra en inventario
  como `UNKNOWN` y se informa `collector_missing`, nunca `ONLINE` inventado.

### Cadencias propuestas (sin habilitar en producción)

- **90 s**: servicio `inneros-ag60-communications.timer` para HA/UniFi, estado
  de host, eventos y cuatro IP críticas (.1/.4/.5/.97).
- **15 min**: `inneros-ag60-lan-discovery.timer`, barrido acotado solo a
  `192.168.1.0/24`; no explora otras redes ni intenta autenticaciones.
- **Edge host Pi01**: publicar telemetría USB HID y estado del servicio solar
  desde el Raspberry Pi; un sondeo TCP desde AMD no reemplaza esta lectura.

### Verificación real obligatoria antes de habilitar

1. Ejecutar `python3 -m pytest -q platform/tests/test_ag60_*.py` en rama desplegable.
2. Corregir divergencia del checkout local respecto a GitHub y confirmar versión
   de `inneros_core_runtime`; no desplegar worktree de pruebas como si fuera producción.
3. Confirmar API UniFi, su CA y permisos solo lectura, y almacenar token en vault.
4. Comprobar al menos una muestra real de Pi01 USB y del portero Dahua.
5. Ejecutar piloto sin `--save`; luego habilitar Mongo con índices y retención.
6. Activar y observar los timers; correlacionar eventos en ventana de 24 h antes de
   considerar AG-60 operativo.

**Estado:** implementación candidata en PR #133; no equivale a monitor desplegado,
ni a cobertura RF completa o compatibilidad nativa con todas las marcas.
