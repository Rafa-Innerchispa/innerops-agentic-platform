"""
InnerOS Hosting Authorization & Security Governance Engine v2.0.
Provides delegated capability grants, multi-domain policy enforcement (supporting all 24 account domains),
staging TTL grants, owner production approval tokens, and continuous audit logging.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from inneros_core_runtime import mongo_store

HOSTING_AUTH_COL = "ralfia_hosting_authorizations"
HOSTING_DOMAINS_COL = "ralfia_hosting_domain_policies"

# Canonical default active mutation domains
DEFAULT_MUTATION_DOMAINS = {
    "innerspark.live",
    "industriasolex.com",
    "pcdoctor.com.ec",
    "pcdoctor.ai",
    "creatorcore.ai",
    "creatoros.dev",
    "danzasjazz.com",
    "innerchispa.us",
    "sgtour.ec",
}

ALL_ACCOUNT_DOMAINS = {
    "pcdoctor.com.ec", "bellcosmeec.com", "creatorcore.ai", "creatoros.dev",
    "cristobalbolon.com", "danzasjazz.com", "dcmobileservices.net", "elecompgps.com",
    "elecompsa.com", "fundacionaei.org", "industriasolex.com", "innerchispa.us",
    "innerspark.live", "iskconecuador.org", "iskconguayaquil.org", "kanahri.com",
    "optica7.com", "pcdoctor.ai", "servifran.site", "sgtour.ec", "soindu.com",
    "thships.com", "torresdelrio.net", "transpower.com.ec"
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_all_account_domains() -> set[str]:
    """Returns the set of all authorized domains in the hosting account."""
    domains = set(ALL_ACCOUNT_DOMAINS)
    try:
        db = mongo_store.get_db()
        custom = db[HOSTING_DOMAINS_COL].find({}, {"domain": 1, "_id": 0})
        for c in custom:
            if c.get("domain"):
                domains.add(c["domain"].lower().strip())
    except Exception:
        pass
    return domains


def is_domain_mutation_allowed(domain: str) -> bool:
    """
    Validates whether a domain is an authorized account domain.
    Enforces that mutations cannot touch foreign/external domains.
    """
    d = (domain or "").lower().strip()
    if not d:
        return False
    valid_domains = get_all_account_domains()
    return d in valid_domains or any(d.endswith("." + v) for v in valid_domains)


def request_hosting_authorization(
    domain: str,
    target_env: str = "staging",
    ttl_minutes: int = 60,
    allowed_actions: list[str] | None = None,
    reason: str = "",
    approval_token: str = "",
    actor: str = "chatgpt",
) -> dict[str, Any]:
    """
    Issues a delegated hosting grant for a domain.
    Staging grants are auto-granted with a TTL.
    Production grants strictly require owner approval token.
    """
    d_clean = (domain or "").lower().strip()
    if not d_clean or not is_domain_mutation_allowed(d_clean):
        return {
            "ok": False,
            "error": "FORBIDDEN_DOMAIN_MUTATION_RESTRICTED",
            "domain": d_clean,
            "message": f"Domain '{d_clean}' is not an authorized domain on this cPanel account."
        }

    env_clean = str(target_env or "staging").lower().strip()
    token_clean = str(approval_token or "").strip()

    if env_clean == "production":
        if not token_clean or len(token_clean) < 8:
            return {
                "ok": False,
                "error": "OWNER_APPROVAL_REQUIRED_FOR_PRODUCTION",
                "domain": d_clean,
                "target_env": "production",
                "message": "Production mutations require owner approval_token (min 8 chars)."
            }

    ttl = max(5, min(int(ttl_minutes or 60), 180))
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=ttl)).isoformat()
    auth_id = f"auth_{secrets.token_hex(6)}"

    doc = {
        "auth_id": auth_id,
        "domain": d_clean,
        "target_env": env_clean,
        "allowed_actions": allowed_actions or ["*"],
        "status": "active",
        "actor": actor,
        "reason": str(reason or "")[:300],
        "owner_approved": (env_clean == "production"),
        "approval_token_hash": hashlib.sha256(token_clean.encode("utf-8")).hexdigest() if token_clean else "",
        "created_at": now.isoformat(),
        "expires_at": expires_at,
        "ttl_minutes": ttl,
        "audit_events": [
            {
                "event": "authorization_granted",
                "timestamp": now.isoformat(),
                "actor": actor,
                "target_env": env_clean,
                "ttl_minutes": ttl
            }
        ]
    }

    try:
        db = mongo_store.get_db()
        db[HOSTING_AUTH_COL].insert_one(dict(doc))
    except Exception as exc:
        return {"ok": False, "error": f"mongo_persistence_error: {str(exc)}"}

    return {
        "ok": True,
        "auth_id": auth_id,
        "domain": d_clean,
        "target_env": env_clean,
        "allowed_actions": doc["allowed_actions"],
        "expires_at": expires_at,
        "ttl_minutes": ttl,
        "message": f"Delegated hosting authorization granted for {d_clean} in {env_clean} mode."
    }


def validate_hosting_authorization(
    domain: str,
    action: str,
    target_env: str = "staging",
    auth_id: str = "",
    approval_token: str = "",
    actor: str = "chatgpt",
) -> dict[str, Any]:
    """Validates that a hosting operation is authorized under an active delegated grant."""
    d_clean = (domain or "").lower().strip()
    if not d_clean or not is_domain_mutation_allowed(d_clean):
        return {
            "ok": False,
            "error": "FORBIDDEN_DOMAIN_MUTATION_RESTRICTED",
            "domain": d_clean,
            "allowed_domains": sorted(list(get_all_account_domains())),
            "message": f"Domain '{d_clean}' is not an authorized account domain."
        }

    env_clean = str(target_env or "staging").lower().strip()
    db = mongo_store.get_db()
    now_iso = _now_iso()

    doc = None
    if auth_id:
        doc = db[HOSTING_AUTH_COL].find_one({"auth_id": auth_id}, {"_id": 0})
        if not doc:
            return {
                "ok": False,
                "error": "AUTHORIZATION_GRANT_NOT_FOUND",
                "auth_id": auth_id,
                "message": f"Authorization grant {auth_id} was not found."
            }
    else:
        # Check if there is an active unexpired grant for this domain and environment
        query = {
            "domain": d_clean,
            "status": "active",
            "expires_at": {"$gt": now_iso}
        }
        if env_clean == "production":
            query["target_env"] = "production"
        doc = db[HOSTING_AUTH_COL].find_one(query, {"_id": 0}, sort=[("created_at", -1)])

    if not doc:
        return {
            "ok": False,
            "error": "UNAUTHORIZED_HOSTING_MUTATION",
            "domain": d_clean,
            "target_env": env_clean,
            "action": action,
            "message": f"Operation '{action}' requires an active delegated authorization grant for {d_clean}. Request one with action: 'request_authorization'."
        }

    # Verify status
    if doc.get("status") != "active":
        return {
            "ok": False,
            "error": "AUTHORIZATION_REVOKED_OR_INACTIVE",
            "auth_id": doc.get("auth_id"),
            "status": doc.get("status")
        }

    # Verify expiration
    if str(doc.get("expires_at") or "") <= now_iso:
        return {
            "ok": False,
            "error": "AUTHORIZATION_EXPIRED",
            "auth_id": doc.get("auth_id"),
            "expired_at": doc.get("expires_at")
        }

    # Verify domain isolation
    if str(doc.get("domain") or "").lower() != d_clean:
        return {
            "ok": False,
            "error": "GRANT_DOMAIN_MISMATCH",
            "grant_domain": doc.get("domain"),
            "requested_domain": d_clean,
            "message": f"Grant {doc.get('auth_id')} is for {doc.get('domain')}, not {d_clean}."
        }

    # Verify environment permissions
    grant_env = str(doc.get("target_env") or "staging").lower()
    if env_clean == "production" and grant_env != "production":
        return {
            "ok": False,
            "error": "GRANT_ENVIRONMENT_MISMATCH",
            "message": "A staging authorization grant cannot execute production mutations."
        }

    # Verify production approval token
    if env_clean == "production" and not doc.get("owner_approved"):
        token_clean = str(approval_token or "").strip()
        if not token_clean or len(token_clean) < 8:
            return {
                "ok": False,
                "error": "APPROVAL_TOKEN_REQUIRED",
                "message": "Production mutations require owner approval_token."
            }

    # Verify action
    allowed = doc.get("allowed_actions") or ["*"]
    if "*" not in allowed and action not in allowed:
        return {
            "ok": False,
            "error": "ACTION_NOT_PERMITTED_BY_GRANT",
            "action": action,
            "allowed_actions": allowed
        }

    return {
        "ok": True,
        "auth_id": doc.get("auth_id"),
        "grant": doc
    }


def record_hosting_audit_event(auth_id: str, action: str, details: dict[str, Any] | None = None) -> None:
    """Records an audit event in the active grant log."""
    try:
        db = mongo_store.get_db()
        db[HOSTING_AUTH_COL].update_one(
            {"auth_id": auth_id},
            {
                "$push": {
                    "audit_events": {
                        "action": action,
                        "timestamp": _now_iso(),
                        "details": details or {}
                    }
                }
            }
        )
    except Exception:
        pass


def revoke_hosting_authorization(auth_id: str, actor: str = "chatgpt") -> dict[str, Any]:
    """Explicitly revokes an active delegated authorization grant."""
    try:
        db = mongo_store.get_db()
        res = db[HOSTING_AUTH_COL].update_one(
            {"auth_id": auth_id, "status": "active"},
            {
                "$set": {
                    "status": "revoked",
                    "revoked_at": _now_iso(),
                    "revoked_by": actor
                }
            }
        )
        if res.matched_count == 0:
            return {"ok": False, "error": "grant_not_found_or_already_revoked", "auth_id": auth_id}
        return {"ok": True, "auth_id": auth_id, "status": "revoked", "message": "Grant revoked successfully."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def check_hosting_authorization(auth_id: str = "", domain: str = "") -> dict[str, Any]:
    """Inspects the current state of a grant or domain active authorization."""
    try:
        db = mongo_store.get_db()
        if auth_id:
            doc = db[HOSTING_AUTH_COL].find_one({"auth_id": auth_id}, {"_id": 0})
        elif domain:
            d_clean = domain.lower().strip()
            doc = db[HOSTING_AUTH_COL].find_one(
                {"domain": d_clean, "status": "active", "expires_at": {"$gt": _now_iso()}},
                {"_id": 0},
                sort=[("created_at", -1)]
            )
        else:
            return {"ok": False, "error": "auth_id_or_domain_required"}

        if not doc:
            return {"ok": False, "error": "no_active_authorization_found"}

        return {
            "ok": True,
            "auth_id": doc.get("auth_id"),
            "domain": doc.get("domain"),
            "target_env": doc.get("target_env"),
            "status": doc.get("status"),
            "allowed_actions": doc.get("allowed_actions"),
            "expires_at": doc.get("expires_at"),
            "audit_events_count": len(doc.get("audit_events") or [])
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
