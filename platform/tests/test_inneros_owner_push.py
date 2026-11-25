from __future__ import annotations

import os

import pytest


def test_sign_and_verify_decision(monkeypatch):
    monkeypatch.setenv("INNEROS_OWNER_PUSH_SECRET", "test-secret-inneros")
    from inneros_core_runtime.owner_push_tokens import sign_decision, verify_decision

    t = sign_decision(task_id="ops_abc", nonce="n1", decision="approve")
    assert verify_decision(task_id="ops_abc", nonce="n1", decision="approve", token=t)
    assert not verify_decision(task_id="ops_abc", nonce="n1", decision="cancel", token=t)


def test_ntfy_not_configured_without_url(monkeypatch):
    monkeypatch.delenv("INNEROS_NTFY_URL", raising=False)
    from inneros_core_runtime.notifications import inneros_ntfy_client as ntfy

    monkeypatch.setenv("INNEROS_NTFY_URL", "")
    # empty url -> not configured
    out = ntfy.publish("hi")
    assert out.get("ok") is False


def test_inneros_primary_default(monkeypatch):
    monkeypatch.delenv("NOTIFY_OPS_PRIMARY", raising=False)
    monkeypatch.setenv("NOTIFY_OPS_INNEROS_PUSH", "1")
    from inneros_core_runtime.notifications import inneros_owner_push as iop

    assert iop.is_primary() is True