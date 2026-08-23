# Ciclo de vida de proyectos — un solo camino

**Regla:** ningún servicio HTTP nuevo se crea con `nohup`, `./run.sh` suelto ni panel `:8096` legacy sin pasar por aquí.

## Problema que resuelve

Antes había **varios caminos** (SRE `:8096`, scripts sueltos, Docker manual, agentes) y **systemd era opcional**. Eso produce errores como «puerto no en uso», servicios caídos tras reboot y dependencia de «¿me lo pones al inicio de Linux?».

## Contrato Ralphi IA

| Fase | `lifecycle` | Qué se crea automáticamente |
|------|-------------|----------------------------|
| Hackathon / idea | `scaffold` | Carpeta, `docs/metadata.json`, `PROJECT_MANIFEST.json`, registro Mongo |
| Servicio en producción | `always_alive` | Todo lo anterior + **`run.sh`** + **systemd user** `ralf-{slug}.service` + **enable** + **Restart=always** + **linger** + entrada en Service Registry `:2002` |

**Plataforma Ralphi** (`ralfia-app`, `ralfia-mcp`, `ralfia-portal`, AG-25) se instala aparte:

```bash
bash scripts/install_user_services.sh
```

## Comando único (agentes y humanos)

```bash
cd /home/rlopez/projects/raphiia-openai
source venv/bin/activate

# 1) Solo estructura (hackathon, aún sin app)
python3 scripts/ralphia_project_create.py \
  --name "Mi Hackathon 2026" \
  --hackathon "Devpost X" \
  --hackathon-url "https://....devpost.com/"

# 2) Proyecto vivo 24/7 (cuando ya hay comando de arranque)
python3 scripts/ralphia_project_create.py \
  --name "Facturación API" \
  --start-cmd "venv/bin/uvicorn main:app --host 0.0.0.0 --port {port}" \
  --health "http://127.0.0.1:{port}/health"

# 3) Activar un scaffold existente
python3 scripts/ralphia_project_create.py \
  --activate mi-hackathon-2026 \
  --start-cmd "venv/bin/python3 main.py"

# 4) Auditar que todo always_alive está en systemd
python3 scripts/ralphia_project_create.py --verify
```

Puertos nuevos: **8120–8999** (automático). Los reservados están en `ai_coordination/PORTS_CANONICAL.md`.

## Qué pasa al crear `always_alive`

1. Asigna puerto libre  
2. Escribe `run.sh` y `~/.config/systemd/user/ralf-{slug}.service`  
3. `systemctl --user enable` + `restart`  
4. `loginctl enable-linger` (sobrevive reboot sin login)  
5. Mongo `ralfia_projects` + `ralfia_service_registry`  
6. Aparece en panel `:2002` vía watchdog/registry  

## Reinicios

| Alcance | Comando |
|---------|---------|
| Plataforma Ralphi | `bash scripts/restart_ralphia.sh` |
| Un proyecto | `systemctl --user restart ralf-{slug}` |
| Ver estado | `systemctl --user status ralf-{slug}` |

## API (panel `:2002`)

- `GET /api/ops/projects` — listado  
- `POST /api/ops/projects/create` — crear  
- `POST /api/ops/projects/{slug}/activate` — scaffold → vivo  
- `GET /api/ops/projects/verify` — auditoría  

## Legacy `:8096`

El panel SRE en `:8096` (`crear_proyecto.py`) **solo crea carpetas** — no systemd. Debe migrarse a llamar `ralphia_project_create.py` o quedar como **deprecated**; el Project Panel definitivo vivirá en `:2002/projects`.

## Para agentes (Cursor, Codex, ChatGPT)

- **NO** crear proyectos con scripts propios  
- **NO** usar `nohup` para servicios permanentes  
- **SÍ** usar `ralphia_project_create.py`  
- **SÍ** ejecutar `--verify` tras cambios de infra  
