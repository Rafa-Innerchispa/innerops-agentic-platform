import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
if not (ROOT / "dev_swarm_scheduler.py").exists():
    ROOT = ROOT.parent


def _source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _function_source(path: str, func_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source)
    match = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            match = ast.get_source_segment(source, node) or ""
    if match:
        return match
    raise AssertionError(f"{func_name} not found in {path}")


class DevSwarmControlPlaneTests(unittest.TestCase):
    def test_scheduler_tick_delegates_to_canonical_fanout(self):
        body = _function_source("dev_swarm_scheduler.py", "scheduler_tick")
        self.assertIn("fanout_execute(", body)
        self.assertNotIn("dev_swarm_launch_task(", body)

    def test_approve_uses_ad_hoc_control_plane(self):
        body = _function_source("mcp_server.py", "approve_and_develop_project")
        self.assertIn("execute_ad_hoc_objective(", body)
        self.assertIn("project_runtime_registry.resolve_project(", body)
        self.assertNotIn("dev_swarm_launch_task(", body)
        self.assertNotIn('or "Rafa-Innerchispa/innerops-agentic-platform"', body)

    def test_ag45_fanout_has_no_per_lane_legacy_launcher(self):
        body = _function_source("pool_agent_runners.py", "run_ag45")
        self.assertIn("fanout_execute(", body)
        self.assertNotIn("ThreadPoolExecutor", body)
        self.assertNotIn("dev_swarm_launch_task(", body)

    def test_legacy_launcher_no_checkout_pull_prepare_repo(self):
        body = _function_source("local_execution_plane.py", "dev_swarm_launch_task")
        self.assertNotIn("prepare_repo(", body)
        self.assertNotIn('["git", "checkout"', body)
        self.assertNotIn('["git", "pull"', body)
        self.assertIn('"checkout_or_pull": False', body)

    def test_capacity_governor_surface_exists(self):
        scheduler = _source("dev_swarm_scheduler.py")
        mcp = _source("mcp_server.py")
        self.assertIn("def capacity_status(", scheduler)
        self.assertIn("def sample_capacity(", scheduler)
        self.assertIn("def dev_swarm_capacity_status(", mcp)
        self.assertIn("def dev_swarm_capacity_tick(", mcp)

    def test_node_frontend_without_package_gets_scaffold_and_npm_test(self):
        from inneros_core_runtime import dev_swarm_scheduler as scheduler

        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            (worktree / "src").mkdir()
            (worktree / "tests").mkdir()
            (worktree / "src" / "App.tsx").write_text("export default function App() { return null; }\n", encoding="utf-8")
            (worktree / "tests" / "App.test.tsx").write_text("export const smoke = true;\n", encoding="utf-8")
            generated = [
                {"path": "src/App.tsx", "content": "export default function App() { return null; }\n"},
                {"path": "tests/App.test.tsx", "content": "export const smoke = true;\n"},
            ]
            files = scheduler._merge_node_scaffold(
                objective="Build a React TypeScript frontend in src/App.tsx",
                task_id="ops_fixture_node",
                worktree=worktree,
                files=generated,
            )
            by_path = {item["path"]: item["content"] for item in files}
            self.assertIn("package.json", by_path)
            self.assertIn("tests/scaffold.test.mjs", by_path)
            for rel, content in by_path.items():
                target = worktree / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            package = json.loads((worktree / "package.json").read_text(encoding="utf-8"))
            self.assertEqual(package["scripts"]["test"], "node tests/scaffold.test.mjs")
            self.assertEqual(scheduler._test_commands_for_policy("fixture/repo", worktree, sorted(by_path)), [["git", "diff", "--check"], ["npm", "test"]])

    def test_js_markers_without_package_do_not_fall_back_to_python_unittest(self):
        from inneros_core_runtime import dev_swarm_scheduler as scheduler

        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            (worktree / "src").mkdir()
            (worktree / "tests").mkdir()
            (worktree / "src" / "Dashboard.tsx").write_text("export const Dashboard = () => null;\n", encoding="utf-8")
            (worktree / "tests" / "Dashboard.test.tsx").write_text("export const smoke = true;\n", encoding="utf-8")
            commands = scheduler._test_commands_for_policy(
                "fixture/repo",
                worktree,
                ["src/Dashboard.tsx", "tests/Dashboard.test.tsx"],
            )
            self.assertEqual(commands, [["git", "diff", "--check"]])
            self.assertFalse(any(command[:3] == ["python3", "-m", "unittest"] for command in commands))

    def test_executor_records_use_single_v10_version(self):
        source = _source("dev_swarm_scheduler.py")
        self.assertIn('EXECUTOR_VERSION = "autonomous_impl_v10_a2a_liveness"', source)
        self.assertNotIn("autonomous_impl_v4", source)
        self.assertIn("command_not_allowlisted_non_retryable", source)

    def test_project_runtime_missing_project_fails_actionable(self):
        from inneros_core_runtime import project_runtime_registry as registry

        with patch.object(registry, "_load", return_value={"version": registry.REGISTRY_VERSION, "projects": {}}):
            result = registry.resolve_project(project_id="missing-project", repo="", node="primary")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "project_not_registered")

    def test_approve_project_resolves_workforce_and_other_project(self):
        from inneros_core_runtime import dev_swarm_scheduler as scheduler
        from inneros_core_runtime import mcp_server

        calls = []

        def fake_resolve(project_id="", repo="", node="primary"):
            calls.append({"project_id": project_id, "repo": repo, "node": node})
            pid = project_id or repo.split("/", 1)[1]
            return {
                "ok": True,
                "node": "amd",
                "project_path": f"/home/rlopez/inneros/inneros_core/workspaces/{pid}",
                "project": {"project_id": pid, "repo": f"Rafa-Innerchispa/{pid}"},
            }

        def fake_policy(repo):
            return {"ok": True, "write_scope": "worktree", "policy": {"profile": "node-tests"}}

        def fake_execute(repo, objective, task_id, correlation_id, preferred_branch, entrypoint, dry_run):
            return {
                "ok": True,
                "repo": repo,
                "task_id": task_id,
                "branch": preferred_branch,
                "executor_version": scheduler.EXECUTOR_VERSION,
                "worker": {"executor": {"version": scheduler.EXECUTOR_VERSION}},
            }

        with patch.object(mcp_server, "get_project_reuse_analysis", return_value={"ok": False}), \
            patch.object(mcp_server.project_runtime_registry, "resolve_project", side_effect=fake_resolve), \
            patch.object(mcp_server.local_execution_plane, "repo_policy_status", side_effect=fake_policy), \
            patch.object(mcp_server.dev_swarm_scheduler, "execute_ad_hoc_objective", side_effect=fake_execute):
            workforce = mcp_server.approve_and_develop_project("innerspark-workforce-ai", "Build a React TypeScript test fixture")
            other = mcp_server.approve_and_develop_project("cozmo-alive", "Build a small Node test fixture")

        self.assertTrue(workforce["ok"])
        self.assertEqual(workforce["repo"], "Rafa-Innerchispa/innerspark-workforce-ai")
        self.assertTrue(other["ok"])
        self.assertEqual(other["repo"], "Rafa-Innerchispa/cozmo-alive")
        self.assertEqual(calls[0]["project_id"], "innerspark-workforce-ai")
        self.assertEqual(calls[1]["project_id"], "cozmo-alive")


    def test_existing_worktree_must_match_base_sha(self):
        from inneros_core_runtime import dev_swarm_scheduler as scheduler

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            worktrees = Path(tmp) / "worktrees"
            branch = "local-agent/ops_sha_guard"
            worktree = worktrees / branch.replace("/", "__")
            source.mkdir()
            worktree.mkdir(parents=True)

            def fake_run(command, cwd, timeout_seconds=30):
                if command[:2] == ["git", "status"]:
                    return {"ok": True, "stdout": "## local-agent/ops_sha_guard\n"}
                if command[:2] == ["git", "rev-parse"]:
                    return {"ok": True, "stdout": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"}
                raise AssertionError(command)

            with patch.object(scheduler.local_execution_plane, "_run", side_effect=fake_run), \
                patch.object(scheduler.local_execution_plane, "report_evidence", return_value={"ok": True}):
                result = scheduler._fanout_create_worktree_from_base(
                    repo=scheduler.SAFE_INNEROS_REPO,
                    branch=branch,
                    base_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    task_id="ops_sha_guard",
                    correlation_id="sha-guard",
                    objective="Repair scheduler",
                    base_snapshot={
                        "source_path": str(source),
                        "worktrees_path": str(worktrees),
                        "requested_base_ref": "main",
                        "resolved_base_ref": "origin/main",
                        "base_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    },
                )

            self.assertFalse(result["ok"])
            self.assertEqual(result["worktree"]["error"], "worktree_base_sha_mismatch")
            self.assertTrue(result["evidence"]["ok"])


    def test_gitlab_reported_paths_must_exist_and_match_policy(self):
        from inneros_core_runtime import dev_swarm_scheduler as scheduler

        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            valid = worktree / "commands" / "helpers" / "cache_archiver.go"
            valid.parent.mkdir(parents=True)
            valid.write_text("package helpers\n", encoding="utf-8")
            allowed = [
                "commands/helpers/cache_archiver.go",
                "commands/helpers/cache_archiver_test.go",
                "commands/helpers/cache_extractor.go",
                "commands/helpers/cache_extractor_test.go",
                "commands/helpers/retry_helper.go",
                "commands/helpers/retry_helper_test.go",
            ]

            with patch.object(scheduler.local_execution_plane, "_repo_config", return_value={"allowed_paths": allowed, "package_roots": ["."]}):
                result = scheduler._verified_write_classes(
                    "gitlab-community/gitlab-org/gitlab-runner",
                    worktree,
                    ["commands/helpers/cache_archiver.go", "src/go.mod", "src/internal/cache/cache.go"],
                )

            self.assertFalse(result["ok"])
            self.assertEqual(result["classes"]["product"], ["commands/helpers/cache_archiver.go"])
            rejected = {item["path"]: item["reason"] for item in result["invalid_files"]}
            self.assertEqual(rejected["src/go.mod"], "path_not_allowed_for_repo_profile")
            self.assertEqual(rejected["src/internal/cache/cache.go"], "path_not_allowed_for_repo_profile")

    def test_worker_repo_falls_back_to_launch_plan(self):
        from inneros_core_runtime import dev_swarm_scheduler as scheduler

        worker = {
            "task_id": "ops_launch_repo_only",
            "launch": {
                "plan": {"repo": "Rafa-Innerchispa/innerspark-workforce-ai"},
                "prepared": {"repo": "wrong/fallback"},
            },
        }

        self.assertEqual(scheduler._worker_repo(worker), "Rafa-Innerchispa/innerspark-workforce-ai")

    def test_fanout_does_not_duplicate_still_running_worker(self):
        from inneros_core_runtime import dev_swarm_scheduler as scheduler

        existing = {
            "worker_id": "worker_existing",
            "task_id": "ops_running",
            "repo": "gitlab-community/gitlab-org/gitlab-runner",
            "branch": "chatgpt/fix/running",
            "status": "running",
            "launch": {"worktree": {"worktree": "/tmp/worktree"}},
            "executor": {"status": "running", "phase": "inference"},
        }

        with (
            patch.object(scheduler, "_active_worker_for_task", return_value=existing),
            patch.object(scheduler, "_task_doc", side_effect=AssertionError("must not reload task")),
        ):
            result = scheduler._fanout_execute_one("gitlab-community/gitlab-org/gitlab-runner", "ops_running")

        self.assertTrue(result["ok"])
        self.assertEqual(result["outcome"], "ALREADY_RUNNING")
        self.assertEqual(result["worker_id"], "worker_existing")
        self.assertEqual(result["worktree"], "/tmp/worktree")

    def test_stale_worker_reclaim_marks_retryable_then_exhausted(self):
        from inneros_core_runtime import dev_swarm_scheduler as scheduler

        class Collection:
            def __init__(self):
                self.updates = []
            def update_one(self, query, update, upsert=False):
                self.updates.append((query, update, upsert))
                class Result:
                    modified_count = 1
                return Result()

        class Db(dict):
            def __getitem__(self, key):
                self.setdefault(key, Collection())
                return dict.__getitem__(self, key)

        db = Db()
        retry = scheduler._reclaim_stale_workers(
            db,
            [{"task_id": "ops_retry", "executor": {"stale_reclaim_count": 0}}],
            "2026-08-26T00:00:00+00:00",
            "unit_test",
        )
        exhausted = scheduler._reclaim_stale_workers(
            db,
            [{"task_id": "ops_done", "executor": {"stale_reclaim_count": scheduler.MAX_STALE_RECLAIMS}}],
            "2026-08-26T00:01:00+00:00",
            "unit_test",
        )
        self.assertEqual(retry, {"retriable": 1, "exhausted": 0})
        self.assertEqual(exhausted, {"retriable": 0, "exhausted": 1})
        worker_updates = db[scheduler.WORKERS_COL].updates
        self.assertEqual(worker_updates[0][1]["$set"]["executor.status"], "failed_retryable")
        self.assertEqual(worker_updates[1][1]["$set"]["executor.status"], "blocked")
        self.assertEqual(worker_updates[1][1]["$set"]["blocker"], "stale_worker_retry_budget_exhausted")


if __name__ == "__main__":
    unittest.main()
