"""One-shot, owner-operated Muse Wonder diagnostic with complete private metrology.

ONLY an isolated synthetic lab experiment. Not a replacement for the production
Home Assistant approval pipeline. Never expose as a public endpoint, MCP tool,
automatic scheduler, or paid agent loop. No network on import or dry-run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib import request, error

from .muse_experiment_metrics import ExperimentJournal, price_quote, quote_from_response

MODEL = "muse-wonder-1.0"
URL = "https://api.meta.ai/v1/responses"
PROJECT = "inneros-meta-guardian-2026"
CASE = "inneros-agent-coordination-p0"
DEFAULT_DIR = "runtime/muse_selfheal_trials"
BASELINE_CI = "https://github.com/Rafa-Innerchispa/innerops-agentic-platform/actions/runs/41510104055"
MAX_RESPONSE_BYTES = 524288
PROMPT = """FICTIONAL LAB DATA ONLY: This is a sanitized synthetic
reproduction of four types of failures from an AI agent orchestration system.
No real customer data, source code, IPs, logs, credentials or internal memory
are provided.

A local CI run in an isolated agent-control-plane experiment returned 333 passing
tests and four failing tests. These are symptoms, not evidence that the
implementation is defective.

F1 (local fallback): expected generic 'all_local_model_routes_unavailable';
actual 'intel_ollama_no_model'. Both represent fail-closed operation, but
the status contract changed.
F2 (manual task admission): expected 'manual_dispatch_only'; actual
'execution_automation_frozen'. Manual tasks must never be auto-claimed.
F3 (agent false completion): a shell-script regression test expected one
bounded executor plan marker but found two. Actual agent work must be
verified by ACK, committed changes and test evidence.
F4 (provider trust boundary): expected 'owner_budget_grant_required';
actual 'resource_task_not_executable'. External provider execution
must remain blocked without a verified owner budget grant.

Please act as a senior software reliability investigator. Diagnose probable
causes and explain when the failing assertion could be stale versus when the
implementation violates a safety invariant. Prioritize the smallest
non-destructive changes and test updates. You have NO file-edit tools and
NO authority to deploy, spend again, or change production systems.

