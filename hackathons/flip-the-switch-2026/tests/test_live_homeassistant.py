"""Safety tests with a fake HTTP fixture; NOT a live-device demonstration."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from inneros_incident_room.live_homeassistant import (
    HomeAssistantClient, LiveHAError, LiveRoomPolicy, local_ha_url, policy_from_env,
)
from inneros_incident_room.inneros_live import InnerOSLiveReader


ROOM = "!testroom:local"
OWNER = "@operator:local"
LIGHT = "light.demo_lamp"


class FakeHA:
    def __init__(self):
        self.value = "off"
        self.writes = []
        self.fail = False

    def ping(self):
        return True

    def lights(self, allowed):
        return [{"entity_id": LIGHT, "name": "Test Lamp", "state": self.value}]

    def state(self, entity):
        if self.fail:
            raise LiveHAError("unavailable")
        return {"entity_id": entity, "state": self.value,
                "last_updated": "2026-11-06T00:00:00Z", "fetched_at": "2026-11-06T12:00:00Z"}

    def turn_light(self, entity, desired):
        self.writes.append((entity, desired))
        self.value = desired


def frame(message, mid="m1", sender=OWNER, room=ROOM, addressed=True):
    return {"event": "message", "data": {"room_id": room, "payload": {
        "sender": sender, "body": message, "message_id": mid, "addressed": addressed}}}


class LivePolicyTests(unittest.TestCase):
    def setUp(self):
        self.ha = FakeHA()
        self.policy = LiveRoomPolicy(ROOM, OWNER, self.ha, frozenset({LIGHT}),
                                     actions_enabled=True, id_factory=lambda: "act1", clock=lambda: 1000)

    def test_real_command_route_requires_authentic_switch_room(self):
        self.assertIsNone(self.policy.handle(frame("!lights", room="!other:local")))
        self.assertIsNone(self.policy.handle(frame("!lights", addressed=False)))
        self.assertEqual(self.ha.writes, [])

    def test_real_read_never_calls_mutation(self):
        self.assertIn("[HA LIVE]", self.policy.handle(frame("!lights")))
        self.assertIn("[HA LIVE READ]", self.policy.handle(frame("!state " + LIGHT, mid="m2")))
        self.assertEqual(self.ha.writes, [])

    def test_rejects_unlisted_light_and_switch(self):
        self.assertIn("not in", self.policy.handle(frame("!state light.other")))
        self.assertIn("not in", self.policy.handle(frame("!propose switch.power on", mid="m2")))
        self.assertEqual(self.ha.writes, [])

    def test_no_unauthorized_proposal(self):
        self.assertIn("BLOCKED", self.policy.handle(frame("!propose " + LIGHT + " on", sender="@other:local")))
        self.assertEqual(self.ha.writes, [])

    def test_requires_write_gate(self):
        self.policy.actions_enabled = False
        self.assertIn("BLOCKED", self.policy.handle(frame("!propose " + LIGHT + " on")))
        self.assertEqual(self.ha.writes, [])

    def test_deny_means_zero_service_calls(self):
        proposal = self.policy.handle(frame("!propose " + LIGHT + " on"))
        self.assertIn("HA-act1", proposal)
        result = self.policy.handle(frame("!deny HA-act1", mid="m2"))
        self.assertIn("DENIED", result)
        self.assertEqual(self.ha.writes, [])

    def test_approval_changes_state_with_live_readback(self):
        self.policy.handle(frame("!propose " + LIGHT + " on"))
        response = self.policy.handle(frame("!approve HA-act1", mid="m2"))
        self.assertIn("[HA LIVE VERIFIED]", response)
        self.assertEqual(self.ha.writes, [(LIGHT, "on")])
        self.assertEqual(self.ha.value, "on")
        self.assertIn("BLOCKED", self.policy.handle(frame("!approve HA-act1", mid="m3")))
        self.assertEqual(len(self.ha.writes), 1)

    def test_wrong_operator_cannot_approve(self):
        self.policy.handle(frame("!propose " + LIGHT + " on"))
        self.assertIn("BLOCKED", self.policy.handle(frame("!approve HA-act1", mid="m2", sender="@attacker:local")))
        self.assertEqual(self.ha.writes, [])

    def test_wrong_action_id_cannot_approve(self):
        self.policy.handle(frame("!propose " + LIGHT + " on"))
        self.assertIn("BLOCKED", self.policy.handle(frame("!approve HA-wrong", mid="m2")))
        self.assertEqual(self.ha.writes, [])

    def test_external_state_change_invalidates_approval(self):
        self.policy.handle(frame("!propose " + LIGHT + " on"))
        self.ha.value = "on"
        response = self.policy.handle(frame("!approve HA-act1", mid="m2"))
        self.assertIn("already observed", response)
        self.assertEqual(self.ha.writes, [])

    def test_stale_approval_expires(self):
        self.policy.handle(frame("!propose " + LIGHT + " on"))
        self.policy.clock = lambda: 5000
        self.assertIn("expired", self.policy.handle(frame("!approve HA-act1", mid="m2")))
        self.assertEqual(self.ha.writes, [])

    def test_read_failure_blocks_proposal(self):
        self.ha.fail = True
        self.assertIn("HA LIVE ERROR", self.policy.handle(frame("!propose " + LIGHT + " on")))
        self.assertIsNone(self.policy.pending)
        self.assertEqual(self.ha.writes, [])

    def test_restore_pending_policy_and_dedupe(self):
        self.policy.handle(frame("!propose " + LIGHT + " on"))
        snap = self.policy.snapshot()
        restored = LiveRoomPolicy(ROOM, OWNER, self.ha, frozenset({LIGHT}), actions_enabled=True, clock=lambda: 1000)
        restored.restore(snap)
        self.assertIsNone(restored.handle(frame("!propose " + LIGHT + " on")))
        self.assertIn("[HA LIVE VERIFIED]", restored.handle(frame("!approve HA-act1", mid="m2")))
        self.assertEqual(len(self.ha.writes), 1)

    def test_mcp_read_shows_truthful_quality(self):
        self.policy.inneros_reader = lambda: {
            "registered_devices": 90, "observed_at": "2026-11-06T00:00:00Z",
            "live_telemetry_verified": False, "status_counts": {"STALE": 53, "UNKNOWN": 37}}
        out = self.policy.handle(frame("!inneros"))
        self.assertIn("live_telemetry_verified=False", out)
        self.assertEqual(self.ha.writes, [])

    def test_mcp_not_configured_never_fabricates(self):
        self.assertIn("Not configured", self.policy.handle(frame("!inneros")))


class ConfigTests(unittest.TestCase):
    def test_local_host_validation(self):
        self.assertEqual(local_ha_url("http://10.20.30.40:8123"), "http://10.20.30.40:8123")
        with self.assertRaises(ValueError):
            local_ha_url("http://example.com")
        with self.assertRaises(ValueError):
            local_ha_url("http://user:pass@10.20.30.40:8123")

    def test_mcp_https_required(self):
        with self.assertRaises(ValueError):
            InnerOSLiveReader("http://mcp.pcdoctor.ai/router/mcp", "test")

    def test_no_ha_configuration_means_no_hardware_access(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                policy_from_env(ROOM, OWNER)


class HttpHA(BaseHTTPRequestHandler):
    calls = []
    value = "off"
    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer local-test-only":
            self.send_error(401)
            return
        if self.path == "/api/":
            value = {"message": "API running."}
        elif self.path == "/api/states":
            value = [{"entity_id": LIGHT, "state": HttpHA.value, "attributes": {"friendly_name": "Test Lamp"}}]
        elif self.path == "/api/states/light.demo_lamp":
            value = {"entity_id": LIGHT, "state": HttpHA.value,
                     "attributes": {"friendly_name": "Test Lamp"}, "last_updated": "now"}
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(value).encode())
    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer local-test-only":
            self.send_error(401)
            return
        if self.path == "/api/services/light/turn_on":
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            HttpHA.calls.append(body)
            HttpHA.value = "on"
            value = []
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(value).encode())
    def log_message(self, *args):
        pass


class HomeAssistantHttpTests(unittest.TestCase):
    def test_actual_http_contract_against_test_server_not_real_device(self):
        HttpHA.calls = []
        HttpHA.value = "off"
        http = ThreadingHTTPServer(("127.0.0.1", 0), HttpHA)
        runner = Thread(target=http.serve_forever, daemon=True)
        runner.start()
        try:
            ha = HomeAssistantClient("http://127.0.0.1:" + str(http.server_port), "local-test-only")
            self.assertTrue(ha.ping())
            self.assertEqual(ha.state(LIGHT)["state"], "off")
            room = LiveRoomPolicy(ROOM, OWNER, ha, frozenset({LIGHT}), actions_enabled=True, clock=lambda:1000,
                                  id_factory=lambda:"test")
            room.handle(frame("!propose " + LIGHT + " on"))
            out = room.handle(frame("!approve HA-test", mid="m2"))
            self.assertIn("[HA LIVE VERIFIED]", out)
            self.assertEqual(ha.state(LIGHT)["state"], "on")
            self.assertEqual(HttpHA.calls, [{"entity_id": LIGHT}])
        finally:
            http.shutdown()
            http.server_close()
            runner.join(timeout=2)


if __name__ == "__main__":
    unittest.main()