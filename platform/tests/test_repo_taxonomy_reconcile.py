import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repo_taxonomy_reconcile.py"
spec = importlib.util.spec_from_file_location("repo_taxonomy_reconcile", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

POLICY = {
    "owner": "Rafa-Innerchispa",
    "featured_repositories": [
        "Rafa-Innerchispa/a",
        "Rafa-Innerchispa/b",
        "Rafa-Innerchispa/c",
        "Rafa-Innerchispa/d",
        "Rafa-Innerchispa/e",
        "Rafa-Innerchispa/f",
    ],
    "overrides": {},
    "rules": {
        "probe_name_patterns": ["-smoke","-probe","-baseline"],
        "snapshot_name_patterns": ["hackathon","assemblyai"],
        "internal_name_patterns": ["brand-assets","service-ops"],
        "confidence": {"auto_accept":0.90,"provisional":0.70},
    },
}


def repo(name, private=False, branch="main", description="", size=10):
    return {
        "name": name,
        "nameWithOwner": f"Rafa-Innerchispa/{name}",
        "isPrivate": private,
        "defaultBranchRef": {"name": branch},
        "description": description,
        "repositoryTopics": [],
        "size": size,
    }


def test_hyperloom_child_is_probe_with_parent():
    r = mod.classify_repo(repo("hyperloom-r9700-agent-smoke"), POLICY)
    assert r["role"] == "experimental_probe"
    assert r["parent"] == "Rafa-Innerchispa/hyperloom-r9700-experimental"
    assert r["allow_auto_publication"] is False
    assert mod.validate_record(r, POLICY)["status"] == "PASS"


def test_probe_without_parent_is_blocked():
    r = mod.classify_repo(repo("something-probe"), POLICY)
    v = mod.validate_record(r, POLICY)
    assert v["status"] == "BLOCKED"
    assert "experimental_probe_requires_parent" in v["errors"]


def test_private_internal_pattern():
    r = mod.classify_repo(repo("pcdoctor-brand-assets", private=True), POLICY)
    assert r["role"] == "internal_operations"
    assert r["portfolio_tier"] == "hidden"


def test_snapshot_is_provisional_not_auto_featured():
    r = mod.classify_repo(repo("inneros-demo-hackathon"), POLICY)
    assert r["role"] == "validation_snapshot"
    assert r["classification_confidence"] < 0.90
    assert mod.validate_record(r, POLICY)["status"] == "PASS_WITH_WARNINGS"


def test_low_confidence_becomes_needs_review():
    r = mod.classify_repo(repo("miscellaneous-public-repo", description="unknown"), POLICY)
    assert mod.validate_record(r, POLICY)["status"] == "NEEDS_REVIEW"


def test_featured_must_use_main():
    p = json.loads(json.dumps(POLICY))
    p["overrides"]["Rafa-Innerchispa/a"] = {
        "role":"featured_system","lifecycle":"active","portfolio_tier":"featured",
        "portfolio_visible":True,"profile_featured":True,"allow_auto_publication":False,
    }
    r = mod.classify_repo(repo("a", branch="dev"), p)
    v = mod.validate_record(r, p)
    assert v["status"] == "BLOCKED"
    assert "featured_default_branch_not_main" in v["errors"]


def test_taxonomy_cannot_publish():
    r = mod.classify_repo(repo("miscellaneous-public-repo"), POLICY)
    assert r["allow_auto_publication"] is False
