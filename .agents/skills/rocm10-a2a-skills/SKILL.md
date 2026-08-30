---
name: rocm10-a2a-skills
description: ROCm 10 / ROCm.AI AMD Skills, Diagnostics, Serving & A2A Fleet Protocol Integration guidelines for InnerOS/ARIA.
---

# ROCm 10 & A2A Fleet Protocol Integration Skill

## Overview
This Skill provides the canonical reference and execution rules for ROCm 10 / ROCm.AI AMD Skills, local GPU diagnostics, serving LLMs on AMD hardware, and A2A (Agent-to-Agent) fleet protocol interoperability in InnerOS / ARIA.

## ROCm 10 / ROCm.AI AMD Skills Pattern
1. **Node Residency & Hardware Policy**:
   - **Primary AI Compute Node**: `.5` `ralfiia-amd` (AMD Radeon AI PRO R9700 / ROCm / vLLM).
   - **Baseline Resident Model**: `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ` via vLLM on port `8000` (`http://localhost:8000/v1`).
   - **Concurrency Limit**: Generation concurrency starts at 1 until benchmark proves higher throughput.
   - **Upgrade Policy**: NO major driver upgrade to ROCm 10 in production on R9700 prior to Aug 31 without compatibility matrix and rollback verification.

2. **AMD Skills Procedures**:
   - `rocm-doctor`: System diagnostics, VRAM monitoring, ROCm driver health checks.
   - `serving`: Governed local LLM inference via vLLM / Lemonade server (`http://localhost:13305/api/v1`).
   - `profiling`: Performance and latency tracing.

3. **Cloud Burst Optimization (AMD MI325X)**:
   - Evaluated exclusively on supported AMD Instinct hardware (MI325X cloud burst) under strict budget and approval gates.

## A2A (Agent-to-Agent) Fleet Protocol & Mailboxes
1. **Core Architectural Distinction**:
   - `MCP` = Agent-to-Tools/Data bridge (stateless or tool execution).
   - `A2A` = Agent-to-Agent durable protocol with Agent Cards, scoped capabilities, and durable dispatch.
   - `RACB` (Resource & Access Control Boundary) = Task claim, execution lifecycle, and evidence logging.

2. **Canonical A2A Execution Lifecycle**:
   $$\text{Stable Identity} \rightarrow \text{Live Coordination} \rightarrow \text{Mandatory Reads} \rightarrow \text{ACK Revision} \rightarrow \text{Inbox/ACK} \rightarrow \text{A2A Status/Cards} \rightarrow \text{RACB Ops Task Claim} \rightarrow \text{Correlation ID} \rightarrow \text{Heartbeat} \rightarrow \text{Result \& Evidence}$$

3. **Agent Cards & Interoperability**:
   - Agents (`ANTIGRAVITY`, `CHATGPT`, `CURSOR`, `CODEX`) exchange structured Agent Cards containing capabilities, versions, scopes, and health metadata.
