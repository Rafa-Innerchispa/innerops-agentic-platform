# WhatsApp Safe Ops — `.4` + `.5`

## Objetivo

RalfIA permite a Rafael consultar y recuperar servicios conocidos desde un chat
1:1 de WhatsApp sin aceptar shell libre, contraseñas, nombres de unidades ni
parámetros arbitrarios. El mismo canal integra texto, audio e imagen como contexto
de conversación y Daily Life Memory, con privacidad `PRIVATE_*`.

## Consultas naturales

- `estado`: consulta los dos servidores.
- `estado .4` o `estado .5`: consulta un nodo.
- `servicios`: consulta el catálogo seguro completo.
- `diagnostica MCP en .5`: muestra estado y hasta 20 líneas saneadas.
- `logs del Panel en .4`: equivalente de solo lectura.

Las consultas no cambian el sistema. Los logs se limitan y se redactan si contienen
campos con aspecto de token, contraseña, secreto, API key, autorización o cookie.

## Operaciones permitidas

Servicios tipados: Panel, MCP, RalfIA App, Coordinación, worker WhatsApp (solo `.4`)
y Evolution API. Acciones tipadas: `start`, `restart` y `recover`.

Ejemplo:

1. Rafael escribe `recupera MCP en .5`.
2. RalfIA comprueba primero el estado. Si ya está sano, no ejecuta nada.
3. Si hace falta actuar, responde con un desafío de seis caracteres válido por
   tres minutos.
4. Rafael responde `confirmar ABC123` desde el mismo número y el mismo chat.
5. El runner toma un lock por nodo/servicio, ejecuta únicamente el comando fijo
   del catálogo, comprueba el estado final y notifica el resultado.

No están permitidos `stop`, reboot, comandos shell, rutas, paquetes, unidades
arbitrarias ni solicitudes de contraseña sudo por WhatsApp.

## Identidad y autorización

Solo la línea principal confirmada de Rafael se registra como `owner` y recibe
`whatsapp:maintenance:confirm`. La línea operativa PC Doctor se registra como
`operational_line`; las cuentas descubiertas desde Evolution se registran como
`service_principal`. Ambas pueden consultar el estado y crear una solicitud,
pero no pueden confirmarla ni ejecutar la acción. Una solicitud creada por esas
líneas se deriva a la línea principal para aprobación.

La autorización procede exclusivamente de `ralfia_whatsapp_identities`:

- la línea principal humana se vincula a `principal_rafael_owner`;
- la línea PC Doctor y cada instancia Evolution usan principales separados y
  nunca heredan el rol `owner`;
- nombre escrito, Google Contacts, CRM o una coincidencia de teléfono no elevan
  privilegios;
- `fromMe`, estados, eventos internos, mensajes salientes y grupos no autorizan
  operaciones;
- una operación requiere una solicitud autorizada y la confirmación posterior
  del principal humano; cuando Rafael inicia la solicitud, la confirmación se
  vincula además al mismo sender y chat.

Mongo conserva el número canónico porque es necesario para autenticar y responder,
pero los reportes y auditorías operativas usan hashes. El bootstrap tiene modo
dry-run y nunca imprime los números.

## Monitor de dos nodos

`ralfia-dual-node-monitor.service` es la única fuente de transiciones de salud y
alertas de disponibilidad para `.4` y `.5`. El temporizador
`ralfia-notify.timer` conserva el polling de correo y coordinación, pero delega
la salud al monitor dual para impedir alertas duplicadas o contradictorias.

`ralfia-dual-node-monitor.service` se instala en `.4` y `.5`. Una lease Mongo hace
que solo uno sea líder; el otro queda standby y asume tras expirar la lease.

- ciclo: 30 segundos;
- alerta: después de dos fallos consecutivos;
- una sola alerta por transición a DOWN;
- recordatorio de falla persistente cada 30 minutos;
- una sola alerta RECUPERADO al volver a estar sano;
- si cae un nodo completo se genera una alerta de nodo, no una tormenta por cada
  servicio;
- el aviso intenta enviarse por Evolution del nodo opuesto y luego por el otro.

La vigilancia externa no depende de acceso SSH cruzado: si falta telemetría SSH
pero el puerto/HTTP responde, el servicio no se declara caído. Esto evita falsos
positivos y evita ampliar permisos entre servidores.

## Colecciones de auditoría

- `ralfia_whatsapp_identities`
- `ralfia_whatsapp_identity_audit`
- `ralfia_whatsapp_admin_jobs`
- `ralfia_whatsapp_admin_audit`
- `ralfia_whatsapp_service_locks`
- `ralfia_dual_node_monitor_state`
- `ralfia_dual_node_monitor_lease`
- `ralfia_dual_node_monitor_audit`

Cada operación registra principal, hashes de sender/chat, nodo, servicio, acción,
estado antes/después, timestamps y correlación cuando existe.

## Instalación y rollback

Antes de desplegar se conserva un snapshot del código y de las unidades de usuario.
La unidad se instala en `~/.config/systemd/user/`, se ejecuta `daemon-reload` y se
habilita en ambos nodos. El worker que ejecuta trabajos WhatsApp permanece solo en
`.4` para no duplicar acciones; el monitor sí corre en ambos por su lease.

