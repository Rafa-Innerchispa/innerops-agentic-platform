# InnerOS | Aprobaciones móviles multicanal

**Estado:** fase 1, transporte implementado en rama. No desplegado ni conectado todavía.

## Qué haremos

- **Canal principal:** ntfy autohospedado, HTTPS, topic privado, ACL deny-all,
  tokens por dispositivo. En Android la versión de F-Droid funciona sin FCM
  mediante conexión directa; hay que permitir notificaciones y desactivar
  restricciones de batería para ntfy en el móvil del propietario.
- **Canal alternativo:** bot privado de Telegram por Bot API y chat ID
  verificado. Botón de aprobación abre una pantalla autenticada, no autoriza
  cambios directamente desde Telegram.
- **Respaldo obligatorio:** SMTP existente para alertas P0, en paralelo a push,
  y fallback si fallan los demás. PR #210 corrige el bug de retorno temprano
  cuando las sesiones WhatsApp caen.
- **WhatsApp:** opcional. No es dependencia crítica para continuar trabajando.

## Seguridad: una sola autoridad

El módulo `platform/inneros_core_runtime/notifications/owner_multichannel.py`
solo construye notificaciones y transporta mensajes a ntfy o Telegram.
No contiene endpoints, no cambia estados OPS, no lee secretos y no aprueba nada.

Los botones «Aprobar» y «Rechazar» muestran una solicitud específica en
HTTPS. El *backend* de aprobaciones debe verificar sesión del dueño y passkey
WebAuthn con user verification (PIN/huella), identidad, RP ID/origen,
challenge antireplay, hash de acción/alcance, ventana TTL, estado de OPS, y
hacer transición atómica por CAS en Mongo / single-writer Temporal.
El envío de un enlace o la recepción de un mail no equivale a autorización.
Enlaces sin login ni passkey nunca autorizan operaciones.

La colección canónica de solicitudes requerirá idempotencia por request_id,
task_id existente, action hash, estado, caducidad, propietario y auditoría;
outbox por canal con intento, proveedor, recibo, error, retry y decisión final.
No confundir `provider_accepted` con entregado, leído o aprobado.
Si todos los canales fallan, conservar solicitud en bandeja web autenticada
y no ejecutar una operación protegida.

## Qué falta para funcionar de verdad

1. Aprovisionar ntfy en host con capacidad (no añadir procesos al AMD / 94%
   sin liberar espacio), TLS público protegido o acceso móvil robusto, ACL,
   token de envío/lectura privado. Nunca publicar topic abierto o secrets.
2. Vincular teléfono Android, probar con Wi-Fi apagado, datos móviles,
   pantalla bloqueada y reinicio; revisar ahorro de batería.
3. Crear bot Telegram mediante BotFather y guardar token/chat ID en vault.
4. Crear pantalla web InnerOS de solicitudes + autenticación WebAuthn/passkey
   y API de decisión con firma, validación, idempotencia, auditoría y rollback.
5. Conectar notificaciones al outbox canónico y al scheduler existente,
   no crear segundo control plane.
6. Canary E2E: 2 solicitudes inocuas (aprobar y rechazar), passkey real,
   estado Temporal, auditoría y recibos; simular WhatsApp fuera, ntfy fuera
   y Telegram fuera, con SMTP vivo. No activar cambios físicos por una prueba.
7. Merge con gobernanza efectiva de main (issue #204); PR #210 de email
   fallback debe integrarse antes de verificar la entrega automática.

Código fase 1: validaciones URL HTTPS y task ID, expiración, botones view
que NO mutan, payload y senders de ntfy/Telegram con recibo provider-accepted.
Los unit tests usan HTTP mock y no envían push ni mensajes externos.

Issue de UX/autorización existente: #180. No duplicar tareas.

## Orden de entrega, todos los eventos

Añadido `platform/inneros_core_runtime/notifications/owner_notification_router.py`
con orden estricto **push → WhatsApp → Telegram → email**, para clases
approval, incident, report, task_status, test_result, service_health,
opportunity, digest y other (incluye nuevos eventos clasificados de forma
conservadora). Preferencias por usuario y categoría activas de forma
predeterminada; deshabilitar un aviso ordinario NO pausa ninguna tarea.
Alertas de aprobación, incidentes o criticidad máxima no se silencian sin
una política de seguridad especial. Todas las notificaciones relevantes
deben salir desde el outbox canónico, no del chat, de CI o de un timer nuevo.

El router calcula intentos y recibos sin realizar ningún cambio OPS; usa
senders inyectados, nunca credenciales fijas. Si `push` devuelve error,
intenta WhatsApp, luego Telegram y finalmente correo. En avisos high,
critical o aprobaciones, `provider_accepted` no se toma como leido:
tras 120 segundos sin `owner_ack` se prueba el siguiente canal, hasta
agotar la lista. Una alerta agotada permanece en la cola persistente para
recuperación manual (la persistencia durable aún NO está cableada).
Para reportes informativos, la aceptación del proveedor es un intento
exitoso de envío, pero NO una constancia de lectura por el destinatario.

**Controles por tarea:** el plan de la bandeja autenticada de InnerOS
requiere acciones Pausar/Reanudar cuando el estado real las admita,
además de Aprobar/Rechazar/Cerrar. La acción debe verificarse con
passkey/owner auth, transición única Temporal, CAS y evidencia. La opción
"desactivar avisos" es distinta de "pausar ejecución". Ningún botón
del transporte actual modifica estados: faltan esos endpoints seguros.

Pruebas aisladas del router y transportes: **32 passed** con mocks,
incluida prioridad, failover, escalamiento, opt-out de categoría normal
y preservación de alertas críticas. Los tests NO son evidencia de
envío real, conexión del teléfono ni worker outbox autónomo.