Respond with JSON or clear headings containing:
1. A table of F1..F4 hypotheses, uncertainty and evidence still needed;
2. For each, whether to fix test expectation or implementation and WHY;
3. Minimal safe patch outlines (not unverifiable claims of fixed code);
4. Reproduction plan and exact before/after verification gates;
5. Main risks, rollback and owner approval requirements.
No generic filler or invented measurements."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _save(path: Path, document: dict[str, Any]) -> None:
    data = (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _text(response: dict[str, Any]) -> str:
    lines = []
    for item in response.get("output", []) or []:
        if isinstance(item, dict) and item.get("type") == "message":
            for part in item.get("content", []) or []:
                if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    lines.append(part["text"])
    return "\n".join(lines).strip()


def run_trial(
    *, trial_id: str, record_dir: str | Path, authorized: bool,
    approval_ref: str | None = None, max_output_tokens: int = 4096,
    reasoning_effort: str = "medium", budget_usd: str = "0.50",
    credential_loader: Callable[[], str] | None = None,
    transport: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Execute exactly one request, after creating an exclusive claim."""
    if not authorized or not approval_ref:
        raise PermissionError("A conscious owner CLI acknowledgement and audit reference are required")
    if not trial_id or len(trial_id) > 60 or not all(ch.isalnum() or ch in "_-" for ch in trial_id):
        raise ValueError("Invalid trial ID")
    if type(max_output_tokens) is not int or not 1024 <= max_output_tokens <= 8192:
        raise ValueError("Choose 1024-8192 output tokens, including hidden reasoning")
    if reasoning_effort not in ("minimal", "low", "medium", "high"):
        raise ValueError("Unsupported Wonder reasoning effort")
    body = {"model": MODEL, "store": False, "input": PROMPT,
            "reasoning": {"effort": reasoning_effort},
            "max_output_tokens": max_output_tokens}
    request_bytes = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    # Bytes in a UTF-8 prompt provide an intentionally generous local proxy
    # for billable input tokens, not the provider's authoritative count.
    quote = price_quote(MODEL, input_tokens=len(PROMPT.encode("utf-8")),
                        output_tokens=max_output_tokens)
    from decimal import Decimal
    cap = Decimal(str(budget_usd))
    if not cap.is_finite() or cap <= 0 or cap > Decimal("1.00"):
        raise ValueError("Owner-operated experiment maximum preflight budget is $1")
    if Decimal(quote["estimated_cost_usd"]) > cap:
        raise ValueError("Worst-case token quote exceeds the owner-approved budget")
    base = Path(record_dir).expanduser()
    base_existed = base.exists()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix" and not base_existed:
        base.chmod(0o700)
    folder = base / trial_id
    folder.mkdir(mode=0o700, exist_ok=False)  # atomic dedupe BEFORE credentials / request
    # The local terminal's --owner-authorized is NOT a signed HA grant; mark so.
    _save(folder / "claim.json", {
        "trial_id": trial_id, "model": MODEL, "created_at": _timestamp(),
        "project_id": PROJECT, "case_id": CASE,
        "owner_cli_ack_only": True, "verified_ha_approval": False,
        "approval_ref": approval_ref, "max_output_tokens": max_output_tokens,
        "reasoning_effort": reasoning_effort, "price_cap_usd": str(cap),
        "preflight_quote": quote, "network_attempts_max": 1, "automatic_retries": 0,
    })
    _save(folder / "request.json", {
        "requested_at": _timestamp(), "request_body": body,
        "request_sha256": _sha(request_bytes),
        "data_classification": "SYNTHETIC_FIXTURE_ONLY",
    })

    # Exact owner-vault integration from the central Meta provider, not a key
    # held by the hackathon repository. Never log or expose the credential.
    if credential_loader is None:
        from .meta_model_provider import _get_server_key
        credential_loader = _get_server_key

    started = time.perf_counter_ns()
    status = None
    raw = b""
    headers: Any = {}
    transport_error: str | None = None
    key = ""
    try:
        key = credential_loader()
        if not isinstance(key, str) or not key:
            raise PermissionError("No central vault key")
        req = request.Request(URL, data=request_bytes, method="POST",
                              headers={"Authorization": "Bearer " + key,
                                       "Content-Type": "application/json"})
        try:
            with (transport or request.urlopen)(req, timeout=90) as resp:
                status = int(getattr(resp, "status", 200))
                headers = getattr(resp, "headers", {})
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except error.HTTPError as exc:
            status, headers = exc.code, exc.headers
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
    except Exception as exc:
        # Never save an exception's message, it may contain secrets.
        transport_error = type(exc).__name__
    elapsed = round((time.perf_counter_ns() - started) / 1e6, 3)
    # The provider should never echo our API key, but scrub it defensively.
    raw = raw.replace(key.encode(), b"[REDACTED]") if key else raw
    response: dict[str, Any] = {}
    if len(raw) > MAX_RESPONSE_BYTES:
        transport_error = "RESPONSE_TOO_LARGE"
    else:
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
            response = parsed if isinstance(parsed, dict) else {}
        except (ValueError, UnicodeError):
            transport_error = "INVALID_JSON"
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    try:
        cost = quote_from_response(MODEL, usage)
    except ValueError:
        cost = None
    rid = response.get("id") if isinstance(response.get("id"), str) else None
    output = _text(response)
    completed = status == 200 and response.get("status") == "completed" and bool(rid) and bool(output)
    outcome = (
        "REAL_SUCCESS" if completed else
        "INCOMPLETE" if response.get("status") == "incomplete" else
        "BILLING_BLOCKED" if status == 402 else
        "AUTH_BLOCKED" if status in (401, 403) else
        "NETWORK_ERROR" if transport_error else "UNVERIFIED_RESPONSE"
    )
    receipt = {
        "schema": "inneros.muse.wonder.one_shot.v1",
        "trial_id": trial_id, "case_id": CASE, "project_id": PROJECT,
        "model_requested": MODEL, "model_returned": response.get("model"),
        "provider_response_id": rid,
        "provider_completion_status": response.get("status"),
        "http_status": status, "result": outcome, "started_or_claimed_at": _timestamp(),
        "latency_ms": elapsed, "request_sha256": _sha(request_bytes),
        "response_sha256": _sha(raw) if raw else None,
        "response_bytes": len(raw), "visible_text_bytes": len(output.encode()),
        "visible_text_sha256": _sha(output.encode()) if output else None,
        "usage": usage, "estimated_cost_quote": cost,
        "verified_billing_usd": None,
        "billing_status": "NOT_RECONCILED",
        "request_id": (headers.get("x-request-id") if headers else None),
        "transport_error_type": transport_error,
        "automatic_retries": 0,
        "data_truth": "SYNTHETIC_FIXTURE_ONLY",
        "provider_truth": "RECEIPT_NEEDS_INDEPENDENT_VERIFICATION",
    }
    _save(folder / "provider_response.json", response)
    _save(folder / "receipt.json", receipt)
    journal = ExperimentJournal(base / "muse_experiments.sqlite3")
    journal.append("META_RESPONSE", CASE, {
        "case_id": CASE, "project_id": PROJECT,
        "experiment_arm": "META_WONDER_STANDARD",
        "model": MODEL, "status": outcome,
        "truth": "RECORDED_FROM_OPERATOR_PROBE_NOT_INDEPENDENTLY_VERIFIED",
        "provider_response_id": rid, "request_sha256": _sha(request_bytes),
        "response_sha256": _sha(raw) if raw else None,
        "input_tokens": usage.get("input_tokens") if isinstance(usage.get("input_tokens"), int) else None,
        "output_tokens": usage.get("output_tokens") if isinstance(usage.get("output_tokens"), int) else None,
        "reasoning_tokens": (usage.get("output_tokens_details", {}) or {}).get("reasoning_tokens")
        if isinstance(usage.get("output_tokens_details", {}), dict) else None,
        "request_latency_ms": elapsed,
        "estimated_cost_usd": float(cost["estimated_cost_usd"]) if cost else None,
    })
    return receipt


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="One-shot Muse Wonder trial; synthetic only, no loops, no public API")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--one-shot", action="store_true")
    p.add_argument("--trial-id", default="muse-wonder-selfheal-20261102")
    p.add_argument("--record-dir", default=DEFAULT_DIR)
    p.add_argument("--max-output-tokens", type=int, default=4096)
    p.add_argument("--reasoning-effort", choices=("minimal", "low", "medium", "high"), default="medium")
    p.add_argument("--budget-usd", default="0.50")
    p.add_argument("--owner-authorized", action="store_true")
    p.add_argument("--approval-ref", default="")
    args = p.parse_args(argv)
    if args.dry_run:
        q = price_quote(MODEL, input_tokens=len(PROMPT.encode()),
                        output_tokens=args.max_output_tokens)
        print(json.dumps({
            "state": "NOT_RUN", "case_id": CASE, "model": MODEL,
            "baseline_CI": BASELINE_CI, "max_output_tokens": args.max_output_tokens,
            "preflight_upper_proxy": q,
            "note": "No API request, credentials or credits used",
        }, indent=2))
        return 0
    try:
        receipt = run_trial(
            trial_id=args.trial_id, record_dir=args.record_dir,
            authorized=args.owner_authorized, approval_ref=args.approval_ref,
            max_output_tokens=args.max_output_tokens,
            reasoning_effort=args.reasoning_effort,
            budget_usd=args.budget_usd,
        )
        print(json.dumps({k: v for k, v in receipt.items() if k not in ("usage",)}, indent=2))
        return 0 if receipt["result"] == "REAL_SUCCESS" else 2
    except (PermissionError, ValueError, FileExistsError, OSError) as exc:
        print(json.dumps({"state": "BLOCKED_BEFORE_REQUEST", "error_class": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
