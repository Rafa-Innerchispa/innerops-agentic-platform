from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
SCHEDULER_PATH = PLATFORM_ROOT / "inneros_core_runtime" / "dev_swarm_scheduler.py"
_SPEC = importlib.util.spec_from_file_location("worktree_dev_swarm_scheduler_stream_recovery", SCHEDULER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
scheduler = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scheduler)


class DevSwarmStreamRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = {
            "summary": "implemented",
            "files": [
                {
                    "path": "platform/inneros_core_runtime/example.py",
                    "content": "VALUE = 1\n",
                }
            ],
        }
        self.raw = json.dumps(self.payload)

    def test_imports_scheduler_from_this_worktree(self) -> None:
        self.assertEqual(Path(scheduler.__file__).resolve(), SCHEDULER_PATH.resolve())

    def test_parse_pure_json_object(self) -> None:
        self.assertEqual(scheduler._fanout_parse_model_json(self.raw), self.payload)

    def test_parse_fenced_json_object(self) -> None:
        wrapped = f"```json\n{self.raw}\n```"
        self.assertEqual(scheduler._fanout_parse_model_json(wrapped), self.payload)

    def test_parse_complete_object_before_truncated_stream_suffix(self) -> None:
        wrapped = f"implementation follows\n{self.raw}\nnext chunk {{\"partial\":"
        self.assertEqual(scheduler._fanout_parse_model_json(wrapped), self.payload)

    def test_parse_sse_data_object(self) -> None:
        wrapped = f"data: {self.raw}\ndata: [DONE]"
        self.assertEqual(scheduler._fanout_parse_model_json(wrapped), self.payload)

    def test_truly_truncated_json_is_not_invented(self) -> None:
        self.assertIsNone(
            scheduler._fanout_parse_model_json('{"summary":"broken","files":[')
        )

    def test_amd_unreachable_is_transport_failure_not_json_failure(self) -> None:
        failure = scheduler._local_model_failure(
            {
                "ok": False,
                "error": "amd_vllm_unreachable_from_intel",
                "provider_id": "local-amd-5",
                "selected_node": "amd",
                "selected_model": "Qwen3-Coder",
            }
        )
        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual(failure["kind"], "transport")
        self.assertEqual(failure["error"], "amd_vllm_unreachable_from_intel")
        self.assertEqual(failure["provider_id"], "local-amd-5")

    def test_provider_failure_is_separate_from_transport(self) -> None:
        failure = scheduler._local_model_failure(
            {"ok": False, "error": "model_not_found", "provider_id": "local-amd-5"}
        )
        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual(failure["kind"], "provider")

    def test_successful_model_has_no_failure_classification(self) -> None:
        self.assertIsNone(scheduler._local_model_failure({"ok": True}))

    def test_real_product_write_gate_remains_required(self) -> None:
        gate = scheduler._quality_gate_guidance(
            repo=scheduler.SAFE_INNEROS_REPO,
            product_root="platform",
            rejected_files=[],
            write_classes={"product": [], "diagnostic": ["platform/tests/probe.py"]},
        )
        self.assertTrue(
            any("product-code write" in item for item in gate["repair_instructions"])
        )


if __name__ == "__main__":
    unittest.main()
