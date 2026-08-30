from __future__ import annotations

from unittest import mock

from inneros_core_runtime import a2a_bridge


class FakeCollection:
    def __init__(self):
        self.docs = []

    def find_one(self, query, projection=None):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def update_one(self, query, update, upsert=False):
        doc = {**query, **(update.get("$set") or {})}
        self.docs.append(doc)
        return mock.Mock(modified_count=1, upserted_id="fake")


class FakeDb(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = FakeCollection()
        return dict.__getitem__(self, key)


def test_a2a_status_and_cards_are_live():
    with mock.patch.object(a2a_bridge.mongo_store, "get_db", return_value=FakeDb()):
        assert a2a_bridge.status()["ok"] is True
    cards = a2a_bridge.agent_cards()
    assert cards["ok"] is True
    assert cards["count"] >= 55
    assert "AG-25" in cards["cards"]


def test_a2a_dispatch_creates_ops_task_without_shell():
    db = FakeDb()
    with (
        mock.patch.object(a2a_bridge.mongo_store, "get_db", return_value=db),
        mock.patch.object(a2a_bridge.coordination_live, "create_ops_task", return_value={"ok": True, "created": True, "task_id": "ops_a2a"}),
    ):
        result = a2a_bridge.dispatch(agent_id="AG-25", title="Probe", body="Do a safe thing", correlation_id="corr-a2a")
    assert result["ok"] is True
    assert result["task"]["ops_task_id"] == "ops_a2a"
    assert result["task"]["assignee"] == "ralfia"
    assert result["task"]["correlation_id"] == "corr-a2a"
    assert result["task"]["bridge_version"] == a2a_bridge.BRIDGE_VERSION
