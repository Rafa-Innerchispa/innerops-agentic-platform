from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock

from raphiia_openai import dev_swarm_scheduler as scheduler


class DevSwarmRepoInferenceTests(unittest.TestCase):
    def test_candidate_loader_includes_new_critical_before_old_normal(self) -> None:
        class Cursor(list):
            def sort(self, *_args):
                return Cursor(sorted(self, key=lambda row: row.get("created_at", ""), reverse=True))

            def limit(self, n):
                return Cursor(self[:n])

        class Collection:
            def __init__(self):
                self.rows = [
                    {"task_id": "normal_old", "status": "proposed", "priority": "normal", "created_at": "2026-08-20T00:00:00+00:00"},
                    {"task_id": "critical_new", "status": "proposed", "priority": "critical", "created_at": "2026-08-26T00:00:00+00:00"},
                ]

            def find(self, query, _projection):
                rows = [row for row in self.rows if row["status"] == query.get("status")]
                if "priority" in query:
                    rows = [row for row in rows if row["priority"] == query["priority"]]
                return Cursor(rows)

        db = {scheduler.coordination_live.OPS_TASKS_COL: Collection()}
        rows = scheduler._load_scheduler_candidates(db, {"status": "proposed"}, 1)
        self.assertEqual(rows[0]["task_id"], "critical_new")

    def test_candidate_loader_ignores_stale_duplicate_proposed_task(self) -> None:
        class Cursor(list):
            def sort(self, spec, *_args):
                if isinstance(spec, list):
                    rows = list(self)
                    for key, direction in reversed(spec):
                        rows.sort(key=lambda row: row.get(key, ""), reverse=direction < 0)
                    return Cursor(rows)
                return Cursor(sorted(self, key=lambda row: row.get(spec, ""), reverse=True))

            def limit(self, n):
                return Cursor(self[:n])

        class Collection:
            def __init__(self):
                self.rows = [
                    {
                        "task_id": "ops_watchdog_dupe",
                        "status": "proposed",
                        "priority": "p0",
                        "created_at": "2026-08-27T15:12:05+00:00",
                        "updated_at": "2026-08-27T15:12:05+00:00",
                        "revision": 1,
                    },
                    {
                        "task_id": "ops_watchdog_dupe",
                        "status": "blocked",
                        "priority": "p0",
                        "created_at": "2026-08-27T15:03:30+00:00",
                        "updated_at": "2026-08-29T15:48:55+00:00",
                        "revision": 8,
                    },
                ]

            def find(self, query, _projection):
                rows = []
                for row in self.rows:
                    if "task_id" in query and row["task_id"] != query["task_id"]:
                        continue
                    if "status" in query and row["status"] != query["status"]:
                        continue
                    if "priority" in query and row["priority"] != query["priority"]:
                        continue
                    rows.append(row)
                return Cursor(rows)

        db = {scheduler.coordination_live.OPS_TASKS_COL: Collection()}
        rows = scheduler._load_scheduler_candidates(db, {"status": "proposed"}, 10)
        self.assertEqual(rows, [])

    def test_new_inneros_task_without_legacy_correlation_is_eligible(self) -> None:
        task = {
            "task_id": "ops_new_inneros",
            "status": "proposed",
            "assignee": "codex",
            "execution_lane": "local_dev_swarm",
            "priority": "p0",
            "correlation_id": "devswarm-repo-inference-20260825",
            "related_project": "InnerOS platform",
            "title": "Fix Dev Swarm repo inference in InnerOS runtime",
            "checklist": ["Repair resource fabric and local execution scheduler"],
        }
        with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
            ok, reason, repo = scheduler._eligible_reason(task)
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, scheduler.SAFE_INNEROS_REPO)

    def test_explicit_allowlisted_repo_is_accepted_without_legacy_correlation(self) -> None:
        task = {
            "task_id": "ops_explicit_repo",
            "status": "proposed",
            "assignee": "chatgpt",
            "priority": "p0",
            "correlation_id": "brand-new-correlation",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "title": "Run platform tests",
        }
        with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
            ok, reason, repo = scheduler._eligible_reason(task)
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, "Rafa-Innerchispa/innerops-agentic-platform")

    def test_email_finance_whatsapp_tasks_are_not_inferred_as_dev_repo(self) -> None:
        for title in (
            "Process email inbox and invoice summary",
            "WhatsApp quote follow-up for customer",
            "Funding finance registry update",
        ):
            task = {
                "task_id": "ops_non_dev",
                "status": "proposed",
                "assignee": "codex",
                "priority": "p0",
                "title": title,
                "checklist": ["Operational task, no code repo"],
            }
            ok, reason, repo = scheduler._eligible_reason(task)
            self.assertFalse(ok)
            self.assertEqual(reason, "non_development_ops_filtered")
            self.assertIsNone(repo)

    def test_email_with_development_keywords_still_filtered_by_kind_tag(self) -> None:
        task = {
            "task_id": "ops_email_noise",
            "status": "proposed",
            "assignee": "chatgpt",
            "priority": "p0",
            "kind": "email_ops",
            "tags": ["email"],
            "title": "Fix reply workflow for admissions email",
            "checklist": ["Operational email handling, no repository."],
        }
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "non_development_ops_filtered")
        self.assertIsNone(repo)

    def test_spanish_platform_repair_terms_are_development_intent(self) -> None:
        task = {
            "task_id": "ops_spanish_repair",
            "status": "proposed",
            "assignee": "codex",
            "execution_lane": "local_dev_swarm",
            "priority": "p0",
            "related_project": "InnerOS platform",
            "title": "Corregir scheduler y reparar verifier del Dev Swarm",
            "checklist": ["Arreglar runtime local y pruebas de regresion"],
        }
        with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
            ok, reason, repo = scheduler._eligible_reason(task)
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, scheduler.SAFE_INNEROS_REPO)

    def test_innerops_hackathon_with_xprize_context_is_eligible(self) -> None:
        task = {
            "task_id": "ops_innerops_bootstrap",
            "status": "proposed",
            "assignee": "codex",
            "execution_lane": "local_dev_swarm",
            "priority": "critical",
            "correlation_id": "innerops-allthingsagentic-20260821",
            "related_project": "innerops-agentic-platform",
            "title": "Bootstrap InnerOps All Things Agentic",
            "checklist": ["Preserve XPRIZE baseline", "Create innerops-agentic-platform repo and docs"],
        }
        with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
            ok, reason, repo = scheduler._eligible_reason(task)
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, scheduler.SAFE_INNEROS_REPO)

    def test_cloudflare_platform_repair_is_eligible(self) -> None:
        task = {
            "task_id": "ops_cloudflare_tools",
            "status": "proposed",
            "assignee": "chatgpt",
            "priority": "p0",
            "title": "AG-44 Cloudflare tools need DNS WAF and tunnel implementation",
            "checklist": ["Wire provider tools to owner_vault and MCP runtime"],
        }
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked_missing_task_binding")
        self.assertIsNone(repo)

    def test_xprize_product_without_innerops_context_is_not_inferred(self) -> None:
        task = {
            "task_id": "ops_xprize_product",
            "status": "proposed",
            "assignee": "antigravity",
            "priority": "critical",
            "correlation_id": "xprize-pre-submit-hardening-20260815",
            "title": "CORRECCION P0: produccion real, no reemplazar datos DB por demos",
            "checklist": ["Repo publico cero PII", "Conservar usuarios reales en Firestore", "No tocar Devpost sin validacion"],
        }
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked_missing_task_binding")
        self.assertIsNone(repo)

    def test_cloudflare_hostname_ops_without_ag44_context_is_not_inferred(self) -> None:
        task = {
            "task_id": "ops_cloudflare_hostname",
            "status": "proposed",
            "assignee": "cursor",
            "priority": "critical",
            "title": "Configurar Cloudflare workforce.pcdoctor.ai ahora",
            "checklist": ["Verifica DNS TLS y HTTP 200 sin tocar otros hostnames"],
        }
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked_missing_task_binding")
        self.assertIsNone(repo)

    def test_workforce_femar_without_explicit_repo_stays_excluded(self) -> None:
        task = {
            "task_id": "ops_workforce",
            "status": "proposed",
            "assignee": "codex",
            "priority": "p0",
            "title": "Fix workforce.pcdoctor.ai FEMAR schedules",
            "checklist": ["Do not touch product without explicit repo"],
        }
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked_missing_task_binding")
        self.assertIsNone(repo)


    def test_workforce_devswarm_task_resolves_to_workforce_repo_not_platform(self) -> None:
        task = {
            "task_id": "ops_workforce_devswarm",
            "status": "blocked",
            "owner": "dev_swarm",
            "assignee": "ralfia",
            "priority": "p0",
            "dev_swarm_retry_requested": True,
            "correlation_id": "workforce-full-parity-gemini-analytics-20260824",
            "title": "P0 Workforce parity + Gemini HR/Payroll analytics + 2-year synthetic dataset",
            "checklist": [
                "Preservar Workforce existente y tenants/auth/datos; no recrear FEMAR.",
                "Implementacion de features grandes por Dev Swarm/modelos locales.",
                "Browser QA de todos los menus CRUD/reportes.",
            ],
        }
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked_missing_task_binding")
        self.assertIsNone(repo)

    def test_workforce_explicit_package_root_resolves_to_workforce_repo(self) -> None:
        task = {
            "task_id": "ops_workforce_nested",
            "status": "proposed",
            "assignee": "chatgpt",
            "priority": "p0",
            "correlation_id": "devswarm-code-repair-20260826",
            "repo": "Rafa-Innerchispa/innerspark-workforce-ai",
            "title": "Restore Jest dependencies",
            "checklist": ["Run npm ci in services/femar-mvp-core inside isolated worktree"],
        }
        with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
            ok, reason, repo = scheduler._eligible_reason(task)
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, "Rafa-Innerchispa/innerspark-workforce-ai")

    def test_scheduler_dry_run_selects_p0_when_capacity_free(self) -> None:
        class Cursor(list):
            def sort(self, *_args):
                return Cursor(sorted(self, key=lambda row: row.get("created_at", ""), reverse=True))

            def limit(self, n):
                return Cursor(self[:n])

        class Tasks:
            rows = [
                {
                    "task_id": "ops_workforce_nested",
                    "status": "proposed",
                    "assignee": "chatgpt",
                    "priority": "p0",
                    "created_at": "2026-08-26T20:00:00+00:00",
                    "repo": "Rafa-Innerchispa/innerspark-workforce-ai",
                    "checklist": ["Run npm ci in services/femar-mvp-core"],
                },
                {
                    "task_id": "ops_email",
                    "status": "proposed",
                    "assignee": "ralfia",
                    "priority": "normal",
                    "created_at": "2026-08-26T19:00:00+00:00",
                    "kind": "email_ops",
                    "tags": ["email"],
                    "title": "Process invoice email",
                },
                {
                    "task_id": "ops_needs_repo",
                    "status": "proposed",
                    "assignee": "codex",
                    "execution_lane": "local_dev_swarm",
                    "priority": "p0",
                    "created_at": "2026-08-26T18:00:00+00:00",
                    "coordination_bucket": "needs_repo_metadata",
                    "title": "Old task without safe repo metadata",
                },
            ]

            def find(self, query, _projection):
                rows = [r for r in self.rows if r.get("status") == query.get("status")]
                if "priority" in query:
                    rows = [r for r in rows if r.get("priority") == query["priority"]]
                return Cursor(rows)

            def update_one(self, *_args, **_kwargs):
                return None

        class Workers:
            def count_documents(self, _query):
                return 0

            def find(self, *_args, **_kwargs):
                return Cursor([])

        db = {scheduler.coordination_live.OPS_TASKS_COL: Tasks(), scheduler.WORKERS_COL: Workers(), "ralfia_coordination_locks": Workers()}
        with mock.patch.object(scheduler, "_db", return_value=db), \
             mock.patch.object(scheduler, "_state", return_value={"enabled": True, "max_concurrent": 4}), \
             mock.patch.object(scheduler, "capacity_status", return_value={"recommendation": {"recommended_concurrency_total": 4}}), \
             mock.patch.object(scheduler, "reconcile_capacity_state", return_value={"ok": True, "active_worker_count": 0}), \
             mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
            result = scheduler.scheduler_tick(limit=4, dry_run=True)
        self.assertEqual(result["available"], 4)
        self.assertEqual(result["selected"][0]["task_id"], "ops_workforce_nested")
        self.assertEqual(result["selected"][0]["repo"], "Rafa-Innerchispa/innerspark-workforce-ai")
        reasons = {row["task_id"]: row["reason"] for row in result["filtered"]}
        self.assertEqual(reasons["ops_email"], "non_development_ops_filtered")
        self.assertEqual(reasons["ops_needs_repo"], "needs_repo_metadata")
        self.assertFalse(result["skipped"])

    def test_scheduler_live_selection_publishes_durable_event(self) -> None:
        class Cursor(list):
            def sort(self, *_args):
                if _args and isinstance(_args[0], list):
                    return Cursor(self)
                return Cursor(sorted(self, key=lambda row: row.get("created_at", ""), reverse=True))

            def limit(self, n):
                return Cursor(self[:n])

        class Tasks:
            rows = [
                {
                    "task_id": "ops_platform_live",
                    "status": "proposed",
                    "assignee": "dev_swarm",
                    "execution_lane": "local_dev_swarm",
                    "priority": "p0",
                    "created_at": "2026-09-06T16:00:00+00:00",
                    "updated_at": "2026-09-06T16:00:00+00:00",
                    "revision": 1,
                    "repo": scheduler.SAFE_INNEROS_REPO,
                    "correlation_id": "durable-spine-test",
                    "title": "Repair scheduler telemetry",
                    "checklist": ["Implement durable event evidence"],
                },
            ]

            def find(self, query, _projection):
                rows = self.rows
                if "status" in query:
                    rows = [r for r in rows if r.get("status") == query["status"]]
                if "priority" in query:
                    rows = [r for r in rows if r.get("priority") == query["priority"]]
                if "task_id" in query:
                    rows = [r for r in rows if r.get("task_id") == query["task_id"]]
                return Cursor(rows)

            def find_one(self, query, _projection=None):
                rows = self.find(query, _projection)
                return rows[0] if rows else None

            def update_one(self, *_args, **_kwargs):
                return None

        class Workers:
            def count_documents(self, _query):
                return 0

            def find(self, *_args, **_kwargs):
                return Cursor([])

        db = {scheduler.coordination_live.OPS_TASKS_COL: Tasks(), scheduler.WORKERS_COL: Workers()}
        with mock.patch.object(scheduler, "_db", return_value=db), \
             mock.patch.object(scheduler, "_state", return_value={"enabled": True, "max_concurrent": 4}), \
             mock.patch.object(scheduler, "capacity_status", return_value={"recommendation": {"recommended_concurrency_total": 4}}), \
             mock.patch.object(scheduler, "reconcile_capacity_state", return_value={"ok": True, "active_worker_count": 0}), \
             mock.patch.object(scheduler, "_save_state", return_value={}), \
             mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}), \
             mock.patch.object(scheduler, "fanout_execute", return_value={"ok": True, "started": ["ops_platform_live"]}), \
             mock.patch.object(scheduler.durable_coordination_spine, "publish_event", return_value={"ok": True, "event_id": "evt_selected"}) as publish_event:
            result = scheduler.scheduler_tick(limit=1, dry_run=False)

        self.assertTrue(result["ok"])
        self.assertEqual(result["selected"][0]["task_id"], "ops_platform_live")
        publish_event.assert_any_call(
            "scheduler.selected",
            actor="dev_swarm",
            task_id="ops_platform_live",
            correlation_id="durable-spine-test",
            repo=scheduler.SAFE_INNEROS_REPO,
            provider="local-amd-5",
            model="",
            status="selected",
            payload={"priority": "p0", "available_before_selection": 4, "selected_index": 0},
        )

    def test_fail_worker_early_publishes_blocked_event_fail_closed(self) -> None:
        class Workers:
            def update_one(self, *_args, **_kwargs):
                return None

        with mock.patch.object(scheduler, "_db", return_value={scheduler.WORKERS_COL: Workers()}), \
             mock.patch.object(scheduler.coordination_live, "update_ops_task_state", side_effect=RuntimeError("racb offline")), \
             mock.patch.object(scheduler.durable_coordination_spine, "publish_event", side_effect=RuntimeError("nats offline")), \
             mock.patch.object(scheduler.mongo_store, "log_sync") as log_sync:
            result = scheduler._fail_worker_early("ops_fail", "base_snapshot_failed")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "base_snapshot_failed")
        log_sync.assert_called_once()

    def test_cursor_task_without_local_dev_swarm_lane_is_not_claimed(self) -> None:
        task = {
            "task_id": "ops_cursor_project_factory",
            "status": "proposed",
            "assignee": "cursor",
            "priority": "p0",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "title": "Project Factory should stay on Cursor lane",
        }
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "execution_lane_required_for_dev_swarm")
        self.assertIsNone(repo)

    def test_codex_task_without_local_dev_swarm_lane_is_not_claimed(self) -> None:
        task = {
            "task_id": "ops_codex_runtime_fix",
            "status": "proposed",
            "assignee": "codex",
            "priority": "p0",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "title": "Codex-owned runtime fix",
        }
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "execution_lane_required_for_dev_swarm")
        self.assertIsNone(repo)
        self.assertEqual(scheduler.classify_coordination_backlog_task(task), "needs_execution_lane")

    def test_stale_in_progress_task_without_worker_is_blocked_by_reconciler(self) -> None:
        class Cursor(list):
            def limit(self, n):
                return Cursor(self[:n])

        class Tasks:
            def __init__(self):
                self.rows = [
                    {
                        "task_id": "ops_stale",
                        "status": "in_progress",
                        "owner": "dev_swarm",
                        "assignee": "dev_swarm",
                        "repo": scheduler.SAFE_INNEROS_REPO,
                        "correlation_id": "stale-test",
                        "last_heartbeat_at": "2026-09-05T00:00:00+00:00",
                        "updated_at": "2026-09-05T00:00:00+00:00",
                    }
                ]

            def find(self, query, _projection=None):
                statuses = set((query.get("status") or {}).get("$in") or [])
                return Cursor([row for row in self.rows if not statuses or row.get("status") in statuses])

            def find_one(self, query, _projection=None):
                for row in self.rows:
                    if row.get("task_id") == query.get("task_id"):
                        return row
                return None

            def update_one(self, query, patch):
                row = self.find_one({"task_id": query.get("task_id")})
                if not row:
                    return mock.Mock(modified_count=0)
                allowed_statuses = set((query.get("status") or {}).get("$in") or [])
                if allowed_statuses and row.get("status") not in allowed_statuses:
                    return mock.Mock(modified_count=0)
                row.update(patch.get("$set") or {})
                row.setdefault("state_history", []).append((patch.get("$push") or {}).get("state_history"))
                return mock.Mock(modified_count=1)

        class Workers:
            def find_one(self, *_args, **_kwargs):
                return None

        tasks = Tasks()
        db = {scheduler.coordination_live.OPS_TASKS_COL: tasks, scheduler.WORKERS_COL: Workers()}
        now = scheduler.datetime.fromisoformat("2026-09-06T17:00:00+00:00")
        with mock.patch.object(scheduler, "_publish_dev_swarm_event", return_value={"event_id": "evt_blocked"}) as publish:
            count = scheduler._reconcile_stale_ops_tasks(db, now, "2026-09-06T17:00:00+00:00", "unit_test")

        self.assertEqual(count, 1)
        self.assertEqual(tasks.rows[0]["status"], "blocked")
        self.assertEqual(tasks.rows[0]["blocker"], "stale_ops_task_timeout")
        self.assertFalse(tasks.rows[0]["dev_swarm_retry_requested"])
        self.assertEqual(tasks.rows[0]["state_history"][0]["from"], "in_progress")
        publish.assert_called_once()
        self.assertEqual(publish.call_args.args[0], "task.blocked")

    def test_recent_evidence_prevents_stale_task_reconciliation(self) -> None:
        class Cursor(list):
            def limit(self, n):
                return Cursor(self[:n])

        class Tasks:
            def __init__(self):
                self.rows = [
                    {
                        "task_id": "ops_recent_evidence",
                        "status": "verification",
                        "owner": "codex",
                        "assignee": "codex",
                        "repo": scheduler.SAFE_INNEROS_REPO,
                        "last_heartbeat_at": "2026-09-05T00:00:00+00:00",
                        "updated_at": "2026-09-05T00:00:00+00:00",
                        "last_evidence_at": "2026-09-06T16:55:00+00:00",
                        "evidence_history": [{"at": "2026-09-06T16:55:00+00:00", "status": "verification"}],
                    }
                ]

            def find(self, query, _projection=None):
                statuses = set((query.get("status") or {}).get("$in") or [])
                return Cursor([row for row in self.rows if not statuses or row.get("status") in statuses])

            def find_one(self, query, _projection=None):
                for row in self.rows:
                    if row.get("task_id") == query.get("task_id"):
                        return row
                return None

            def update_one(self, *_args, **_kwargs):
                return mock.Mock(modified_count=1)

        class Workers:
            def find_one(self, *_args, **_kwargs):
                return None

        tasks = Tasks()
        db = {scheduler.coordination_live.OPS_TASKS_COL: tasks, scheduler.WORKERS_COL: Workers()}
        now = scheduler.datetime.fromisoformat("2026-09-06T17:00:00+00:00")
        with mock.patch.object(scheduler, "_publish_dev_swarm_event") as publish:
            count = scheduler._reconcile_stale_ops_tasks(db, now, "2026-09-06T17:00:00+00:00", "unit_test")

        self.assertEqual(count, 0)
        self.assertEqual(tasks.rows[0]["status"], "verification")
        publish.assert_not_called()

    def test_manual_execution_lane_is_never_claimed_by_dev_swarm(self) -> None:
        task = {
            "task_id": "ops_manual_fixture",
            "status": "proposed",
            "assignee": "dev_swarm",
            "execution_lane": "manual",
            "priority": "p0",
            "repo": "Rafa-Innerchispa/innerops-agentic-platform",
            "title": "Owner manual approval step",
        }
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "execution_lane_not_local_dev_swarm:manual")
        self.assertIsNone(repo)

    def test_classifies_webmcp_readonly_ping_as_closed_watchdog_noise(self) -> None:
        task = {
            "task_id": "ops_ping",
            "status": "blocked",
            "assignee": "ralfia",
            "owner": "dev_swarm",
            "from_agent": "A2A",
            "priority": "p0",
            "correlation_id": "wmcp_1788459566755_pj367ax",
            "title": "WebMCP: inneros-webmcp action",
            "checklist": ["Read-only smoke verification: inspect the project status and report one concise finding. Do not modify files."],
            "evidence": {},
        }
        self.assertEqual(scheduler.classify_coordination_backlog_task(task), "closed_watchdog_noise")

    def test_does_not_cancel_cursor_webmcp_demo_ack_as_smoke_noise(self) -> None:
        task = {
            "task_id": "ops_cursor_demo",
            "status": "proposed",
            "assignee": "cursor",
            "from_agent": "CHATGPT",
            "priority": "p0",
            "correlation_id": "wmcp_1788451139447_hpq4lj4",
            "title": "WebMCP: inneros-webmcp action",
            "checklist": ["Demo video grabacion - ACK desde panel", "IDE target=cursor"],
            "evidence": {},
        }
        self.assertIsNone(scheduler.classify_coordination_backlog_task(task))

    def test_classifies_email_with_coding_metadata_as_operational_backlog(self) -> None:
        task = {
            "task_id": "ops_email",
            "status": "proposed",
            "assignee": "ralfia",
            "priority": "normal",
            "task_class": "coding",
            "correlation_id": "email:mail_0c75e736b617",
            "from_agent": "AG-38",
            "title": "[Correo/AG-38] Request For Quotation#214",
            "checklist": ["Revisar evidencia extraida", "document_type: cotizacion_propuesta"],
        }
        self.assertEqual(scheduler.classify_coordination_backlog_task(task), "email_ops_backlog")

    def test_classifies_pass_ready_blocked_worker_for_guardian(self) -> None:
        task = {
            "task_id": "ops_ready",
            "status": "blocked",
            "assignee": "dev_swarm",
            "owner": "dev_swarm",
            "priority": "p0",
            "title": "Integration lane",
            "next_action": "PASS: ready for Integration Guardian",
            "heartbeat_history": [{"next_action": "PASS: ready for Integration Guardian"}],
        }
        self.assertEqual(scheduler.classify_coordination_backlog_task(task), "ready_for_integration_guardian")

    def test_backlog_hygiene_dry_run_does_not_mutate_rows(self) -> None:
        class Cursor(list):
            def sort(self, *_args):
                return self

            def limit(self, n):
                return Cursor(self[:n])

        class Tasks:
            def __init__(self):
                self.rows = [
                    {
                        "task_id": "ops_ping",
                        "status": "blocked",
                        "assignee": "ralfia",
                        "owner": "dev_swarm",
                        "from_agent": "A2A",
                        "correlation_id": "wmcp_1",
                        "title": "WebMCP: inneros-webmcp action",
                        "checklist": ["read-only ping"],
                        "evidence": {},
                    },
                    {
                        "task_id": "ops_email",
                        "status": "proposed",
                        "assignee": "ralfia",
                        "correlation_id": "email:mail_1",
                        "title": "[Correo/AG-17] factura",
                        "task_class": "coding",
                    },
                ]
                self.updates = []

            def find(self, query, _projection):
                allowed = set(query["status"]["$in"])
                return Cursor([row for row in self.rows if row["status"] in allowed])

            def update_one(self, *args, **kwargs):
                self.updates.append((args, kwargs))

        tasks = Tasks()
        db = {scheduler.coordination_live.OPS_TASKS_COL: tasks}
        with mock.patch.object(scheduler, "_db", return_value=db):
            result = scheduler.reconcile_coordination_backlog_hygiene(dry_run=True)
        self.assertEqual(result["counts"]["closed_watchdog_noise"], 1)
        self.assertEqual(result["counts"]["email_ops_backlog"], 1)
        self.assertEqual(tasks.updates, [])

    def test_quality_gate_guidance_for_missing_json_and_no_product_write(self) -> None:
        gate = scheduler._quality_gate_guidance(
            repo="Rafa-Innerchispa/amd-ralfiia-hybrid-ops-copilot",
            product_root="",
            rejected_files=[{"reason": "missing_files_array"}],
            write_classes={"product": [], "diagnostic": []},
        )

        self.assertEqual(gate["version"], "dev_swarm_quality_gate_v1")
        self.assertIn("missing_files_array", gate["reasons"])
        self.assertTrue(any("single JSON object" in item for item in gate["repair_instructions"]))
        self.assertTrue(any("product-code write" in item for item in gate["repair_instructions"]))

    def test_quality_gate_guidance_for_nested_product_root_and_tests(self) -> None:
        gate = scheduler._quality_gate_guidance(
            repo="Rafa-Innerchispa/innerspark-workforce-ai",
            product_root="services/femar-mvp-core",
            rejected_files=[
                {"reason": "path_not_allowed_for_repo_profile"},
                {"reason": "undeclared_imports_denied"},
            ],
            write_classes={
                "product": [],
                "diagnostic": ["services/femar-mvp-core/src/inneros_dev_swarm/foo.ts"],
            },
            failed_checks=[
                {"command": ["npm", "--prefix", "services/femar-mvp-core", "test", "--", "--runInBand"]}
            ],
        )

        joined = " ".join(gate["repair_instructions"])
        self.assertIn("services/femar-mvp-core/src", joined)
        self.assertIn("absent from the existing package manifests", joined)
        self.assertIn("diagnostic-only", joined)
        self.assertEqual(
            gate["failed_commands"],
            [["npm", "--prefix", "services/femar-mvp-core", "test", "--", "--runInBand"]],
        )

    def test_quality_gate_failure_text_is_compact(self) -> None:
        text = scheduler._quality_gate_failure_text(
            {"reasons": ["missing_files_array"], "repair_instructions": ["x" * 5000]}
        )

        self.assertTrue(text.startswith("dev_swarm_quality_gate:missing_files_array:"))
        self.assertLessEqual(len(text), 4000)

    def test_diff_numstat_blocks_massive_control_plane_fixture_rewrite(self) -> None:
        risks = scheduler._diff_numstat_risks(
            "228\t2581\tplatform/inneros_core_runtime/dev_swarm_scheduler.py\n",
            "Verify scheduler can accept and launch a safe fixture.",
        )

        reasons = {risk["reason"] for risk in risks}
        self.assertIn("autonomous_diff_deletes_too_many_lines", reasons)
        self.assertIn("fixture_control_plane_diff_too_large", reasons)

    def test_diff_numstat_allows_small_additive_change(self) -> None:
        risks = scheduler._diff_numstat_risks(
            "18\t2\tplatform/inneros_core_runtime/dev_swarm_scheduler.py\n",
            "Implement focused scheduler regression.",
        )

        self.assertEqual(risks, [])


    def test_innerops_platform_product_paths_count_as_real_writes(self) -> None:
        with mock.patch.object(scheduler, "_primary_product_root", return_value="platform"):
            classes = scheduler._implementation_write_classes(
                scheduler.SAFE_INNEROS_REPO,
                Path("/tmp/worktree"),
                [
                    "platform/src/execution/fabric.py",
                    "platform/inneros_core_runtime/dev_swarm_scheduler.py",
                    "platform/raphiia_openai/__init__.py",
                    "platform/src/inneros_dev_swarm/contract.ts",
                    "README.md",
                ],
            )

        self.assertEqual(
            classes["product"],
            [
                "platform/inneros_core_runtime/dev_swarm_scheduler.py",
                "platform/raphiia_openai/__init__.py",
                "platform/src/execution/fabric.py",
            ],
        )
        self.assertEqual(classes["diagnostic"], ["platform/src/inneros_dev_swarm/contract.ts"])
        self.assertEqual(classes["other"], ["README.md"])



if __name__ == "__main__":
    unittest.main()
