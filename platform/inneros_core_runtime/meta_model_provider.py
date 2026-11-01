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
MAX_OUTPUT_TOKENS = 256
MAX_INPUT_CHARS = 6000
DEFAULT_DB = "~/.local/state/inneros/model-provider-meta.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _serial(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


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
    except (ImportError, OSError, RuntimeError, ValueError):
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

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        c.execute("PRAGMA busy_timeout=5000")
        return c

    def issue(
        self, *, project_id: str, prompt: str, approval: dict[str, Any],
        verifier: Callable[[dict[str, Any]], bool] | None,
        classification: str = SOURCE_POLICY,
        max_output_tokens: int = 192, ttl_seconds: int = 180,
    ) -> dict[str, Any]:
        prompt = _validate_prompt(prompt, classification)
        if not project_id or len(project_id) > 96:
            raise ValueError("A scoped project ID is required")
        if isinstance(max_output_tokens, bool) or not 16 <= int(max_output_tokens) <= MAX_OUTPUT_TOKENS:
            raise ValueError("Output tokens must be between 16 and 256")
        if isinstance(ttl_seconds, bool) or not 1 <= int(ttl_seconds) <= 300:
            raise ValueError("Grant TTL must be within 1–300 seconds")
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
        return {
            "grant_id": gid, "project_id": project_id, "model": MODEL,
            "prompt_sha256": prompt_hash, "max_output_tokens": int(max_output_tokens),
            "expires_in_seconds": ttl_seconds, "approval_ref": scope["approval_ref"],
        }

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
    body = {"model": info["model"], "input": prompt, "store": False,
            "max_output_tokens": info["max_output_tokens"]}
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
                if isinstance(rid, str) and rid and response.get("status") == "completed" and output:
                    receipt["status"] = "REAL_SUCCESS"
                    receipt["provider_response_id"] = rid
                    receipt["output_text"] = output
                else:
                    receipt["error_type"] = "UNVERIFIED_PROVIDER_RESPONSE"
    except Exception as exc:
        # Deliberately do not persist exception messages (might contain credentials).
        receipt["status"] = "BLOCKED"
        receipt["error_type"] = type(exc).__name__
        receipt["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
    # Receipt store contains only safe metadata. Output text stays in the trusted caller.
    ledger._save_receipt(grant_id, project_id, receipt)
    return receipt
