"""Mantiene contributions.json alineado con MRs/issues detectados por correo/API."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

AGENT = Path("/home/rlopez/inneros/inneros_core/workspaces/gitlab-contributorops-agent")
MANIFEST_PATH = AGENT / "contributions.json"
DEFAULT_PROJECT = "gitlab-org/gitlab"

MR_URL = re.compile(r"gitlab\.com/([a-z0-9_.-]+/[a-z0-9_.-]+)/-/merge_requests/(\d+)", re.I)
ISSUE_URL = re.compile(r"gitlab\.com/([a-z0-9_.-]+/[a-z0-9_.-]+)/-/issues/(\d+)", re.I)


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        return {"items": []}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _save_manifest(data: dict[str, Any]) -> None:
    MANIFEST_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _existing_keys(items: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for it in items:
        keys.add(f"{it.get('kind')}:{it.get('project')}:{it.get('iid')}")
    return keys


def _discover_from_mongo(limit: int = 40) -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    rows = list(
        db.email_messages.find(
            {
                "$or": [
                    {"snippet": {"$regex": "gitlab\\.com", "$options": "i"}},
                    {"body_text": {"$regex": "gitlab\\.com", "$options": "i"}},
                ]
            },
            {"snippet": 1, "body_text": 1, "subject": 1},
        )
        .sort("received_at", -1)
        .limit(max(10, min(limit, 200)))
    )
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        text = f"{row.get('subject') or ''} {row.get('snippet') or ''} {row.get('body_text') or ''}"
        for pattern, kind in ((MR_URL, "mr"), (ISSUE_URL, "issue")):
            for match in pattern.finditer(text):
                project, iid = match.group(1), int(match.group(2))
                key = f"{kind}:{project}:{iid}"
                if key in seen:
                    continue
                seen.add(key)
                found.append({"kind": kind, "project": project, "iid": iid, "source": "email_discovery"})
    return found


def sync_manifest_from_email_and_api(*, limit: int = 30, dry_run: bool = False) -> dict[str, Any]:
    manifest = _load_manifest()
    items = list(manifest.get("items") or [])
    keys = _existing_keys(items)
    discovered = _discover_from_mongo(limit=limit)
    added: list[dict[str, Any]] = []
    for entry in discovered:
        key = f"{entry['kind']}:{entry['project']}:{entry['iid']}"
        if key in keys:
            continue
        items.append({"kind": entry["kind"], "project": entry["project"], "iid": entry["iid"]})
        keys.add(key)
        added.append(entry)
    if added and not dry_run:
        manifest["items"] = items
        _save_manifest(manifest)
    return {"ok": True, "dry_run": dry_run, "added": added, "total_items": len(items)}
