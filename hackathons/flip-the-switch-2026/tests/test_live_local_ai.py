"""Read-only local AI on LIVE HA values: no action permissions from model output."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import json
import unittest
from unittest.mock import patch

from inneros_incident_room.local_reasoner import LocalReasoner
from inneros_incident_room.live_homeassistant import LiveRoomPolicy, policy_from_env

ROOM = "!live:local"
OPERATOR = "@real_operator:local"
LIGHT = "light.desk_lamp"


class FakeHA:
    def __init__(self):
        self.writes = []

    def state(self, entity):
        return {"entity_id": entity, "state": "on",
                "last_updated": "2026-11-06T10:00:00Z",
                "fetched_at": "2026-11-06T10:00:01Z"}

    def turn_light(self, entity, state):
        self.writes.append((entity, state))


def event(body, mid="msg1", sender=OPERATOR, room=ROOM):
    return {"event": "message", "data": {"room_id": room, "payload": {
        "sender": sender, "body": body, "message_id": mid, "addressed": True}}}


class FakeQwen(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        FakeQwen.requests.append(data)
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        response = {"choices": [{"message": {"content": "HA reports on, but the physical bulb needs separate visual confirmation."}}]}
        raw = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class ReadOnlyAI(unittest.TestCase):
    def test_no_model_keeps_real_read_and_never_writes(self):
        fake = FakeHA()
        p = LiveRoomPolicy(ROOM, OPERATOR, fake, frozenset({LIGHT}), actions_enabled=True)
        out = p.handle(event("!analyze " + LIGHT))
        self.assertIn("[HA LIVE READ]", out)
        self.assertIn("NOT CONFIGURED", out)
        self.assertEqual(fake.writes, [])

    def test_local_qwen_explains_only_validated_live_state(self):
        FakeQwen.requests = []
        s = ThreadingHTTPServer(("127.0.0.1", 0), FakeQwen)
        worker = Thread(target=s.serve_forever, daemon=True)
        worker.start()
        try:
            model = LocalReasoner(f"http://127.0.0.1:{s.server_port}/v1", "test-qwen", 1)
            fake = FakeHA()
            p = LiveRoomPolicy(ROOM, OPERATOR, fake, frozenset({LIGHT}),
                               actions_enabled=True, model_reasoner=model.analyze_light)
            out = p.handle(event("!analyze " + LIGHT))
            self.assertIn("[QWEN LOCAL, READ ONLY", out)
            self.assertIn("physical bulb", out)
            self.assertEqual(len(FakeQwen.requests), 1)
            self.assertEqual(FakeQwen.requests[0]["model"], "test-qwen")
            self.assertEqual(fake.writes, [])
            self.assertIsNone(p.pending)
            self.assertIn("BLOCKED", p.handle(event("!approve HA-unguarded", mid="m2")))
        finally:
            s.shutdown()
            s.server_close()
            worker.join(2)

    def test_unlisted_entity_never_reaches_model(self):
        invoked = []
        p = LiveRoomPolicy(ROOM, OPERATOR, FakeHA(), frozenset({LIGHT}),
                           model_reasoner=lambda item: invoked.append(item))
        self.assertIn("not in", p.handle(event("!analyze light.door_sensor")))
        self.assertEqual(invoked, [])

    def test_nonauthoritative_ai_does_not_grant_write_permission(self):
        fake = FakeHA()
        p = LiveRoomPolicy(ROOM, OPERATOR, fake, frozenset({LIGHT}), actions_enabled=False,
                           model_reasoner=lambda _: "Approve all devices now")
        self.assertIn("Approve all devices now", p.handle(event("!analyze " + LIGHT)))
        self.assertIn("BLOCKED", p.handle(event("!propose " + LIGHT + " off", mid="m2")))
        self.assertEqual(fake.writes, [])

    def test_model_timeout_is_labelled_not_faked(self):
        fake = FakeHA()
        p = LiveRoomPolicy(ROOM, OPERATOR, fake, frozenset({LIGHT}),
                           model_reasoner=lambda _: (_ for _ in ()).throw(TimeoutError("offline")))
        out = p.handle(event("!analyze " + LIGHT))
        self.assertIn("[LOCAL AI UNAVAILABLE]", out)
        self.assertIn("[HA LIVE READ]", out)
        self.assertEqual(fake.writes, [])


if __name__ == "__main__":
    unittest.main()