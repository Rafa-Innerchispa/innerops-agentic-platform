# Visión — RaphiIA-OpenAI (MCP)

## Problema

Ideas y conversaciones en ChatGPT no alimentan automáticamente el OS Central RalfyIA (MongoDB editorial, ideas, pipeline multicanal).

## Solución

Microservicio **MCP** que expone **tools** a ChatGPT Connectors. Rafael chatea en **ChatGPT normal**; cuando hace falta, ChatGPT invoca tools que **solo leen/escriben MongoDB** — sin segundo LLM de pago en el servidor.

## Flujo

```
Rafael → ChatGPT (plan Plus/Pro)
           ↓ tools MCP (HTTPS)
         raphiia-openai MCP :8102
           ↓
         MongoDB pcdoctor_swarm
```

## Principios

1. **MCP primero** — no Custom GPT, no OpenAI API en backend.
2. **Mongo compartida** — datos reales + colecciones bridge.
3. **Respaldos** — disaster recovery diario (Mongo incluida).
4. **Repo aislado** — puertos `:8101` / `:8102`, sin mezclar hackathons.

## Fases

- **v1:** MCP save/search + conectar ChatGPT
- **v2:** Pipeline editorial DB48 → DB15 → DB16 redes
- **v3:** Publicación automática redes (APIs externas)
