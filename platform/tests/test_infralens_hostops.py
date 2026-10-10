from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from inneros_core_runtime import capability_gateway as cg
from inneros_core_runtime import infralens_hostops as ih


FINAL = ih.POLICY["final_digest"]


def _proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_hostops_rejects_wrong_node(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(ih.whatsapp_service_ops, "normalize_node", lambda node: node)
    out = ih.deploy(
        node="primary",
        source_path=str(tmp_path),
        expected_sha="a" * 40,
        approval_id="hostap_test",
        dry_run=True,
    )
    assert out["ok"] is False
    assert out["error"] == "node_not_allowlisted"


def test_hostops_dry_run_is_bounded_and_preserves_final512(monkeypatch, tmp_path: Path):
    source = tmp_path / "worktrees" / "infralens"
    source.mkdir(parents=True)
    (source / "docker-compose.presentation.yml").write_text("services: {}\n", encoding="utf-8")

    monkeypatch.setattr(ih.whatsapp_service_ops, "normalize_node", lambda node: "amd")
    monkeypatch.setattr(ih.prr, "trusted_roots", lambda node: [str(tmp_path)])
    monkeypatch.setattr(ih, "_approval", lambda approval_id, node: {"ok": True, "approval_id": approval_id})

    def fake_run(node, args, timeout=60, input_text=None):
        if args[:4] == ["git", "-C", str(source), "rev-parse"]:
            return _proc(stdout="f" * 40 + "\n")
        if args[:3] == ["docker", "inspect", "--format"]:
            name = args[-1]
            return _proc(stdout=f"id-{name}|img-{name}|ref-{name}|true\n")
        if args[:4] == ["docker", "image", "inspect", "--format"]:
            return _proc(stdout=FINAL + "\n")
        raise AssertionError(f"unexpected command in dry-run: {args}")

    monkeypatch.setattr(ih, "_run", fake_run)

    out = ih.deploy(
        node="amd",
        source_path=str(source),
        expected_sha="f" * 40,
        approval_id="hostap_test",
        dry_run=True,
    )

    assert out["ok"] is True
    assert out["dry_run"] is True
    assert out["plan"]["source_sha"] == "f" * 40
    assert out["plan"]["immutable_final512"] == FINAL
    assert set(out["plan"]["containers"]) == {"infralens-track2-ocr", "infralens-track2-ui"}
    assert out["plan"]["services"] == ["vision-backend", "streamlit-ui"]


def test_hostops_rejects_sha_mismatch(monkeypatch, tmp_path: Path):
    source = tmp_path / "worktrees" / "infralens"
    source.mkdir(parents=True)
    (source / "docker-compose.presentation.yml").write_text("services: {}\n", encoding="utf-8")

    monkeypatch.setattr(ih.whatsapp_service_ops, "normalize_node", lambda node: "amd")
    monkeypatch.setattr(ih.prr, "trusted_roots", lambda node: [str(tmp_path)])
    monkeypatch.setattr(ih, "_approval", lambda approval_id, node: {"ok": True})

    def fake_run(node, args, timeout=60, input_text=None):
        if args[:2] == ["git", "-C"]:
            return _proc(stdout="a" * 40 + "\n")
        raise AssertionError(args)

    monkeypatch.setattr(ih, "_run", fake_run)
    out = ih.deploy(
        node="amd",
        source_path=str(source),
        expected_sha="b" * 40,
        approval_id="hostap_test",
        dry_run=True,
    )
    assert out["ok"] is False
    assert out["error"] == "source_sha_mismatch"


def test_hostops_rejects_final512_digest_drift(monkeypatch, tmp_path: Path):
    source = tmp_path / "worktrees" / "infralens"
    source.mkdir(parents=True)
    (source / "docker-compose.presentation.yml").write_text("services: {}\n", encoding="utf-8")

    monkeypatch.setattr(ih.whatsapp_service_ops, "normalize_node", lambda node: "amd")
    monkeypatch.setattr(ih.prr, "trusted_roots", lambda node: [str(tmp_path)])
    monkeypatch.setattr(ih, "_approval", lambda approval_id, node: {"ok": True})

    def fake_run(node, args, timeout=60, input_text=None):
        if args[:2] == ["git", "-C"]:
            return _proc(stdout="f" * 40 + "\n")
        if args[:3] == ["docker", "inspect", "--format"]:
            name = args[-1]
            return _proc(stdout=f"id-{name}|img-{name}|ref-{name}|true\n")
        if args[:4] == ["docker", "image", "inspect", "--format"]:
            return _proc(stdout="sha256:not-the-final-image\n")
        raise AssertionError(args)

    monkeypatch.setattr(ih, "_run", fake_run)
    out = ih.deploy(
        node="amd",
        source_path=str(source),
        expected_sha="f" * 40,
        approval_id="hostap_test",
        dry_run=True,
    )
    assert out["ok"] is False
    assert out["error"] == "immutable_final512_digest_mismatch"


def test_compact_gateway_catalogues_governed_infralens_hostops(monkeypatch):
    found = cg.capability_search(query="infralens deploy", max_results=20)
    ids = {item["capability_id"] for item in found["capabilities"]}
    assert "peer.infralens.presentation.deploy.v1" in ids

    approvals = cg.capability_search(query="host approval", max_results=20)
    ids = {item["capability_id"] for item in approvals["capabilities"]}
    assert "host.approval.issue.v1" in ids


def test_deploy_capability_delegates_to_bounded_handler(monkeypatch):
    monkeypatch.setattr(
        ih,
        "deploy",
        lambda **kw: {"ok": True, "dry_run": kw.get("dry_run"), "source_path": kw["source_path"]},
    )
    out = cg.capability_invoke(
        "peer.infralens.presentation.deploy.v1",
        {
            "node": "amd",
            "source_path": "/tmp/example",
            "expected_sha": "f" * 40,
            "approval_id": "hostap_test",
            "dry_run": True,
        },
        idempotency_key="test-infralens-hostops-cap",
    )
    assert out["ok"] is True
    assert out["result"]["ok"] is True
    assert out["result"]["dry_run"] is True

def test_gateway_catalogues_service_action_and_cursor_owner_order():
    service = cg.capability_search(query="service restart approval", max_results=30)
    service_ids = {item["capability_id"] for item in service["capabilities"]}
    assert "peer.service.action.v1" in service_ids

    cursor = cg.capability_search(query="cursor owner claim", max_results=30)
    cursor_ids = {item["capability_id"] for item in cursor["capabilities"]}
    assert "coordination.cursor.owner_order.v1" in cursor_ids


def test_service_action_requires_valid_host_approval(monkeypatch):
    from inneros_core_runtime import capability_gateway_peer as cgp
    from inneros_core_runtime import local_execution_plane as lep
    from raphiia_openai.agents import ag41_peer_ops_executor as ag41

    monkeypatch.setattr(
        lep,
        "validate_host_approval",
        lambda **kw: {"ok": True, "approval_id": kw["approval_id"]},
    )
    monkeypatch.setattr(
        ag41,
        "peer_ops_action",
        lambda **kw: {"ok": True, "service_id": kw["service_id"], "action": kw["action"], "node": kw["node"]},
    )
    out = cgp._service_action_with_approval(
        service_id="mcp",
        node="amd",
        action="restart",
        approval_id="hostap_test",
    )
    assert out["ok"] is True
    assert out["service_id"] == "mcp"
    assert out["approval"]["ok"] is True


def test_cursor_owner_order_capability_delegates_to_canonical_orchestrator(monkeypatch):
    from inneros_core_runtime import cursor_ops_orchestrator as co

    monkeypatch.setattr(
        co,
        "owner_order_execute",
        lambda **kw: {
            "ok": True,
            "stage": "claimed",
            "claim": {"task_id": kw.get("task_id"), "owner_actor": kw.get("owner_actor")},
        },
    )
    out = cg.capability_invoke(
        "coordination.cursor.owner_order.v1",
        {
            "task_id": "ops_123456abcdef",
            "owner_actor": "RAFAEL",
            "owner_approved": True,
        },
        idempotency_key="test-cursor-owner-order-cap",
    )
    assert out["ok"] is True
    assert out["result"]["ok"] is True
    assert out["result"]["claim"]["task_id"] == "ops_123456abcdef"
