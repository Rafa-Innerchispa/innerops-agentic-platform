# Politica Local-First y Ahorro de Creditos

**Regla principal:** todo lo que pueda procesarse localmente en RalfIA debe procesarse localmente antes de usar servicios de pago o creditos externos.

## Objetivo

Mantener la mayor autonomia posible y ahorrar creditos de ChatGPT, OpenAI API, Gemini, Perplexity, Google Cloud u otros servicios externos. RalfIA debe actuar como centro local de procesamiento, memoria, busqueda y automatizacion.

## Orden de preferencia

1. **Datos locales primero**
   - MongoDB `pcdoctor_swarm`
   - Postgres
   - archivos locales
   - Qdrant
   - logs y documentacion del servidor

2. **Modelos locales primero**
   - Ollama para resumen, clasificacion, borradores simples, extraccion y tareas repetitivas.
   - Whisper local para transcripcion.
   - Qdrant local para busqueda semantica/RAG.

3. **Automatizacion local primero**
   - scripts Python/Node locales
   - n8n local
   - APIs internas
   - MCP tools de RalfIA

4. **Nube solo cuando sea necesario**
   - ChatGPT/Codex para razonamiento complejo, arquitectura, debugging dificil, decisiones de diseno y cambios delicados.
   - OpenAI/Gemini/Perplexity APIs solo con autorizacion o si el beneficio supera el costo.
   - Google Cloud para backups, contingencia o servicios que no puedan correr localmente.

## Reglas para agentes

- No usar APIs de pago si una consulta local, script local o modelo local puede resolverlo.
- No hacer busquedas web si la informacion esta en repos, docs locales, Mongo, Qdrant o servicios internos.
- No subir archivos/datos a terceros sin necesidad clara.
- Para inventarios, health checks, logs, resumenes y transformaciones, usar primero herramientas locales.
- Antes de proponer infraestructura cloud, verificar si RalfIA o el servidor AMD pueden cubrir la necesidad.
- Si una tarea puede dividirse, hacer localmente la parte pesada y usar ChatGPT/Codex solo para juicio, revision o integracion.

## Casos recomendados para local

| Tarea | Ruta local preferida |
|------|----------------------|
| Consultar clientes/proyectos | Mongo/Postgres via RalfIA MCP |
| Buscar documentos | Qdrant + archivos locales |
| Transcribir audio | Whisper local |
| Resumir lotes grandes | Ollama local |
| Revisar puertos/servicios | `ss`, systemd, Docker, portal `:8800` |
| Automatizar flujos | n8n local |
| Guardar memoria | Mongo `pcdoctor_swarm` |
| Registrar decisiones | Agent Coordination Hub / Mongo |

## Casos donde si vale usar ChatGPT/Codex

- Arquitectura y decisiones de diseno.
- Cambios de codigo con riesgo.
- Debugging donde hace falta razonamiento profundo.
- Redaccion estrategica importante.
- Revision de seguridad y continuidad.
- Coordinacion entre Cursor, Antigravity y RalfIA.

## Indicador obligatorio en planes

Cuando un agente proponga una tarea grande, debe indicar:

```text
Ruta local: que se puede hacer en RalfIA sin gastar creditos.
Ruta nube: que requiere ChatGPT/API/cloud y por que.
Ahorro: como se minimiza el consumo.
```



## Google AI Spend Guard

Google AI model use must stay behind Resource Fabric and explicit lanes:

- Local AMD/Intel remains the default for coding, tests, summaries and repeated
  processing.
- `google_ai_model_smoke` is dry-run unless `allow_live=true`.
- Smoke tests are capped at 512 prompt characters and 32 output tokens.
- Embedding smoke returns dimensions only and does not ask for generative text.
- Use `google-gemini-35-bounded-review` (`gemini-3.5-flash-lite`, Vertex
  `global`) as the live Google reviewer lane while Gemma is unavailable.
- AI Studio/Gemini API keys reported by Google as leaked must not be used; use
  Vertex OAuth/gcloud or replace the key server-side.
- Gemma must not be reported as live until a real smoke succeeds for the exact
  model ID and region.
