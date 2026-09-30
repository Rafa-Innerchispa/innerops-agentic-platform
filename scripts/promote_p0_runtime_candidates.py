#!/usr/bin/env python3
"""Promote validated runtime-only modules into the repair checkout.

This is intentionally canary-only and reversible. It reads the newest staged
runtime recovery report, verifies hashes/syntax/secret scan results, and copies
approved candidates into the repair branch. It never writes production, commits,
pushes, restarts services, or deploys.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST_RUNTIME = ROOT / "platform" / "inneros_core_runtime"
EVIDENCE_ROOT = ROOT / ".canary" / "runtime-recovery"
ACK = "I_UNDERSTAND_CANARY_ONLY"
APPROVED_COMMON = "runtime_only_common_identical"
APPROVED_INTEL_PREFIX = "mcp_gateway/"
MANIFEST_PATH = ROOT / "docs" / "P0_RUNTIME_RECOVERY_MANIFEST.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def newest_report() -> tuple[Path, dict]:
    reports = sorted(EVIDENCE_ROOT.glob("*/report.json"))
    if not reports:
        raise SystemExit("REFUSED: no staged runtime recovery report found")
    path = reports[-1]
    return path, json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    if os.getenv("INNEROS_P0_RECOVERY_ACK") != ACK:
        raise SystemExit(f"REFUSED: set INNEROS_P0_RECOVERY_ACK={ACK}")
    branch = os.popen(f"git -C '{ROOT}' branch --show-current").read().strip()
    if branch != "repair/coordination-recovery-20260929":
        raise SystemExit(f"REFUSED: expected repair branch, got {branch!r}")
    if str(ROOT).startswith("/home/rlopez/inneros/inneros_core"):
        raise SystemExit("REFUSED: never run candidate promotion in production checkout")

    report_path, report = newest_report()
    modules = report.get("modules") or {}
    candidates: list[dict] = []
    errors: list[str] = []

    for rel, item in sorted(modules.items()):
        category = item.get("classification")
        approved = category == APPROVED_COMMON or (
            category == "runtime_only_intel" and rel.startswith(APPROVED_INTEL_PREFIX)
        )
        if not approved:
            continue
        intel = item.get("syntax", {}).get("intel") or {}
        hits = item.get("secret_rule_hits", {}).get("intel") or []
        source_raw = item.get("snapshot_paths", {}).get("intel")
        source = Path(source_raw) if source_raw else None
        dest = DEST_RUNTIME / rel
        expected_hash = (item.get("hashes") or {}).get("intel")

        if not intel.get("syntax_ok"):
            errors.append(f"{rel}: Intel syntax not valid")
        elif hits:
            errors.append(f"{rel}: secret-rule hits present")
        elif not source or not source.is_file():
            errors.append(f"{rel}: staged Intel snapshot missing")
        elif digest(source) != expected_hash:
            errors.append(f"{rel}: staged snapshot hash mismatch")
        elif dest.exists():
            errors.append(f"{rel}: destination already exists; refusing overwrite")
        else:
            candidates.append({
                "module": rel,
                "classification": category,
                "source": source,
                "destination": dest,
                "sha256": expected_hash,
                "amd_sha256": (item.get("hashes") or {}).get("amd"),
            })

    if errors:
        raise SystemExit(json.dumps({"ok": False, "error": "candidate_validation_failed", "details": errors}, indent=2))
    if not candidates:
        raise SystemExit("REFUSED: no approved candidates found")

    for item in candidates:
        item["destination"].parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item["source"], item["destination"])

    manifest = {
        "version": "p0-runtime-recovery-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_report": str(report_path.relative_to(ROOT)),
        "production_mutated": False,
        "deployment_performed": False,
        "policy": {
            "common_modules": "identical on Intel and AMD, absent from branch",
            "intel_only_modules": "only mcp_gateway/* preserved; requires independent canary",
            "overwrites": "forbidden",
        },
        "modules": [
            {
                "module": item["module"],
                "classification": item["classification"],
                "sha256": item["sha256"],
                "amd_sha256": item["amd_sha256"],
            }
            for item in candidates
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "mode": "canary_checkout_candidate_promotion",
        "production_mutated": False,
        "deployment_performed": False,
        "candidate_count": len(candidates),
        "common_identical_count": sum(1 for item in candidates if item["classification"] == APPROVED_COMMON),
        "intel_only_gateway_count": sum(1 for item in candidates if item["classification"] == "runtime_only_intel"),
        "manifest": str(MANIFEST_PATH.relative_to(ROOT)),
        "next_gate": "review git diff, compile, test, and secret-scan before commit",
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
