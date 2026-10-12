from __future__ import annotations

from inneros_core_runtime import project_runtime_registry as prr


def test_migrate_existing_registers_ambient_guardian(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INNEROS_CORE_ROOT", str(tmp_path))

    result = prr.migrate_existing(actor="pytest")

    assert result["ok"] is True
    resolved = prr.resolve_project(
        project_id="ambient-guardian-amazon-2026",
        repo="Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026",
        node="primary",
    )
    assert resolved["ok"] is True
    project = resolved["project"]
    assert project["project_id"] == "ambient-guardian-amazon-2026"
    assert project["repo"] == "Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026"
    assert project["policy_class"] == "product-app"
    assert project["write_scope"] == "worktree"
    assert project["allowed_commands_profile"] == "python-tests"
    assert project["package_roots"] == ["."]
    assert "src" in project["allowed_paths"]
    assert "tests" in project["allowed_paths"]
    assert ".env" not in project["allowed_paths"]
