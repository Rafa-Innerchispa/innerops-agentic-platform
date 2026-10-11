"""Static policy gates for the trusted local release executor."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "inneros_local_release_executor.py"
WORKFLOW = ROOT / ".github" / "workflows" / "inneros-local-release.yml"


def test_local_release_is_fail_closed_and_has_rollback():
    source = SCRIPT.read_text()
    assert 'choices=("plan", "apply")' in source
    assert 'default="plan"' in source
    assert 'candidate_not_on_origin_main' in source
    assert 'checkout_sha_mismatch' in source
    assert 'dirty_candidate_checkout' in source
    assert 'approved_release_sha_not_pinned' in source
    assert 'self_hosted_runner_required' in source
    assert 'snapshot.mkdir' in source
    assert 'rollback_performed": True' in source
    assert 'os.replace(tmp, dest)' in source
    assert 'deployed_hash_mismatch' in source
    assert 'rsync' not in source
    assert 'git reset --hard' not in source
    assert 'shell=True' not in source


def test_release_workflow_does_not_use_hosted_or_pr_dispatch():
    source = WORKFLOW.read_text()
    assert "workflow_dispatch:" in source
    assert "pull_request:" not in source
    assert "self-hosted, linux, x64, inneros-amd" in source
    assert "inneros-production" in source
    assert "contents: read" in source
    assert "cancel-in-progress: false" in source
    assert "persist-credentials: false" in source
    assert "fetch-depth: 0" in source
    assert "--mode \"$RELEASE_MODE\"" in source
    assert "--restart" not in source
