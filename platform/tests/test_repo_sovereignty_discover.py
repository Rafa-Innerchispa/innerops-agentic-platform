import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repo_sovereignty_discover.py"
spec = importlib.util.spec_from_file_location("repo_sovereignty_discover", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_equal():
    assert mod.decide_branch_state("a","a",False,False) == "equal"


def test_create_missing_gitlab_branch():
    assert mod.decide_branch_state("a","",False,False) == "create"


def test_fast_forward_gitlab_behind():
    assert mod.decide_branch_state("new","old",True,False) == "fast_forward"


def test_preserve_gitlab_ahead():
    assert mod.decide_branch_state("old","new",False,True) == "gitlab_ahead_preserved"


def test_preserve_true_divergence():
    assert mod.decide_branch_state("left","right",False,False) == "diverged_preserved"


def test_missing_source_is_failure():
    assert mod.decide_branch_state("","right",False,True) == "source_missing"


def test_large_repo_list_json_is_not_truncated_before_parse():
    rows = [
        {
            "name": f"repo-{i:03d}",
            "nameWithOwner": f"Rafa-Innerchispa/repo-{i:03d}",
            "isPrivate": False,
            "url": f"https://github.com/Rafa-Innerchispa/repo-{i:03d}",
            "defaultBranchRef": {"name": "main"},
        }
        for i in range(300)
    ]
    raw = __import__("json").dumps(rows)
    assert len(raw.encode("utf-8")) > 12000
    parsed = mod.parse_repo_list_json(raw)
    assert len(parsed) == 300
    assert parsed[-1]["name"] == "repo-299"
