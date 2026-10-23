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
