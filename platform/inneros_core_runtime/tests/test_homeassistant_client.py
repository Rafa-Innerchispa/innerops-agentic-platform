import unittest
from unittest.mock import patch

from inneros_core_runtime import homeassistant_client as ha


DEVICE = {
    "id": "dev-1",
    "name": "智能遥控",
    "name_by_user": None,
    "manufacturer": "Broadlink",
    "connections": [["mac", "78:0f:77:5a:ee:9b"]],
    "identifiers": [["broadlink", "780f775aee9b"]],
}

ENTITY = {
    "entity_id": "remote.zhi_neng_yao_kong",
    "name": None,
    "original_name": None,
    "device_id": "dev-1",
    "platform": "broadlink",
}


class HomeAssistantClientTests(unittest.TestCase):
    def fake_ws(self, message_type, payload=None):
        if message_type == "config/device_registry/list":
            return {"ok": True, "data": [DEVICE]}
        if message_type == "config/entity_registry/list":
            return {"ok": True, "data": [ENTITY]}
        if message_type == "search/related":
            return {"ok": True, "data": {"entity": [payload["item_id"]]}}
        self.fail(f"unexpected ws call: {message_type}")

    @patch.object(ha, "ws_call")
    def test_batch_rename_device_by_mac_dry_run(self, ws_call):
        ws_call.side_effect = self.fake_ws
        out = ha.ha_batch_rename(
            [{"type": "device", "mac": "78:0f:77:5a:ee:9b", "name": "RM Mini Living"}],
            dry_run=True,
        )

        self.assertTrue(out["ok"])
        self.assertTrue(out["dry_run"])
        result = out["results"][0]
        self.assertEqual(result["payload"]["device_id"], "dev-1")
        self.assertEqual(result["payload"]["name_by_user"], "RM Mini Living")

    @patch.object(ha, "ws_call")
    def test_entity_rename_rejects_entity_id_change_flow(self, ws_call):
        ws_call.side_effect = self.fake_ws
        out = ha.ha_rename_entity_name(
            "remote.zhi_neng_yao_kong",
            "RM Mini Living",
            dry_run=True,
            allow_entity_id_change=True,
        )

        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "entity_id_change_not_supported_here")

    @patch.object(ha, "ws_call")
    def test_search_entity_references_uses_ws_related_search(self, ws_call):
        ws_call.side_effect = self.fake_ws
        out = ha.ha_search_entity_references("switch.sp3s_15a")

        self.assertTrue(out["ok"])
        ws_call.assert_called_once_with("search/related", {"item_type": "entity", "item_id": "switch.sp3s_15a"})


if __name__ == "__main__":
    unittest.main()
