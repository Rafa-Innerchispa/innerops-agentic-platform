# RalfIA Control Plane

**Estado:** diseño operativo seguro, sin cambios de puertos ni reinicios.
**Servidor principal:** `ralphi-ia-ver-10` (`192.168.1.4`)
**Proyecto base:** `/home/rlopez/projects/raphiia-openai`

RalfIA debe funcionar como el **control plane** de PC Doctor S.A. e InnerChispa LLC: un centro de datos, memoria, herramientas, agentes y auditoria que puede ser usado por ChatGPT, Cursor, Gemini, Perplexity, Notion, n8n, Antigravity y futuros clientes.

El nombre tecnico de este tipo de sistema puede describirse como:

- **AI control plane**: plano central de control para modelos, agentes, datos y herramientas.
- **Integration fabric**: capa que conecta muchos servicios sin que cada uno dependa del otro directamente.
- **Composable business operating system**: sistema operativo de negocio adaptable a distintos procesos y clientes.
- **Sovereign AI hub**: centro de IA propio, donde los datos viven bajo control del servidor y sus respaldos.

## Principios

1. **RalfIA es la fuente de verdad.** Los chats y herramientas externas pueden razonar, pero los datos durables viven en MongoDB, Postgres, Qdrant, archivos y backups de RalfIA.
2. **MCP primero.** ChatGPT, Cursor, Gemini y otros clientes deben entrar por MCP o APIs acotadas, no por accesos directos improvisados a bases.
3. **No romper hackatones.** Los servicios existentes siguen operativos. No se cambian puertos, contenedores, systemd units ni rutas sin plan explicito.
4. **Procesar local cuando se pueda.** Ollama, Whisper, Qdrant y herramientas locales se usan para reducir costos y mantener soberania.
5. **Nube solo como extension y contingencia.** Google Cloud puede alojar backups, replicas o servicios de emergencia, pero no debe ser la unica fuente de verdad.
6. **Auditoria por defecto.** Toda escritura importante desde un agente debe dejar evento: quien, tool, coleccion, timestamp y resultado.

## Arquitectura Objetivo

```text
ChatGPT / Cursor / Gemini / Perplexity / Notion / Antigravity
        |
        | MCP / HTTPS / API keys / OAuth
        v
RalfIA Gateway
        |
        +-- MCP tools: buscar, guardar, consultar, resumir, crear tareas
        +-- REST/webhooks: n8n, formularios, Evolution API, automatizaciones
        +-- Auth/auditoria: API keys por cliente, logs, permisos
        |
        v
Datos y servicios internos
        |
        +-- MongoDB pcdoctor_swarm: memoria operativa y documentos
        +-- Postgres: datos estructurados y apps
        +-- Qdrant: busqueda semantica/RAG
        +-- Ollama: modelos locales
        +-- Whisper: transcripcion local
        +-- n8n: automatizaciones y webhooks
        +-- repos/proyectos: hackatones, clientes, CRMs, agentes
```

## Estado Actual Verificado

| Area | Estado |
|------|--------|
| SSH desde Windows | Configurado con llave local, usuario `rlopez` |
| MCP RaphiIA | Vivo en `127.0.0.1:8102/mcp` |
| Health RaphiIA | Vivo en `127.0.0.1:8101/status` |
| Auth MCP | Activa con `MCP_API_KEY` |
| MongoDB | `pcdoctor_swarm` responde |
| Qdrant | Responde en `6333` |
| Ollama | Responde en `11434` |
| Open WebUI | `3000` |
| AnythingLLM | `3001` |
| n8n | `5678` |
| Cursor Server | Activo por Remote SSH |
| Cloudflare Tunnel | Actualmente apunta a Ollama |
| ngrok activo | Actualmente apunta al gateway `5188`, no al MCP |

## Puertos Reservados

No cambiar estos puertos sin aprobacion explicita:

