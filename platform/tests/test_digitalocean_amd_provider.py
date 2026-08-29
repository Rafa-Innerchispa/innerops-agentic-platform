import unittest
from unittest.mock import patch

from inneros_core_runtime import digitalocean_amd_provider as do


class FakeUpdateResult:
    modified_count = 1


class FakeCursor(list):
    def sort(self, *args, **kwargs):
        return self

    def limit(self, value):
        return FakeCursor(self[:value])


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.updates = []

    def insert_one(self, doc):
        self.docs.append(dict(doc))

    def update_one(self, query, update, upsert=False):
        self.updates.append((query, update, upsert))
        if upsert:
            doc = dict(update.get("$set") or {})
            self.docs.append(doc)
        return FakeUpdateResult()

    def update_many(self, query, update):
        self.updates.append((query, update, False))
        return FakeUpdateResult()

    def find(self, query=None, projection=None):
        query = query or {}
        rows = []
        for doc in self.docs:
            if query.get("provider") and doc.get("provider") != query["provider"]:
                continue
            if "status" in query and "$in" in query["status"] and doc.get("status") not in query["status"]["$in"]:
                continue
            if "droplet_id" in query and "$in" in query["droplet_id"] and doc.get("droplet_id") not in query["droplet_id"]["$in"]:
                continue
            rows.append(dict(doc))
        return FakeCursor(rows)


class FakeDb(dict):
    def __getitem__(self, key):
        self.setdefault(key, FakeCollection())
        return dict.__getitem__(self, key)


