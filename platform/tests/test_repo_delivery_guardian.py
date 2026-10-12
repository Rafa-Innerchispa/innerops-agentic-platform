"""Universal fleet delivery audit regression: never confuse code, CI and production."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repo_delivery_guardian.py"
SPEC = importlib.util.spec_from_file_location("repo_delivery_guardian", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

NOW = datetime(2026, 10, 12, 16, 50, tzinfo=timezone.utc)
REPO = "Rafa-Innerchispa/innerops-service-ops"
SHA = "a" * 40


def github_good():
    return {
        "source_ok": True, "default_branch": "main", "head_sha": SHA,
        "protected": True, "issues_enabled": True,
        "ci_success_on_head": True, "release_exists": True,
        "latest_release": "v1.1.0", "private": True,
        "branch_inventory_complete": True, "remote_branch_count": 1,
        "open_pr_count": 0, "unreviewed_branch_count": 0,
        "last_successful_ci_run_id": 1234,
    }


def sources():
    rows = [{"nameWithOwner": REPO, "isPrivate": True}]
    gh = {REPO: github_good()}
    cat = {"generated_at": NOW.isoformat(),
           "rows": [{"repository": REPO, "role": "active_product",
                     "lifecycle": "active"}]}
    discovery = {"timestamp": NOW.isoformat(), "rows": [
        {"repo": REPO, "mirror_fsck_ok": True,
         "github_visibility": "private", "gitlab_visibility": "private"}]}
    gitlab = {"timestamp": NOW.isoformat(), "rows": [
        {"github": REPO, "branches_ok": True, "tags_ok": True}]}
    receipts = {"repositories": {}}
    return rows, gh, cat, discovery, gitlab, receipts


def test_good_github_records_never_certify_live_production():
    result = mod.evaluate(*sources(), now=NOW)
    assert result["counts"]["governed"] == 1
    assert result["github_coverage_complete"] is True
    assert result["universal_coverage_certified"] is False
    assert result["counts"]["production_certified"] == 0
    assert result["projects"][0]["prod_status"] == "NO_CERTIFICADO"
    assert result["gitlab_only_project_coverage"] == "NOT_YET_ATTESTED"


def test_orphan_branches_do_not_trigger_merge_or_delete():
    inputs = list(sources())
    inputs[1] = {REPO: {**github_good(),
                        "unreviewed_branch_count": 5,
                        "unreviewed_branch_sample": ["feature/one", "legacy/beta"]}}
    result = mod.evaluate(*inputs, now=NOW)
    assert result["counts"]["needs_attention"] == 1
    assert "branches_require_semantic_triage" in result["projects"][0]["gaps"]
    assert result["no_branch_merged_or_deleted"] is True


def test_old_mirror_and_unknown_default_are_not_misreported():
    inputs = list(sources())
    inputs[2] = {**inputs[2], "generated_at": (NOW - timedelta(days=3)).isoformat()}
    inputs[1] = {REPO: {**github_good(), "source_ok": False, "head_sha": None,
                        "branch_inventory_complete": False}}
    result = mod.evaluate(*inputs, now=NOW)
    gaps = set(result["projects"][0]["gaps"])
    assert "taxonomy_missing_or_stale" in gaps
    assert "github_api_unverified" in gaps
    assert "github_branch_pr_inventory_unverified" in gaps
    assert "default_branch_sha_unknown" in gaps


def test_untrusted_receipt_and_task_claim_cannot_mean_production():
    inputs = list(sources())
    inputs[5] = {"repositories": {REPO: {"amd": {
        "repo": REPO, "runtime_git_sha": SHA, "verified": True,
        "independent_verifier": False, "runtime_import_sha256": "b" * 64,
        "runtime_pid": 123, "tests_exit_code": 0, "smoke_exit_code": 0,
        "rollback_snapshot": "s", "evidence_path": "receipt.json",
        "verified_at_utc": NOW.isoformat(),
    }}}}
    result = mod.evaluate(*inputs, now=NOW)
    assert result["projects"][0]["prod_status"] == "NO_CERTIFICADO"
    assert result["projects"][0]["host_receipt_status"] == {"amd": False}
    assert result["counts"]["production_certified"] == 0


def test_all_metadata_still_requires_fresh_independent_host_check():
    inputs = list(sources())
    inputs[5] = {"repositories": {REPO: {"amd": {
        "repo": REPO, "runtime_git_sha": SHA, "verified": True,
        "independent_verifier": True, "runtime_import_sha256": "b" * 64,
        "runtime_pid": 123, "tests_exit_code": 0, "smoke_exit_code": 0,
        "rollback_snapshot": "s", "evidence_path": "receipt.json",
        "verified_at_utc": NOW.isoformat(),
    }}}}
    result = mod.evaluate(*inputs, now=NOW)
    assert result["projects"][0]["prod_status"] == "HOST_EVIDENCE_RECORDED_RECHECK_REQUIRED"
    assert result["counts"]["production_certified"] == 0


def test_invalid_or_duplicate_git_portfolio_rejected():
    inputs = list(sources())
    inputs[0] = []
    with pytest.raises(ValueError, match="invalid_or_empty"):
        mod.evaluate(*inputs, now=NOW)
    inputs[0] = [{"nameWithOwner": REPO, "isPrivate": True}] * 2
    with pytest.raises(ValueError, match="duplicate_repository"):
        mod.evaluate(*inputs, now=NOW)


def test_pagination_flattens_but_refuses_oversized_or_invalid_pages():
    with patch.object(mod, "_run", return_value=([[{"name": "main"}], [{"name": "feat"}]], None)):
        result, error = mod._pages("gh", "repos/example/project/branches?per_page=100")
    assert error is None and len(result) == 2
    with patch.object(mod, "_run", return_value=([[1, 2, 3]], None)):
        result, error = mod._pages("gh", "endpoint", max_count=3)
    assert result is None and error == "pagination_limit_reached"
    with patch.object(mod, "_run", return_value=({"not_pages": True}, None)):
        result, error = mod._pages("gh", "endpoint")
    assert result is None and error == "invalid_paginated_result"


def test_inspector_tracks_pr_branches_and_preserves_legacy_branches():
    meta = {"default_branch": "main", "has_issues": True, "private": True}
    branch = {"commit": {"sha": SHA}, "protected": True}
    releases = [{"tag_name": "v1.1.0", "draft": False,
                 "published_at": NOW.isoformat()}]
    runs = {"workflow_runs": [{
        "head_sha": SHA, "head_branch": "main",
        "status": "completed", "conclusion": "success", "id": 7}]}
    refs = [
        {"name": "main", "commit": {"sha": SHA}},
        {"name": "feature/reviewed", "commit": {"sha": "b" * 40}},
        {"name": "legacy/no-pr", "commit": {"sha": "c" * 40}},
    ]
    prs = [{"head": {"ref": "feature/reviewed",
                     "repo": {"full_name": REPO}}}]
    def api(_gh, endpoint):
        if endpoint.endswith("/branches/main"):
            return branch, None
        if "/releases?" in endpoint:
            return releases, None
        if "/actions/runs?" in endpoint:
            return runs, None
        return meta, None
    def pages(_gh, endpoint):
        return (refs, None) if "/branches?" in endpoint else (prs, None)
    with patch.object(mod, "_api", side_effect=api):
        with patch.object(mod, "_pages", side_effect=pages):
            result = mod.inspect("gh", {"nameWithOwner": REPO})
    assert result["source_ok"] is True
    assert result["unreviewed_branch_count"] == 1
    assert result["unreviewed_branch_sample"] == ["legacy/no-pr"]
    assert result["open_pr_count"] == 1
    assert result["ci_success_on_head"] is True


def test_local_report_is_private_and_outside_writes_are_denied(tmp_path):
    with patch.object(mod, "ROOT", tmp_path / "safe"):
        safe = mod.ROOT / "results" / "delivery.json"
        mod.save_private(safe, {"repo": REPO})
        assert json.loads(safe.read_text()) == {"repo": REPO}
        assert safe.stat().st_mode & 0o777 == 0o600
        with pytest.raises(ValueError, match="output_must_be_inside"):
            mod.save_private(tmp_path / "outside.json", {"blocked": True})


def test_next_gate_prioritizes_preservation_and_branch_review():
    assert mod.next_gate(["backup_mirror_unverified", "branches_require_semantic_triage"], "active") == (
        "PRESERVE_AND_VERIFY_BACKUP_BEFORE_CHANGES"
    )
    assert mod.next_gate(["branches_require_semantic_triage"], "active") == (
        "TRIAGE_BRANCHES_THEN_SCOPED_PR_WITH_CI"
    )
    assert mod.next_gate([], "experimental") == (
        "PRESERVE_EXPERIMENT_OR_LEGACY_WITHOUT_FORCED_DEPLOY"
    )


def test_script_has_no_deploy_or_force_push_steps():
    code = SCRIPT.read_text()
    assert "subprocess.run" in code
    assert "git push" not in code
    assert "git reset --hard" not in code
    assert "gh repo edit" not in code
    assert "rsync --delete" not in code
