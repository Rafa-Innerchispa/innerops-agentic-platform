# Judge-ready evidence pack - InnerOS / All Things Agentic

Date: 2026-08-30 UTC
Prepared by: Codex infrastructure lane
Scope: Evidence only. No Workforce product code changes in this commit.

## Public routes verified

| Surface | URL | Result |
|---|---|---|
| InnerOS app login | https://inneros.creatorcore.ai/app/login | HTTP 200, text/html |
| Workforce shell | https://workforce.creatorcore.ai/ | HTTP 200, text/html |
| ISKCON InnerOS login | https://inneros.iskconguayaquil.org/app/login | HTTP 200, text/html |
| ISKCON Desk | https://inneros.iskconguayaquil.org/desk | HTTP 200, text/html |
| Visitors portal | https://visitors.creatorcore.ai/ | HTTP 200, text/html |
| InnerOS Cloud Run domain | https://inneros.pcdoctor.ai/ | HTTP 200, title InnerOS, server Google Frontend |

## Cloud Run / Cloudflare proof

- Cloud Run project: `innerops-agentic-platform`
- Region: `us-central1`
- Domain mapping: `inneros.pcdoctor.ai -> inneros`
- Cloud Run conditions: `Ready=True`, `CertificateProvisioned=True`, `DomainRoutable=True`
- Required DNS record: `inneros CNAME ghs.googlehosted.com.`
- Cloudflare record: `2d894d8855a6814cca44bfb9e160ec09`, DNS-only CNAME to `ghs.googlehosted.com`
- Authoritative/public DNS observed from `rosa.ns.cloudflare.com`, `santino.ns.cloudflare.com`, `1.1.1.1`, and `8.8.8.8`: CNAME `ghs.googlehosted.com`, A `172.217.204.121`

## Tests and builds

- Platform cloud deployer/provider tests: `pytest inneros_core_runtime/tests/test_cloudflare_dns_upsert.py tests/test_digitalocean_amd_provider.py` => 13 passed
- Dev Swarm/local execution regression suite: `pytest tests/test_capacity_governor_vnext.py tests/test_dev_swarm_repo_inference.py tests/test_local_execution_plane.py` => 42 passed
- ISKCON Desk module: `./.venv/bin/python -m pytest -q` => 2 passed
- Workforce shell/product workspace smoke: `npm test -- --runInBand` in `services/femar-mvp-core` => 4 suites passed, 12 tests passed
- Workforce shell/product workspace build: `npm run build` in `services/femar-mvp-core` => compiled successfully, 47 static pages generated

## Cost and cloud cleanup proof

- DigitalOcean live droplets: 0
- Latest AMD MI325X Hyperloom session: `cloudburst_1788038425_4114048`, droplet `596208188`, region `tor1`, size `gpu-mi325x1-256gb`, status `destroyed`, destroyed at `2026-08-29T21:28:39.755756+00:00`
- FunctionGemma Vertex AI endpoints in `us-central1`: 0
- FunctionGemma Vertex AI models in `us-central1`: 0

## Evidence artifacts

- `docs/HACKATHON_LIVE_EVIDENCE_2026-08-29.md`
- `platform/docs/evidence/hackathon_live_evidence_kpi_card_2026-08-29.json`
- `platform/docs/evidence/functiongemma_live_2026-08-29.json`
- `platform/docs/evidence/google_hackathon_e2e_codex_2026-08-29.json`
- `/home/rlopez/inneros/inneros_core/var/evidence/hyperloom-mi325x-20260829/inneros-hyperloom-evidence.tgz`

## Relevant SHAs

| Lane | SHA |
|---|---|
| KPI card / judge proof branch base | `06432c9dcfcd8ab7b20403485e8e3550a0813dde` |
| Original KPI evidence pack | `2482a7ff77c833a73d295cd226f1a6b904a8ae2d` |
| Google/Gemma final integration | `cf291fe1a84bce16ec41148612708b921b4aefb0` |
| Google branch prior evidence | `66107e47ef1ab076ccf2cefa6c132d80dc1153c2` |
| Hyperloom MI325X evidence | `0e7384b6701098b5e5466b6325cb557d6a391200` |
| AG-44 cloud deployer/provider fix | `a4c57495cda1f03d5185e0aaf786a12e89194976` |

## Product lane boundary

Codex verified public health, build/test status, DNS/certificates, cost cleanup, and stale coordination cleanup. Cursor/ChatGPT own product changes for Workforce and the InnerOS portal. OAuth redirect URI confirmation remains a Rafael/Google Console gate if Google login is required for judge flow:

- `https://inneros.creatorcore.ai/api/auth/google/callback`
- `https://inneros.iskconguayaquil.org/api/auth/google/callback`