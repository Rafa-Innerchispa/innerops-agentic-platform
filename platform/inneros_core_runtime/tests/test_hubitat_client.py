import unittest
from unittest.mock import patch

from inneros_core_runtime import hubitat_client as hub


class HubitatClientTests(unittest.TestCase):
    @patch.object(hub, "HUBITAT_APP_ID", "1")
    @patch.object(hub, "HUBITAT_TOKEN", "token")
    @patch.object(hub, "httpx")
    def test_list_devices_slim_payload(self, httpx_mod):
        response = httpx_mod.request.return_value
        response.status_code = 200
        response.is_success = True
        response.content = b"[]"
        response.json.return_value = [
            {
                "id": "42",
                "name": "Timmy Motion",
                "label": "Timmy Motion",
                "type": "MotionSensor",
                "room": "Living",
                "capabilities": ["MotionSensor", "Sensor"],
                "attributes": {"manufacturer": "Aeotec"},
            }
        ]

        out = hub.list_devices(limit=10)

        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["devices"][0]["id"], "42")
        self.assertEqual(out["devices"][0]["manufacturer"], "Aeotec")

    @patch.object(hub, "HUBITAT_APP_ID", "")
    @patch.object(hub, "HUBITAT_TOKEN", "")
    def test_ping_without_token_reports_discovery(self):
        with patch.object(hub, "discover", return_value={"ok": True, "maker_api_port_open": True}):
            out = hub.ping()

        self.assertTrue(out["ok"])
        self.assertFalse(out["configured"])
        self.assertEqual(out["maker_api"]["error"], "hubitat_not_configured")

    @patch.object(hub, "list_devices")
    def test_find_device_by_query(self, list_devices):
        list_devices.return_value = {
            "ok": True,
            "devices": [
                {"id": "1", "name": "Timmy Temperature", "capabilities": ["TemperatureMeasurement"]},
                {"id": "2", "name": "Kitchen Switch", "capabilities": ["Switch"]},
            ],
        }

        out = hub.find_device("timmy")

        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["matches"][0]["id"], "1")


if __name__ == "__main__":
    unittest.main()
