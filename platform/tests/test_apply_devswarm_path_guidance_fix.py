from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "apply_devswarm_path_guidance_fix.py"
SCHEDULER = ROOT / "platform" / "inneros_core_runtime" / "dev_swarm_scheduler.py"


def _load_patcher():
    spec = importlib.util.spec_from_file_location("apply_devswarm_path_guidance_fix", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("patcher_import_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ApplyDevSwarmPathGuidanceFixTests(unittest.TestCase):
    def test_current_scheduler_converges_to_policy_aware_form(self) -> None:
        patcher = _load_patcher()
        source = SCHEDULER.read_text(encoding="utf-8")

        candidate, _changed = patcher.patch_scheduler_source(source)
        self.assertIn("dev_swarm_path_guidance", candidate)
        self.assertIn("allowed_paths = _repo_allowed_paths(repo) or [product_root]", candidate)
        self.assertIn("instructions.append(_policy_product_path_instruction(repo, product_root))", candidate)
        self.assertIn("repo-policy product root listed above", candidate)
        self.assertNotIn(
            "Use paths under {product_root}/src, {product_root}/app",
            candidate,
        )

        candidate_again, changed_again = patcher.patch_scheduler_source(candidate)
        self.assertFalse(changed_again)
        self.assertEqual(candidate_again, candidate)

    def test_replace_once_fails_closed_on_source_drift(self) -> None:
        patcher = _load_patcher()
        with self.assertRaisesRegex(RuntimeError, "source_drift:probe"):
            patcher._replace_once("alpha", "missing", "replacement", "probe")


if __name__ == "__main__":
    unittest.main()
