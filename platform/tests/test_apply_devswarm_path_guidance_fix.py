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
    def test_patch_applies_to_current_scheduler_and_is_idempotent(self) -> None:
        patcher = _load_patcher()
        source = SCHEDULER.read_text(encoding="utf-8")

        patched, changed = patcher.patch_scheduler_source(source)
        self.assertTrue(changed)
        self.assertIn("dev_swarm_path_guidance", patched)
        self.assertIn("allowed_paths = _repo_allowed_paths(repo) or [product_root]", patched)
        self.assertIn("instructions.append(_policy_product_path_instruction(repo, product_root))", patched)
        self.assertIn("repo-policy product root listed above", patched)
        self.assertNotIn(
            "Use paths under {product_root}/src, {product_root}/app",
            patched,
        )

        patched_again, changed_again = patcher.patch_scheduler_source(patched)
        self.assertFalse(changed_again)
        self.assertEqual(patched_again, patched)

    def test_source_drift_fails_closed(self) -> None:
        patcher = _load_patcher()
        source = SCHEDULER.read_text(encoding="utf-8")
        source = source.replace(
            "local_execution_plane._validate_relative_path(normalized, [product_root])",
            "local_execution_plane._validate_relative_path(normalized, ['unexpected'])",
            1,
        )
        with self.assertRaisesRegex(RuntimeError, "source_drift:normalize_policy"):
            patcher.patch_scheduler_source(source)


if __name__ == "__main__":
    unittest.main()
