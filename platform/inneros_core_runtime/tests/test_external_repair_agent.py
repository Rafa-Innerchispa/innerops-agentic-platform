import unittest
from unittest.mock import patch

from inneros_core_runtime import external_repair_agent as ext


class FakeCollection:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(dict(doc))

    def count_documents(self, query):
        return len(self.docs)

    def find(self, query=None, projection=None):
        query = query or {}
        docs = []
        for doc in self.docs:
            if "$in" in query.get("status", {}):
                if doc.get("status") not in query["status"]["$in"]:
                    continue
            if "provider" in query and doc.get("provider") != query["provider"]:
                continue
            if "updated_at" in query and "$lt" in query["updated_at"]:
                value = doc.get("updated_at")
                if not value or not value < query["updated_at"]["$lt"]:
                    continue
            docs.append(dict(doc))
        return FakeCursor(docs)

    def find_one_and_update(self, query, update, return_document=None, projection=None):
        for doc in self.docs:
            if query.get("run_id") and doc.get("run_id") != query["run_id"]:
                continue
            if "status" in query and "$nin" in query["status"] and doc.get("status") in query["status"]["$nin"]:
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


if __name__ == "__main__":
    unittest.main()
