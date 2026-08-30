from pathlib import Path
from unittest.mock import patch

from inneros_core_runtime import disk_steward


def test_generated_worktree_candidate_can_bypass_inneros_protected_prefix(tmp_path, monkeypatch):
    generated_root = tmp_path / "inneros" / "inneros_core" / "var" / "local_execution" / "worktrees"
    candidate = generated_root / "repo__task"
    candidate.mkdir(parents=True)
    (candidate / "blob.bin").write_bytes(b"x" * 1024)
    monkeypatch.setattr(disk_steward, "GENERATED_ARCHIVE_ROOTS", (generated_root,))
    monkeypatch.setattr(disk_steward, "GENERATED_ARCHIVE_MIN_GB", 0.0)
    monkeypatch.setattr(disk_steward, "GENERATED_ARCHIVE_MIN_AGE_HOURS", 0.0)
    monkeypatch.setattr(disk_steward, "PROTECTED_PREFIXES", (str(tmp_path / "inneros"),))

    rows = disk_steward._generated_dir_candidates()

    assert rows
    assert rows[0]["op"] == "archive_dir"
    assert rows[0]["src"] == str(candidate)
    assert disk_steward._is_generated_archive_candidate(candidate)


def test_non_allowlisted_directory_remains_protected(tmp_path, monkeypatch):
    src = tmp_path / "inneros" / "inneros_core" / "platform"
    src.mkdir(parents=True)
    monkeypatch.setattr(disk_steward, "GENERATED_ARCHIVE_ROOTS", (tmp_path / "other",))
    monkeypatch.setattr(disk_steward, "PROTECTED_PREFIXES", (str(tmp_path / "inneros"),))

    assert not disk_steward._is_generated_archive_candidate(src)
