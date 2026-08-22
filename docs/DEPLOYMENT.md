# Deployment plan

InnerOps will use a separate Google Cloud project for this hackathon. It must not reuse or mutate the XPRIZE evidence project.

## Initial services

1. `innerops-gateway` — authenticated API and agent gateway.
2. `aria-runtime` — orchestration runtime using Google ADK or Google GenAI SDK.
3. `innerops-worker` — asynchronous specialist-agent worker.
4. Firestore — registry, task state and memory metadata.
5. Pub/Sub — asynchronous task/event transport.

## Required environment

Runtime configuration belongs in Google Cloud configuration/Secret Manager, never committed secrets. Expected logical settings include GCP project ID, region, Gemini model selection, Firestore database and Pub/Sub topic/subscription identifiers.

## Reproducibility target

The repository will provide one bootstrap command for local tests and one deployment workflow for the isolated hackathon GCP project. Until the new project is provisioned, this document intentionally does not claim a deployment that does not exist.

## Verification gates

A deployment is PASS only when health endpoint, authenticated ARIA request, specialist-agent dispatch, Firestore task persistence, trace/audit evidence and at least one asynchronous Pub/Sub execution have been verified.
