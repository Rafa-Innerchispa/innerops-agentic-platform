from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from inneros_core_runtime import notion_webhook


class _Collection:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        doc = self.find_one(query)
        if doc is None:
            doc = dict(query)
            self.docs.append(doc)
        doc.update(update.get("$set") or {})

    def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)


class _Db(dict):
    def __getitem__(self, name: str) -> _Collection:
        if name not in self:
            self[name] = _Collection()
        return dict.__getitem__(self, name)


def _raw(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _sig(secret: str, raw_body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def test_notion_verification_challenge_is_allowed_without_secret(monkeypatch) -> None:
    db = _Db()
    monkeypatch.setattr(notion_webhook, "NOTION_WEBHOOK_VERIFICATION_TOKEN", "")
    monkeypatch.setattr(notion_webhook.mongo_store, "get_db", lambda: db)

    result = notion_webhook.handle_notion_webhook(_raw({"verification_token": "verify-me"}))

    assert result["ok"] is True
    assert result["kind"] == "verification"
    assert db[notion_webhook.CONFIG_COL].find_one({"kind": "verification"})["verification_token"] == "verify-me"


def test_notion_event_fails_closed_without_configured_secret(monkeypatch) -> None:
    db = _Db()
    monkeypatch.setattr(notion_webhook, "NOTION_WEBHOOK_VERIFICATION_TOKEN", "")
    monkeypatch.setattr(notion_webhook.mongo_store, "get_db", lambda: db)

    result = notion_webhook.handle_notion_webhook(_raw({"type": "comment.created", "entity": {"id": "page-1"}}))

    assert result["ok"] is False
    assert result["error"] == "webhook_secret_not_configured"
    assert result["http_status"] == 401


def test_notion_event_accepts_valid_signature_from_stored_verification_token(monkeypatch) -> None:
    db = _Db()
    db[notion_webhook.CONFIG_COL].docs.append({"kind": "verification", "verification_token": "stored-secret"})
    monkeypatch.setattr(notion_webhook, "NOTION_WEBHOOK_VERIFICATION_TOKEN", "")
    monkeypatch.setattr(notion_webhook.mongo_store, "get_db", lambda: db)
    monkeypatch.setattr(notion_webhook.mongo_store, "log_sync", lambda *args, **kwargs: None)
    raw_body = _raw({"type": "comment.created", "entity": {"id": "page-1"}})

    result = notion_webhook.handle_notion_webhook(raw_body, signature=_sig("stored-secret", raw_body))

    assert result["ok"] is True
    assert result["kind"] == "event"
    assert result["event_type"] == "comment.created"
