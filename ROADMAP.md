# InnerOS Roadmap

This roadmap describes product direction, not guaranteed delivery dates.

## v0.1 - Public durable operations core

Goal: make the architecture reproducible and understandable from a clean clone.

- converge validated work to `main`;
- finish compact MCP gateway integration;
- document Temporal + LangGraph execution path;
- document NATS and OpenTelemetry integration;
- clean public/private configuration boundary;
- publish focused integration tests;
- publish first reproducible demo workflow;
- prepare `v0.1.0` release notes and public landing page;
- cut `v0.1.0` only after convergence, clean-clone, security/privacy, and MCP-router gates pass.

## v0.2 - Reliable agent fleet

- canonical Temporal-owned task lifecycle;
- eliminate duplicate scheduler ownership;
- stronger worker leasing and recovery semantics;
- clean task projection to Mongo;
- agent capability discovery;
- bounded multi-node execution;
- reproducible local-model failover;
- integration test matrix for Intel/AMD/local/cloud lanes.

## v0.3 - Operator experience

- unified operator dashboard;
- workflow/task traces;
- branch/runtime provenance;
- human approval inbox;
- failure replay and evidence explorer;
- deployment health view;
- simpler installation profile for single-node users.

## v0.4 - Ecosystem

- documented connector SDK;
- reference MCP gateway profiles;
- reusable workflow templates;
- example vertical integrations;
- community contribution catalog;
- compatibility tests for third-party MCP servers.

## v1.0 - Stable operational contract

Target characteristics:

- documented stable task envelope;
- stable capability contract;
- stable execution lifecycle;
- production-grade observability;
- upgrade/migration policy;
- security review;
- clean separation between open core and private operational configuration;
- reference self-hosted deployment;
- public benchmark and chaos/recovery evidence.

## Non-goals

InnerOS does not aim to:
- replace every workflow engine;
- make every operation probabilistic;
- require a specific model vendor;
- hide deterministic rules inside LLM prompts;
- expose customer or private operational data in the public repository.
