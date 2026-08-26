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


if __name__ == "__main__":
    unittest.main()
