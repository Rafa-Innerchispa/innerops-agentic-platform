import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from raphiia_openai.restore_points import build_restore_plan, create_restore_point, list_restore_points


class RestorePointTests(unittest.TestCase):
    def test_create_restore_point_copies_small_files_with_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "repo"
            base.mkdir()
            (base / "config.yaml").write_text("ok: true\n", encoding="utf-8")
            out = Path(tmp) / "restore"

            result = create_restore_point("pre deploy", roots=[base], output_root=out)

            self.assertTrue(result["ok"])
            manifest = result["restore_point"]
            self.assertEqual(manifest["type"], "release_config_checkpoint_not_backup")
            self.assertEqual(manifest["copied_count"], 1)
            self.assertEqual(manifest["files"][0]["relative_path"], "config.yaml")
            stored = Path(result["path"]) / manifest["files"][0]["stored_as"]
            self.assertEqual(stored.read_text(encoding="utf-8"), "ok: true\n")

    def test_large_files_are_hashed_but_not_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "repo"
            base.mkdir()
            (base / "large.bin").write_bytes(b"x" * 20)

            result = create_restore_point("budget", roots=[base], output_root=Path(tmp) / "restore", max_file_bytes=10)

            manifest = result["restore_point"]
            self.assertEqual(manifest["copied_count"], 0)
            self.assertEqual(manifest["skipped"][0]["reason"], "file_too_large")
            self.assertIn("sha256", manifest["skipped"][0])

    def test_list_and_restore_plan_are_approval_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "repo"
            base.mkdir()
            (base / "settings.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
            out = Path(tmp) / "restore"

            created = create_restore_point("pre change", roots=[base], output_root=out)
            point_id = created["restore_point"]["point_id"]
            listing = list_restore_points(output_root=out)
            plan = build_restore_plan(point_id, output_root=out)

            self.assertEqual(listing["restore_points"][0]["point_id"], point_id)
            self.assertTrue(plan["ok"])
            self.assertFalse(plan["execute_supported"])
            self.assertTrue(plan["actions"][0]["requires_approval"])


if __name__ == "__main__":
    unittest.main()
