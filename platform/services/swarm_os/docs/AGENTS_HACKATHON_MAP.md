# Mapa de agentes — Hackathon Band of Agents

| Código | Agente | Band | LLM | Fuente datos |
|--------|--------|------|-----|--------------|
| AG-001 | Router | ✓ LIVE | Featherless | Pregunta operador |
| AG-004 | Memory | ✓ LIVE | Featherless | MongoDB + `/home/rlopez/data/docs/` |
| AG-003 | Analyst | ✓ LIVE | AIML API | Salida Memory |
| AG-005 | Documentation | ✓ LIVE | AIML API | Memory + Analyst |

## Flujo Band (@mentions)

1. **Router** publica plan → `@Memory`
2. **Memory** publica hechos recuperados → `@Analyst`
3. **Analyst** publica riesgos/recomendaciones → `@Documentation`
4. **Documentation** confirma reporte generado

Todo pasa por `hackathon_band/band_adapter.py` → REST `https://app.band.ai/api/v1/agent/...`

## IDs Band (.env)

```
BAND_AGENT_ID_ROUTER=
BAND_AGENT_ID_MEMORY=
BAND_AGENT_ID_ANALYST=
BAND_AGENT_ID_DOCUMENTATION=
```

Cada agente en Band tiene UUID + API key compartida `BAND_API_KEY`.

## LLM por rol

| Rol | Provider | Modelo default |
|-----|----------|----------------|
| Router, Memory | Featherless | `meta-llama/Meta-Llama-3.1-8B-Instruct` |
| Analyst, Documentation | AIML | `deepseek/deepseek-r1` |

Sin fallback local ni Ollama en el pipeline hackathon.
