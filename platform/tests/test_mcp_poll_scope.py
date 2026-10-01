from __future__ import annotations

from inneros_core_runtime.auth_middleware import _required_scopes_for_call


def test_poll_own_mailbox_allows_read_scope():
    token = {"sub": "chatgpt", "scope": "ralfia:read"}
    scopes = _required_scopes_for_call("poll_agent_inbox", token, {"agent": "chatgpt"})
    assert scopes == ["ralfia:read"]


def test_poll_foreign_mailbox_requires_agents_scope():
    token = {"sub": "chatgpt", "scope": "ralfia:read"}
    scopes = _required_scopes_for_call("poll_agent_inbox", token, {"agent": "qwen-coding"})
    assert scopes == ["ralfia:agents"]
