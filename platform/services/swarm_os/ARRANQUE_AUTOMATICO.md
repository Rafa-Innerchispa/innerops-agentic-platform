# Arranque automático — InnerOS + Hackathon Band

**No necesitas recordar comandos.** Tras un apagón o `sudo reboot`, todo vuelve solo.

## Configuración recomendada (una vez, con sudo)

```bash
bash /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/install_services.sh
```

Eso instala y habilita:

| Servicio systemd | Qué hace |
|------------------|----------|
| `swarm-api` | FastAPI `:8100` — InnerOS + **Evolution WhatsApp** (email) |
| `swarm-admin` | InnerOS React `:5173` |
| `swarm-hackathon-api` | Pipeline Band `:8200` — **mismo `.env`**, alerta WhatsApp al terminar |
| `swarm-hackathon-ui` | Dashboard jurado `:5190` |
| `swarm-ngrok` | **2 URLs públicas** — InnerOS `:5173` + Hackathon `:5190` |
| `swarm-bootstrap` | Seed demo + guarda URLs en `data/` |

## Respaldo sin sudo (crontab)

```bash
bash /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/install_autostart_cron.sh
```

## Evolution / WhatsApp — no falta en el branch

InnerOS y Hackathon **comparten el mismo `.env`** del repo raíz:

```
EVOLUTION_BASE_URL=http://192.168.1.4:8082
EVOLUTION_API_KEY=...
EVOLUTION_INSTANCE=ralphi-pcdoctor
HACKATHON_WHATSAPP_TO=593...   # solo para alerta al terminar pipeline hackathon
```

- InnerOS avisa por email → `swarm-api` (`api/email_routes.py`)
- Hackathon avisa al terminar el reporte → `hackathon_band/pipeline.py`
- Tras cambiar `.env`, reinicia: `bash scripts/restart_hackathon_stack.sh`

## URLs públicas (después de reiniciar)

```bash
cat data/public_demo_url.txt          # InnerOS + datacenter
cat data/hackathon_public_url.txt     # Dashboard hackathon
```

## Si algo falla

```bash
sudo systemctl status swarm-api swarm-admin swarm-hackathon-api swarm-hackathon-ui swarm-ngrok
bash scripts/restart_hackathon_stack.sh
bash scripts/bootstrap_on_boot.sh
```

## Aplicar todo de una vez

```bash
bash scripts/apply_hackathon_autostart.sh
```

