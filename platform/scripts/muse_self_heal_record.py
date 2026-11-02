"""CLI to record InnerOS self-healing before/after evidence with no cloud calls.

Usage:
  PYTHONPATH=platform python platform/scripts/muse_self_heal_record.py init
  PYTHONPATH=platform python platform/scripts/muse_self_heal_record.py report
  PYTHONPATH=platform python platform/scripts/muse_self_heal_record.py quote --model muse-wonder-1.0 --input 10000 --output 3000
  PYTHONPATH=platform python platform/scripts/muse_self_heal_record.py record --type AFTER_CI --metrics-json safe-metrics.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from inneros_core_runtime.muse_experiment_metrics import (
    ALLOWED_EVENTS, ExperimentJournal, price_quote, score_case,
)
from inneros_core_runtime.muse_wonder_trial import BASELINE_CI, CASE, DEFAULT_DIR, PROJECT

DEFAULT_DB = str(Path(DEFAULT_DIR) / "muse_experiments.sqlite3")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Record verified-source experimental metrics; no Meta network calls")
    sub = ap.add_subparsers(dest="cmd", required=True)
    baseline = sub.add_parser("init", help="Record the real 333 pass/4 fail GitHub CI baseline once")
    baseline.add_argument("--db", default=DEFAULT_DB)
    baseline.add_argument("--case-id", default=CASE)
    record = sub.add_parser("record", help="Record a sanitized event from a local JSON file")
    record.add_argument("--db", default=DEFAULT_DB)
    record.add_argument("--case-id", default=CASE)
    record.add_argument("--type", required=True, choices=sorted(ALLOWED_EVENTS))
    record.add_argument("--metrics-json", required=True)
    report = sub.add_parser("report", help="Verify chain and compute honest pre/post delta")
    report.add_argument("--db", default=DEFAULT_DB)
    report.add_argument("--case-id", default=CASE)
    quote = sub.add_parser("quote", help="Calculate Standard Mode list-price estimate (not actual billing)")
    quote.add_argument("--model", required=True, choices=("muse-wonder-1.0", "muse-spark-1.3"))
    quote.add_argument("--input", required=True, type=int)
    quote.add_argument("--output", required=True, type=int)
    quote.add_argument("--cached-input", type=int, default=0)
    opts = ap.parse_args(argv)
    if opts.cmd == "quote":
        print(json.dumps(price_quote(opts.model, input_tokens=opts.input,
                                     output_tokens=opts.output,
                                     cached_input_tokens=opts.cached_input), indent=2))
        return 0
    journal = ExperimentJournal(opts.db)
    if opts.cmd == "init":
        case_events = journal.read(opts.case_id)
        if any(e["event_type"] == "BASELINE_CI" for e in case_events):
            print(json.dumps({"case_id": opts.case_id, "baseline_already_exists": True,
                              "journal_valid": journal.verify()["valid"]}))
            return 0
        event = journal.append("BASELINE_CI", opts.case_id, {
            "case_id": opts.case_id, "project_id": PROJECT,
            "workflow_run_url": BASELINE_CI,
            "status": "FAIL_BASELINE_IN_GITHUB_ACTIONS",
            "truth": "SOURCED_GITHUB_CI",
            "tests_passed": 333, "tests_failed": 4, "tests_total": 337,
            "notes_redacted": "13 subtests passed; four coordination/trust-boundary assertion failures",
        })
        print(json.dumps({"baseline_recorded": True, "case_id": opts.case_id,
                          "event_hash": event["event_hash"], "source": BASELINE_CI}))
        return 0
    if opts.cmd == "record":
        path = Path(opts.metrics_json)
        if path.stat().st_size > 25000:
            raise ValueError("Metric JSON exceeds size limit; no raw logs or secrets")
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("Metric payload must be a JSON dictionary")
        ev = journal.append(opts.type, opts.case_id, obj)
        print(json.dumps({"event_recorded": True, "event_type": opts.type,
                          "event_hash": ev["event_hash"], "case_id": opts.case_id}))
        return 0
    validation = journal.verify()
    events = journal.read(opts.case_id)
    result = score_case(events)
    print(json.dumps({"schema": "inneros.muse.selfheal.report.v1", "case_id": opts.case_id,
                      "chain": validation, "event_count": len(events),
                      "event_types": [e["event_type"] for e in events],
                      "case_score": result}, indent=2, sort_keys=True))
    return 0 if validation["valid"] else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error_type": type(exc).__name__, "status": "BLOCKED"}), file=sys.stderr)
        sys.exit(2)