| Puerto | Servicio |
|--------|----------|
| 8091 | Ralphi Gateway |
| 8096 | Ralphi SRE |
| 8097 | UiPath Copilot |
| 8098 | Chutes Deposit Agent |
| 8099 | Hackathon Funding Hub |
| 8100 | Swarm-OS API |
| 8101 | RaphiIA-OpenAI health/status |
| 8102 | RaphiIA MCP |
| 5173 | InnerOS Admin |
| 5188 | Public gateway |
| 5678 | n8n |
| 6333 | Qdrant |
| 11434 | Ollama |

## Clientes a Conectar

| Cliente | Camino recomendado | Notas |
|---------|--------------------|-------|
| ChatGPT | MCP remoto HTTPS a `:8102/mcp` | Sin `OPENAI_API_KEY` en servidor |
| Cursor | Remote SSH + MCP RalfIA | Trabaja sobre repos del servidor |
| Codex | SSH + MCP/API RalfIA | Puede editar codigo y verificar servicios |
| Gemini / Antigravity | MCP RalfIA | Mantener misma fuente de datos |
| Perplexity | MCP si esta disponible, o bridge API/n8n | Ideal para investigacion externa |
| Notion | Notion MCP + sync RalfIA | Notion como interfaz, RalfIA como fuente |
| n8n | Webhooks + API interna | Automatizaciones y sincronizacion |

## Contingencia

Objetivo: si RalfIA cae, mantener consultas, escrituras basicas y continuidad operativa.

### Servidor AMD standby

- MongoDB replica o backups restaurables.
- Postgres replica/snapshots.
- Qdrant snapshots.
- MCP minimo compatible con las tools criticas.
- n8n minimo para flujos esenciales.
- Sin GPU: usar Ollama solo con modelos pequenos o desactivar inferencia local.

### Google Cloud

- Backups cifrados en Cloud Storage.
- Imagen o compose de emergencia para MCP + Mongo/Postgres/Qdrant.
- Opcion de VM standby apagada para bajar costos.
- DNS/tunnel preparado para redirigir `mcp` al nodo disponible.

## Fases Seguras

### Fase 0 - No invasiva

- Corregir documentacion de puertos reales.
- Documentar reglas de no interferencia.
- Verificar backups existentes.
- Exponer inventario read-only.

### Fase 1 - Conector ChatGPT

- Elegir ruta HTTPS estable para `:8102/mcp`.
- Mantener auth por API key inicialmente.
- Probar `search`, `fetch`, `health_check`.
- Registrar eventos en `raphiia_openai_sync_log`.

### Fase 2 - Control plane real

- Agregar tools por dominio: clientes, proyectos, oportunidades, hackatones, tareas, documentos.
- Definir permisos por cliente/tool.
- Crear auditoria estructurada para toda escritura.
- Conectar Cursor/Gemini/Notion al mismo MCP.

### Fase 3 - Alta disponibilidad

- Replicacion o snapshots automatizados al AMD.
- Backups verificados en Google Cloud.
- Runbook de failover.
- Prueba mensual de restauracion.

## Reglas Para Agentes

- No reiniciar servicios sin pedir permiso.
- No cambiar puertos existentes.
- No modificar proyectos de hackaton salvo tarea explicita.
- No leer ni imprimir secretos.
- No escribir directo en bases productivas sin tool acotada y auditoria.
- Preferir scripts read-only para inventario y health checks.
- Antes de tocar systemd, Docker, gateways o tunnels, documentar plan y rollback.


## Politica Local-First y Ahorro de Creditos

RalfIA debe procesar localmente todo lo que sea razonable antes de usar creditos externos. Ver [`CREDIT_AND_LOCAL_FIRST_POLICY.md`](CREDIT_AND_LOCAL_FIRST_POLICY.md).

Orden preferido: Mongo/Postgres/archivos locales -> Qdrant -> Ollama/Whisper/n8n -> MCP/API local -> nube solo cuando aporte valor claro.
