# AG-39 RAUL — Catálogo Local

**Numeración:** AG-39 · **Nombre:** **RAUL** (Raul / Raúl)  
**ID:** `AG-39_raul_local_catalog`

## Misión

Hidratar el catálogo Contifico completo en Mongo **desde AMD `.5`**, sin créditos cloud.
Invocable desde **WhatsApp, voz, MCP o ChatGPT**:

- *"Dile a Raul que hidrate el catálogo"*
- *"Raul, estado del catálogo"*
- *"Raul busca cámaras Hikvision"*

## Canales

| Canal | Cómo llamarlo |
|-------|----------------|
| WhatsApp | `dile a Raul…` / `Raul hidrata el catálogo` |
| Voz | `dile a Raul que…` |
| MCP | `raul_dispatch`, `raul_catalog_status`, `raul_hydrate_catalog` |
| ChatGPT | perfil MCP `raul` |

## Lanzar hidratación completa

```bash
bash ~/inneros/inneros_core/platform/scripts/run_ag39_raul_hydrator.sh
# log: /home/rlopez/data/logs/raul_hydrator.log
```

## Política

- 0 créditos LLM cloud
- Ollama local solo para informes de progreso
- Contifico API read-only throttled desde red local
