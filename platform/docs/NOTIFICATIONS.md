# Notificaciones RalfIA — Evolution API directo

**Sin n8n.** WhatsApp vía Evolution `:8082`, correos vía Swarm IMAP `:8100`.

## Qué notifica

| Canal | Trigger | Destino |
|-------|---------|---------|
| **Correo importante** | IMAP poll cada 5 min, solo importancia **alta** | WhatsApp Rafael |
| **Coordinación** | INBOX priority high, tareas BLOCKED, servicios caídos | WhatsApp Rafael |
| **Spam filtrado** | Newsletters/marketing → **baja**, sin alerta | — |

## Configuración (.env raphiia-openai)

```env
EVOLUTION_BASE_URL=http://192.168.1.4:8082
EVOLUTION_API_KEY=...
EVOLUTION_INSTANCE=RalphiIA-pcdoctor
NOTIFY_WHATSAPP_TO=593999059000
NOTIFY_EMAIL_POLL=1
NOTIFY_COORDINATION=1
```

## Arranque

```bash
cd /home/rlopez/projects/raphiia-openai
source venv/bin/activate
python scripts/setup_notifications.py --test   # config Mongo + prueba WhatsApp
```

Timer systemd (cada 5 min):

```bash
cp /home/rlopez/data/ai_coordination/systemd/user/ralfia-notify.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ralfia-notify.timer
```

AG-25 también lanza notify cada ~6 min (cada 3 ciclos de 120s).

## Actualizar Evolution API (Intel .4 + AMD .5)

Los agentes y operadores pueden ejecutar (sin shell libre por WhatsApp):

```bash
/home/rlopez/inneros/inneros_core/platform/scripts/upgrade_evolution_api.sh both
```

- Recrea contenedores Docker con `evoapicloud/evolution-api:latest` (hoy **2.3.7**, sin licencia).
- **No** subir a `2.4.x` en producción sin activar licencia Evolution Foundation (503 `LICENSE_REQUIRED`).
- WhatsApp: `recupera Evolution en .4` / `.5` solo **reinicia** el contenedor (catálogo tipado).

Autorización ops sin UI de “encuesta”: botones **Confirmar/Cancelar** + texto `CONFIRMAR <código>` / `CANCELAR <código>`.

### Línea AMD Innerchispa (.5)

| Campo | Valor |
|-------|--------|
| Nacional | `0962546650` |
| E.164 | `593962546650` |
| Instancia Evolution | `Innerchispa` |
| Base URL | `http://192.168.1.5:8082` (Tailscale `100.72.153.124:8082`) |

Emparejar tras cambio de chip: `GET /instance/connect/Innerchispa?number=593962546650` (código de enlace) o manager en `:8082/manager`. Alertas ops al owner siguen en `NOTIFY_WHATSAPP_TO` (línea personal Intel); AMD es segunda línea operativa (`WHATSAPP_AMD_SEND_ENABLED`).

## Correos — cuentas IMAP

Las cuentas viven en Mongo `email_accounts` (gestión Swarm UI o API `:8100/api/v1/email/accounts`).

`setup_notifications.py` configura `email_settings.global.whatsapp_numbers` con tu número.

## Código

| Archivo | Rol |
|---------|-----|
| `raphiia_openai/notifications/evolution_client.py` | Envío WhatsApp |
| `raphiia_openai/notifications/email_poll.py` | Llama Swarm `/email/poll` |
| `raphiia_openai/notifications/coordination_alerts.py` | Alertas coordinación |
| `scripts/ralfia_notify.py` | Orquestador |
| Swarm `tools/email_agent.py` | Filtro spam + Ollama clasificación |

## ChatGPT

MCP **no hace push** a ChatGPT. Las notificaciones van a **tu WhatsApp**. ChatGPT sigue leyendo INBOX cuando consulta MCP.