class DigitalOceanAmdProviderTests(unittest.TestCase):
    def test_balance_normalizes_account_values(self):
        with patch.object(do, "_request", return_value={
            "ok": True,
            "status": 200,
            "data": {
                "generated_at": "2026-08-26T00:00:00Z",
                "account_balance": "-5.00",
                "month_to_date_balance": "-5.00",
                "month_to_date_usage": "0.00",
            },
        }):
            result = do.balance()
        self.assertTrue(result["ok"])
        self.assertEqual(result["account_balance_usd"], -5.0)
        self.assertEqual(result["month_to_date_usage_usd"], 0.0)

    def test_create_failed_response_does_not_persist_creating_session(self):
        db = FakeDb()
        with patch.object(do, "_token", return_value="token"), \
            patch.object(do, "_mutation_allowed", return_value={"ok": True}), \
            patch.object(do, "_validate_create_inputs", return_value={"ok": True, "hourly_rate_usd": 3.8}), \
            patch.object(do, "_request", return_value={"ok": False, "status": 422, "error": "digitalocean_http_error", "data": {"message": "invalid"}}), \
            patch.object(do.mongo_store, "get_db", return_value=db):
            result = do.create_gpu_droplet(
                name="inneros-amd-burst",
                region="tor1",
                size="gpu-mi325x1-256gb",
                image="ubuntu-24-04-x64",
                approval_id="approval-ok",
                dry_run=False,
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["executed"])
        self.assertEqual(result["session"]["status"], "create_failed")
        self.assertEqual(db[do.SESSIONS_COLLECTION].docs, [])

    def test_create_missing_droplet_id_does_not_persist_creating_session(self):
        db = FakeDb()
        with patch.object(do, "_token", return_value="token"), \
            patch.object(do, "_mutation_allowed", return_value={"ok": True}), \
            patch.object(do, "_validate_create_inputs", return_value={"ok": True, "hourly_rate_usd": 3.8}), \
            patch.object(do, "_request", return_value={"ok": True, "status": 202, "data": {"droplet": {}}}), \
            patch.object(do.mongo_store, "get_db", return_value=db):
            result = do.create_gpu_droplet(
                name="inneros-amd-burst",
                region="tor1",
                size="gpu-mi325x1-256gb",
                image="ubuntu-24-04-x64",
                approval_id="approval-ok",
                dry_run=False,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "digitalocean_create_returned_no_droplet_id")
        self.assertEqual(db[do.SESSIONS_COLLECTION].docs, [])

    def test_cleanup_failed_sessions_dry_run_finds_ghosts(self):
        db = FakeDb()
        db[do.SESSIONS_COLLECTION] = FakeCollection([
            {
                "session_id": "cloudburst_old",
                "provider": do.PROVIDER_ID,
                "status": "creating",
                "droplet_id": "",
                "updated_at": "2026-08-25T00:00:00+00:00",
            }
        ])
        with patch.object(do.mongo_store, "get_db", return_value=db):
            result = do.cleanup_failed_sessions(max_age_seconds=60, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["matched"], 1)

    def test_resource_provider_document_reflects_live_status(self):
        with patch.object(do, "status", return_value={
            "token_present": True,
            "account_reachable": True,
            "balance": {"account_balance": "-5.00"},
            "mutations_require": ["approval_id"],
        }):
            doc = do.resource_provider_document()
        self.assertEqual(doc["provider_id"], do.PROVIDER_ID)
        self.assertEqual(doc["status"], "active")
        self.assertEqual(doc["cost_policy"], "explicit_burst_only")

    def test_list_ssh_keys_redacts_public_key_material(self):
        with patch.object(do, "_request_all", return_value={
            "ok": True,
            "pages": 1,
            "ssh_keys": [{"id": 123, "name": "inneros", "fingerprint": "aa:bb", "public_key": "ssh-ed25519 AAA"}],
        }):
            result = do.list_ssh_keys()
        self.assertTrue(result["ok"])
        self.assertEqual(result["ssh_keys"][0]["id"], 123)
        self.assertTrue(result["ssh_keys"][0]["public_key_present"])
        self.assertNotIn("public_key", result["ssh_keys"][0])

    def test_create_ssh_key_dry_run_redacts_public_key(self):
        result = do.create_ssh_key("inneros", "ssh-ed25519 AAAATEST user@host", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertTrue(result["payload"]["public_key_present"])
        self.assertNotIn("AAAATEST", str(result))

    def test_create_ssh_key_rejects_private_or_invalid_material(self):
        result = do.create_ssh_key("inneros", "-----BEGIN OPENSSH PRIVATE KEY-----", dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "ssh_public_key_invalid_or_missing")


    def test_hyperloom_preflight_selects_mi325x_tor1_gpu_base_and_ssh_key(self):
        with patch.object(do, "status", return_value={"token_present": True, "account_reachable": True}), \
            patch.object(do, "list_sizes", return_value={
                "ok": True,
                "sizes": [{
                    "slug": "gpu-mi325x1-256gb",
                    "available": True,
                    "regions": ["tor1"],
                    "price_hourly": 3.8,
                    "gpu_info": {"model": "amd_mi325x", "vram": {"amount": 256, "unit": "gib"}},
                }],
            }), \
            patch.object(do, "list_images", return_value={"ok": True, "images": [{"slug": "gpu-amd-base", "name": "AMD AI/ML Ready Image"}]}), \
            patch.object(do, "list_ssh_keys", return_value={"ok": True, "ssh_keys": [{"id": 58806485, "name": "inneros-amd-5-id-ed25519", "fingerprint": "aa:bb", "public_key_present": True}]}):
            result = do.hyperloom_mi325x_preflight(spend_limit_usd=7.6)
        self.assertTrue(result["ok"])
        self.assertTrue(result["ready_for_apply"])
        self.assertEqual(result["selected"]["region"], "tor1")
        self.assertEqual(result["selected"]["size"], "gpu-mi325x1-256gb")
        self.assertEqual(result["selected"]["image"], "gpu-amd-base")
        self.assertEqual(result["create_args"]["ssh_key_ids"], ["58806485"])
        self.assertEqual(result["selected"]["estimated_max_session_hours"], 2.0)

    def test_hyperloom_preflight_rejects_wrong_region_and_missing_key(self):
        with patch.object(do, "status", return_value={"token_present": True, "account_reachable": True}), \
            patch.object(do, "list_sizes", return_value={"ok": True, "sizes": [{"slug": "gpu-mi325x1-256gb", "available": True, "regions": ["tor1"], "price_hourly": 3.8}]}), \
            patch.object(do, "list_images", return_value={"ok": True, "images": [{"slug": "gpu-amd-base"}]}), \
            patch.object(do, "list_ssh_keys", return_value={"ok": True, "ssh_keys": []}):
            result = do.hyperloom_mi325x_preflight(region="nyc2")
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["size_region_match"])
        self.assertFalse(result["checks"]["ssh_key_available"])

    def test_hyperloom_session_plan_stays_dry_run_by_default(self):
        fake_preflight = {
            "ok": True,
            "create_args": {
                "name": "inneros-hyperloom-mi325x",
                "region": "tor1",
                "size": "gpu-mi325x1-256gb",
                "image": "gpu-amd-base",
                "ssh_key_ids": ["58806485"],
                "project_id": "inneros-hyperloom-mi325x",
                "task_id": "ops_0554539ce084",
                "spend_limit_usd": 8.0,
                "idle_minutes": 30,
                "dry_run": False,
            },
        }
        with patch.object(do, "hyperloom_mi325x_preflight", return_value=fake_preflight), \
            patch.object(do, "create_gpu_droplet", return_value={"ok": True, "dry_run": True, "executed": False}) as create:
            result = do.hyperloom_mi325x_session_plan()
        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertTrue(create.call_args.kwargs["dry_run"])

    def test_hyperloom_bootstrap_script_has_no_secret_and_leaves_local_gpu_untouched(self):
        result = do.hyperloom_mi325x_bootstrap_script(workspace="/opt/inneros/hyperloom;rm -rf /", workload="demo smoke")
        self.assertTrue(result["ok"])
        script = result["script"]
        self.assertFalse(result["contains_secret"])
        self.assertIn("pip install hyperloom-inference-optimizer==1.0.0", script)
        self.assertIn("HYPERLOOM_BOOTSTRAP_READY", script)
        self.assertIn("ANTHROPIC_API_KEY=<SET_ON_NODE_OR_USE_GATEWAY>", script)
        self.assertNotIn("rm -rf", script)
        self.assertNotIn("/dev/kfd", script)

    def test_hyperloom_evidence_check_requires_destroy_confirmation(self):
        evidence = {
            "droplet_id": "123456",
            "region": "tor1",
            "size": "gpu-mi325x1-256gb",
            "image": "gpu-amd-base",
            "ssh_connected": True,
            "hyperloom_version": "1.0.0",
            "runtime_versions": {"rocm": "7.2"},
            "command_line": "hyperloom smoke",
            "wall_time_seconds": 42,
            "gpu_metrics": {"vram_gb": 256},
            "workload_result": {"ok": True},
        }
        result = do.hyperloom_mi325x_evidence_check(evidence)
        self.assertFalse(result["ok"])
        self.assertIn("destroy_confirmation", result["missing"])
        evidence["destroy_confirmation"] = "destroyed"
        result = do.hyperloom_mi325x_evidence_check(evidence)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
