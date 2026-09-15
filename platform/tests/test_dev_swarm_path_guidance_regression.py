from __future__ import annotations

import unittest
from unittest import mock

from raphiia_openai import dev_swarm_scheduler as scheduler


class DevSwarmPathGuidanceRegressionTests(unittest.TestCase):
    def test_innerops_guidance_uses_real_allowed_product_roots(self) -> None:
        profile = {
            "allowed_paths": [
                "platform/inneros_core_runtime",
                "platform/raphiia_openai",
                "platform/tests",
                "README.md",
            ]
        }
        with mock.patch.object(scheduler.local_execution_plane, "_repo_config", return_value=profile):
            gate = scheduler._quality_gate_guidance(
                repo=scheduler.SAFE_INNEROS_REPO,
                product_root="platform",
                rejected_files=[{"reason": "path_not_allowed_for_repo_profile"}],
                write_classes={"product": [], "diagnostic": []},
            )

        guidance = " ".join(gate["repair_instructions"])
        self.assertIn("platform/inneros_core_runtime", guidance)
        self.assertIn("platform/raphiia_openai", guidance)
        self.assertNotIn("platform/src", guidance)

    def test_tests_are_not_presented_as_product_code_roots(self) -> None:
        profile = {
            "allowed_paths": [
                "platform/inneros_core_runtime",
                "platform/raphiia_openai",
                "platform/tests",
            ]
        }
        with mock.patch.object(scheduler.local_execution_plane, "_repo_config", return_value=profile):
            gate = scheduler._quality_gate_guidance(
                repo=scheduler.SAFE_INNEROS_REPO,
                product_root="platform",
                rejected_files=[{"reason": "path_not_allowed_for_repo_profile"}],
                write_classes={"product": [], "diagnostic": []},
            )

        guidance = " ".join(gate["repair_instructions"])
        self.assertNotIn("platform/tests", guidance)
        self.assertIn("product-code write", guidance)


if __name__ == "__main__":
    unittest.main()
