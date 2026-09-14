from __future__ import annotations

import unittest
from unittest.mock import patch

from raphiia_openai.memory import agent_messages


class Cursor(list):
    def sort(self, *_args):
        return self

    def limit(self, n):
        return Cursor(self[:n])


class UpdateResult:
    def __init__(self, matched: int, modified: int):
        self.matched_count = matched
        self.modified_count = modified


class Collection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query, *_args, **_kwargs):
        rows = []
        for row in self.rows:
            ok = True
            for key, expected in query.items():
                value = row.get(key)
                if isinstance(expected, dict) and "$in" in expected:
                    ok = value in set(expected["$in"])
                else:
                    ok = value == expected
                if not ok:
                    break
            if ok:
                rows.append(row)
        return Cursor(rows)

    def find_one(self, query, *_args, **_kwargs):
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                return dict(row)
        return None

    def update_one(self, query, update, **_kwargs):
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                before = dict(row)
                row.update(update.get("$set", {}))
                return UpdateResult(1, 1 if row != before else 0)
        return UpdateResult(0, 0)


class AgentMessageTaskReconcileTests(unittest.TestCase):
    def test_completed_ops_task_message_stops_counting_as_open(self):
        messages = Collection([
            {"_id": "m1", "message_id": "msg_1", "target_agent": "codex", "status": "open", "payload": {"task_id": "ops_123456789abc"}, "created_at": "2026-09-14T00:00:00+00:00"},
            {"_id": "m2", "message_id": "msg_2", "target_agent": "codex", "status": "open", "body": "plain note", "created_at": "2026-09-14T00:00:01+00:00"},
        ])
        tasks = Collection([{"task_id": "ops_123456789abc", "status": "completed", "revision": 4}])
        db = {agent_messages.COL_AGENT_MESSAGES: messages, agent_messages.OPS_TASKS_COL: tasks}

        with patch.object(agent_messages.mongo_store, "get_db", return_value=db):
            result = agent_messages.reconcile_task_message_statuses("codex")

        self.assertEqual(result["updated"], 1)
        self.assertEqual(messages.rows[0]["status"], "done")
        self.assertEqual(messages.rows[0]["linked_ops_task_status"], "completed")
        self.assertEqual(messages.rows[1]["status"], "open")

    def test_partial_ops_task_message_becomes_acknowledged_not_unread(self):
        messages = Collection([
            {"_id": "m1", "message_id": "msg_1", "target_agent": "codex", "status": "open", "tags": ["ops_abcdef123456"], "created_at": "2026-09-14T00:00:00+00:00"},
        ])
        tasks = Collection([{"task_id": "ops_abcdef123456", "status": "partial", "revision": 2}])
        db = {agent_messages.COL_AGENT_MESSAGES: messages, agent_messages.OPS_TASKS_COL: tasks}

        with patch.object(agent_messages.mongo_store, "get_db", return_value=db):
            result = agent_messages.reconcile_task_message_statuses("codex")

        self.assertEqual(result["counts"], {"acknowledged": 1})
        self.assertEqual(messages.rows[0]["status"], "acknowledged")
        self.assertEqual(messages.rows[0]["acknowledged_by"], "ops_task_lifecycle")
