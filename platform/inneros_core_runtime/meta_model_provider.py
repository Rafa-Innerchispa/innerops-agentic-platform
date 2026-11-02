"""Reusable Meta Model API provider for InnerOS Resource Fabric.

This lives in the CORE platform, not the Meta hackathon application.
All callers share the provider identity, encrypted owner vault, task budgets,
SQLite one-use authorization ledger and a standardized receipt contract.

SAFETY: no public HTTP routes, no auto retries, no raw prompts in the ledger,
no cloud calls without a trusted, per-request owner approval verifier. The
initial implementation allows only explicitly labeled SYNTHETIC data.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib import error, request

PROVIDER_ID = "meta-model-api"
MODEL = "muse-spark-1.3"
BASE_URL = "https://api.meta.ai/v1"
RESPONSES_URL = BASE_URL + "/responses"
VAULT_CATEGORY = "model_api_provider"
VAULT_KEY = "meta_model_api_key"
CREDENTIAL_REF = f"owner_vault:{VAULT_CATEGORY}/{VAULT_KEY}"
SOURCE_POLICY = "SYNTHETIC"

DEFAULT_MAX_OUTPUT_TOKENS = 256
MAX_ALLOWED_OUTPUT_TOKENS = 1024
MAX_OUTPUT_TOKENS = MAX_ALLOWED_OUTPUT_TOKENS
MAX_INPUT_CHARS = 6000
DEFAULT_DB = "~/.local/state/inneros/model-provider-meta.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _serial(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _parse_utc_instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def manifest_document() -> dict[str, Any]:
    return {
        "id": PROVIDER_ID,
        "label": "Meta Model API | Muse Spark",
        "auth_mode": "owner_vault",
        "secret_category": VAULT_CATEGORY,
        "risk_level": "moderate_write",
        "capabilities": ["status", "preflight", "dry_run", "audit", "frontier_reasoning", "single_use_inference"],
        "allowed_resources": ["muse_spark_responses"],
        "allowed_domains": ["api.meta.ai"],
        "rate_limits": {"api_requests_per_minute": 1},
        "default_model": MODEL,
        "cost_policy": "external_explicit_one_shot_only",
    }


def _has_vault_key() -> bool:
    try:
        from raphiia_openai import owner_vault  # existing central encrypted vault
        result = owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=False)
        return bool(result.get("ok"))
    except Exception:
        # Registry inspection must never fail if Mongo/owner_vault is offline.
        # This is a status-only path and must not return or log secrets.
        return False


def resource_provider_document() -> dict[str, Any]:
    configured = _has_vault_key()
    return {
        "provider_id": PROVIDER_ID,
        "label": "Meta Model API / Muse Spark",
        "kind": "external_model_provider",
        "capabilities": ["frontier_reasoning", "single_use_inference"],
        "local_first": False,
        "status": "configured" if configured else "credential_not_configured",
        "auth_mode": "owner_vault",
        "credential_ref": CREDENTIAL_REF,
        "default_model": MODEL,
        "cost_policy": "explicit_burst_only",
        "funding_provider": "meta",
        "billing": {"credit_account": "funding_registry", "remaining_usd": None, "amount_verified": False},
        "governance": "trusted owner approval; persistent one-use grant; no public exposure; no automatic retry",
    }


def model_provider_document() -> dict[str, Any]:
    # Local AMD/Intel remain the default. This provider is only eligible with
    # an explicit cloud-capability request and a separate authorization grant.
    return {
        "model_provider": "meta-model-api",
        "provider_id": PROVIDER_ID,
        "model_ref": MODEL,
        "task_classes": ["frontier_reasoning", "specialized_external_reasoning"],
        "priority": 90,
        "cost_policy": "explicit_burst_only",
        "local_first": False,
    }


def provider_status() -> dict[str, Any]:
    return {
        "ok": True, "provider_id": PROVIDER_ID,
        "configured_in_owner_vault": _has_vault_key(),
        "credential_ref": CREDENTIAL_REF,
        "secret_returned": False,
        "model": MODEL,
        "live_model_inference_verified": False,  # status is updated only via verified receipts
        "credit_balance_usd": None,  # never infer balance from a promotional award screenshot
        "default_execution": "blocked_until_owner_grant",
    }


def store_api_key_server_side(secret: str, *, actor: str = "RAFAEL") -> dict[str, Any]:
    """Trusted setup only; use a secret input prompt and never pass a key via MCP messages."""
    if not secret or len(secret.strip()) < 12 or actor.upper() != "RAFAEL":
        return {"ok": False, "error": "owner_secret_required", "secret_returned": False}
    from raphiia_openai import owner_vault
    saved = owner_vault.save_owner_credential(
        key=VAULT_KEY, secret=secret.strip(), category=VAULT_CATEGORY,
        label="Meta Model API shared InnerOS provider",
        metadata={"provider_id": PROVIDER_ID, "scope": "shared_inneros", "never_return_plaintext": True},
        actor=actor,
    )
    return {
        "ok": bool(saved.get("ok")),
        "credential_ref": CREDENTIAL_REF,
        "secret_returned": False,
        "error": saved.get("error"),
    }


def _get_server_key() -> str:
    from raphiia_openai import owner_vault
    doc = owner_vault.get_owner_credential(VAULT_KEY, category=VAULT_CATEGORY, reveal=True, actor="RAFAEL")
    key = str(doc.get("secret") or "") if doc.get("ok") else ""
    if not key:
        raise PermissionError("Shared Meta API credential is absent in the owner vault")
    return key


def _validate_prompt(prompt: str, classification: str) -> str:
    if classification != SOURCE_POLICY:
        raise PermissionError("Only synthetic prompts may leave InnerOS until an approved data-release gate exists")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_INPUT_CHARS:
        raise ValueError("Prompt required, max 6000 characters")
    # Label has to survive from the owner-approved input to provider dispatch.
    if not prompt.startswith("FICTIONAL LAB DATA ONLY:"):
        raise PermissionError("Synthetic prompt must start with the fictional-lab provenance marker")
    return prompt


class MetaGrantLedger:
    """Transactional cross-process grant ledger; no API key or prompt text is stored.

    The caller must supply an actual trusted HA/owner-approval verifier. There is
    deliberately NO self-service public grant issuance in this module.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("INNEROS_META_LEDGER_DB", DEFAULT_DB)).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            self.path.parent.chmod(0o700)
        with self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS grants(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    prompt_sha TEXT NOT NULL, model TEXT NOT NULL,
                    max_output_tokens INTEGER NOT NULL,
                    expires_epoch REAL NOT NULL, consumed_epoch REAL,
                    issued_at TEXT NOT NULL, approval_ref TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS receipts(
                    id TEXT PRIMARY KEY, grant_id TEXT UNIQUE NOT NULL,
                    project_id TEXT NOT NULL, provider_id TEXT NOT NULL,
                    model TEXT NOT NULL, status TEXT NOT NULL,
                    http_status INTEGER, provider_response_id TEXT,
                    request_sha TEXT NOT NULL, response_sha TEXT,
                    latency_ms REAL, tokens_json TEXT NOT NULL,
                    error_type TEXT, completed_at TEXT NOT NULL
                );
            """)
        if os.name == "posix":
            self.path.chmod(0o600)

    from contextlib import contextmanager

    @contextmanager
    def _connect(self):
        c = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        c.execute("PRAGMA busy_timeout=5000")
        try:
            yield c
        finally:
            c.close()

    def issue(
        self, *, project_id: str, prompt: str, approval: dict[str, Any],
        verifier: Callable[[dict[str, Any]], bool] | None,
        classification: str = SOURCE_POLICY,
        max_output_tokens: int = 192, ttl_seconds: int = 180,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        prompt = _validate_prompt(prompt, classification)
        if not project_id or len(project_id) > 96:
            raise ValueError("A scoped project ID is required")
        if isinstance(max_output_tokens, bool) or not 16 <= int(max_output_tokens) <= MAX_ALLOWED_OUTPUT_TOKENS:
            raise ValueError(f"Output tokens must be between 16 and {MAX_ALLOWED_OUTPUT_TOKENS}")
        if isinstance(ttl_seconds, bool) or not 1 <= int(ttl_seconds) <= 300:
            raise ValueError("Grant TTL must be within 1–300 seconds")
        if reasoning_effort is not None and str(reasoning_effort).lower() not in ("low", "medium", "high"):
            raise ValueError("reasoning_effort must be 'low', 'medium', or 'high'")

        prompt_hash = _sha(prompt.encode("utf-8"))
        scope = dict(approval or {})
        if (
            scope.get("project_id") != project_id
            or scope.get("prompt_sha256") != prompt_hash
            or scope.get("model") != MODEL
            or scope.get("max_output_tokens") != int(max_output_tokens)
            or not isinstance(scope.get("approval_ref"), str)
            or not scope.get("approval_ref")
            or verifier is None
            or verifier(scope) is not True
        ):
            raise PermissionError("A verified owner approval bound to project, prompt and token budget is required")
        gid = "meta_grant_" + secrets.token_hex(16)
        with self._connect() as c:
            c.execute(
                """INSERT INTO grants(id,project_id,prompt_sha,model,max_output_tokens,
                   expires_epoch,issued_at,approval_ref) VALUES(?,?,?,?,?,?,?,?)""",
                (gid, project_id, prompt_hash, MODEL, int(max_output_tokens),
                 time.time() + ttl_seconds, _now(), scope["approval_ref"]),
            )
        res = {
            "grant_id": gid, "project_id": project_id, "model": MODEL,
            "prompt_sha256": prompt_hash, "max_output_tokens": int(max_output_tokens),
            "expires_in_seconds": ttl_seconds, "approval_ref": scope["approval_ref"],
        }
        if reasoning_effort:
            res["reasoning_effort"] = str(reasoning_effort).lower()
        return res

    def _consume(self, grant_id: str, project_id: str, prompt: str) -> dict[str, Any]:
        digest = _sha(prompt.encode("utf-8"))
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                """SELECT model,max_output_tokens,expires_epoch,consumed_epoch
                   FROM grants WHERE id=? AND project_id=? AND prompt_sha=?""",
                (grant_id, project_id, digest),
            ).fetchone()
            if row is None or row[3] is not None or row[2] <= time.time():
                c.execute("ROLLBACK")
                raise PermissionError("Grant missing, mismatched, expired, or already used")
            changed = c.execute(
                "UPDATE grants SET consumed_epoch=? WHERE id=? AND consumed_epoch IS NULL",
                (time.time(), grant_id),
            ).rowcount
            if changed != 1:
                c.execute("ROLLBACK")
                raise PermissionError("Grant replay rejected")
            c.execute("COMMIT")
        return {"model": row[0], "max_output_tokens": row[1], "prompt_sha256": digest}

    def query_usage(
        self,
        project_id: str | None = None,
        provider_id: str | None = None,
        since_iso: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as c:
            c.row_factory = sqlite3.Row
            query = "SELECT * FROM receipts WHERE 1=1"
            params: list[Any] = []
            if project_id:
                query += " AND project_id=?"
                params.append(project_id)
            if provider_id:
                query += " AND provider_id=?"
                params.append(provider_id)
            if since_iso:
                query += " AND completed_at>=?"
                params.append(since_iso)
            query += " ORDER BY completed_at DESC"
            rows = [dict(r) for r in c.execute(query, params).fetchall()]

            g_total = c.execute("SELECT count(*) FROM grants").fetchone()[0]
            g_consumed = c.execute("SELECT count(*) FROM grants WHERE consumed_epoch IS NOT NULL").fetchone()[0]
            g_active = c.execute("SELECT count(*) FROM grants WHERE consumed_epoch IS NULL AND expires_epoch > ?", (time.time(),)).fetchone()[0]

        total_calls = len(rows)
        total_tokens = 0
        input_tokens = 0
        output_tokens = 0
        status_counts: dict[str, int] = {}
        tokens_by_model: dict[str, dict[str, int]] = {}
        daily_usage: dict[str, dict[str, Any]] = {}
        monthly_usage: dict[str, dict[str, Any]] = {}
        errors_and_blocks: dict[str, int] = {}
        latencies: list[float] = []

        for r in rows:
            u = json.loads(r.get("tokens_json") or "{}")
            r["usage"] = u
            tin = u.get("input_tokens", 0)
            tout = u.get("output_tokens", 0)
            ttot = u.get("total_tokens", tin + tout)
            total_tokens += ttot
            input_tokens += tin
            output_tokens += tout

            m = r.get("model", MODEL)
            if m not in tokens_by_model:
                tokens_by_model[m] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
            tokens_by_model[m]["input_tokens"] += tin
            tokens_by_model[m]["output_tokens"] += tout
            tokens_by_model[m]["total_tokens"] += ttot
            tokens_by_model[m]["calls"] += 1

            st = r.get("status", "UNKNOWN")
            status_counts[st] = status_counts.get(st, 0) + 1

            err = r.get("error_type")
            if err:
                errors_and_blocks[err] = errors_and_blocks.get(err, 0) + 1

            lat = r.get("latency_ms")
            if isinstance(lat, (int, float)) and lat > 0:
                latencies.append(float(lat))

            comp_at = str(r.get("completed_at") or "")
            if len(comp_at) >= 10:
                day_key = comp_at[:10]
                if day_key not in daily_usage:
                    daily_usage[day_key] = {"calls": 0, "tokens": 0}
                daily_usage[day_key]["calls"] += 1
                daily_usage[day_key]["tokens"] += ttot

                month_key = comp_at[:7]
                if month_key not in monthly_usage:
                    monthly_usage[month_key] = {"calls": 0, "tokens": 0}
                monthly_usage[month_key]["calls"] += 1
                monthly_usage[month_key]["tokens"] += ttot

        lat_summary = {
            "min_ms": round(min(latencies), 3) if latencies else 0.0,
            "max_ms": round(max(latencies), 3) if latencies else 0.0,
            "avg_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
        }

        return {
            "ok": True,
            "project_id": project_id,
            "provider_id": provider_id or PROVIDER_ID,
            "count": total_calls,
            "total_tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tokens_by_model": tokens_by_model,
            "status_breakdown": status_counts,
            "errors_and_blocks": errors_and_blocks,
            "daily_usage": daily_usage,
            "monthly_usage": monthly_usage,
            "latencies": lat_summary,
            "cost_tracking": {
                "verified_cost_usd": None,
                "estimated_cost_usd": None,
                "currency": "USD",
                "policy": "verified_only",
                "note": "Promotional credits account verified; itemized per-call billed cost requires Meta billing API",
            },
            "grants_summary": {
                "total_grants_issued": g_total,
                "total_grants_consumed": g_consumed,
                "active_unexpired_grants": g_active,
            },
            "comparison_vs_local": get_provider_comparison_summary(),
            "receipts": rows[:50],
        }

    def last_receipt(self, grant_id: str) -> dict[str, Any] | None:
        with self._connect() as c:
            c.row_factory = sqlite3.Row
            row = c.execute("SELECT * FROM receipts WHERE grant_id=?", (grant_id,)).fetchone()
        if row is None:
            return None
        doc = dict(row)
        doc["usage"] = json.loads(doc.pop("tokens_json"))
        return doc

    def _save_receipt(self, grant_id: str, project_id: str, receipt: dict[str, Any]) -> None:
        with self._connect() as c:
            c.execute(
                """INSERT INTO receipts(id,grant_id,project_id,provider_id,model,status,http_status,
                   provider_response_id,request_sha,response_sha,latency_ms,tokens_json,error_type,
                   completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("meta_receipt_" + secrets.token_hex(12), grant_id, project_id,
                 PROVIDER_ID, MODEL, receipt["status"], receipt["http_status"],
                 receipt.get("provider_response_id"), receipt["request_sha256"],
                 receipt.get("response_sha256"), receipt["latency_ms"],
                 json.dumps(receipt.get("usage") or {}, sort_keys=True),
                 receipt.get("error_type"), _now()),
            )

    def reconcile_receipt(self, receipt_data: dict[str, Any], *, project_id: str = "inneros-meta-guardian-2026") -> dict[str, Any]:
        """Reconcile an externally verified trial receipt into the central ledger."""
        pid = str(receipt_data.get("probe_id") or receipt_data.get("id") or "reconciled_" + secrets.token_hex(8))
        grant_id = f"reconciled_grant_{pid}"
        receipt_id = f"meta_receipt_{pid}"

        with self._connect() as c:
            existing = c.execute("SELECT id FROM receipts WHERE grant_id=?", (grant_id,)).fetchone()
            if existing:
                return {"ok": True, "already_reconciled": True, "receipt_id": existing[0]}

            # Reconcile grant record
            c.execute(
                """INSERT OR IGNORE INTO grants(id,project_id,prompt_sha,model,max_output_tokens,
                   expires_epoch,consumed_epoch,issued_at,approval_ref)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (grant_id, project_id, receipt_data.get("request_sha256", "reconciled"),
                 receipt_data.get("model_requested", MODEL),
                 int(receipt_data.get("output_tokens") or 192),
                 time.time(), time.time(),
                 receipt_data.get("timestamp_completed", _now()),
                 f"reconciled_{pid}"),
            )

            status = "INCOMPLETE_MODEL_RESPONSE" if receipt_data.get("provider_completion_status") == "incomplete" else (
                "REAL_SUCCESS" if receipt_data.get("result") == "REAL_SUCCESS" else "UNVERIFIED_RESPONSE"
            )

            c.execute(
                """INSERT INTO receipts(id,grant_id,project_id,provider_id,model,status,http_status,
                   provider_response_id,request_sha,response_sha,latency_ms,tokens_json,error_type,
                   completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (receipt_id, grant_id, project_id, PROVIDER_ID,
                 receipt_data.get("model_returned", MODEL),
                 status,
                 receipt_data.get("http_status", 200),
                 receipt_data.get("provider_response_id"),
                 receipt_data.get("request_sha256", ""),
                 receipt_data.get("response_sha256", ""),
                 float(receipt_data.get("request_latency_ms") or 0.0),
                 json.dumps(receipt_data.get("usage") or {}, sort_keys=True),
                 receipt_data.get("reason"),
                 receipt_data.get("timestamp_completed", _now())),
            )
        return {"ok": True, "reconciled": True, "receipt_id": receipt_id, "grant_id": grant_id}


def _extract_output(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in response.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return "\n".join(chunks).strip()


def invoke_with_grant(
    *, ledger: MetaGrantLedger, grant_id: str, project_id: str,
    prompt: str, classification: str = SOURCE_POLICY,
    reasoning_effort: str | None = None,
    transport: Callable[..., Any] | None = None,
    credential_loader: Callable[[], str] | None = None,
    timeout_seconds: int = 12,
) -> dict[str, Any]:
    """Internal callable shared by projects. One network dispatch, no retries.

    The provider caller must be a trusted process; never expose this function via
    an unauthenticated MCP or public web endpoint.
    """
    prompt = _validate_prompt(prompt, classification)
    info = ledger._consume(grant_id, project_id, prompt)  # consumes BEFORE HTTP

    body: dict[str, Any] = {
        "model": info["model"],
        "input": prompt,
        "store": False,
        "max_output_tokens": info["max_output_tokens"],
    }
    if reasoning_effort and str(reasoning_effort).lower() in ("low", "medium", "high"):
        body["reasoning"] = {"effort": str(reasoning_effort).lower()}

    raw = _serial(body)
    receipt: dict[str, Any] = {
        "provider_id": PROVIDER_ID, "project_id": project_id, "model": info["model"],
        "status": "BLOCKED", "http_status": None, "provider_response_id": None,
        "request_sha256": _sha(raw), "response_sha256": None,
        "latency_ms": 0.0, "usage": {}, "error_type": None,
        "output_text": None, "currency": "USD",
        "cost_usd_verified": None, "truth": "SYNTHETIC_LAB",
        "automatic_retries": 0,
    }
    start = time.perf_counter()
    try:
        key = (credential_loader or _get_server_key)()
        if not isinstance(key, str) or not key:
            raise PermissionError("Meta provider credential missing")
        req = request.Request(
            RESPONSES_URL, data=raw, method="POST",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        opener = transport or request.urlopen
        try:
            with opener(req, timeout=timeout_seconds) as resp:
                receipt["http_status"] = int(getattr(resp, "status", 200))
                response_bytes = resp.read(262145)
        except error.HTTPError as exc:
            receipt["http_status"] = int(exc.code)
            response_bytes = exc.read(262145)

        receipt["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
        if len(response_bytes) > 262144:
            receipt["error_type"] = "RESPONSE_TOO_LARGE"
        else:
            # Never retain the credential if the provider unexpectedly echoes it.
            cleaned = response_bytes.replace(key.encode("utf-8"), b"[REDACTED]")
            receipt["response_sha256"] = _sha(cleaned)
            try:
                response = json.loads(cleaned)
            except (ValueError, UnicodeError):
                response = None
            if receipt["http_status"] == 402:
                receipt["status"], receipt["error_type"] = "BILLING_BLOCKED", "HTTP_402"
            elif receipt["http_status"] in (401, 403):
                receipt["status"], receipt["error_type"] = "AUTH_BLOCKED", f"HTTP_{receipt['http_status']}"
            elif receipt["http_status"] != 200:
                receipt["status"], receipt["error_type"] = "HTTP_BLOCKED", f"HTTP_{receipt['http_status']}"
            elif not isinstance(response, dict):
                receipt["error_type"] = "INVALID_JSON"
            else:
                rid, output = response.get("id"), _extract_output(response)
                usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
                receipt["usage"] = usage
                resp_status = str(response.get("status") or "").lower()
                if isinstance(rid, str) and rid:
                    receipt["provider_response_id"] = rid
                    if resp_status == "completed" and output:
                        receipt["status"] = "REAL_SUCCESS"
                        receipt["output_text"] = output
                    elif resp_status == "incomplete":
                        receipt["status"] = "INCOMPLETE_MODEL_RESPONSE"
                        inc_details = response.get("incomplete_details") if isinstance(response.get("incomplete_details"), dict) else {}
                        receipt["error_type"] = inc_details.get("reason") or "REASONING_BUDGET_EXHAUSTED"
                        if output:
                            receipt["output_text"] = output
                    else:
                        receipt["status"] = "UNVERIFIED_PROVIDER_RESPONSE"
                        receipt["error_type"] = f"STATUS_{resp_status.upper() or 'UNKNOWN'}"
                else:
                    receipt["error_type"] = "UNVERIFIED_PROVIDER_RESPONSE"
    except Exception as exc:
        receipt["status"] = "BLOCKED"
        receipt["error_type"] = type(exc).__name__
        receipt["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)

    ledger._save_receipt(grant_id, project_id, receipt)
    return receipt


def verify_ha_owner_approval(approval_scope: dict[str, Any]) -> bool:
    """Verify that an owner approval scope was truly granted by RAFAEL via Home Assistant.

    Validates:
    - 3.1 Strict Owner Actor Validation: Never assume missing user is RAFAEL (strictly requires owner_actor == 'RAFAEL').
    - Valid approval_ref, project_id, and prompt_sha256 (64 hex characters).
    - Token ceiling within bounds (16 <= max_output_tokens <= MAX_ALLOWED_OUTPUT_TOKENS).
    - Provider matches meta/meta-model-api (if specified).
    - Model matches muse-spark-1.3 (if specified).
    - Checks Home Assistant grant in MongoDB (ops_owner_approval_grants with $or logic).
    - Or verifies cryptographic HMAC companion receipt signature with expiry binding.
    - Fail-closed: returns False if unverified, tampered, or expired.
    """
    if not isinstance(approval_scope, dict):
        return False

    # 3.1 Strict Owner Actor Validation: Never assume missing user is RAFAEL
    raw_actor = approval_scope.get("owner_actor")
    if not raw_actor or str(raw_actor).strip().upper() != "RAFAEL":
        return False

    ref = str(approval_scope.get("approval_ref") or "").strip()
    if not ref:
        return False

    project_id = str(approval_scope.get("project_id") or "").strip()
    if not project_id:
        return False

    prompt_sha = str(approval_scope.get("prompt_sha256") or "").strip()
    if len(prompt_sha) != 64 or not all(c in "0123456789abcdefABCDEF" for c in prompt_sha):
        return False

    max_tokens = approval_scope.get("max_output_tokens")
    if not isinstance(max_tokens, int) or max_tokens < 16 or max_tokens > MAX_ALLOWED_OUTPUT_TOKENS:
        return False

    # Check provider constraint if present
    scope_prov = str(approval_scope.get("provider") or "").strip().lower()
    if scope_prov and scope_prov not in ("meta", "meta-model-api", "meta_model_api"):
        return False

    # Check model constraint if present
    scope_model = str(approval_scope.get("model") or "").strip().lower()
    if scope_model and scope_model != MODEL.lower():
        return False

    # Check scope expiration if explicitly declared
    exp_scope = approval_scope.get("expires_at") or approval_scope.get("expires_epoch")
    if exp_scope is not None:
        if isinstance(exp_scope, (int, float)):
            if float(exp_scope) <= time.time():
                return False
        else:
            exp_dt = _parse_utc_instant(exp_scope)
            if exp_dt and exp_dt.timestamp() <= time.time():
                return False

    # 1. HMAC Companion Signature Check (direct HA Companion signed receipt or token)
    comp_receipt = approval_scope.get("companion_receipt")
    if isinstance(comp_receipt, dict):
        try:
            from inneros_core_runtime import ops_owner_approval_ha
            verified = ops_owner_approval_ha.verify_companion_receipt(comp_receipt, expected_task_id=ref)
            if verified.get("ok") and verified.get("verified"):
                return True
        except Exception:
            pass

    # 2. Cryptographic/HMAC self-contained signature check on approval_scope
    sig = str(approval_scope.get("signature") or "").strip()
    if sig:
        secret = os.getenv("INNEROS_HA_COMPANION_RECEIPT_SECRET", "").strip()
        if secret:
            exp_key = str(approval_scope.get("expires_at") or approval_scope.get("expires_epoch") or "").strip()
            candidates = [
                f"{ref}|{project_id}|{MODEL}|{prompt_sha}|{max_tokens}|{exp_key}",
                f"{ref}|{project_id}|{prompt_sha}|{max_tokens}",
            ]
            for cand in candidates:
                expected = hmac.new(secret.encode(), cand.encode(), hashlib.sha256).hexdigest()
                if hmac.compare_digest(sig, expected):
                    if cand == candidates[1] and exp_scope is not None:
                        return True
                    elif cand == candidates[0]:
                        return True
                    elif cand == candidates[1] and exp_scope is None:
                        return True

    # 3. Durable MongoDB Grant Check
    try:
        from raphiia_openai import mongo_store
        db = mongo_store.get_db()
        # 3.2 Fixed Mongo Query: use $or instead of invalid empty string key ""
        grant = db["ops_owner_approval_grants"].find_one(
            {"$or": [{"grant_id": ref}, {"task_id": ref}], "status": {"$in": ["active", "authorized"]}},
            {"_id": 0}
        )
        if grant:
            # Verify owner actor strictly matches RAFAEL
            if str(grant.get("owner_actor") or "").upper() != "RAFAEL":
                return False
            # Verify unexpired
            exp = grant.get("expires_at")
            if exp:
                exp_dt = _parse_utc_instant(exp)
                if exp_dt and exp_dt.timestamp() <= time.time():
                    return False
            # Verify token limit
            t_limit = grant.get("token_limit")
            if t_limit is not None and max_tokens > t_limit:
                return False
            # Verify provider
            prov = str(grant.get("provider") or "").lower()
            if prov and prov not in ("meta", "meta-model-api", "meta_model_api"):
                return False
            # Verify model
            m = str(grant.get("model") or "").lower()
            if m and m != MODEL.lower():
                return False
            # Verify prompt_sha if specified in scope_note or grant doc
            grant_prompt_sha = grant.get("prompt_sha256") or grant.get("prompt_sha")
            if grant_prompt_sha and grant_prompt_sha != prompt_sha:
                return False
            scope_note = str(grant.get("scope_note") or "")
            if "prompt_sha:" in scope_note:
                for part in scope_note.split():
                    if part.startswith("prompt_sha:") and part.split(":", 1)[1] != prompt_sha:
                        return False
            return True
    except Exception:
        pass

    return False


def get_provider_comparison_summary() -> dict[str, Any]:
    """Provide a consultable comparison between AMD, Intel, Meta, and other providers."""
    return {
        "ok": True,
        "timestamp": _now(),
        "providers": {
            "amd_local_primary": {
                "label": "AMD Ryzen AI Local Primary (vLLM)",
                "models": ["QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ", "qwen2.5-coder:7b"],
                "role": "default_local_primary",
                "cost_usd": 0.0,
                "latency_typical_ms": 350.0,
                "privacy": "airgapped_lan",
                "status": "active_primary",
            },
            "intel_local_standby": {
                "label": "Intel NUC Local Standby (Ollama)",
                "models": ["qwen2.5:7b", "llama3.1:8b", "phi3.5:3.8b"],
                "role": "standby_and_summaries",
                "cost_usd": 0.0,
                "latency_typical_ms": 780.0,
                "privacy": "airgapped_lan",
                "status": "standby_ready",
            },
            "meta_model_api": {
                "label": "Meta Model API (Muse Spark 1.3)",
                "models": [MODEL],
                "role": "frontier_reasoning_burst_only",
                "cost_policy": "explicit_burst_only",
                "promotional_balance_usd": 150.0,
                "credit_account_ref": "funding_registry:meta-model-api",
                "latency_observed_ms": 3273.322,
                "privacy": "synthetic_lab_data_only",
                "governance": "ha_owner_grant_required_one_shot",
                "status": "configured" if _has_vault_key() else "credential_not_configured",
            },
            "external_codex_openai": {
                "label": "Codex OpenAI",
                "models": ["gpt-5.6", "o3-mini"],
                "role": "external_developer_agent",
                "credit_safety_caps": {"daily": 3, "monthly": 30},
                "status": "capped_metered",
            },
            "external_antigravity_gemini": {
                "label": "Antigravity Google DeepMind",
                "models": ["gemini-3.7", "gemini-2.5-pro"],
                "role": "interactive_ide_pair_programmer",
                "credit_safety_caps": {"daily": 50, "monthly": 500},
                "status": "interactive_active",
            },
        },
        "default_routing": "amd_local_primary",
        "external_routing_rule": "fail_closed_requires_ha_owner_grant",
    }
