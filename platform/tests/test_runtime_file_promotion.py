from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime import runtime_file_promotion as promotion


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RuntimeFilePromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace_platform = self.root / "workspace" / "platform"
        self.active_root = self.root / "active" / "platform"
        self.backup_root = self.root / "backups"
        self.rel = Path("inneros_core_runtime/local_execution_plane.py")
        self.source = self.workspace_platform / self.rel
        self.target = self.active_root / self.rel
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_bytes(b"new-runtime\n")
        self.target.write_bytes(b"old-runtime\n")

        self.patch_active = mock.patch.object(promotion, "ACTIVE_ROOT", self.active_root)
        self.patch_backup = mock.patch.object(promotion, "BACKUP_ROOT", self.backup_root)
        self.patch_workspace = mock.patch.object(
            promotion,
            "_workspace_platform_root",
            return_value=self.workspace_platform,
        )
        self.patch_approval = mock.patch.object(
            promotion.local_execution_plane,
            "validate_host_approval",
            return_value={"ok": True},
        )
        self.patch_audit = mock.patch.object(promotion, "_audit")
        for patcher in (
            self.patch_active,
            self.patch_backup,
            self.patch_workspace,
            self.patch_approval,
            self.patch_audit,
        ):
            patcher.start()

    def tearDown(self) -> None:
        for patcher in (
            self.patch_audit,
            self.patch_approval,
            self.patch_workspace,
            self.patch_backup,
            self.patch_active,
        ):
            patcher.stop()
        self.tmp.cleanup()

    def args(self) -> dict[str, str]:
        return {
            "project_id": promotion.PLATFORM_PROJECT_ID,
            "repo": promotion.PLATFORM_REPO,
            "relative_path": self.rel.as_posix(),
            "node": "primary",
        }

    def apply_args(self) -> dict[str, str]:
        return {
            **self.args(),
            "expected_source_sha256": digest(self.source),
            "expected_target_sha256": digest(self.target),
            "approval_id": "hostap_test",
            "actor": "chatgpt",
            "task_id": "ops_test",
            "correlation_id": "corr_test",
        }

    def test_plan_reports_hashes_without_content(self) -> None:
        result = promotion.plan_promotion(**self.args())

        self.assertTrue(result["ok"])
        self.assertTrue(result["would_change"])
        self.assertEqual(result["source_sha256"], digest(self.source))
        self.assertEqual(result["target_sha256"], digest(self.target))
        self.assertNotIn("content", result)

    def test_apply_creates_backup_and_atomically_replaces_target(self) -> None:
        old_hash = digest(self.target)
        result = promotion.apply_promotion(**self.apply_args(), dry_run=False)

        self.assertTrue(result["ok"])
        self.assertEqual(self.target.read_bytes(), b"new-runtime\n")
        self.assertEqual(result["target_sha256"], digest(self.source))
        backup = Path(result["backup_path"])
        self.assertTrue(backup.is_file())
        self.assertEqual(digest(backup), old_hash)

    def test_stale_target_hash_blocks_without_mutation(self) -> None:
        args = self.apply_args()
        args["expected_target_sha256"] = "0" * 64

        result = promotion.apply_promotion(**args, dry_run=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "target_hash_mismatch")
        self.assertEqual(self.target.read_bytes(), b"old-runtime\n")
        self.assertFalse(self.backup_root.exists())

    def test_rollback_restores_backup(self) -> None:
        applied = promotion.apply_promotion(**self.apply_args(), dry_run=False)
        self.assertTrue(applied["ok"])

        rollback = promotion.rollback_promotion(
            project_id=promotion.PLATFORM_PROJECT_ID,
            repo=promotion.PLATFORM_REPO,
            relative_path=self.rel.as_posix(),
            backup_path=applied["backup_path"],
            expected_current_sha256=applied["target_sha256"],
            expected_backup_sha256=applied["backup_sha256"],
            approval_id="hostap_test",
            actor="chatgpt",
            task_id="ops_test",
            correlation_id="corr_test",
            node="primary",
            dry_run=False,
        )

        self.assertTrue(rollback["ok"])
        self.assertEqual(self.target.read_bytes(), b"old-runtime\n")

    def test_rejects_non_runtime_paths(self) -> None:
        result = promotion.plan_promotion(
            project_id=promotion.PLATFORM_PROJECT_ID,
            repo=promotion.PLATFORM_REPO,
            relative_path="README.md",
            node="primary",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "relative_path_not_allowlisted")


if __name__ == "__main__":
    unittest.main()
