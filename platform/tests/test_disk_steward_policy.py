import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from raphiia_openai import disk_steward


class DiskStewardPolicyTests(unittest.TestCase):
    def test_mount_for_path_prefers_longest_mount(self):
        mounts = [
            {"mount": "/", "is_primary": True},
            {"mount": "/mnt/datos_agentes", "is_primary": True},
        ]

        match = disk_steward._mount_for_path("/mnt/datos_agentes/backups/off-root", mounts)

        self.assertEqual(match["mount"], "/mnt/datos_agentes")

    def test_large_backup_tree_on_primary_mount_is_critical(self):
        mounts = [
            {"mount": "/", "is_primary": True, "free_pct": 55},
            {"mount": "/mnt/datos_agentes", "is_primary": True, "free_pct": 17.5},
        ]
        backups = [{"path": "/mnt/datos_agentes/backups/off-root", "size_gb": 649}]

        issues = disk_steward.scan_backup_placement(mounts, backups)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["level"], "critical")
        self.assertEqual(issues[0]["required_action"], "second_gate_review_before_move_or_delete")

    def test_archive_mount_backup_does_not_raise_placement_issue(self):
        mounts = [{"mount": "/home/rlopez/data", "is_primary": True, "free_pct": 60}]
        backups = [{"path": "/home/rlopez/data/backups/qdrant_sync", "size_gb": 400}]

        issues = disk_steward.scan_backup_placement(mounts, backups)

        self.assertEqual(issues, [])

    def test_alert_dedup_suppresses_same_signature_inside_window(self):
        status = {
            "overall": "critical",
            "primary_worst": {"mount": "/mnt/datos_agentes", "level": "critical", "free_pct": 17.5},
            "backup_placement_issues": [
                {"level": "critical", "path": "/mnt/datos_agentes/backups/off-root", "size_gb": 649}
            ],
        }
        state = {
            "last_alert": {
                "signature": disk_steward._alert_signature(status),
                "at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            }
        }

        self.assertFalse(disk_steward._should_emit_alert(status, state))

    def test_alert_dedup_allows_changed_signature(self):
        old_status = {
            "overall": "warning",
            "primary_worst": {"mount": "/", "level": "warning", "free_pct": 25},
            "backup_placement_issues": [],
        }
        new_status = {
            "overall": "critical",
            "primary_worst": {"mount": "/mnt/datos_agentes", "level": "critical", "free_pct": 17.5},
            "backup_placement_issues": [],
        }
        state = {"last_alert": {"signature": disk_steward._alert_signature(old_status), "at": datetime.now(timezone.utc).isoformat()}}

        self.assertTrue(disk_steward._should_emit_alert(new_status, state))


if __name__ == "__main__":
    unittest.main()
