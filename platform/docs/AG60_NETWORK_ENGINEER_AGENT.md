# AG-60 Network Engineer Agent — contrato canónico

AG-60 se amplía como el ingeniero de redes de InnerOS. No se crea otro agente vacío.

## Objetivo
Recibir órdenes humanas como "revisa toda esta red", "por qué se cae esta cámara", "qué hay conectado a este puerto" o "separa dos edificios", y ejecutar el máximo trabajo posible con evidencia.

## Observe / Diagnose
Por defecto opera en lectura:
- inventario L2/L3;
- identidad estable por asset_id, MAC, serial y provider ID;
- puertos, link, velocidad, PoE, PVID, VLAN, FDB/MAC table, STP y errores cuando el proveedor lo exponga;
- routing, subnets, DHCP, rutas, WAN, NAT y ACL cuando exista adapter;
- Wi-Fi: AP, radio, canal, ancho, RSSI, retries, roaming y SSID→VLAN;
- CCTV, videoporteros, PBX y control de acceso desde la perspectiva de red;
- ping, TCP acotado, path probe y comparación temporal;
- topología, enlaces, failure domains y confianza de cada edge;
- baseline e historial de cambios;
- investigación multi-fuente: Device Fabric, APIs de fabricante, Tailscale, Guardian y documentación persistente.

## Act / Verify
Toda mutación sigue:
observe → snapshot → plan → policy/approval → change → verify → rollback if needed → evidence

Las mutaciones solo se permiten detrás de operaciones gobernadas y con rollback verificable.

## Persistencia y recuperación
### InnerOS / Mongo
Verdad operativa completa:
- network_engineer_site_facts
- network_engineer_findings
- network_engineer_snapshots
- colecciones existentes de samples/eventos de AG-60.

### GitHub
Se versiona:
- código y adapters;
- contratos y runbooks;
- manifest sanitizado por sitio;
- modelos, roles, vendors y hallazgos no sensibles;
- hashes e índice de snapshots.

No se versiona información sensible en texto plano.

### Disaster Recovery cifrado
Debe contener MongoDB, vault, llave de cifrado y runtime env necesarios, con restore drill probado.

## Sitio sin credenciales
Sin acceso administrativo el agente todavía puede hacer discovery dentro del alcance autorizado, identificar servicios y fabricantes, construir un mapa probable de red y determinar qué información falta. La recuperación de acceso debe seguir los procedimientos oficiales del fabricante y la autorización del cliente.

## Bellini I-II / III-IV
Política objetivo:
- cada edificio es un dominio de seguridad separado;
- DEFAULT DENY lateral I-II ↔ III-IV;
- management solo desde origen autorizado;
- servicios comunales futuros en una zona shared-services con reglas explícitas;
- antes de cambiar: identificar puerto físico, PVID/tagged/native, gateway/DHCP, dependencia WAN y rollback;
- después: canarios bidireccionales de aislamiento y continuidad de servicio.

## Criterio de terminado
Una auditoría termina solo si:
- scope y gaps están explícitos;
- hechos tienen fuente y timestamp;
- hallazgos están persistidos;
- snapshot/evidence hash existe;
- si hubo cambio, hay before/after + rollback + canarios;
- el manifest sanitizado de recuperación se puede regenerar.
