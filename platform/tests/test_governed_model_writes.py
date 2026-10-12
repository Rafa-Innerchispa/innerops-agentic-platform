"""Ensure Temporal materializes only governed local-model file payloads."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inneros_core_runtime import governed_model_writes as gmw


class GovernedMaterializationTests(unittest.TestCase):
    def test_platform_prefix_rewritten_for_flat_runtime_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            (wt / "tests").mkdir()
            self.assertEqual(
                gmw._rewrite_path_for_worktree(wt, "platform/tests/example.py"),
                "tests/example.py",
            )
            self.assertEqual(
                gmw._rewrite_path_for_worktree(wt, "tests/example.py"),
                "tests/example.py",
            )

    def test_structured_candidate_invokes_allowlisted_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            (wt / "tests").mkdir()
            envelope = {
                "task_id": "ops_governed",
                "correlation_id": "corr-governed",
                "repo": "Rafa-Innerchispa/innerops-agentic-platform",
                "work_branch": "chatgpt/ops-governed",
                "objective": "Implement a tiny test marker",
            }
            payload = {"summary": "done", "files": [
                {"path": "platform/tests/test_marker.py", "content": "assert True\n"},
            ]}
            def validate(parsed, *_args, **_kwargs):
                return list(parsed["files"]), []
            with (
                patch("inneros_core_runtime.dev_swarm_scheduler._fanout_parse_model_json",
                      return_value=payload),
                patch("inneros_core_runtime.dev_swarm_scheduler._safe_generated_files",
                      side_effect=validate) as validator,
                patch("inneros_core_runtime.dev_swarm_scheduler._merge_node_scaffold",
                      side_effect=lambda **kwargs: kwargs["files"]),
                patch("inneros_core_runtime.local_execution_plane.write_file",
                      return_value={"ok": True}) as writer,
            ):
                result = gmw.apply_candidate_response(
                    envelope, wt, model_text='{"summary":"done"}',
                )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["files_touched"], ["tests/test_marker.py"])
            self.assertEqual(validator.call_args.args[0]["files"][0]["path"], "tests/test_marker.py")
            self.assertEqual(writer.call_args.kwargs["path"], "tests/test_marker.py")
            self.assertEqual(writer.call_args.kwargs["task_id"], "ops_governed")

    def test_narrative_without_file_payload_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("inneros_core_runtime.dev_swarm_scheduler._fanout_parse_model_json",
                      return_value=None),
                patch("inneros_core_runtime.dev_swarm_scheduler._safe_generated_files",
                      return_value=([], [])),
                patch("inneros_core_runtime.dev_swarm_scheduler._merge_node_scaffold",
                      return_value=[]),
                patch("inneros_core_runtime.local_execution_plane.write_file") as writer,
            ):
                result = gmw.apply_candidate_response(
                    {"task_id": "ops_narrative", "repo": "Rafa-Innerchispa/innerops-agentic-platform",
                     "work_branch": "chatgpt/narrative"},
                    Path(tmp), model_text="I've implemented all files",
                )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "model_output_non_actionable")
            writer.assert_not_called()

    def test_partial_write_is_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files = [{"path": "tests/a.py", "content": "a = 1\n"},
                     {"path": "tests/b.py", "content": "b = 2\n"}]
            with (
                patch("inneros_core_runtime.dev_swarm_scheduler._fanout_parse_model_json",
                      return_value={"files": files}),
                patch("inneros_core_runtime.dev_swarm_scheduler._safe_generated_files",
                      return_value=(files, [])),
                patch("inneros_core_runtime.dev_swarm_scheduler._merge_node_scaffold",
                      return_value=files),
                patch("inneros_core_runtime.local_execution_plane.write_file",
                      side_effect=[{"ok": True}, {"ok": False, "error": "denied"}]),
            ):
                result = gmw.apply_candidate_response(
                    {"task_id": "ops_partial", "repo": "Rafa-Innerchispa/innerops-agentic-platform",
                     "work_branch": "chatgpt/partial"}, Path(tmp),
                    model_text='{"files":[]}',
                )
            self.assertFalse(result["ok"])
            self.assertEqual(result["files_touched"], ["tests/a.py"])
            self.assertEqual(result["write_count"], 2)


if __name__ == "__main__":
    unittest.main()
