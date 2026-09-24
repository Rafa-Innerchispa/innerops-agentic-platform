import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repo_sovereignty_health_check.py"
spec = importlib.util.spec_from_file_location("repo_sovereignty_health_check", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def healthy_catalog():
    return {
        "repository_count": 55,
        "generated_at": "2026-09-24T00:00:00+00:00",
        "needs_review": [],
        "blocked": [],
        "unclassified": [],
    }


def healthy_discovery():
    return {
        "ok": True,
        "count": 55,
        "timestamp": "2026-09-24T00:00:00+00:00",
        "failures": [],
        "rows": [
            {
                "repo": "Rafa-Innerchispa/example",
                "github_visibility": "public",
                "gitlab_visibility": "public",
                "mirror_fsck_ok": True,
                "mirror": "/mirror/example.git",
            }
        ],
    }


def test_healthy_state_passes():
    result = mod.evaluate(healthy_catalog(), healthy_discovery())
    assert result["ok"] is True
    assert result["issues"] == []


def test_needs_review_is_detected():
    catalog = healthy_catalog()
    catalog["needs_review"] = ["Rafa-Innerchispa/new-repo"]
    result = mod.evaluate(catalog, healthy_discovery())
    assert result["ok"] is False
    assert result["counts"]["needs_review"] == 1
    assert any(x["kind"] == "needs_review" for x in result["issues"])


def test_visibility_mismatch_is_detected():
    discovery = healthy_discovery()
    discovery["rows"][0]["gitlab_visibility"] = "private"
    result = mod.evaluate(healthy_catalog(), discovery)
    assert result["ok"] is False
    assert result["counts"]["visibility_mismatches"] == 1


def test_damaged_mirror_is_detected():
    discovery = healthy_discovery()
    discovery["rows"][0]["mirror_fsck_ok"] = False
    result = mod.evaluate(healthy_catalog(), discovery)
    assert result["ok"] is False
    assert result["counts"]["mirror_fsck_failures"] == 1
