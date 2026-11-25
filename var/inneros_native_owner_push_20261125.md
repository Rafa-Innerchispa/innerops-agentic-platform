# InnerOS push propio (sin Home Assistant)

## Qué es

- **ntfy** en Intel (`:2586`) — notificación en el móvil igual que una push de sistema (app ntfy, topic `ralfia-owner-ops`).
- **PWA InnerOS Owner** (`:8244/owner-ops/`) — panel con Aprobar/Cancelar firmados (HMAC).
- **Flujo OPS** — `NOTIFY_OPS_PRIMARY=inneros_push`; HA/Telegram desactivados por defecto en `.env.ops-notify`.

## Teléfono (una vez)

1. Instalar app **ntfy** (Play Store o F-Droid).
2. Suscribirse: `http://192.168.1.4:2586/ralfia-owner-ops` (misma Wi‑Fi o Tailscale).
3. Abrir `http://192.168.1.4:8244/owner-ops/` → menú del navegador → **Añadir a pantalla de inicio**.

Las autorizaciones IDE llegan con botones **Aprobar** / **Cancelar** en la notificación (acciones HTTP ntfy).

## Intel

```bash
cd /home/rlopez/inneros/inneros_core/platform
git pull   # tras merge PR
bash scripts/setup_inneros_owner_push.sh
systemctl --user restart inneros-temporal-worker
```

Variables clave en `.env.ops-notify`: `INNEROS_NTFY_URL`, `INNEROS_OWNER_PUSH_PUBLIC_URL`, `INNEROS_OWNER_PUSH_SECRET` (recomendado en producción).

## Sin dependencias de terceros para entrega

- No usa FCM/Google push oficial ni Home Assistant.
- ntfy es open source, corre en tu Intel; el topic es tuyo.
- Decide/approve reutiliza `atlas_ops_owner_decisions` + `handle_owner_reply` (mismo contrato que Alexa/Telegram).