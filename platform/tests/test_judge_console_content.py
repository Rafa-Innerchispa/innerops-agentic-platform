from __future__ import annotations

from unittest import mock

from inneros_core_runtime import digitalocean_amd_provider, ingest_drop_folder, judge_console_content


class FakeCursor(list):
    def sort(self, *_args):
        return self


class FakeCollection:
    def __init__(self):
        self.docs = []

    def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set") or {})
                return mock.Mock(modified_count=1)
        doc = dict(update.get("$set") or {})
        doc.update(update.get("$setOnInsert") or {})
        self.docs.append(doc)
        return mock.Mock(modified_count=0, upserted_id="fake")

    def find(self, query, projection=None):
        rows = []
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                rows.append(dict(doc))
        return FakeCursor(rows)

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return mock.Mock(inserted_id="fake")


class FakeDb(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = FakeCollection()
        return dict.__getitem__(self, key)


def test_judge_content_seeds_persistent_sections_with_freshness():
    db = FakeDb()
    with (
        mock.patch.object(judge_console_content, "_db", return_value=db),
        mock.patch.object(judge_console_content, "_runtime_snapshot", return_value={
            "judge_kpis": {"total_events": 2, "verified_events": 1, "artifacts": ["art1"]},
            "resource_fabric": {"providers": [], "models": [], "routing_policy": "local-first"},
            "local_models": {"ok": True},
            "digitalocean": {"ok": True, "token_present": True},
        }),
    ):
        result = judge_console_content.get_content(refresh=True)
    assert result["ok"] is True
    assert result["count"] >= 6
    sections = {row["section_id"]: row for row in result["sections"]}
    assert sections["live_pass_evidence"]["freshness"]["source"] == "inneros_judge_trace_events"
    assert sections["model_routing_policy"]["content"]["policy_version"] == "inneros-model-routing-v1"


def test_model_routing_policy_exposes_cost_and_selection_boundary():
    result = judge_console_content.model_routing_policy(task_class="cloud_burst_gpu", project_id="judge")
    assert result["matching_routes"][0]["provider_id"] == "digitalocean-amd-cloud"
    assert result["matching_routes"][0]["cost_policy"] == "explicit_approval_required"
    assert "selected_model" in result["matching_routes"][0]


def test_mi325x_plan_does_not_execute_without_owner_confirmation():
    with (
        mock.patch.object(digitalocean_amd_provider, "list_sizes", return_value={"ok": True, "sizes": [{"slug": "gpu-mi325x1-256gb", "regions": ["tor1"], "price_hourly": "3.8"}]}),
        mock.patch.object(digitalocean_amd_provider, "preflight", return_value={"ok": True}),
    ):
        result = digitalocean_amd_provider.mi325x_deploy_plan(project_id="judge", dry_run=True)
    assert result["ok"] is True
    assert result["executed"] is False
    assert result["approval_required"] is True
    assert result["estimate"]["size"] == "gpu-mi325x1-256gb"


def test_ingest_drop_status_creates_dirs_and_reports_qdrant(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_drop_folder, "ROOT", tmp_path / "inneros_ingest")
    ingest_drop_folder.ensure_dirs()
    sample = ingest_drop_folder.ROOT / "staging" / "note.txt"
    sample.write_text("hello", encoding="utf-8")
    with mock.patch.object(ingest_drop_folder.hybrid_context, "qdrant_health", return_value={"ok": True}):
        result = ingest_drop_folder.status()
    assert result["ok"] is True
    assert result["pending_count"] == 1
    assert result["qdrant"]["ok"] is True
