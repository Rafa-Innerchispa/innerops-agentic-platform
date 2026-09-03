import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# The live service exports PYTHONPATH to the canonical runtime. Tests for this
# isolated worktree must put the worktree platform first or they silently test
# production instead of the branch under review.
PLATFORM_ROOT = Path(__file__).resolve().parents[2]
for name in list(sys.modules):
    if name == "inneros_core_runtime" or name.startswith("inneros_core_runtime.") or name == "raphiia_openai" or name.startswith("raphiia_openai."):
        sys.modules.pop(name, None)
sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import external_repair_agent as ext


class StandingOwnerAuthorizationTests(unittest.TestCase):
    def test_codex_budget_threshold_is_observe_only(self):
        with patch.object(ext, "external_credit_status", return_value={
            "ok": True,
            "providers": [{"provider": "codex", "hard_blocked": True}],
        }):
            result = ext._budget_allows("codex")
        self.assertTrue(result["ok"])
        self.assertEqual(result["enforcement"], "observe_only")
        self.assertTrue(result["threshold_exceeded"])

    def test_codex_dev_admission_does_not_require_approval_id(self):
        with patch.object(ext, "detect_provider", return_value={"ok": True, "provider": "codex", "status": "ready"}), \
            patch.object(ext, "_budget_allows", return_value={"ok": True, "credit": {}, "enforcement": "observe_only", "threshold_exceeded": False}), \
            patch.object(ext, "_standing_owner_authorization", return_value={"ok": True, "authorization_mode": "standing_owner", "repo": "Rafa-Innerchispa/inneros-webmcp"}), \
            patch.object(ext, "record_external_repair_run", return_value={"ok": True, "run": {"outcome": "admitted_not_executed_by_mcp"}}):
            result = ext.external_repair_agent_run_task("codex", "ops_fixture", dry_run=False)
        self.assertTrue(result["ok"])

    def test_unbound_development_task_is_rejected(self):
        with patch.object(ext, "detect_provider", return_value={"ok": True, "provider": "codex", "status": "ready"}), \
            patch.object(ext, "_budget_allows", return_value={"ok": True, "credit": {}, "enforcement": "observe_only", "threshold_exceeded": False}), \
            patch.object(ext, "_standing_owner_authorization", return_value={"ok": False, "error": "verified_repo_binding_required"}):
            result = ext.external_repair_agent_run_task("codex", "ops_fixture", dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "verified_repo_binding_required")

    def test_cloud_mutation_still_requires_per_run_approval(self):
        with patch.object(ext, "detect_provider", return_value={"ok": True, "provider": "digitalocean-amd-cloud", "status": "ready"}), \
            patch.object(ext, "_budget_allows", return_value={"ok": True, "credit": {}}):
            result = ext.external_repair_agent_run_task("digitalocean-amd-cloud", "ops_fixture", dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "external_spend_approval_required")

    def test_policy_rejects_cloud_provider_as_standing_development_provider(self):
        result = ext.external_provider_execution_policy_set(providers=["codex", "digitalocean-amd-cloud"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "development_provider_not_supported")


if __name__ == "__main__":
    unittest.main()
