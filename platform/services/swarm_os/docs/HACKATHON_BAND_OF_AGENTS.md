# Hackathon Band of Agents (BOA26) — PC Doctor / Ralphi-IA

Módulo aislado `hackathon_band/` para el hackathon **Band of Agents** (track Internal Enterprise Workflows).

## Pitch

> Most companies do not lack data. They lack memory.

## Arquitectura real (sin simulación)

```
Pregunta → Router (Band + Featherless)
        → Memory (Band + Featherless + MongoDB/docs reales)
        → Analyst (Band + AIML)
        → Documentation (Band + AIML) → reporte MD
```

| Componente | Puerto | Descripción |
|------------|--------|-------------|
| API hackathon | **8200** | FastAPI — pipeline, SSE, status |
| UI jurado | **5190** | Vite + React |
| InnerOS | 5173 | **NO TOCAR** |
| Swarm API | 8100 | **NO TOCAR** |

## Memoria organizacional (REAL)

Memory Agent consulta:

1. **MongoDB** `pcdoctor_swarm`: `sop_visits`, `technical_reports`, `reports`, `inspections`, `documents`, `clients`
2. **Docs servidor**: `/home/rlopez/data/docs/` (markdown reales)

No se inventan incidentes ni archivos ficticios.

## Variables .env obligatorias

Ver `hackathon_band/.env.example` en la raíz del repo (`.env.example` sección hackathon).

Rafael debe pegar en `.env` del servidor:

- `BAND_API_KEY` + 4 `BAND_AGENT_ID_*`
- `FEATHERLESS_API_KEY`
- `AIML_API_KEY`

Sin estas variables el pipeline **no arranca** (error claro).

## Arranque

```bash
cd /home/rlopez/projects/innerspark-swarm-os-cursor-local
source venv/bin/activate
git checkout hackathon/band-fireless-2026

# Verificar keys
python hackathon_band/hackathon_demo.py --check

# API :8200
python hackathon_band/api_server.py

# UI :5190 (otra terminal)
cd hackathon_band/ui && npm install && npm run dev
```

URL jurado: `http://192.168.1.4:5190`

## CLI demo

```bash
python hackathon_band/hackathon_demo.py -q "¿Qué sabemos sobre fallas de cámaras PoE?"
```

Reporte: `hackathon_band/outputs/hackathon_report.md`

## Reglas

- Commits solo en rama `hackathon/band-fireless-2026`
- No commitear `.env` ni secretos
- Band audit cache en `.band_local/` es solo log UI — **no simula Band**
