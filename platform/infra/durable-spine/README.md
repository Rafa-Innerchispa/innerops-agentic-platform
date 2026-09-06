# InnerOS Durable Spine Local Runtime

This directory is a local-first runtime sandbox for the MCP/A2A durable spine.
It is intentionally not started by default and binds every exposed port to
`127.0.0.1` so it is not public through Cloudflare, ngrok, or the LAN.

## Layers

- MCP/A2A remains the public agent contract.
- MongoDB remains the current source of truth for live ops tasks.
- `ralfia_coordination_events` is the new event ledger for replayable lifecycle evidence.
- NATS JetStream is the durable event bus for queue fanout, acknowledgements, replay and consumers.
- Temporal is the workflow engine for long-running task lifecycle, retries, approvals and stale recovery.
- OpenTelemetry carries trace/span context across agents, tools, workers and evidence.

## Local bring-up

From this folder:

```bash
docker compose up -d nats temporal otel-collector
```

Local endpoints:

- NATS: `127.0.0.1:4222`
- NATS monitoring: `http://127.0.0.1:8222`
- Temporal gRPC: `127.0.0.1:7233`
- Temporal UI: `http://127.0.0.1:8233`
- OpenTelemetry OTLP/gRPC: `127.0.0.1:4317`
- OpenTelemetry OTLP/HTTP: `http://127.0.0.1:4318`

## Safety

Do not expose these ports publicly. Put Cloudflare Access/OAuth in front of any
future browser UI. For the first production pass, deploy NATS/Temporal only on
the internal service network and keep MCP as the authenticated edge.
