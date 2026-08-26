import unittest
from unittest.mock import patch

from inneros_core_runtime import external_repair_agent as ext
from inneros_core_runtime import coordination_live
from inneros_core_runtime.settings import COL_AGENT_MESSAGES


def _get_dotted(doc, key):
    value = doc
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _matches(doc, query):
    for key, expected in (query or {}).items():
        if key == "$or":
            if not any(_matches(doc, clause) for clause in expected):
                return False
            continue
        value = _get_dotted(doc, key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$nin" in expected and value in expected["$nin"]:
                return False
            if "$lt" in expected:
                if not value or not value < expected["$lt"]:
                    return False
            if "$gte" in expected:
                if not value or not value >= expected["$gte"]:
                    return False
            if "$exists" in expected:
                exists = value is not None
                if bool(expected["$exists"]) != exists:
                    return False
            if not set(expected).intersection({"$in", "$nin", "$lt", "$gte", "$exists"}):
                return False
        elif value != expected:
            return False
    return True


class FakeCollection:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("InsertOneResult", (), {"inserted_id": doc.get("_id") or "fake_inserted_id"})()

    def count_documents(self, query):
        return len([doc for doc in self.docs if _matches(doc, query or {})])

    def find_one(self, query=None, projection=None):
        for doc in self.docs:
            if _matches(doc, query or {}):
                return dict(doc)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        docs = []
        for doc in self.docs:
            if not _matches(doc, query):
                continue
            docs.append(dict(doc))
        return FakeCursor(docs)

    def find_one_and_update(self, query, update, return_document=None, projection=None):
        for doc in self.docs:
            if not _matches(doc, query):
                continue
            if "$set" in update:
                doc.update(update["$set"])
            if "$inc" in update:
                for key, value in update["$inc"].items():
                    doc[key] = int(doc.get(key) or 0) + int(value)
            if "$push" in update:
                for key, value in update["$push"].items():
                    entry = value.get("$each", [value])[0] if isinstance(value, dict) else value
                    doc.setdefault(key, []).append(entry)
            return dict(doc)
        return None

    def update_one(self, query, update, **kwargs):
        modified = 0
        for doc in self.docs:
            if not _matches(doc, query):
                continue
            if "$set" in update:
                doc.update(update["$set"])
            if "$inc" in update:
                for key, value in update["$inc"].items():
                    doc[key] = int(doc.get(key) or 0) + int(value)
            if "$push" in update:
                for key, value in update["$push"].items():
                    entry = value.get("$each", [value])[0] if isinstance(value, dict) else value
                    doc.setdefault(key, []).append(entry)
            modified = 1
            break
        if modified == 0 and kwargs.get("upsert"):
            doc = dict(query)
            if "$set" in update:
                doc.update(update["$set"])
            self.docs.append(doc)
            modified = 1
        return type("UpdateResult", (), {"modified_count": modified})()

    def update_many(self, query, update):
        run_ids = set(query.get("run_id", {}).get("$in", []))
        for doc in self.docs:
            if doc.get("run_id") in run_ids and "$set" in update:
                doc.update(update["$set"])


class FakeCursor(list):
    def sort(self, *args, **kwargs):
        return self

    def limit(self, value):
        return FakeCursor(self[:value])


class FakeDb(dict):
    def __getitem__(self, key):
        self.setdefault(key, FakeCollection())
        return dict.__getitem__(self, key)


class ExternalRepairAgentTests(unittest.TestCase):
    def test_unknown_provider_rejected(self):
        result = ext.detect_provider("unknown")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "provider_not_supported")
        self.assertIn("digitalocean-amd-cloud", result["supported"])

    def test_digitalocean_provider_detected_as_api_cloud_burst(self):
        fake_status = {
            "ok": True,
            "token_present": True,
            "account_reachable": True,
            "mutations_require": ["approval_id", "apply_window"],
        }
        with patch("raphiia_openai.digitalocean_amd_provider.status", return_value=fake_status), \
            patch("raphiia_openai.digitalocean_amd_provider.preflight", return_value={"ok": True}):
            result = ext.detect_provider("digitalocean-amd-cloud")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["provider_type"], "ephemeral_cloud_burst")

    def test_digitalocean_credit_status_includes_provider_balance(self):
        db = FakeDb()
        with patch.object(ext, "_db", return_value=db), \
            patch.object(ext, "_credit_config", return_value={
                "enabled": True,
                "daily_hard_limit": {"digitalocean-amd-cloud": 1},
                "monthly_hard_limit": {"digitalocean-amd-cloud": 6},
            }), \
            patch("raphiia_openai.digitalocean_amd_provider.balance", return_value={"ok": True, "account_balance": "-5.00"}):
            result = ext.external_credit_status("digitalocean-amd-cloud")
        row = result["providers"][0]
        self.assertFalse(row["hard_blocked"])
        self.assertEqual(row["provider_credit"]["account_balance"], "-5.00")

    def test_missing_provider_is_unavailable_not_ready(self):
        with patch("shutil.which", return_value=None):
            result = ext.detect_provider("cursor")
        self.assertTrue(result["ok"])
        self.assertFalse(result["installed"])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["unavailable_reason"], "cli_not_installed")

    def test_budget_hard_limit_blocks_execution(self):
        with patch.object(ext, "external_credit_status", return_value={
            "ok": True,
            "providers": [{
                "provider": "codex",
                "daily_chargeable_runs": 3,
                "monthly_chargeable_runs": 3,
                "daily_hard_limit": 3,
                "monthly_hard_limit": 30,
                "hard_blocked": True,
            }],
        }):
            result = ext._budget_allows("codex")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "blocked_by_budget")

    def test_run_requires_explicit_spend_approval(self):
        with patch.object(ext, "_budget_allows", return_value={"ok": True, "credit": {}}):
            result = ext.external_repair_agent_run_task("codex", "ops_fixture", dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "external_spend_approval_required")

    def test_start_checkpoint_recover_complete_without_task_update(self):
        db = FakeDb()
        with patch.object(ext, "_db", return_value=db), \
            patch.object(ext, "_budget_allows", return_value={"ok": True, "credit": {}}), \
            patch.object(ext, "_report_external_repair_result", return_value={"ok": True}), \
            patch.object(ext.coordination_live, "heartbeat_ops_task", return_value={"ok": True}):
            started = ext.start_external_repair_run(provider="codex", task_id="ops_fixture", dry_run=True)
            self.assertTrue(started["ok"])
            run_id = started["run"]["run_id"]

            checkpoint = ext.checkpoint_external_repair_run(run_id, phase="fixture", evidence={"x": 1})
            self.assertTrue(checkpoint["ok"])
            self.assertEqual(checkpoint["run"]["status"], "checkpointed")

            recovered = ext.recover_external_repair_runs(provider="codex")
            self.assertTrue(recovered["ok"])
            self.assertEqual(len(recovered["active_runs"]), 1)

            completed = ext.complete_external_repair_run(run_id, update_task=False)
            self.assertTrue(completed["ok"])
            self.assertEqual(completed["run"]["status"], "completed")

    def test_reconcile_resolves_terminal_handoff_and_auto_claims_next_task(self):
        db = FakeDb()
        db[coordination_live.OPS_TASKS_COL].docs.extend([
            {
                "task_id": "ops_done",
                "assignee": "codex",
                "status": "completed",
                "owner": "system",
                "priority": "p0",
                "revision": 7,
                "correlation_id": "corr-done",
                "created_at": "2026-08-26T00:00:00+00:00",
                "updated_at": "2026-08-26T00:10:00+00:00",
            },
            {
                "task_id": "ops_next",
                "assignee": "codex",
                "status": "proposed",
                "owner": None,
                "priority": "p0",
                "revision": 1,
                "correlation_id": "corr-next",
                "created_at": "2026-08-26T00:11:00+00:00",
            },
        ])
        db[COL_AGENT_MESSAGES].docs.append({
            "message_id": "msg_done_handoff",
            "target_agent": "chatgpt",
            "type": "handoff",
            "status": "open",
            "priority": "normal",
            "correlation_id": "corr-done",
            "payload": {"task_id": "ops_done"},
        })
        with patch.object(ext, "_db", return_value=db), \
            patch.object(ext, "_auto_claim_enabled", return_value=True), \
            patch.object(ext, "detect_provider", return_value={"ok": True, "provider": "codex", "status": "ready", "auth_ready": True}), \
            patch.object(ext, "_budget_allows", return_value={"ok": True, "credit": {}}), \
            patch.object(ext, "external_credit_status", return_value={"ok": True, "providers": []}), \
            patch.object(ext.coordination_live, "bump_revision", return_value={"ok": True}), \
            patch.object(coordination_live.mongo_store, "get_db", return_value=db), \
            patch.object(ext.coordination_live, "update_ops_task_state", wraps=coordination_live.update_ops_task_state):
            result = ext.external_repair_agent_reconcile(provider="codex", auto_claim=True, dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["handoffs"]["resolved"], ["msg_done_handoff"])
        self.assertTrue(result["claim"]["claimed"])
        claimed = db[coordination_live.OPS_TASKS_COL].find_one({"task_id": "ops_next"})
        self.assertEqual(claimed["status"], "in_progress")
        self.assertEqual(claimed["owner"], "codex")

    def test_reconcile_does_not_claim_when_provider_has_active_task(self):
        db = FakeDb()
        db[coordination_live.OPS_TASKS_COL].docs.extend([
            {
                "task_id": "ops_active",
                "assignee": "codex",
                "status": "in_progress",
                "owner": "codex",
                "priority": "p0",
                "revision": 3,
                "created_at": "2026-08-26T00:00:00+00:00",
                "updated_at": "2026-08-26T00:10:00+00:00",
                "last_heartbeat_at": ext._now(),
            },
            {
                "task_id": "ops_waiting",
                "assignee": "codex",
                "status": "proposed",
                "owner": None,
                "priority": "p0",
                "revision": 1,
                "created_at": "2026-08-26T00:11:00+00:00",
            },
        ])
        with patch.object(ext, "_db", return_value=db), \
            patch.object(ext, "_auto_claim_enabled", return_value=True), \
            patch.object(ext, "detect_provider", return_value={"ok": True, "provider": "codex", "status": "ready", "auth_ready": True}), \
            patch.object(ext, "_budget_allows", return_value={"ok": True, "credit": {}}), \
            patch.object(ext, "external_credit_status", return_value={"ok": True, "providers": []}), \
            patch.object(coordination_live.mongo_store, "get_db", return_value=db):
            result = ext.external_repair_agent_reconcile(provider="codex", auto_claim=True, dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["claim"]["reason"], "provider_has_active_tasks")
        waiting = db[coordination_live.OPS_TASKS_COL].find_one({"task_id": "ops_waiting"})
        self.assertEqual(waiting["status"], "proposed")

    def test_reconcile_ignores_stale_active_task_when_no_live_run(self):
        db = FakeDb()
        db[coordination_live.OPS_TASKS_COL].docs.extend([
            {
                "task_id": "ops_stale",
                "assignee": "codex",
                "status": "in_progress",
                "owner": "codex",
                "priority": "p0",
                "revision": 3,
                "created_at": "2026-08-24T00:00:00+00:00",
                "updated_at": "2026-08-24T00:10:00+00:00",
                "last_heartbeat_at": "2026-08-24T00:10:00+00:00",
            },
            {
                "task_id": "ops_waiting",
                "assignee": "codex",
                "status": "proposed",
                "owner": None,
                "priority": "p0",
                "revision": 1,
                "created_at": "2026-08-26T00:11:00+00:00",
            },
        ])
        with patch.object(ext, "_db", return_value=db), \
            patch.object(ext, "_auto_claim_enabled", return_value=True), \
            patch.object(ext, "detect_provider", return_value={"ok": True, "provider": "codex", "status": "ready", "auth_ready": True}), \
            patch.object(ext, "_budget_allows", return_value={"ok": True, "credit": {}}), \
            patch.object(ext, "external_credit_status", return_value={"ok": True, "providers": []}), \
            patch.object(coordination_live.mongo_store, "get_db", return_value=db):
            result = ext.external_repair_agent_reconcile(provider="codex", auto_claim=True, dry_run=False)
        self.assertTrue(result["ok"])
        self.assertTrue(result["claim"]["claimed"])
        waiting = db[coordination_live.OPS_TASKS_COL].find_one({"task_id": "ops_waiting"})
        self.assertEqual(waiting["status"], "in_progress")

    def test_claim_blocks_candidate_when_budget_disallows(self):
        db = FakeDb()
        db[coordination_live.OPS_TASKS_COL].docs.append({
            "task_id": "ops_budget",
            "assignee": "codex",
            "status": "proposed",
            "owner": None,
            "priority": "p0",
            "revision": 1,
            "created_at": "2026-08-26T00:11:00+00:00",
        })
        with patch.object(ext, "_db", return_value=db), \
            patch.object(ext, "detect_provider", return_value={"ok": True, "provider": "codex", "status": "ready", "auth_ready": True}), \
            patch.object(ext, "_budget_allows", return_value={"ok": False, "error": "blocked_by_budget", "credit": {}}), \
            patch.object(ext.coordination_live, "bump_revision", return_value={"ok": True}), \
            patch.object(coordination_live.mongo_store, "get_db", return_value=db), \
            patch.object(ext.coordination_live, "update_ops_task_state", wraps=coordination_live.update_ops_task_state):
            result = ext.external_repair_agent_claim_next(provider="codex", dry_run=False)
        self.assertTrue(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertEqual(result["reason"], "blocked_by_budget")
        task = db[coordination_live.OPS_TASKS_COL].find_one({"task_id": "ops_budget"})
        self.assertEqual(task["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
