# Hackathon Live Evidence - 2026-08-29

This file is the judge-facing evidence index for the All Things Agentic demo. It maps every visible claim to something reproducible: an ops task, commit, test, runtime probe, cloud record, or evidence bundle.

## What Judges Can Verify Live

| Claim | Status | Live check | Evidence |
| --- | --- | --- | --- |
| MCP/A2A catalog remains broad and stable | PASS | Run `tools/list` or catalog/profile probe and confirm at least 612 tools with key tools present. | `msg_4d09db1104fda01a` |
| Agent registry has 55 functional agents and 60 total cards | PASS | Run `inneros_agent_fabric_status`. | `ops_3ca94bbe8609`, commit `a8eab403` |
| Self-heal KPI ledger blocks inflated ROI | PASS | Run `pytest -q tests/test_productivity_self_heal_metrics.py`. | `ops_6f431dccae8d`, commit `f07f5216ea1106a83d91ae3591ae222dac9b02e6` |
| KPI case: 120 min baseline, 10 min assisted, 110 min saved, 91.67 percent reduction, 12x speedup, 1.8333 HHR | PARTIAL | Inspect the KPI card and ledger calculation. | `platform/docs/evidence/hackathon_live_evidence_kpi_card_2026-08-29.json` |
| AMD local ROCm/vLLM runtime is factual | PASS | Run `local_model_runtime_status` and ROCm profiling evidence script against active `:8000`. | `ops_3ca94bbe8609`, commit `a8eab403` |
| Hyperloom MI325X burst was provisioned, tested, archived and destroyed | PASS | Inspect evidence archive and verify no active cloud-burst droplet remains. | `ops_0554539ce084`, commit `0e7384b6701098b5e5466b6325cb557d6a391200` |
| Google mandatory stack source path exists | PARTIAL | Confirm docs/source and rerun strict Google live proof before final claim. | `docs/GOOGLE_HACKATHON_COMPLIANCE_2026-08-29.md`, `ops_025150ef7943` |
| Public Indie Hackers proof | PARTIAL | Attach public URL or screenshot before PASS. | pending evidence ref |

## KPI Truth Boundary

The Broadlink productivity case is useful evidence, but it is not yet counted as verified Human Hours Returned. The preserved calculation is:

- Human baseline: 120 minutes
- Assisted time: 10 minutes
- Saved time: 110 minutes
- Human Hours Returned: 1.8333
- Reduction: 91.67 percent
- Speedup: 12.0x

Current status is `legacy_unclassified_pending_evidence_review`. It becomes verified HHR only after evidence refs are reviewed and migrated without overwriting the original event/history.

## Demo Contract

The compact contract consumed by demo surfaces lives at:

`platform/docs/evidence/hackathon_live_evidence_kpi_card_2026-08-29.json`

Demo views must display `PASS` and `PARTIAL` exactly as provided. They must not convert partial Google, public-proof, or unclassified KPI evidence into PASS.
