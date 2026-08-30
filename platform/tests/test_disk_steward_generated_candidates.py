from pathlib import Path
from unittest.mock import patch

from inneros_core_runtime import disk_steward


class FakeCollection:
    def __init__(self):
        self.docs = {}

    def update_one(self, query, update, upsert=False):
        key = query["plan_id"]
        doc = self.docs.get(key, {})
        doc.update(update.get("$set", {}))
        doc.update(update.get("$setOnInsert", {}))
        self.docs[key] = doc

        class Result:
            matched_count = 1
            modified_count = 1

        return Result()

    def find_one(self, query, projection=None):
        doc = self.docs.get(query.get("plan_id"))
        return dict(doc) if doc else None


class FakeDb(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


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


def test_plan_migration_blocks_non_allowlisted_source(tmp_path, monkeypatch):
    fake_db = FakeDb()
    src = tmp_path / "inneros" / "inneros_core" / "platform"
    src.mkdir(parents=True)
    dest = tmp_path / "archive"
    dest.mkdir()
    monkeypatch.setattr(disk_steward, "PROTECTED_PREFIXES", (str(tmp_path / "inneros"),))
    monkeypatch.setattr(disk_steward, "GENERATED_ARCHIVE_ROOTS", (tmp_path / "generated",))
    monkeypatch.setattr(disk_steward, "ALLOWED_DEST_ROOTS", (dest,))
    monkeypatch.setattr(disk_steward.mongo_store, "get_db", lambda: fake_db)

    result = disk_steward.disk_steward_plan_migration(str(src), str(dest))

    assert result["ok"] is False
    assert result["error"] == "protected_source"


def test_plan_and_execute_dry_run_for_nested_backup_root(tmp_path, monkeypatch):
    fake_db = FakeDb()
    source_root = tmp_path / "backups"
    source = source_root / "snapshot_1"
    source.mkdir(parents=True)
    (source / "data.txt").write_text("ok", encoding="utf-8")
    dest_root = tmp_path / "hdd" / "archive"
    dest_root.mkdir(parents=True)
    monkeypatch.setattr(disk_steward, "BACKUP_SCAN_DIRS", [str(source_root)])
    monkeypatch.setattr(disk_steward, "ALLOWED_DEST_ROOTS", (dest_root,))
    monkeypatch.setattr(disk_steward, "_mount_source", lambda path: "srcdev" if str(path).startswith(str(source_root)) else "destdev")
    monkeypatch.setattr(disk_steward.mongo_store, "get_db", lambda: fake_db)

    planned = disk_steward.disk_steward_plan_migration(str(source), str(dest_root), reason="test")
    executed = disk_steward.disk_steward_execute_migration(planned["plan"]["plan_id"], dry_run=True)

    assert planned["ok"] is True
    assert planned["executed"] is False
    assert planned["plan"]["source_path"] == str(source.resolve())
    assert executed["ok"] is True
    assert executed["dry_run"] is True
    assert executed["executed"] is False


def test_cleanup_requires_verified_true(tmp_path, monkeypatch):
    fake_db = FakeDb()
    monkeypatch.setattr(disk_steward.mongo_store, "get_db", lambda: fake_db)

    result = disk_steward.disk_steward_cleanup_verified("dsm_any", verified=False)

    assert result["ok"] is False
    assert result["error"] == "verified_true_required"
