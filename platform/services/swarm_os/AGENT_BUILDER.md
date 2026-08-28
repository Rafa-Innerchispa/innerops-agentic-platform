# Google Cloud Agent Builder — nota honesta para Devpost

## Qué es "Google Cloud Agent Builder"

En el contexto del **Google Cloud Rapid Agent Hackathon**, el criterio *Google Cloud Agent Builder* se refiere al ecosistema de diseño y prototipado de agentes con herramientas de Google:

- **[Google AI Studio](https://aistudio.google.com)** — prototipo conversacional, flujos multimodales, pruebas rápidas con Gemini.
- **Vertex AI Agent Builder** — despliegue gestionado en GCP (agentes en la nube, grounding, herramientas).

Rafael usó **AI Studio** para explorar el concepto InnerOS (8 Droides, narrativa PC Doctor, UX del enjambre) antes de implementarlo en producción local.

**Enlace al prototipo AI Studio:** https://ai.studio/apps/a2d230ce-a60c-431a-a56f-f24a6aa14989

## Qué construyó Rafael (la verdad técnica)

| Aspecto | Implementación real |
|--------|---------------------|
| Orquestación | **CrewAI** en servidor local (`innerspark-swarm-os-cursor-local`) |
| Ejecución | **Ollama** local + tools Python (MongoDB, SRI, IMAP, WhatsApp) |
| Razonamiento cloud | **Gemini API** para capa de asistente/clasificación — no sustituye la ejecución local |
| Datos | **MongoDB** (`pcdoctor_swarm`) + **MongoDB MCP** partner |
| Despliegue | FastAPI `:8100`, admin React `:5173` — **no** desplegado en Vertex |

El sistema **no es un agente hospedado en Vertex Agent Builder**. Es un **agente funcional multi-paso** diseñado con AI Studio y **ejecutado de forma soberana** en el stack PC Doctor.

## Cómo presentarlo al jurado (honesto y ganador)

1. **Diseño en AI Studio, ejecución local** — "Prototipé la arquitectura de 8 agentes en Google AI Studio; la implementación de producción corre con CrewAI en nuestro servidor porque PC Doctor necesita soberanía de datos y tools reales (SRI, correo, WhatsApp)."

2. **Gemini donde aporta** — Mostrar `GEMINI_API_KEY` + asistente/búsqueda; dejar claro que los pasos críticos (cotización, informe, MongoDB) son tools locales verificables.

3. **Demo reproducible** — `POST /api/v1/hackathon/tour/run` + UI `/inneros` + módulos laterales (datacenter, email, visits, quotes).

4. **MongoDB MCP** — Mostrar `.cursor/mcp.json` o `config/mongodb-mcp.json` y explicar consultas asistidas sobre colecciones operativas.

5. **No oversell** — No decir "desplegamos en Vertex" si no es cierto. Decir: "Cumplimos el espíritu del criterio Agent Builder: diseño con herramientas Google + agente funcional en producción local."

## Evidencias rápidas

- README hackathon + este archivo
- App AI Studio (enlace arriba)
- Repo público + LICENSE
- Video 3 min: tour 5 pasos desde `/inneros`
- `GET /api/v1/hackathon/compliance` — autoevaluación Devpost
