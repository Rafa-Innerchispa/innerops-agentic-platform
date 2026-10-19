from __future__ import annotations

import json
from pathlib import Path

from inneros_core_runtime import local_execution_plane as lep
from inneros_core_runtime import project_runtime_registry as prr

MC3_EXTRAS = {
    "policy_class": "product-app",
    "allowed_commands_profile": "python-tests",
    "allowed_paths": [
        "app",
        "src",
        "tests",
        "scripts",
        "docs",
        ".github",
        "README.md",
        "pyproject.toml",
        "requirements.txt",
        "Dockerfile",
        "docker-compose.yml",
    ],
    "package_roots": ["app", "."],
    "write_scope": "worktree_branch_only",
}

MC4_EXTRAS = {
    "policy_class": "product-app",
    "allowed_commands_profile": "python-tests",
    "allowed_paths": [
        "app",
        "src",
        "tests",
        "scripts",
        "docs",
        "docker",
        "tools",
        "evidence",
        "demo",
        ".github",
        "README.md",
        "pyproject.toml",
        "requirements.txt",
        ".dockerignore",
    ],
    "package_roots": ["app", "src", "."],
    "write_scope": "worktree_branch_only",
}


ACT3_EXTRAS = {
    "policy_class": "product-app",
    "allowed_commands_profile": "python-tests",
    "allowed_paths": [
        "src",
        "tests",
        "docs",
        "submission",
        "scripts",
        ".github",
        "README.md",
        "pyproject.toml",
        "requirements.txt",
        "Dockerfile",
        "docker-compose.yml",
    ],
    "package_roots": ["src", "."],
    "write_scope": "worktree_branch_only",
}


def _register_hackathon_pair(core_root: Path, *, actor: str = "pytest") -> None:
    ws = core_root / "workspaces"
    mc3 = ws / "amd-academy-mc3-rag"
    act3 = ws / "inneros-amd-act-iii"
    mc3.mkdir(parents=True, exist_ok=True)
    act3.mkdir(parents=True, exist_ok=True)
    prr.register_project(
        "amd-academy-mc3-rag",
        "Rafa-Innerchispa/amd-academy-mc3-rag",
        str(mc3),
        actor=actor,
        source="pytest",
        **MC3_EXTRAS,
    )
    prr.register_project(
        "inneros-amd-act-iii",
        "Rafa-Innerchispa/inneros-amd-act-iii",
        str(act3),
        actor=actor,
        source="pytest",
        **ACT3_EXTRAS,
    )


def test_register_amd_academy_mc3_rag(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INNEROS_CORE_ROOT", str(tmp_path))
    _register_hackathon_pair(tmp_path)

    resolved = prr.resolve_project(
        project_id="amd-academy-mc3-rag",
        repo="Rafa-Innerchispa/amd-academy-mc3-rag",
        node="amd",
    )
    assert resolved["ok"] is True
    project = resolved["project"]
    assert project["policy_class"] == "product-app"
    assert project["write_scope"] == "worktree_branch_only"
    assert project["allowed_commands_profile"] == "python-tests"
    assert project["package_roots"] == ["app", "."]
    assert "app" in project["allowed_paths"]
    assert "Dockerfile" in project["allowed_paths"]


def test_register_amd_academy_mc4_web_retrieval(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INNEROS_CORE_ROOT", str(tmp_path))
    ws = tmp_path / "workspaces"
    mc4 = ws / "amd-academy-mc4-web-retrieval"
    mc4.mkdir(parents=True, exist_ok=True)
    prr.register_project(
        "amd-academy-mc4-web-retrieval",
        "Rafa-Innerchispa/amd-academy-mc4-web-retrieval",
        str(mc4),
        actor="pytest",
        source="pytest",
        **MC4_EXTRAS,
    )

    resolved = prr.resolve_project(
        project_id="amd-academy-mc4-web-retrieval",
        repo="Rafa-Innerchispa/amd-academy-mc4-web-retrieval",
        node="amd",
    )
    assert resolved["ok"] is True
    project = resolved["project"]
    assert project["allowed_commands_profile"] == "python-tests"
    assert project["write_scope"] == "worktree_branch_only"
    assert project["package_roots"] == ["app", "src", "."]
    assert "docker" in project["allowed_paths"]
    assert "tools" in project["allowed_paths"]


def test_register_inneros_amd_act_iii(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INNEROS_CORE_ROOT", str(tmp_path))
    _register_hackathon_pair(tmp_path)

    resolved = prr.resolve_project(
        project_id="inneros-amd-act-iii",
        repo="Rafa-Innerchispa/inneros-amd-act-iii",
        node="primary",
    )
    assert resolved["ok"] is True
    project = resolved["project"]
    assert project["write_scope"] == "worktree_branch_only"
    assert project["package_roots"] == ["src", "."]
    assert "submission" in project["allowed_paths"]


def test_hackathon_projects_in_canonical_registry_json() -> None:
    root = Path(__file__).resolve().parents[2]
    registry = json.loads(
        (root / "var" / "project_runtime_registry" / "registry.json").read_text(encoding="utf-8")
    )
    mc3 = registry["projects"]["amd-academy-mc3-rag"]
    assert mc3["repo"] == "Rafa-Innerchispa/amd-academy-mc3-rag"
    assert mc3["paths"]["amd"].endswith("/workspaces/amd-academy-mc3-rag")

    mc4 = registry["projects"]["amd-academy-mc4-web-retrieval"]
    assert mc4["repo"] == "Rafa-Innerchispa/amd-academy-mc4-web-retrieval"
    assert mc4["paths"]["amd"].endswith("/workspaces/amd-academy-mc4-web-retrieval")
    assert mc4["allowed_commands_profile"] == "python-tests"

    act3 = registry["projects"]["inneros-amd-act-iii"]
    assert act3["repo"] == "Rafa-Innerchispa/inneros-amd-act-iii"
    assert act3["write_scope"] == "worktree_branch_only"


def test_dev_swarm_scope_ok_for_hackathon_repos() -> None:
    for repo in (
        "Rafa-Innerchispa/amd-academy-mc3-rag",
        "Rafa-Innerchispa/inneros-amd-act-iii",
    ):
        scope = lep.dev_swarm_scope_status(repo=repo)
        assert scope["ok"] is True, (repo, scope)
        assert scope["policy"]["ok"] is True, repo



def test_dev_swarm_scope_ok_for_mc4_registered_registry(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INNEROS_CORE_ROOT", str(tmp_path))
    ws = tmp_path / "workspaces"
    mc4 = ws / "amd-academy-mc4-web-retrieval"
    mc4.mkdir(parents=True, exist_ok=True)
    prr.register_project(
        "amd-academy-mc4-web-retrieval",
        "Rafa-Innerchispa/amd-academy-mc4-web-retrieval",
        str(mc4),
        actor="pytest",
        source="pytest",
        **MC4_EXTRAS,
    )

    scope = lep.dev_swarm_scope_status(
        repo="Rafa-Innerchispa/amd-academy-mc4-web-retrieval"
    )
    assert scope["ok"] is True, scope
    assert scope["policy"]["ok"] is True, scope
    assert scope["policy"]["policy"]["profile"] == "python-tests"
