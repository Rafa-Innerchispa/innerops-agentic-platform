# InnerSpark Swarm-OS — Cursor Local

Sistema multi-agente **PC Doctor S.A.** para inspecciones de campo, clientes (RUC/SRI),
informes técnicos y cotizaciones. Base de datos: **MongoDB local**.

> **¿Cambias de modelo IA o se acaban los créditos?** Lee primero:  
> [`AGENTS.md`](AGENTS.md) → [`docs/INSTRUCCIONES_AGENTE.md`](docs/INSTRUCCIONES_AGENTE.md)  
> **Mapa del proyecto:** [`docs/MAPA_PROYECTO.md`](docs/MAPA_PROYECTO.md)  
> **Esquema MongoDB DBxx:** [`docs/ESQUEMA_MONGODB_DBxx.md`](docs/ESQUEMA_MONGODB_DBxx.md)

## Ubicación en servidor

```
/home/rlopez/projects/innerspark-swarm-os-cursor-local/
```

## Servicios externos (ya en el servidor)

| Servicio | Puerto | Uso |
|----------|--------|-----|
| MongoDB | 27017 | Base operativa `pcdoctor_swarm` |
| Ollama | 11434 | Modelo local (`neural-chat:7b`) |
| Esta API | 8100 | Orquestación de agentes |

## Arranque

```bash
cd /home/rlopez/projects/innerspark-swarm-os-cursor-local
source venv/bin/activate
./run_api.sh
```

## Endpoints

```bash
# Estado
curl http://192.168.1.4:8100/status

# Flujo completo (inspección → informe → cotización)
curl -X POST http://192.168.1.4:8100/inspection/start \
  -H "Content-Type: application/json" \
  -d '{"input": "RUC 0991386866001, Urbanización Parques del Río. 2 cámaras dañadas, cable UTP desordenado, switch sin etiquetar."}'
```

## Agentes (CrewAI)

1. Director — coordina
2. Campo — hallazgos de visita
3. Cliente — RUC + SRI + MongoDB
4. Bitácora — pendientes
5. Informes — informe técnico
6. Cotizador — inventario + totales
7. Revisor — gates Playbook
8. Comunicaciones — borrador correo/WhatsApp

## RUC / cédula (API Intuito)

Configura en `.env` tus credenciales (no uses las del manual si son solo demo):

```
RUC_API_USER=tu_usuario
RUC_API_PASS=tu_password
```

- **Cédula 10 dígitos** → se convierte a RUC persona natural (`cedula + 001`)
- **RUC 13 dígitos** → consulta directa
- Sin credenciales → fallback a mock local

```bash
curl -X POST http://192.168.1.4:8100/ruc/lookup \
  -H "Content-Type: application/json" \
  -d '{"id": "0991386866001"}'
```

## Audio y archivos (local)

```bash
# 1) Crear inspección
curl -X POST http://192.168.1.4:8100/inspection/quick \
  -H "Content-Type: application/json" \
  -d '{"input": "visita ciudadela"}'

# 2) Subir audio → Whisper :9001 transcribe y agrega al texto
curl -X POST http://192.168.1.4:8100/inspection/INSPECTION_ID/upload-audio \
  -F "file=@nota.wav"

# 3) Analizar PDF/foto ya subida
curl -X POST http://192.168.1.4:8100/inspection/INSPECTION_ID/analyze-file \
  -H "Content-Type: application/json" \
  -d '{"path": "/ruta/al/archivo.jpg", "question": "¿Qué daños ves?"}'

# 4) Ejecutar agentes con todo el contexto acumulado
curl -X POST http://192.168.1.4:8100/inspection/start \
  -H "Content-Type: application/json" \
  -d '{"input": "...", "inspection_id": "INSPECTION_ID"}'
```

Whisper debe estar corriendo: `cd /home/rlopez/whisper-service && docker compose up -d`

## Esquema de datos v2 (MongoDB)

**Crear toda la estructura en MongoDB** (colecciones DB01–DB52 + índices):

```bash
python scripts/init_mongodb_schema.py
```

Ver estado **desde tu Windows**: `curl http://192.168.1.4:8100/status`  
(En el servidor el `.env` usa `127.0.0.1` porque Mongo/Ollama están en la misma máquina — ver `docs/ACCESO_RED.md`)

**Migración opcional** (solo si tienes datos viejos en `inspections`):

```bash
python scripts/migrate_v1_to_v2.py
```

Correcciones canónicas vs Notion: `docs/CANON_CORRECCIONES_DBxx.md`

## ¿Copiar Google AI Studio?

**No copiar la lógica rota.** Solo importar:
- Plantillas PDF / nomenclatura
- Reglas de negocio (Playbook) como `.md` en `docs/`
- Ideas de roles de agentes

La orquestación y validaciones las construimos aquí, con MongoDB + gates del Playbook.

## Hackathon Band of Agents (BOA26)

Código de la demo multi-agente con **Band**, memoria MongoDB real y entrega WhatsApp/email.

| Qué | Dónde |
|-----|--------|
| **Rama del hackathon** | [`hackathon/band-fireless-2026`](https://github.com/Rafa-Innerchispa/innerspark-swarm-os-cursor-local/tree/hackathon/band-fireless-2026) |
| Código pipeline + UI | `hackathon_band/` |
| Variables requeridas | `.env.example` + `hackathon_band/.env.example` |
| Documentación | `docs/HACKATHON_BAND_OF_AGENTS.md` |

```bash
# Verificar configuración (sin ejecutar pipeline)
python hackathon_band/hackathon_demo.py --check

# API hackathon :8200 + UI :5190
./run_hackathon_api.sh
./run_hackathon_ui.sh
```

**Secretos:** copia `.env.example` → `.env` en el servidor y rellena keys localmente. **Nunca** commitees `.env`.

## Proyectos relacionados (no mezclar)

- `inneros/` — hackathon Google AI Studio
- `agentes/` — prototipo DevOps bash
- `ai-server-v2/` — Ralphi RAG + Docker infra
