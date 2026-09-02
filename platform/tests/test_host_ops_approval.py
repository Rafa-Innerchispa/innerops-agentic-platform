from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parents[1]
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime.agents import ag41_peer_ops_executor as ag41
from inneros_core_runtime.agents import ag44_cloud_deployer as ag44
from raphiia_openai import project_runtime_registry as prr


class _Collection:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def insert_one(self, doc: dict):
        key = str(doc.get("approval_id") or f"row_{len(self.docs) + 1}")
        self.docs[key] = dict(doc)
        return object()

    def find_one(self, query: dict, projection: dict | None = None):
        doc = self.docs.get(str(query.get("approval_id") or ""))
        return dict(doc) if doc else None


class _DB:
    def __init__(self) -> None:
        self.collections: dict[str, _Collection] = {}

    def __getitem__(self, name: str) -> _Collection:
        return self.collections.setdefault(name, _Collection())


def _install_fake_store(monkeypatch: pytest.MonkeyPatch) -> _DB:
    db = _DB()
    monkeypatch.setattr(ag44.mongo_store, "get_db", lambda: db)
    monkeypatch.setattr(ag44, "record_agent_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(ag41, "record_agent_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        prr,
        "resolve_project",
        lambda **kwargs: {
            "ok": True,
            "project_path": f"/home/rlopez/projects/{kwargs.get('project_id') or 'unknown'}",
            "project": {
                "project_id": kwargs.get("project_id") or "",
                "repo": kwargs.get("repo") or "",
            },
        },
    )
    monkeypatch.setattr(ag41, "_helper", lambda *args, **kwargs: {"ok": True, "helper_returncode": 0})
    return db


def test_host_ops_issuer_creates_scoped_systemd_token(monkeypatch: pytest.MonkeyPatch):
    _install_fake_store(monkeypatch)
    issued = ag44.cloud_approval_issue(
        provider="host_ops",
        action="systemd_user_mutation",
        project_id="inneros-alpha-alpaca",
        ttl_minutes=30,
        note="test",
    )
    assert issued["ok"] is True
    assert issued["provider"] == "host_ops"
    assert issued["action"] == "systemd_user_mutation"
    assert issued["project_id"] == "inneros-alpha-alpaca"

    result = ag41.peer_user_service(
        action="write",
        service_name="inneros-alpha.service",
        project_id="inneros-alpha-alpaca",
        repo="Rafa-Innerchispa/inneros-alpha-alpaca",
        unit_content="[Unit]\nDescription=test\n",
        approval_id=issued["approval_id"],
        dry_run=True,
    )
    assert result["ok"] is True


def test_host_ops_token_cannot_cross_project(monkeypatch: pytest.MonkeyPatch):
    _install_fake_store(monkeypatch)
    issued = ag44.cloud_approval_issue(
        provider="host_ops",
        action="systemd_user_mutation",
        project_id="inneros-alpha-alpaca",
    )
    with pytest.raises(PermissionError, match="approval_scope_mismatch:project"):
        ag41.peer_user_service(
            action="write",
            service_name="other.service",
            project_id="other-project",
            repo="Rafa-Innerchispa/other-project",
            unit_content="[Unit]\nDescription=other\n",
            approval_id=issued["approval_id"],
            dry_run=True,
        )


def test_host_ops_systemd_token_cannot_install_packages(monkeypatch: pytest.MonkeyPatch):
    _install_fake_store(monkeypatch)
    issued = ag44.cloud_approval_issue(
        provider="host_ops",
        action="systemd_user_mutation",
        project_id="inneros-alpha-alpaca",
    )
    with pytest.raises(PermissionError, match="approval_scope_mismatch:action"):
        ag41.peer_package_install(
            packages=["python3-venv"],
            approval_id=issued["approval_id"],
            dry_run=True,
        )


def test_expired_host_ops_token_is_rejected(monkeypatch: pytest.MonkeyPatch):
    db = _install_fake_store(monkeypatch)
    issued = ag44.cloud_approval_issue(
        provider="host_ops",
        action="systemd_user_mutation",
        project_id="inneros-alpha-alpaca",
    )
    collection = db[ag44.GCP_APPROVAL_COLLECTION]
    collection.docs[issued["approval_id"]]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).isoformat()
    with pytest.raises(PermissionError, match="approval_id_expired"):
        ag41.peer_user_service(
            action="write",
            service_name="inneros-alpha.service",
            project_id="inneros-alpha-alpaca",
            repo="Rafa-Innerchispa/inneros-alpha-alpaca",
            unit_content="[Unit]\nDescription=test\n",
            approval_id=issued["approval_id"],
            dry_run=True,
        )


def test_host_ops_issuer_rejects_unknown_action(monkeypatch: pytest.MonkeyPatch):
    _install_fake_store(monkeypatch)
    result = ag44.cloud_approval_issue(
        provider="host_ops",
        action="arbitrary_root_shell",
        project_id="inneros-alpha-alpaca",
    )
    assert result["ok"] is False
    assert result["error"] == "host_ops_action_not_allowed"
