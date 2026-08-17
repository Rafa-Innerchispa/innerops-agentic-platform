#!/usr/bin/env python3
"""Añade scopes ChatGPT mínimos a clientes/tokens admin con rollback auditable."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from raphiia_openai import oauth_store
from raphiia_openai.settings import MONGO_URI

MIGRATION_ID = "chatgpt-agent-memory-scopes-20260719"
AUDIT_COLLECTION = "ralfia_oauth_scope_migrations"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scope_union(value: str) -> str:
    return " ".join(sorted(set((value or "").split()).union(oauth_store.CHATGPT_SCOPES)))


def apply() -> dict[str, int]:
    db = oauth_store.get_db()
    portal_users = MongoClient(MONGO_URI)["hackathon_autopilot"]["users"]
    counts = {"clients": 0, "access_tokens": 0, "refresh_tokens": 0}

    for client in db["ralfia_oauth_clients"].find({"client_name": {"$regex": "chatgpt", "$options": "i"}}):
        previous = str(client.get("scope") or "")
        updated = _scope_union(previous)
        if updated == previous:
            continue
        db[AUDIT_COLLECTION].update_one(
            {"migration_id": MIGRATION_ID, "collection": "ralfia_oauth_clients", "document_id": client["_id"]},
            {"$setOnInsert": {"previous_scope": previous, "new_scope": updated, "created_at": _now()}},
            upsert=True,
        )
        db["ralfia_oauth_clients"].update_one({"_id": client["_id"]}, {"$set": {"scope": updated}})
        counts["clients"] += 1

    for collection, key in (
        ("ralfia_oauth_tokens", "access_tokens"),
        ("ralfia_oauth_refresh_tokens", "refresh_tokens"),
    ):
        for token_doc in db[collection].find({"revoked": {"$ne": True}}):
            user = portal_users.find_one(
                {"username": token_doc.get("username"), "role": "admin", "oauth_enabled": {"$ne": False}},
                {"_id": 1},
            )
            if not user:
                continue
            previous = str(token_doc.get("scope") or "")
            updated = _scope_union(previous)
            if updated == previous:
                continue
            db[AUDIT_COLLECTION].update_one(
                {"migration_id": MIGRATION_ID, "collection": collection, "document_id": token_doc["_id"]},
                {"$setOnInsert": {"previous_scope": previous, "new_scope": updated, "created_at": _now()}},
                upsert=True,
            )
            db[collection].update_one({"_id": token_doc["_id"]}, {"$set": {"scope": updated}})
            counts[key] += 1
    return counts


def rollback() -> dict[str, int]:
    db = oauth_store.get_db()
    counts = {"clients": 0, "access_tokens": 0, "refresh_tokens": 0}
    mapping = {
        "ralfia_oauth_clients": "clients",
        "ralfia_oauth_tokens": "access_tokens",
        "ralfia_oauth_refresh_tokens": "refresh_tokens",
    }
    for audit in db[AUDIT_COLLECTION].find({"migration_id": MIGRATION_ID, "rolled_back_at": {"$exists": False}}):
        collection = str(audit.get("collection") or "")
        if collection not in mapping:
            continue
        db[collection].update_one(
            {"_id": audit.get("document_id")}, {"$set": {"scope": audit.get("previous_scope") or ""}}
        )
        db[AUDIT_COLLECTION].update_one({"_id": audit["_id"]}, {"$set": {"rolled_back_at": _now()}})
        counts[mapping[collection]] += 1
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    print(rollback() if args.rollback else apply())
