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
