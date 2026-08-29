from __future__ import annotations

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

    def test_new_inneros_task_without_legacy_correlation_is_eligible(self) -> None:
        task = {
            "task_id": "ops_new_inneros",
            "status": "proposed",
            "assignee": "codex",
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
            "priority": "critical",
            "correlation_id": "innerops-allthingsagentic-20260821",
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
        with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
            ok, reason, repo = scheduler._eligible_reason(task)
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, scheduler.SAFE_INNEROS_REPO)

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
        self.assertEqual(reason, "repo_not_inferred")
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
        self.assertEqual(reason, "repo_not_inferred")
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
        self.assertEqual(reason, "repo_not_inferred")
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
        with mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
            ok, reason, repo = scheduler._eligible_reason(task)
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, "Rafa-Innerchispa/innerspark-workforce-ai")

    def test_workforce_explicit_package_root_resolves_to_workforce_repo(self) -> None:
        task = {
            "task_id": "ops_workforce_nested",
            "status": "proposed",
            "assignee": "chatgpt",
            "priority": "p0",
            "correlation_id": "devswarm-code-repair-20260826",
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
        self.assertEqual(result["filtered"][0]["reason"], "non_development_ops_filtered")


if __name__ == "__main__":
    unittest.main()
