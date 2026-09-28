# Security Policy

## Supported branch

Security fixes are maintained on `main`. Feature and agent branches are temporary integration branches and are not release channels.

## Reporting a vulnerability

Do not open public issues containing credentials, tokens, private network details, customer information, exploit payloads, or operational secrets.

Report security issues privately to the repository owner through GitHub's private vulnerability reporting when enabled, or through an established private InnerChispa security contact.

Include:
- affected component and commit SHA;
- reproduction steps;
- impact;
- logs with secrets and personal data removed;
- suggested mitigation if known.

## Public repository boundary

This repository is intended to contain reusable InnerOS platform code, public architecture documentation, tests, safe fixtures, and reproducible examples.

It must not contain:
- production credentials or tokens;
- private keys;
- customer data;
- personal phone numbers or personal email addresses used as runtime configuration;
- exact private LAN/Tailscale topology unless required for a sanitized example;
- live tunnel URLs tied to production;
- raw coordination data or agent inbox exports;
- production database dumps;
- deployment secrets.

Examples must use placeholders such as `192.0.2.10`, `example.com`, and `user@example.com`.

## Agent and MCP security requirements

All agent/tool execution must preserve:
- least privilege;
- explicit capability/tool authorization;
- server-derived identity;
- bounded filesystem and repository scope;
- immutable terminal task states;
- auditable evidence;
- human approval for destructive or high-impact actions;
- no secret material in model-visible logs.

## Dependency and secret scanning

Before merge to `main`, changes should pass:
- repository tests relevant to the touched component;
- secret scanning;
- dependency review where dependency manifests change;
- a diff review for accidental operational data disclosure.

Security-sensitive changes to OAuth, MCP authorization, task ownership, Temporal workflows, or sandboxing require an explicit verification note in the pull request.
