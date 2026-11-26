"""Owner-operated SMTP2GO connector. No public listener, account deletion or secrets in receipts."""
from __future__ import annotations

import json
import re
import secrets
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable
from pymongo.errors import DuplicateKeyError

BASE_URL = "https://api.smtp2go.com/v3/"
READ_ENDPOINTS = frozenset({
    "api_keys/permissions", "subaccounts/search", "subaccounts/usage", "domain/view",
    "users/smtp/view", "activity/search", "stats/email_cycle", "stats/email_history",
    "stats/email_summary", "stats/email_bounces", "stats/email_spam", "stats/email_unsubs",
    "allowed_senders/view", "suppression/view", "webhook/view", "email/search",
    "email/scheduled/search",
})
WRITE_ENDPOINTS = frozenset({
    "subaccount/add", "subaccount/edit", "subaccount/reopen", "domain/add", "domain/verify",
    "domain/tracking", "domain/returnpath", "domain/subaccount_access", "users/smtp/add",
    "users/smtp/edit", "allowed_senders/add", "allowed_senders/update", "suppression/add",
    "webhook/add", "webhook/edit", "email/send", "email/mime",
})
SECRET_NAMES = {"password", "email_password", "secret", "api_key", "authorization", "encrypted_secret"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower() in SECRET_NAMES else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return re.sub(r"api-[A-Za-z0-9]{32}", "[REDACTED]", value)
    return value


def validate_domain(domain: str) -> str:
    domain = domain.strip().lower().rstrip(".")
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
        raise ValueError("A valid sender domain is required")
    return domain


class SMTP2GOError(RuntimeError):
    pass


class SMTP2GOClient:
    def __init__(self, api_key: str, *, transport: Callable | None = None):
        if not re.fullmatch(r"api-[A-Za-z0-9]{32}", api_key):
            raise ValueError("SMTP2GO credential is incomplete or masked")
        self._key = api_key
        self._transport = transport or urllib.request.urlopen

    def request(self, endpoint: str, payload: dict | None = None, *, apply: bool = False) -> dict:
        if endpoint not in READ_ENDPOINTS | WRITE_ENDPOINTS:
            raise PermissionError("Endpoint is not permitted; deletion and account closure are disabled")
        if endpoint in WRITE_ENDPOINTS and not apply:
            return {"dry_run": True, "endpoint": endpoint, "payload": redact(payload or {})}
        body = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(BASE_URL + endpoint, data=body, headers={
            "Content-Type": "application/json", "X-Smtp2go-Api-Key": self._key,
            "User-Agent": "InnerOS-Managed-Mail/1.0",
        })
        try:
            # No automatic retries: a timed-out mutation may already have succeeded.
            with self._transport(req, timeout=25, context=ssl.create_default_context()) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raw = exc.read(16000).decode("utf-8", "replace").replace(self._key, "[REDACTED]")
            for k, v in (payload or {}).items():
                if k.lower() in SECRET_NAMES and isinstance(v, str) and v:
                    raw = raw.replace(v, "[REDACTED]")
            raise SMTP2GOError(f"SMTP2GO HTTP {exc.code}: {redact(raw)[:1500]}") from None
        except (OSError, ValueError) as exc:
            # Never repeat str(exc): a transport can include the raw request/credential.
            raise SMTP2GOError(f"SMTP2GO transport failed: {type(exc).__name__}; reconcile before retry") from None
        if not isinstance(result, dict):
            raise SMTP2GOError("Unexpected SMTP2GO response")
        if isinstance(result.get("data"), dict) and result["data"].get("error"):
            error = str(result["data"]["error"]).replace(self._key, "[REDACTED]")
            for k, v in (payload or {}).items():
                if k.lower() in SECRET_NAMES and isinstance(v, str) and v:
                    error = error.replace(v, "[REDACTED]")
            raise SMTP2GOError(str(redact(error))[:1500])
        return result


class ManagedMail:
    """Internal API used by approved owner operations; it never exposes the admin key to tenants."""
    def __init__(self, api: SMTP2GOClient, vault: Any, db: Any):
        self.api, self.vault, self.db = api, vault, db

    @classmethod
    def from_owner_vault(cls) -> "ManagedMail":
        from raphiia_openai import mongo_store, owner_vault
        cred = owner_vault.get_owner_credential("admin_api_key", category="smtp2go", reveal=True)
        if not cred.get("ok") or not cred.get("secret"):
            raise SMTP2GOError("SMTP2GO owner credential is not configured")
        return cls(SMTP2GOClient(cred["secret"]), owner_vault, mongo_store.get_db())

    def _audit(self, action: str, client_id: str, result: Any) -> dict:
        safe = redact(result)
        self.db["ralfia_smtp2go_audit"].insert_one({
            "at": datetime.now(timezone.utc), "action": action, "client_id": client_id,
            "result": safe, "provider": "SMTP2GO",
        })
        return safe

    def clients(self) -> dict:
        return redact(self.api.request("subaccounts/search", {"page_size": 100}))

    def _reserve(self, operation: str, resource: str, client_id: str) -> str:
        key = f"{operation}:{resource}"
        try:
            self.db["ralfia_smtp2go_provisioning"].insert_one({
                "_id": key, "client_id": client_id, "state": "pending",
                "started_at": datetime.now(timezone.utc),
            })
        except DuplicateKeyError:
            raise SMTP2GOError("Provisioning is already recorded; reconcile the provider result instead of repeating it") from None
        return key

    def _finish(self, operation_id: str) -> None:
        self.db["ralfia_smtp2go_provisioning"].update_one({"_id": operation_id}, {"$set": {
            "state": "completed", "finished_at": datetime.now(timezone.utc),
        }})

    def _client(self, client_id: str) -> dict:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", client_id):
            raise ValueError("Invalid InnerOS client ID")
        record = self.db["ralfia_smtp2go_clients"].find_one({"client_id": client_id}, {"_id": 0})
        if not record:
            raise LookupError("Client is not registered in managed mail")
        return record

    def register(self, client_id: str, subaccount_id: str, domain: str, *, apply: bool = False) -> dict:
        domain = validate_domain(domain)
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", client_id):
            raise ValueError("Invalid InnerOS client ID")
        accounts = self.api.request("subaccounts/search", {"page_size": 100})["data"]["subaccounts"]
        account = next((a for a in accounts if a["id"] == subaccount_id), None)
        if not account:
            raise LookupError("Provider subaccount was not found; no tenant mapping changed")
        collection = self.db["ralfia_smtp2go_clients"]
        old = collection.find_one({"client_id": client_id}, {"_id": 0})
        if old and (old["subaccount_id"] != subaccount_id or old["domain"] != domain):
            raise PermissionError("An existing tenant binding cannot be reassigned")
        conflict = collection.find_one({"domain": domain, "client_id": {"$ne": client_id}})
        if conflict:
            raise PermissionError("Domain already belongs to another managed client")
        record = {"client_id": client_id, "subaccount_id": subaccount_id, "domain": domain,
                  "provider": "SMTP2GO", "hosting_relay_status": (old or {}).get("hosting_relay_status", "not_configured")}
        if not apply:
            return {"dry_run": True, "registration": record}
        collection.create_index("client_id", unique=True)
        collection.create_index("domain", unique=True)
        try:
            collection.update_one({"client_id": client_id, "subaccount_id": subaccount_id, "domain": domain}, {"$setOnInsert": record}, upsert=True)
        except DuplicateKeyError:
            raise PermissionError("Concurrent tenant binding conflict; no reassignment performed") from None
        return self._audit("register", client_id, {"ok": True, "registration": record})

    def create_client(self, client_id: str, name: str, domain: str, *, cycle_limit: int, apply: bool = False) -> dict:
        domain = validate_domain(domain)
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", client_id) or not name.strip():
            raise ValueError("Client ID and name are required")
        if not isinstance(cycle_limit, int) or isinstance(cycle_limit, bool) or cycle_limit <= 0:
            raise ValueError("The contracted provider allowance is required")
        old = self.db["ralfia_smtp2go_clients"].find_one({"client_id": client_id}, {"_id": 0})
        if old:
            if old["domain"] != domain:
                raise PermissionError("Existing client domain does not match")
            return {"ok": True, "reused": True, "client": old}
        if self.db["ralfia_smtp2go_clients"].find_one({"domain": domain}):
            raise PermissionError("Domain already belongs to another managed client")
        # Do not duplicate an existing provider account just because it lacks a local mapping.
        matches = [a for a in self.clients()["data"]["subaccounts"] if a["name"].strip().casefold() == name.strip().casefold()]
        if matches:
            raise SMTP2GOError("Provider account already exists; register its ID instead of creating a duplicate")
        payload = {"fullname": name.strip(), "limit": cycle_limit, "dedicated_ip": False,
                   "archiving": False, "enable_sms": False, "enforce_2fa": True}
        reservation = self._reserve("create_client", domain, client_id) if apply else None
        result = self.api.request("subaccount/add", payload, apply=apply)
        if not apply:
            return result
        # Reconcile via the provider rather than guessing the mutation response's ID layout.
        matches = [a for a in self.clients()["data"]["subaccounts"] if a["name"].strip().casefold() == name.strip().casefold()]
        if len(matches) != 1:
            return self._audit("create_client", client_id, {"requires_reconciliation": True, "provider_request_id": result.get("request_id")})
        registered = self.register(client_id, matches[0]["id"], domain, apply=True)
        self._finish(reservation)
        return registered

    def status(self, client_id: str) -> dict:
        c = self._client(client_id)
        scope = {"subaccount_id": c["subaccount_id"]}
        account = next((a for a in self.clients()["data"]["subaccounts"] if a["id"] == c["subaccount_id"]), None)
        return redact({"client": c, "account": account,
                       "domains": self.api.request("domain/view", scope),
                       "smtp_users": self.api.request("users/smtp/view", scope)})

    def ensure_domain(self, client_id: str, *, apply: bool = False) -> dict:
        c = self._client(client_id); scope = {"subaccount_id": c["subaccount_id"]}
        domains = self.api.request("domain/view", scope)["data"].get("domains", [])
        exists = any(d.get("domain", {}).get("fulldomain") == c["domain"] for d in domains)
        endpoint = "domain/verify" if exists else "domain/add"
        return self._audit(endpoint, client_id, self.api.request(endpoint, {**scope, "domain": c["domain"]}, apply=apply))

    def ensure_smtp_user(self, client_id: str, *, apply: bool = False) -> dict:
        c = self._client(client_id); username = c.get("smtp_username", f"inneros-{client_id}-relay")
        key = c.get("smtp_password_key", f"{client_id}_smtp_password")
        existing = self.api.request("users/smtp/view", {"subaccount_id": c["subaccount_id"], "username": username})["data"].get("results", [])
        cred = self.vault.get_owner_credential(key, category="smtp2go", reveal=True)
        if existing:
            if not cred.get("ok") or not cred.get("secret"):
                raise SMTP2GOError("Existing SMTP user has no accessible credential; do not rotate it blindly")
            return {"ok": True, "reused": True, "username": username, "password_vault_key": key}
        if not apply:
            return {"dry_run": True, "username": username, "subaccount_id": c["subaccount_id"], "custom_ratelimit": False}
        reservation = self._reserve("smtp_user", f"{c['subaccount_id']}:{username}", client_id)
        password = cred.get("secret") if cred.get("ok") else None
        password = password or "A1!" + secrets.token_urlsafe(27)
        saved = self.vault.save_owner_credential(key=key, secret=password, category="smtp2go", label=f"Managed mail {client_id}", metadata={"client_id": client_id, "domain": c["domain"], "username": username, "executed_by": "SMTP2GO managed mail owner operation"})
        if not saved.get("ok"):
            raise SMTP2GOError("Vault persistence failed; no SMTP user created")
        user_payload = {"subaccount_id": c["subaccount_id"], "username": username,
            "email_password": password, "description": f"InnerOS managed relay | {c['domain']}",
            "custom_ratelimit": False, "open_tracking_enabled": False, "click_tracking_enabled": False,
            "archive_enabled": False, "status": "allowed", "bounce_notifications": "from"}
        result = self.api.request("users/smtp/add", user_payload, apply=True)
        # Explicitly reconcile the new, unused user's credential before binding it to a host.
        self.api.request("users/smtp/edit", user_payload, apply=True)
        self.db["ralfia_smtp2go_clients"].update_one({"client_id": client_id}, {"$set": {"smtp_username": username, "smtp_password_key": key}})
        self._finish(reservation)
        return self._audit("ensure_smtp_user", client_id, {"ok": True, "username": username, "request_id": result.get("request_id"), "password_vault_key": key})

    def auth_check(self, client_id: str) -> dict:
        c = self._client(client_id)
        cred = self.vault.get_owner_credential(c.get("smtp_password_key", f"{client_id}_smtp_password"), category="smtp2go", reveal=True)
        if not cred.get("ok") or not cred.get("secret"):
            raise SMTP2GOError("SMTP password is not available")
        try:
            with smtplib.SMTP("mail.smtp2go.com", 587, timeout=25) as smtp:
                smtp.ehlo(); smtp.starttls(context=ssl.create_default_context()); smtp.ehlo()
                code, _ = smtp.login(c.get("smtp_username", f"inneros-{client_id}-relay"), cred["secret"])
                return self._audit("auth_check", client_id, {"ok": code == 235, "smtp_code": code, "tls": smtp.sock.version(), "messages_sent": 0})
        except (OSError, smtplib.SMTPException) as exc:
            raise SMTP2GOError(f"SMTP authentication check failed: {type(exc).__name__}") from None

    def activity(self, client_id: str, *, limit: int = 20) -> dict:
        c = self._client(client_id)
        return redact(self.api.request("activity/search", {"subaccounts": [c["subaccount_id"]], "limit": min(max(limit, 1), 100), "include_headers": False}))

    def update_client(self, client_id: str, *, name: str | None = None, cycle_limit: int | None = None, apply: bool = False) -> dict:
        c = self._client(client_id); payload = {"id": c["subaccount_id"]}
        if name is not None:
            if not name.strip(): raise ValueError("Name cannot be empty")
            payload["fullname"] = name.strip()
        if cycle_limit is not None:
            if not isinstance(cycle_limit, int) or isinstance(cycle_limit, bool) or cycle_limit <= 0: raise ValueError("Invalid contracted allowance")
            payload["limit"] = cycle_limit
        return self._audit("update_client", client_id, self.api.request("subaccount/edit", payload, apply=apply))
