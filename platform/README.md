# InnerOS Platform Runtime

This directory contains the core InnerOS runtime and MCP/tool surface used by the frozen All Things Agentic Hackathon submission.

## Runtime surfaces

- Core API: `http://127.0.0.1:8101`
- MCP / tool surface: `http://127.0.0.1:8102`
- Canonical runtime package: `inneros_core_runtime`

## Key components

- `inneros_core_runtime/gemini_runtime.py` — Gemini 3.5+ runtime integration
- `inneros_core_runtime/google_adk_a2a.py` — Google ADK / A2A integration
- `inneros_core_runtime/google_extra_models.py` — additional Google model routes including FunctionGemma support
- `inneros_core_runtime/resource_fabric.py` — local/cloud capability routing
- `inneros_core_runtime/a2a_*` — agent discovery, A2A bridge and durable task handling
- `inneros_core_runtime/dev_swarm_scheduler.py` — bounded development-agent scheduler
- `inneros_core_runtime/work_liveness.py` — liveness and stalled-work detection
- `inneros_core_runtime/integration_guardian.py` — verification / acceptance gate
- `inneros_core_runtime/racb_locks.py` — ownership and coordination locks

## Google hackathon path

The final submission uses and demonstrates:

- Gemini 3.5+
- Google ADK
- Google GenAI SDK
- Vertex AI
- FunctionGemma / Gemma
- Cloud Run
- Firestore
- Pub/Sub

Judge-facing proof is available through the live Judge Console documented in the repository root `JUDGES_START_HERE.md`.

## Local-first path

InnerOS routes eligible workloads to sovereign local infrastructure first, including AMD ROCm + vLLM inference. Cloud resources are used when they provide required capability or Google-native execution proof.

## Setup

From this directory:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./run.sh
```

Optional MCP surface:

```bash
./run_mcp.sh
```

Verify:

```bash
curl http://127.0.0.1:8101/status
```

Run the regression suite from the repository root:

```bash
python3 -m unittest discover -s platform/tests -p 'test_*.py'
```

Provider credentials are required only for the integrations being exercised. Secrets are intentionally not committed.

## Frozen hackathon version

Use repository branch:

```text
hackathon-freeze-20260831
```

Normal development can continue elsewhere without changing the source evaluated by judges.
