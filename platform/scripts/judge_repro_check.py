#!/usr/bin/env python3
"""Read-only judge reproducibility check for InnerOS evidence packs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_FILES = [
    "docs/JUDGE_READY_EVIDENCE_2026-08-30.md",
    "docs/HACKATHON_LIVE_EVIDENCE_2026-08-29.md",
    "docs/KPI_ROI_EVIDENCE_2026-08-29.md",
    "docs/evidence/FINAL_TECHNICAL_GAPS_2026-08-30.md",
    "platform/docs/evidence/hackathon_live_evidence_kpi_card_2026-08-29.json",
]


def _load_text(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _load_json(root: Path, rel: str) -> dict[str, Any]:
    return json.loads(_load_text(root, rel))


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def check_files(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "check": f"required_file:{rel}",
            "status": _status((root / rel).is_file()),
            "path": rel,
        }
        for rel in REQUIRED_FILES
    ]


def check_evidence_content(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    live = _load_text(root, "docs/HACKATHON_LIVE_EVIDENCE_2026-08-29.md")
    judge = _load_text(root, "docs/JUDGE_READY_EVIDENCE_2026-08-30.md")
    card = _load_json(root, "platform/docs/evidence/hackathon_live_evidence_kpi_card_2026-08-29.json")

    checks = [
        ("live_doc_uses_58_a2a_cards", "58 A2A agent cards" in live),
        ("live_doc_no_stale_55_60_claim", "55 functional agents" not in live and "60 total cards" not in live),
        ("live_doc_no_stale_612_tool_claim", "612 tools" not in live),
        ("judge_doc_has_public_routes", "https://inneros.creatorcore.ai/app/login" in judge),
        ("judge_doc_has_cost_cleanup", "DigitalOcean live droplets: 0" in judge),
        ("kpi_truth_policy_blocks_inflation", bool(card.get("truth_policy", {}).get("unverified_legacy_events_are_not_verified_hhr"))),
        ("kpi_keeps_public_proof_partial", any(item.get("claim") == "Public Indie Hackers proof exists" and item.get("status") == "PARTIAL" for item in card.get("live_verification", []))),
        ("kpi_uses_current_a2a_claim", any("58 A2A agent cards" in item.get("claim", "") for item in card.get("live_verification", []))),
    ]
    for name, ok in checks:
        results.append({"check": name, "status": _status(ok)})
    return results


def check_runtime() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    canonical_platform = Path("/home/rlopez/inneros/inneros_core/platform")
    if canonical_platform.is_dir():
        sys.path.insert(0, str(canonical_platform))
    try:
        from inneros_core_runtime import mcp_server
    except Exception as exc:
        return [
            {
                "check": "runtime_import",
                "status": "PARTIAL",
                "detail": f"inneros_core_runtime unavailable: {exc}",
            }
        ]

    try:
        a2a = mcp_server.a2a_agent_cards()
        count = len(a2a.get("agents") or a2a.get("cards") or [])
        if not count:
            count = int(a2a.get("count") or 0)
        results.append({"check": "runtime_a2a_agent_cards", "status": _status(count == 58), "count": count})
    except Exception as exc:
        results.append({"check": "runtime_a2a_agent_cards", "status": "FAIL", "detail": repr(exc)})

    try:
        profiles = mcp_server.list_mcp_tool_profiles()
        count = int(profiles.get("profile_count") or len(profiles.get("profiles") or []))
        results.append({"check": "runtime_mcp_profile_count", "status": _status(count == 39), "count": count})
    except Exception as exc:
        results.append({"check": "runtime_mcp_profile_count", "status": "FAIL", "detail": repr(exc)})

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repository root to inspect")
    parser.add_argument("--skip-runtime", action="store_true", help="Do not import/query local MCP runtime")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    results = check_files(root)
    if all(item["status"] == "PASS" for item in results):
        results.extend(check_evidence_content(root))
    if not args.skip_runtime:
        results.extend(check_runtime())

    statuses = {item["status"] for item in results}
    overall = "PASS" if statuses <= {"PASS"} else "PARTIAL" if "FAIL" not in statuses else "FAIL"
    payload = {"overall": overall, "root": str(root), "results": results}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
