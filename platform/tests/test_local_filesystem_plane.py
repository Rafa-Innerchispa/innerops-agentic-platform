from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from raphiia_openai import local_filesystem_plane as fs


class LocalFilesystemPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(
            os.environ,
            {"RALFIA_FS_ROOTS_JSON": f'["{self.root}"]', "RALFIA_FS_DISABLE_AUDIT": "1"},
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_write_and_read_under_trusted_root(self) -> None:
        target = self.root / "inneros3" / "README.md"

        written = fs.write_file(str(target), "hello\n", "chatgpt", "ops_test", "corr_test", mode="create")
        self.assertTrue(written["ok"])

        read = fs.read_file(str(target))
        self.assertTrue(read["ok"])
        self.assertEqual(read["content"], "hello\n")

    def test_denies_outside_trusted_root(self) -> None:
        result = fs.write_file("/etc/ralfia-test.txt", "nope\n", "chatgpt", "ops_test", "corr_test")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "path_outside_trusted_roots")

    def test_denies_sensitive_path(self) -> None:
        result = fs.write_file(str(self.root / ".ssh" / "config"), "nope\n", "chatgpt", "ops_test", "corr_test")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "sensitive_path_denied")

    def test_denies_secret_content(self) -> None:
        result = fs.write_file(str(self.root / "note.txt"), "api_key=abcdef123456\n", "chatgpt", "ops_test", "corr_test")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "secret_content_denied")

    def test_quarantine_is_reversible(self) -> None:
        quarantine = self.root / "quarantine"
        target = self.root / "old.txt"
        target.write_text("old\n", encoding="utf-8")

        with mock.patch.object(fs, "QUARANTINE_ROOT", quarantine):
            moved = fs.move_to_quarantine(str(target), "chatgpt", "ops_test", "corr_test", "cleanup")

        self.assertTrue(moved["ok"])
        self.assertFalse(target.exists())
        self.assertTrue(Path(moved["quarantine_path"]).exists())
        self.assertIn("rollback", moved)

    def test_git_init_repo(self) -> None:
        target = self.root / "new-repo"

        result = fs.git_init_repo(str(target), "chatgpt", "ops_test", "corr_test")
        self.assertTrue(result["ok"])
        self.assertTrue((target / ".git").exists())


if __name__ == "__main__":
    unittest.main()