Rollback de código: `git revert <commit-safe-ops>` y nuevo despliegue. Rollback de
la unidad: deshabilitar `ralfia-dual-node-monitor.service`, restaurar el snapshot y
ejecutar `systemctl --user daemon-reload`. No se borran memorias ni conversaciones.

## Contrato P0 de evidencia y anti-loop (2026-07-19)

- `get_server_status`, `estado` y `servicios` derivan de una sola llamada a
  `whatsapp_service_ops.status_snapshot`.
- Toda afirmación de estado lleva `target_host`, `service_id`, `checked_at`, `source`,
  `evidence_ref` y `tool_call_id`.
- Consultar estado nunca llama a AG31 ni modifica su estado interno.
- El modelo local no puede afirmar malware, ataque, actualización maliciosa, corrupción
  de configuración ni revisión de logs sin evidencia estructurada compatible.
- `whatsapp_message_ledger` registra únicamente IDs, hashes, dirección y metadatos
  operativos; no duplica el texto del mensaje.
- `fromMe=true`, eventos outbound, huellas de autorespuesta y ecos recientes se bloquean
  antes del modelo. Bot→bot nunca se interpreta como intención humana.
- Las conversaciones 1:1 verificadas del owner comparten la clave
  `owner:<principal_id>:whatsapp`; los grupos permanecen aislados.

## Confirmaciones interactivas

Evolution API 2.3.7 ofrece botones reply. Los IDs ejecutables están limitados a
`maint.confirm.<challenge>`, `maint.cancel.<job_id>` y opciones `menu.*` enumeradas
en el parser. El backend los convierte a comandos tipados; un ID ajeno se descarta.
Las operaciones continúan aplicando misma identidad, mismo chat, TTL de 180 segundos,
estado de un solo uso, rate limit, cooldown y lock por servicio.

Evolution puede devolver HTTP 200 aunque algunos clientes no muestren el botón. Por
eso toda confirmación se entrega también como texto con el mismo challenge. El texto
no amplía permisos: siguen siendo obligatorios owner verificado, mismo chat, TTL y
challenge de un solo uso.

`menu` o `ayuda` abre opciones guiadas de estado, correos, servicios,
notificaciones y solicitud personalizada. La opción personalizada acepta texto o voz,
pero no convierte lenguaje natural en shell libre: consulta herramientas tipadas o
crea una propuesta que requiere confirmación cuando existe cambio de estado.

## Voz, imágenes y coherencia operativa

- una nota de voz se transcribe localmente y conserva `media.kind=audio`;
- el modelo no puede inferir imagen o video a partir de una palabra mal transcrita;
- OCR/visión solo se incorporan cuando `media.kind=image`, como contexto no ejecutable;
- preguntas naturales de estado y diagnóstico se enrutan a herramientas tipadas;
- la recomendación se genera desde el servicio realmente afectado. No existe una
  sugerencia fija de “recupera MCP” para fallos del Panel u otro componente;
- primero se recomienda diagnóstico; recuperar o reiniciar siempre requiere la
  confirmación de mantenimiento.

## Revisión y respuesta de correos

- `correo` muestra asunto, prioridad, resumen y `mail_id` de los mensajes recientes;
- `correo mail_…` obtiene el cuerpo por IMAP cuando hace falta y muestra acciones
  posibles junto con un enlace HMAC temporal en `correo.pcdoctor.ai`;
- `responder mail_…: texto` solo prepara una vista previa. El envío SMTP ocurre
  únicamente después de responder `sí` desde el mismo chat autorizado;
- la auditoría de respuesta conserva hashes y longitudes, no el cuerpo ni credenciales;
- el análisis es determinista y fundamentado en asunto/cuerpo. Los mensajes de
  marketing no se convierten en pagos por coincidencias parciales de palabras.

## SSH entre `.4` y `.5`

Cada nodo usa una clave `ralfia_peer_ops_ed25519` exclusiva. En el peer,
`authorized_keys` aplica `from=`, `restrict` y
`command=/home/rlopez/bin/ralfia-peer-ops`.

No hay PTY, shell, agent forwarding, X11 ni port forwarding. El wrapper permite solamente:

- `systemctl --user is-active|start|restart` para unidades allowlisted;
- `journalctl --user -u ... -n 1..50 --no-pager`;
- `docker inspect|logs|start|restart` para contenedores allowlisted;
- `hostname` como prueba de conectividad.

Todo lo demás termina con `peer_ops_command_denied` y código 126.

## OAuth coordinación

Los clientes cuyo nombre registrado es `ChatGPT` reciben automáticamente
`ralfia:agents` y los cuatro scopes específicos de memoria, pero no `ralfia:admin`.
La migración de tokens admin activos es auditable:

```bash
python scripts/migrate_chatgpt_agent_scope.py
python scripts/migrate_chatgpt_agent_scope.py --rollback
```

El script nunca imprime tokens y conserva el scope anterior en
`ralfia_oauth_scope_migrations`.
