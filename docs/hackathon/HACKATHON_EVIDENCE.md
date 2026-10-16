# Hackathon AMD — inferencia local medible (RalfIA / InnerOS)

Evidencia reproducible para GitHub y demo en vivo.

## Requisitos

- Nodo **AMD** `192.168.1.5` con vLLM en `127.0.0.1:8000`
- Nodo **Intel** `192.168.1.4` con platform runtime (`PYTHONPATH=.`)

## 1. Benchmark vLLM (AMD, ROCm)

```bash
cd /home/rlopez/inneros/inneros_core/platform
PYTHONPATH=. venv/bin/python3 scripts/hackathon_amd_inference_benchmark.py
```

**Artefacto:** `../var/evidence/hackathon_amd_inference_benchmark.json`

Métricas: latencia p50/p95, tokens/s, casos `INFERENCIA_OK`, snippet código, reasoning corto.

## 2. Router Intel → AMD (sin cloud)

```bash
cd platform && PYTHONPATH=. venv/bin/python3 -c "
from inneros_core_runtime import local_model_router as lmr
import time, json
t0=time.perf_counter()
r=lmr.route_ai_task('hackathon_github', 'Responde solo: ROUTER_OK', task_type='coding')
print(json.dumps({'latency_s':round(time.perf_counter()-t0,4),'ok':r.get('ok'),'backend':r.get('backend'),'selected_node':r.get('selected_node')}, indent=2))
"
```

**Artefacto:** `../var/evidence/hackathon_router_intel.json` (generado por script bundle).

## 3. Coordinación multi-agente (0 créditos IDE)

```bash
export INNEROS_COORD_AUTO_OWNER_APPROVE=1 NOTIFY_OPS_CREATE_AUTH=0
venv/bin/python3 scripts/coordination_cross_smoke_v2.py
```

**Artefacto:** `../var/evidence/coordination_cross_test_report.json`  
Esperado: `externals_ok: 6`, `carriles_ok: 8`, frases Alexa con **nonce** único.

## 4. Capacidad Dev Swarm

```bash
PYTHONPATH=. venv/bin/python3 -c "
from inneros_core_runtime import dev_swarm_scheduler as ds
import json
print(json.dumps(ds.capacity_status().get('recommendation'), indent=2))
"
```

## Historia para la demo (30 s)

1. **Privacidad y coste:** coding enruta a **vLLM local AWQ** en R9700, no API cloud.
2. **Medible:** JSON con latencia/tokens/s commit-friendly.
3. **Orquestación:** 8 carriles internos + 6 agentes IDE (competencia/Alexa) con evidencia Mongo.
4. **ROCm:** GPU visible vía `rocm-smi`; modelo Qwen3-Coder-30B en producción LAN.

## Licencia / repo

Publicar solo `var/evidence/*.json` sanitizados (sin PII). Scripts bajo `platform/scripts/`.
