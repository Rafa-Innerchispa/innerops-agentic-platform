# Continuidad — cualquier IA puede retomar este proyecto

**Última actualización:** 2026-06-18  
**Servidor:** `192.168.1.4` (`ralphi-ia-ver-10`)  
**Repo activo:** `/home/rlopez/projects/innerspark-swarm-os-cursor-local/`

---

## 1. Orden de lectura (obligatorio)

Lee en este orden antes de programar:

| # | Archivo | Qué obtienes |
|---|---------|--------------|
| 1 | [`AGENTS.md`](../AGENTS.md) | Reglas duras, puertos, qué no tocar |
| 2 | [`docs/INSTRUCCIONES_AGENTE.md`](INSTRUCCIONES_AGENTE.md) | Onboarding + prompt de arranque |
| 3 | [`docs/MAPA_PROYECTO.md`](MAPA_PROYECTO.md) | Visión Swarm-OS + fases |
| 4 | [`docs/HACKATHON_BAND_OF_AGENTS.md`](HACKATHON_BAND_OF_AGENTS.md) | Demo Band :5190 / :8200 |
| 5 | [`ARRANQUE_AUTOMATICO.md`](../ARRANQUE_AUTOMATICO.md) | systemd, ngrok, autostart |
| 6 | [`docs/RECUPERACION_DESASTRE.md`](RECUPERACION_DESASTRE.md) | Backups + restauración |

Esquema Mongo canónico: [`ESQUEMA_MONGODB_DBxx.md`](ESQUEMA_MONGODB_DBxx.md)

---

## 2. Dónde guardar QUÉ (no mezclar)

```
/home/rlopez/projects/innerspark-swarm-os-cursor-local/
├── docs/                    ← Planes técnicos, onboarding IA, arquitectura (EN GIT)
├── AGENTS.md                ← Entrada Cursor / Codex / cualquier modelo
├── hackathon_band/          ← Demo Band of Agents (rama hackathon)
├── data/                    ← Runtime del repo (URLs ngrok, logs bootstrap)
│   ├── public_demo_url.txt
│   └── hackathon_public_url.txt
└── .env                     ← Secretos (NUNCA git)

/home/rlopez/data/             ← Datos operativos del servidor (FUERA del repo)
├── docs/                      ← Documentos reales que lee Memory Agent
├── backups/
│   ├── disaster_recovery/     ← Backup completo diario (~190 MB tar.gz)
│   └── snapshots/             ← Snapshots ligeros 3x/día
├── manifests/                 ← Estado JSON verificable (backups, servicios)
└── backups/disaster_recovery.log

Google Drive (nube):
  Ralphi-IA-Gdrive:RalphiIA_Backups/disaster_recovery/
```

**Regla:** código y planes → repo `docs/`. Datos de negocio y backups → `/home/rlopez/data/`.

---

## 3. Dos productos en el mismo repo

| Producto | Puertos | Rama típica | Para qué |
|--------|---------|-------------|----------|
| **Swarm-OS / InnerOS** | :8100 API, :5173 admin | `master` | Campo, cotizaciones, Evolution email |
| **Hackathon Band** | :8200 API, :5190 UI | `hackathon/band-fireless-2026` | Demo jurado, 4 agentes Band |

URL pública hackathon (Devpost): ver `data/hackathon_public_url.txt`

---

## 4. Servicios y autostart

```bash
# Verificar
curl -sf http://127.0.0.1:8100/status
curl -sf http://127.0.0.1:8200/api/status
cat data/hackathon_public_url.txt

# Autostart (cron ya instalado)
crontab -l | grep inneros-autostart

# Systemd completo (sudo una vez)
bash scripts/install_services.sh
```

Crontab activo:
- `@reboot` → `scripts/start_on_boot.sh`
- cada 10 min → `scripts/ensure_stack_running.sh`

---

## 5. Backups — verificar

```bash
bash scripts/verify_backup.sh
# o manual:
ls -lt /home/rlopez/data/backups/disaster_recovery/*.tar.gz | head -3
rclone lsf Ralphi-IA-Gdrive:RalphiIA_Backups/disaster_recovery/ | tail -3
```

Restaurar todo: `restaura-a-ralphia` o ver `docs/RECUPERACION_DESASTRE.md`

---

## 6. LLM en hackathon (correcto en UI)

| Agente | Proveedor | Modelo default |
|--------|-----------|----------------|
| Router | Featherless | Meta-Llama-3.1-8B-Instruct |
| Memory | Featherless | mismo |
| Analyst | AIML | deepseek/deepseek-r1 |
| Documentation | AIML | deepseek/deepseek-r1 |

Band = identidad + audit trail (no es el LLM de inferencia).

**AIML lento:** deepseek-r1 razona; 1–3 min por agente Analyst/Doc es normal.

---

## 7. Memoria MongoDB — cómo funciona

- Código: `hackathon_band/memory_source.py`
- Colecciones buscadas: `sop_visits`, `technical_reports`, `reports`, `inspections`, `clients`, `documents`
- Preview UI: botón en Memory Proof → `/api/memory/preview`
- El reporte incluye sección **MongoDB Evidence (verified)** con hits crudos (no solo LLM)

Preguntas sugeridas en UI están ancladas a datos reales (Torres de la Merced, PoE, SOP).

---

## 8. Prompt de arranque (pegar en chat nuevo)

```
Proyecto: /home/rlopez/projects/innerspark-swarm-os-cursor-local
Lee AGENTS.md → docs/CONTINUIDAD_IA.md → docs/INSTRUCCIONES_AGENTE.md
Servidor 192.168.1.4. MongoDB fuente de verdad. No mezclar con /home/rlopez/inneros/
Rama hackathon: hackathon/band-fireless-2026 (demo :5190)
Cambios mínimos. Español con Rafael.
```

---

## 10. Rama hackathon vs InnerOS — qué se comparte

| Capa | Ubicación | ¿Afecta InnerOS al mergear? |
|------|-----------|----------------------------|
| Demo Band UI/API | `hackathon_band/` | **No** — solo rama hackathon / puertos 5190/8200 |
| Band / AIML / Featherless | `hackathon_band/llm_client.py` | **No** en master hasta que decidas |
| Evolution WhatsApp | `tools/evolution_api.py` | **Sí** — compartido (InnerOS Correos + hackathon) |
| Email SMTP | `tools/email_smtp.py` | **Sí** — misma cuenta `email_accounts` |
| MongoDB memoria | `tools/mongo.py` + `memory_source.py` | Hackathon solo; InnerOS usa workflow_v2 |
| Ollama local | `:11434` | InnerOS puede usarlo; hackathon usa cloud por demo |

**Estrategia:** tras el hackathon, cherry-pick a `master`:
- `delivery.py`, `whatsapp_notify.py`, `report_pdf.py` → módulo `tools/delivery/` reutilizable
- UI hackathon no va a InnerOS; la lógica de “reporte + PDF + WhatsApp + email” sí puede ir al flujo campo

**No depender siempre de Band/AIML:** cambiar proveedor en un solo archivo (`llm_client.py`) o añadir `LLM_PROVIDER=ollama|featherless` — Ollama ya está en el servidor.

