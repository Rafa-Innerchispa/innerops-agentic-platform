from __future__ import annotations

import unittest
from unittest import mock

from raphiia_openai import dev_swarm_scheduler as scheduler


INNEROPS_REPO = "Rafa-Innerchispa/innerops-agentic-platform"
WORKFORCE_REPO = "Rafa-Innerchispa/innerspark-workforce-ai"


def _registry_result(project_id: str, repo: str):
    return {
        "ok": True,
        "node": "primary",
        "project_path": f"/home/rlopez/projects/{project_id}",
        "project": {"project_id": project_id, "repo": repo},
    }


def _registry_resolver(*, project_id="", repo="", node="primary"):
    full_repo = repo or f"Rafa-Innerchispa/{project_id}"
    pid = project_id or full_repo.split("/", 1)[1]
    return _registry_result(pid, full_repo)


def _local_task(*, task_id: str, project_id: str, repo: str, title: str = "Bound development task", status: str = "proposed"):
    return {
        "task_id": task_id,
        "status": status,
        "assignee": "chatgpt",
        "priority": "p0",
        "correlation_id": f"{task_id}-corr",
        "project_id": project_id,
        "repo": repo,
        "base_ref": "main",
        "task_class": "coding",
        "execution_lane": "local_dev_swarm",
        "provider_transport": "local_vllm",
        "write_capable": True,
        "title": title,
        "checklist": ["Use the exact registered repository binding"],
    }


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

    def test_inneros_words_do_not_create_a_repo_binding(self) -> None:
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
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "execution_lane_missing")
        self.assertIsNone(repo)

    def test_explicit_repo_alone_is_not_an_executable_envelope(self) -> None:
        task = {
            "task_id": "ops_explicit_repo",
            "status": "proposed",
            "assignee": "chatgpt",
            "priority": "p0",
            "correlation_id": "brand-new-correlation",
            "repo": INNEROPS_REPO,
            "title": "Run platform tests",
        }
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "execution_lane_missing")
        self.assertEqual(repo, INNEROPS_REPO)

    def test_structured_innerops_binding_is_eligible(self) -> None:
        task = _local_task(task_id="ops_bound_innerops", project_id="innerops-agentic-platform", repo=INNEROPS_REPO)
        with mock.patch.object(scheduler.canonical_task_envelope.prr, "resolve_project", side_effect=_registry_resolver), \
             mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
            ok, reason, repo = scheduler._eligible_reason(task)
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, INNEROPS_REPO)

    def test_email_finance_whatsapp_tasks_are_filtered_before_binding(self) -> None:
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

    def test_spanish_platform_words_do_not_bypass_binding(self) -> None:
        task = {
            "task_id": "ops_spanish_repair",
            "status": "proposed",
            "assignee": "codex",
            "priority": "p0",
            "related_project": "InnerOS platform",
            "title": "Corregir scheduler y reparar verifier del Dev Swarm",
            "checklist": ["Arreglar runtime local y pruebas de regresion"],
        }
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "execution_lane_missing")
        self.assertIsNone(repo)

    def test_xprize_and_cloudflare_text_do_not_infer_repo(self) -> None:
        for task in (
            {
                "task_id": "ops_xprize_product",
                "status": "proposed",
                "assignee": "antigravity",
                "priority": "critical",
                "correlation_id": "xprize-pre-submit-hardening-20260815",
                "title": "CORRECCION P0: produccion real, no reemplazar datos DB por demos",
                "checklist": ["Repo publico cero PII", "No tocar Devpost sin validacion"],
            },
            {
                "task_id": "ops_cloudflare_hostname",
                "status": "proposed",
                "assignee": "cursor",
                "priority": "critical",
                "title": "Configurar Cloudflare workforce.pcdoctor.ai ahora",
                "checklist": ["Verifica DNS TLS y HTTP 200"],
            },
        ):
            ok, reason, repo = scheduler._eligible_reason(task)
            self.assertFalse(ok)
            self.assertEqual(reason, "execution_lane_missing")
            self.assertIsNone(repo)

    def test_workforce_femar_without_structured_binding_stays_excluded(self) -> None:
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
        self.assertEqual(reason, "execution_lane_missing")
        self.assertIsNone(repo)

    def test_structured_workforce_binding_resolves_only_to_workforce(self) -> None:
        task = _local_task(
            task_id="ops_workforce_bound",
            project_id="innerspark-workforce-ai",
            repo=WORKFORCE_REPO,
            title="Restore Jest dependencies in FEMAR",
        )
        with mock.patch.object(scheduler.canonical_task_envelope.prr, "resolve_project", side_effect=_registry_resolver), \
             mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
            ok, reason, repo = scheduler._eligible_reason(task)
        self.assertTrue(ok)
        self.assertEqual(reason, "eligible")
        self.assertEqual(repo, WORKFORCE_REPO)
        self.assertNotEqual(repo, INNEROPS_REPO)

    def test_external_ide_lane_is_not_swarm_eligible_even_with_exact_repo(self) -> None:
        task = _local_task(task_id="ops_cursor", project_id="innerops-agentic-platform", repo=INNEROPS_REPO)
        task["execution_lane"] = "cursor"
        task["provider_transport"] = "ide_inbox"
        ok, reason, repo = scheduler._eligible_reason(task)
        self.assertFalse(ok)
        self.assertEqual(reason, "execution_lane_not_local_dev_swarm")
        self.assertEqual(repo, INNEROPS_REPO)

    def test_scheduler_dry_run_selects_only_structured_local_task_when_capacity_free(self) -> None:
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

        bound = _local_task(task_id="ops_workforce_bound", project_id="innerspark-workforce-ai", repo=WORKFORCE_REPO)
        bound["created_at"] = "2026-08-26T20:00:00+00:00"
        unbound = {
            "task_id": "ops_unbound",
            "status": "proposed",
            "assignee": "codex",
            "priority": "p0",
            "created_at": "2026-08-26T19:00:00+00:00",
            "title": "InnerOS repair from prose only",
        }
        email = {
            "task_id": "ops_email",
            "status": "proposed",
            "assignee": "ralfia",
            "priority": "normal",
            "created_at": "2026-08-26T18:00:00+00:00",
            "kind": "email_ops",
            "tags": ["email"],
            "title": "Process invoice email",
        }

        class Tasks:
            rows = [bound, unbound, email]

            def find(self, query, _projection):
                rows = []
                for row in self.rows:
                    if "task_id" in query and row.get("task_id") != query["task_id"]:
                        continue
                    if "status" in query and row.get("status") != query["status"]:
                        continue
                    if "priority" in query and row.get("priority") != query["priority"]:
                        continue
                    rows.append(row)
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
             mock.patch.object(scheduler.canonical_task_envelope.prr, "resolve_project", side_effect=_registry_resolver), \
             mock.patch.object(scheduler.local_execution_plane, "repo_policy_status", return_value={"ok": True, "write_scope": "trusted"}):
            result = scheduler.scheduler_tick(limit=4, dry_run=True)
        self.assertEqual(result["available"], 4)
        self.assertEqual([row["task_id"] for row in result["selected"]], ["ops_workforce_bound"])
        self.assertEqual(result["selected"][0]["repo"], WORKFORCE_REPO)
        skipped = {row["task_id"]: row["reason"] for row in result["skipped"]}
        self.assertEqual(skipped["ops_unbound"], "execution_lane_missing")
        filtered = {row["task_id"]: row["reason"] for row in result["filtered"]}
        self.assertEqual(filtered["ops_email"], "non_development_ops_filtered")


if __name__ == "__main__":
    unittest.main()
