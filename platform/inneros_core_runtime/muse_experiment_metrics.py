"""Reusable, local-first experiment metrics for InnerOS Muse-assisted self-healing.

No provider calls, keys, credentials or customer telemetry. This module supplies
standardized token accounting, pre/post CI measurements, and a private, tamper-
evident event journal. A journal is not a cryptographically signed provider receipt.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from typing import Any

USD_PER_MILLION = {
    "muse-spark-1.3": {"input": Decimal("1.25"), "cached_input": Decimal("0.15"), "output": Decimal("4.25")},
    "muse-wonder-1.0": {"input": Decimal("4.00"), "cached_input": Decimal("0.20"), "output": Decimal("20.00")},
}
SCHEMA_VERSION = "inneros.muse.selfheal.metrics.v1"
ALLOWED_EVENTS = frozenset({
    "BASELINE_CI", "LOCAL_DIAGNOSIS", "META_REQUEST", "META_RESPONSE",
    "PATCH_PROPOSAL", "OWNER_APPROVAL", "ISOLATED_PATCH",
    "AFTER_CI", "ROLLBACK", "HUMAN_REVIEW", "BILLING_RECONCILIATION",
    "FINAL_OUTCOME", "EXPERIMENT_BLOCKED",
})
# Avoid arbitrary extra fields in journal, particularly request headers,
# prompts, API keys, customer data, CI raw logs, and private memory.
ALLOWED_METRICS = frozenset({
    "case_id", "project_id", "commit_sha", "workflow_run_url", "job_url",
    "model", "model_mode", "reasoning_effort", "experiment_arm",
    "status", "truth", "result", "failure_class", "error_code",
    "tests_passed", "tests_failed", "tests_skipped", "tests_total",
    "test_duration_ms", "request_latency_ms", "time_to_first_token_ms",
    "wall_duration_ms", "model_inference_ms", "local_execution_ms",
    "human_review_ms", "tool_call_count", "tool_execution_count",
    "files_changed", "lines_added", "lines_deleted", "candidate_patches",
    "successful_patches", "rollbacks", "unexpected_agent_loops",
    "duplicate_claims", "false_completions", "missing_acks",
    "input_tokens", "cached_input_tokens", "output_tokens",
    "reasoning_tokens", "total_tokens", "max_output_tokens",
    "provider_response_id", "provider_request_id", "request_sha256",
    "response_sha256", "evidence_sha256", "approval_ref", "evidence_url",
    "estimated_cost_usd", "verified_billing_usd", "billing_source",
    "reviewer_accuracy_rating", "reviewer_usefulness_rating",
    "hypotheses_count", "hypotheses_verified", "risks_identified",
    "notes_redacted", "confidence_label", "rollback_verified",
    "passed_after", "retries", "time_saved_ms",
})
NUMERIC_FIELDS = frozenset({
    "tests_passed", "tests_failed", "tests_skipped", "tests_total",
    "test_duration_ms", "request_latency_ms", "time_to_first_token_ms",
    "wall_duration_ms", "model_inference_ms", "local_execution_ms",
    "human_review_ms", "tool_call_count", "tool_execution_count",
    "files_changed", "lines_added", "lines_deleted", "candidate_patches",
    "successful_patches", "rollbacks", "unexpected_agent_loops",
    "duplicate_claims", "false_completions", "missing_acks",
    "input_tokens", "cached_input_tokens", "output_tokens",
    "reasoning_tokens", "total_tokens", "max_output_tokens",
    "estimated_cost_usd", "verified_billing_usd",
    "reviewer_accuracy_rating", "reviewer_usefulness_rating",
    "hypotheses_count", "hypotheses_verified", "risks_identified",
    "retries", "time_saved_ms",
})


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical(item: Any) -> bytes:
    return json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def price_quote(
    model: str, *, input_tokens: int, output_tokens: int,
    cached_input_tokens: int = 0, extra_tool_cost_usd: str = "0",
) -> dict[str, Any]:
    """Quote Standard-mode list price, NOT actual billed usage or credit expiry."""
    if model not in USD_PER_MILLION:
        raise ValueError("Unsupported standard model; no invented pricing")
    for value in (input_tokens, output_tokens, cached_input_tokens):
        if type(value) is not int or value < 0:
            raise ValueError("Token counters must be nonnegative integers")
    if cached_input_tokens > input_tokens:
        raise ValueError("Cached input cannot exceed reported input tokens")
    try:
        extra = Decimal(str(extra_tool_cost_usd))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid separate tool price") from None
    if not extra.is_finite() or extra < 0:
        raise ValueError("Tool price must be finite and nonnegative")
    fees = USD_PER_MILLION[model]
    uncached = input_tokens - cached_input_tokens
    price = (
        Decimal(uncached) * fees["input"]
        + Decimal(cached_input_tokens) * fees["cached_input"]
        + Decimal(output_tokens) * fees["output"]
    ) / Decimal(1000000) + extra
    return {
        "model": model, "pricing_mode": "STANDARD",
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": uncached,
        "output_tokens": output_tokens,
        "rate_usd_per_1m": {k: str(v) for k, v in fees.items()},
        "extra_tool_cost_usd": str(extra),
        "estimated_cost_usd": str(price),
        "cost_truth": "LIST_PRICE_ESTIMATE_NOT_META_BILLING",
        "source": "https://dev.meta.ai/docs/pricing-rate-limits",
    }


def quote_from_response(model: str, usage: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(usage, dict):
        raise ValueError("Provider usage counters required")
    i = usage.get("input_tokens")
    o = usage.get("output_tokens")
    details = usage.get("input_tokens_details")
    c = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
    quote = price_quote(model, input_tokens=i, output_tokens=o, cached_input_tokens=c)
    od = usage.get("output_tokens_details")
    rt = od.get("reasoning_tokens") if isinstance(od, dict) else None
    quote["reasoning_tokens"] = rt if isinstance(rt, int) and 0 <= rt <= o else None
    quote["visible_output_tokens_estimated"] = o - rt if isinstance(rt, int) and 0 <= rt <= o else None
    quote["total_tokens_reported"] = usage.get("total_tokens")
    return quote


def _allow_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        raise ValueError("Metrics must be a mapping")
    unknown = set(metrics) - ALLOWED_METRICS
    if unknown:
        raise ValueError("Refusing unknown telemetry fields (possible sensitive data): " + ", ".join(sorted(unknown)[:5]))
    safe: dict[str, Any] = {}
    for key, value in metrics.items():
        if value is None:
            safe[key] = None
        elif key in NUMERIC_FIELDS:
            if type(value) not in (int, float) or value < 0 or value != value:
                raise ValueError("Invalid nonnegative numeric metric: " + key)
            safe[key] = value
        elif key in ("rollback_verified", "passed_after"):
            if type(value) is not bool:
                raise ValueError("Expected boolean: " + key)
            safe[key] = value
        elif isinstance(value, str) and len(value) <= 500:
            safe[key] = value
        else:
            raise ValueError("Invalid or excessive metric payload: " + key)
    if "model" in safe and safe["model"] not in USD_PER_MILLION and safe["model"] not in ("amd-local-qwen", "intel-local-ollama"):
        raise ValueError("Unrecognized model metric")
    return safe


class ExperimentJournal:
    """Append-only local SQLite journal with atomic SHA-256 event chaining.

    The chain provides tamper-evidence *within the DB*, not independent
    attestation. Export an anchor SHA to a separate trusted store.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            self.path.parent.chmod(0o700)
        con = sqlite3.connect(str(self.path), timeout=5)
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE
                )
            """)
            con.commit()
        finally:
            con.close()
        if os.name == "posix":
            self.path.chmod(0o600)

    def append(self, event_type: str, case_id: str, metrics: dict[str, Any]) -> dict[str, Any]:
        if event_type not in ALLOWED_EVENTS:
            raise ValueError("Unrecognized event type")
        if not isinstance(case_id, str) or not case_id or len(case_id) > 80 or not all(ch.isalnum() or ch in "-_" for ch in case_id):
            raise ValueError("Invalid case ID")
        metrics = _allow_metrics(metrics)
        if metrics.get("case_id", case_id) != case_id:
            raise ValueError("Mismatched case ID")
        con = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        try:
            con.execute("BEGIN IMMEDIATE")
            last = con.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            previous = last[0] if last else "0" * 64
            document = {
                "schema": SCHEMA_VERSION, "recorded_at": _utc(),
                "event_type": event_type, "case_id": case_id,
                "metrics": metrics, "previous_hash": previous,
            }
            event_hash = _digest(_canonical(document))
            con.execute(
                "INSERT INTO events(recorded_at,event_type,case_id,data_json,previous_hash,event_hash) VALUES(?,?,?,?,?,?)",
                (document["recorded_at"], event_type, case_id, _canonical(metrics).decode(), previous, event_hash),
            )
            con.execute("COMMIT")
            return {"event_hash": event_hash, "previous_hash": previous, **document}
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def read(self, case_id: str | None = None) -> list[dict[str, Any]]:
        con = sqlite3.connect(str(self.path))
        try:
            if case_id is None:
                rows = con.execute("SELECT seq,recorded_at,event_type,case_id,data_json,previous_hash,event_hash FROM events ORDER BY seq").fetchall()
            else:
                rows = con.execute(
                    "SELECT seq,recorded_at,event_type,case_id,data_json,previous_hash,event_hash FROM events WHERE case_id=? ORDER BY seq", (case_id,)
                ).fetchall()
        finally:
            con.close()
        return [{
            "seq": row[0], "recorded_at": row[1], "event_type": row[2],
            "case_id": row[3], "metrics": json.loads(row[4]),
            "previous_hash": row[5], "event_hash": row[6],
        } for row in rows]

    def verify(self) -> dict[str, Any]:
        rows = self.read()
        previous = "0" * 64
        for row in rows:
            doc = {
                "schema": SCHEMA_VERSION, "recorded_at": row["recorded_at"],
                "event_type": row["event_type"], "case_id": row["case_id"],
                "metrics": row["metrics"], "previous_hash": previous,
            }
            if row["previous_hash"] != previous or row["event_hash"] != _digest(_canonical(doc)):
                return {"valid": False, "failed_seq": row["seq"], "total_events": len(rows)}
            previous = row["event_hash"]
        return {"valid": True, "total_events": len(rows), "last_hash": previous}


def score_case(events: list[dict[str, Any]]) -> dict[str, Any]:
    """No success inferred from a model's statement. Only sourced CI before/after."""
    baseline = next((e for e in events if e["event_type"] == "BASELINE_CI" and e["metrics"].get("workflow_run_url")), None)
    after = next((e for e in reversed(events) if e["event_type"] == "AFTER_CI" and e["metrics"].get("workflow_run_url")), None)
    response = next((e for e in reversed(events) if e["event_type"] == "META_RESPONSE"), None)
    b = baseline["metrics"] if baseline else {}
    a = after["metrics"] if after else {}
    baseline_fail = b.get("tests_failed")
    after_fail = a.get("tests_failed")
    return {
        "baseline_verified_source": baseline["metrics"]["workflow_run_url"] if baseline else None,
        "after_verified_source": after["metrics"]["workflow_run_url"] if after else None,
        "baseline_failed": baseline_fail,
        "after_failed": after_fail,
        "failed_tests_delta": baseline_fail - after_fail if type(baseline_fail) is int and type(after_fail) is int else None,
        "meta_result": (response or {}).get("metrics", {}).get("status", "NOT_RUN"),
        "claim_self_healed": bool(after and baseline and type(baseline_fail) is int and baseline_fail > 0 and after_fail == 0),
        "source_warning": "Evidence URLs must be independently checked; journal is not signed provider attestation",
    }
