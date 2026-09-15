from __future__ import annotations

import unittest

from inneros_core_runtime.dev_swarm_path_guidance import (
    allowed_product_code_roots,
    product_path_instruction,
)


class DevSwarmPathGuidanceTests(unittest.TestCase):
    def test_innerops_profile_projects_only_real_product_roots(self) -> None:
        roots = allowed_product_code_roots(
            "platform",
            [
                "platform/inneros_core_runtime",
                "platform/raphiia_openai",
                "platform/tests",
                "platform/pyproject.toml",
                "README.md",
            ],
        )
        self.assertEqual(
            roots,
            ["platform/inneros_core_runtime", "platform/raphiia_openai"],
        )

    def test_instruction_never_broadens_policy(self) -> None:
        text = product_path_instruction(
            "platform",
            [
                "platform/inneros_core_runtime",
                "platform/raphiia_openai",
                "platform/tests",
            ],
        )
        self.assertIn("platform/inneros_core_runtime", text)
        self.assertIn("platform/raphiia_openai", text)
        self.assertNotIn("platform/src", text)
        self.assertNotIn("platform/tests", text)

    def test_root_level_repo_preserves_existing_product_roots(self) -> None:
        roots = allowed_product_code_roots(
            "",
            ["src", "tests", "docs", "backend", "README.md"],
        )
        self.assertEqual(roots, ["src", "backend"])


if __name__ == "__main__":
    unittest.main()
