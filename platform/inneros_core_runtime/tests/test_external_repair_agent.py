import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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
            if "$regex" in expected:
                flags = re.I if "i" in str(expected.get("$options") or "") else 0
                if re.search(str(expected["$regex"]), str(value or ""), flags) is None:
                    return False
            if not set(expected).intersection({"$in", "$nin", "$lt", "$gte", "$exists", "$regex"}):
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


    def test_status_exposes_nonterminal_tasks_even_when_active_runs_empty(self):
        db = FakeDb()
        db[coordination_live.OPS_TASKS_COL].docs.append({
            "task_id": "ops_active_no_run",
            "assignee": "codex",
            "status": "in_progress",
            "owner": "codex",
            "priority": "p0",
            "revision": 2,
            "correlation_id": "corr-active",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "created_at": ext._now(),
            "updated_at": ext._now(),
            "last_heartbeat_at": ext._now(),
        })
        with patch.object(ext, "_db", return_value=db), \
            patch.object(ext, "detect_provider", return_value={"ok": True, "provider": "codex", "status": "ready", "auth_ready": True}), \
            patch.object(ext, "external_credit_status", return_value={"ok": True, "providers": []}):
            result = ext.external_repair_agent_status("codex")
        self.assertTrue(result["ok"])
        self.assertEqual(result["active_runs"], [])
        self.assertEqual(result["pending_nonterminal_count"], 1)
        self.assertEqual(result["nonterminal_statuses"], {"in_progress": 1})
        self.assertEqual(result["nonterminal_buckets"], {"ACTIVE_TASK_NO_RUN": 1})
        self.assertEqual(result["nonterminal_tasks"][0]["action"], "MONITOR_TASK_STATE")

    def test_nonterminal_summary_classifies_partial_blocked_and_proposed(self):
        db = FakeDb()
        db[coordination_live.OPS_TASKS_COL].docs.extend([
            {
                "task_id": "ops_partial_old",
                "assignee": "codex",
                "status": "partial",
                "owner": "codex",
                "priority": "p0",
                "revision": 2,
                "created_at": "2026-08-24T00:00:00+00:00",
                "updated_at": "2026-08-24T00:10:00+00:00",
            },
            {
                "task_id": "ops_blocked_wait",
                "assignee": "codex",
                "status": "blocked",
                "owner": "codex",
                "priority": "p1",
                "revision": 3,
                "created_at": "2026-08-24T00:00:00+00:00",
                "updated_at": "2026-08-24T00:10:00+00:00",
                "blocker": "human_required",
            },
            {
                "task_id": "ops_proposed",
                "assignee": "codex",
                "status": "proposed",
                "owner": None,
                "priority": "p0",
                "revision": 1,
                "created_at": "2026-08-26T00:00:00+00:00",
                "updated_at": "2026-08-26T00:00:00+00:00",
            },
        ])
        with patch.object(ext, "_db", return_value=db):
            result = ext.provider_nonterminal_summary("codex", stale_after_seconds=60)
        buckets = {row["task_id"]: row["bucket"] for row in result["tasks"]}
        self.assertEqual(buckets["ops_partial_old"], "STALE_RECOVERABLE")
        self.assertEqual(buckets["ops_blocked_wait"], "BLOCKED")
        self.assertEqual(buckets["ops_proposed"], "PROPOSED")
        self.assertEqual(result["pending_nonterminal_count"], 3)

    def test_completed_run_closes_nonterminal_task_without_rerun(self):
        db = FakeDb()
        db[coordination_live.OPS_TASKS_COL].docs.append({
            "task_id": "ops_7fbd43c2f9c9",
            "assignee": "codex",
            "status": "blocked",
            "owner": "codex",
            "priority": "critical",
            "revision": 4,
            "correlation_id": "hyperloom-r9700-master-amd-challenge1-20260907",
            "created_at": "2026-09-07T23:53:32+00:00",
            "updated_at": "2026-09-08T00:10:00+00:00",
            "blocker": "stale_ops_task_timeout",
        })
        db[ext.RUNS_COL].docs.append({
            "run_id": "extrep_hyperloom_done",
            "provider": "codex",
            "task_id": "ops_7fbd43c2f9c9",
            "status": "completed",
            "result": "PASS",
            "updated_at": "2026-09-08T01:00:00+00:00",
            "evidence": {"result": "PASS", "commit_sha": "c201c97507b35f10a1b0189f97ce192f1e10adb8"},
        })
        with patch.object(ext, "_db", return_value=db), \
            patch.object(coordination_live.mongo_store, "get_db", return_value=db), \
            patch.object(ext.coordination_live, "bump_revision", return_value={"ok": True}):
            result = ext.reconcile_completed_runs_to_tasks("codex", dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["closed_count"], 1)
        task = db[coordination_live.OPS_TASKS_COL].find_one({"task_id": "ops_7fbd43c2f9c9"})
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["evidence"]["result"], "PASS")
        self.assertTrue(task["evidence"]["reconciled_from_completed_run"])




    def test_completed_run_without_success_result_is_review_not_close_bucket(self):
        db = FakeDb()
        db[coordination_live.OPS_TASKS_COL].docs.append({
            "task_id": "ops_partial_review",
            "assignee": "codex",
            "status": "partial",
            "owner": "codex",
            "priority": "critical",
            "revision": 4,
            "created_at": "2026-09-07T23:53:32+00:00",
            "updated_at": "2026-09-08T00:10:00+00:00",
        })
        db[ext.RUNS_COL].docs.append({
            "run_id": "extrep_partial_text",
            "provider": "codex",
            "task_id": "ops_partial_review",
            "status": "completed",
            "result": "PARTIAL",
            "updated_at": "2026-09-08T01:00:00+00:00",
            "evidence": {"summary": "dry-run only"},
        })
        with patch.object(ext, "_db", return_value=db):
            result = ext.provider_nonterminal_summary("codex")
        row = result["tasks"][0]
        self.assertEqual(row["bucket"], "TERMINAL_RUN_REVIEW")
        self.assertEqual(row["action"], "REVIEW_COMPLETED_RUN_RESULT")

    def test_completed_run_without_success_result_does_not_close_partial_task(self):
        db = FakeDb()
        db[coordination_live.OPS_TASKS_COL].docs.append({
            "task_id": "ops_partial_review",
            "assignee": "codex",
            "status": "partial",
            "owner": "codex",
            "priority": "critical",
            "revision": 4,
            "correlation_id": "corr-partial",
            "created_at": "2026-09-07T23:53:32+00:00",
            "updated_at": "2026-09-08T00:10:00+00:00",
        })
        db[ext.RUNS_COL].docs.append({
            "run_id": "extrep_partial_text",
            "provider": "codex",
            "task_id": "ops_partial_review",
            "status": "completed",
            "result": "partial evidence gathered; owner scope remains",
            "updated_at": "2026-09-08T01:00:00+00:00",
            "evidence": {"summary": "dry-run only"},
        })
        with patch.object(ext, "_db", return_value=db):
            result = ext.reconcile_completed_runs_to_tasks("codex", dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["closed_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "completed_run_without_explicit_success_result")
        task = db[coordination_live.OPS_TASKS_COL].find_one({"task_id": "ops_partial_review"})
        self.assertEqual(task["status"], "partial")

    def test_completed_message_closes_hyperloom_without_rerun(self):
        db = FakeDb()
        db[coordination_live.OPS_TASKS_COL].docs.append({
            "task_id": "ops_7fbd43c2f9c9",
            "assignee": "codex",
            "status": "blocked",
            "owner": "codex",
            "priority": "critical",
            "revision": 4,
            "correlation_id": "hyperloom-r9700-master-amd-challenge1-20260907",
            "created_at": "2026-09-07T23:53:32+00:00",
            "updated_at": "2026-09-08T00:10:00+00:00",
            "blocker": "stale_ops_task_timeout",
        })
        db[COL_AGENT_MESSAGES].docs.append({
            "message_id": "msg_7d38c1470c4428c0",
            "from_agent": "CHATGPT",
            "target_agent": "codex",
            "title": "Contexto de cierre: reconciliación no terminal + HyperLoom ya integrado",
            "body": "ops_7fbd43c2f9c9 HyperLoom NO debe reejecutarse. ChatGPT ya integró el checkpoint técnico en rama canónica, head c201c97507b35f10a1b0189f97ce192f1e10adb8. Reconcílialo/ciérralo con evidencia.",
            "payload": {"hyperloom_task_id": "ops_7fbd43c2f9c9", "hyperloom_canonical_commit": "c201c97507b35f10a1b0189f97ce192f1e10adb8"},
            "correlation_id": "ops-state-reconciliation-nonterminal-fix-20260908",
            "status": "open",
            "created_at": "2026-09-08T14:15:06+00:00",
        })
        with patch.object(ext, "_db", return_value=db), \
            patch.object(coordination_live.mongo_store, "get_db", return_value=db), \
            patch.object(ext.coordination_live, "bump_revision", return_value={"ok": True}):
            result = ext.reconcile_completed_runs_to_tasks("codex", dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["closed_count"], 1)
        self.assertEqual(result["closed"][0]["message_id"], "msg_7d38c1470c4428c0")
        task = db[coordination_live.OPS_TASKS_COL].find_one({"task_id": "ops_7fbd43c2f9c9"})
        self.assertEqual(task["status"], "completed")
        self.assertTrue(task["evidence"]["reconciled_from_agent_message"])
        self.assertTrue(task["evidence"]["no_rerun"])
        self.assertEqual(task["evidence"]["commit_sha"], "c201c97507b35f10a1b0189f97ce192f1e10adb8")

    def test_reconcile_records_buckets_and_does_not_duplicate_claims(self):
        db = FakeDb()
        db[coordination_live.OPS_TASKS_COL].docs.extend([
            {
                "task_id": "ops_recent",
                "assignee": "codex",
                "status": "in_progress",
                "owner": "codex",
                "priority": "p0",
                "revision": 2,
                "created_at": ext._now(),
                "updated_at": ext._now(),
                "last_heartbeat_at": ext._now(),
            },
            {
                "task_id": "ops_waiting",
                "assignee": "codex",
                "status": "proposed",
                "owner": None,
                "priority": "p0",
                "revision": 1,
                "created_at": "2026-08-26T00:00:00+00:00",
                "updated_at": "2026-08-26T00:00:00+00:00",
            },
        ])
        with patch.object(ext, "_db", return_value=db), \
            patch.object(ext, "_auto_claim_enabled", return_value=True), \
            patch.object(ext, "detect_provider", return_value={"ok": True, "provider": "codex", "status": "ready", "auth_ready": True}), \
            patch.object(ext, "_budget_allows", return_value={"ok": True, "credit": {}}), \
            patch.object(ext, "external_credit_status", return_value={"ok": True, "providers": []}), \
            patch.object(coordination_live.mongo_store, "get_db", return_value=db):
            first = ext.external_repair_agent_reconcile(provider="codex", auto_claim=True, dry_run=False)
            second = ext.external_repair_agent_reconcile(provider="codex", auto_claim=True, dry_run=False)
        self.assertTrue(first["ok"])
        self.assertEqual(first["claim"]["reason"], "provider_has_active_tasks")
        self.assertTrue(second["ok"])
        waiting = db[coordination_live.OPS_TASKS_COL].find_one({"task_id": "ops_waiting"})
        self.assertEqual(waiting["status"], "proposed")
        recent = db[coordination_live.OPS_TASKS_COL].find_one({"task_id": "ops_recent"})
        self.assertEqual(recent["nonterminal_reconcile_bucket"], "ACTIVE_TASK_NO_RUN")


if __name__ == "__main__":
    unittest.main()
