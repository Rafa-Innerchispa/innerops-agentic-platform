# Governance

InnerOS Agentic Platform is an open-source project maintained by InnerChispa LLC.

## Project direction

The project is developed in public with `main` as the canonical integration branch. Maintainers prioritize:

1. durable execution over fragile agent loops;
2. local-first and vendor-neutral model routing;
3. explicit security and approval boundaries;
4. reproducible evidence over agent self-reporting;
5. interoperable protocols and replaceable components;
6. practical operational value over demo-only complexity.

## Maintainer responsibilities

Maintainers may:
- accept, request changes to, or decline contributions;
- define release scope;
- maintain compatibility and security boundaries;
- deprecate obsolete interfaces with documented migration;
- protect project trademarks and official distribution identity.

## Contribution decisions

Changes are evaluated on:
- correctness;
- security;
- testability;
- operational usefulness;
- architectural fit;
- maintenance cost;
- backward compatibility;
- public/private data boundary.

A technically valid contribution may still be declined when it duplicates an existing subsystem, creates conflicting orchestration ownership, or introduces unnecessary infrastructure.

## Architecture ownership

InnerOS keeps explicit responsibility boundaries:

- Temporal: durable execution lifecycle;
- LangGraph: agent reasoning/state graphs;
- NATS JetStream: event distribution;
- MongoDB: projections, evidence metadata, and operational search;
- MCP: bounded capabilities and tool protocol;
- OpenTelemetry: tracing and correlation;
- local/cloud model routers: inference selection;
- human approval: high-impact decision boundary.

## Releases

Releases are cut from `main` only after reproducibility, security, and integration checks. Public interfaces use semantic versioning where practical.

## Commercial services

InnerChispa may offer paid deployment, support, hosting, integrations, appliances, training, security work, and private modules around the Apache-2.0 core.

## Trademarks

The Apache License 2.0 covers the software in this repository. It does not grant a general license to use InnerOS, InnerChispa, logos, or other brand assets in a way that implies endorsement or official status.
