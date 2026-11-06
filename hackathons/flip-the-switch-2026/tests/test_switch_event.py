import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from inneros_incident_room.switch_event import RoomPolicy, SwitchConfig, ConnectionState

ROOM = "!room-id:demo"
HUMAN = "@user-owner:example"


def event(text, sender=HUMAN, room=ROOM, addressed=True, mid="m1"):
    return {"event": "message", "data": {"type": "message", "room_id": room,
        "payload": {"addressed": addressed, "sender": sender, "message_id": mid,
                    "body": text, "sender_name": "Display User"}}, "id": 42}


class SwitchRoomTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.p = RoomPolicy(ROOM, HUMAN, clock=lambda: self.now[0], id_factory=lambda: "test000001")

    def open(self):
        reply = self.p.handle(event("!incident"))
        self.assertIn("SYNTHETIC", reply)
        return self.p.pending["action"].action_id

    def test_human_and_agent_workflow(self):
        action = self.open()
        reply = self.p.handle(event("!approve " + action, mid="m2"))
        self.assertIn("verified_simulation", reply)
        self.assertIn("digest_valid=True", reply)
        self.assertEqual(self.p.state["synthetic-camera-a"], "healthy")

    def test_mention_prefix_command(self):
        reply = self.p.handle(event("@ralphiia !incident"))
        self.assertIn("SYNTHETIC", reply)

    def test_denial_no_change(self):
        action = self.open()
        reply = self.p.handle(event("!deny " + action, mid="m2"))
        self.assertIn("DENIED", reply)
        self.assertEqual(self.p.state["synthetic-camera-a"], "degraded")

    def test_unauthorized_sender_cannot_approve(self):
        action = self.open()
        reply = self.p.handle(event("!approve " + action, sender="@attacker:example", mid="m2"))
        self.assertIn("BLOCKED", reply)
        self.assertEqual(self.p.state["synthetic-camera-a"], "degraded")

    def test_spoofed_display_name_does_not_help(self):
        action = self.open()
        reply = self.p.handle(event("!approve " + action, sender="@other:example", mid="m2"))
        self.assertIn("BLOCKED", reply)

    def test_unaddressed_is_ignored(self):
        self.assertIsNone(self.p.handle(event("!incident", addressed=False)))
        self.assertIsNone(self.p.pending)

    def test_wrong_room_is_ignored(self):
        self.assertIsNone(self.p.handle(event("!incident", room="other")))
        self.assertIsNone(self.p.pending)

    def test_replay_message_id_is_ignored(self):
        self.open()
        self.assertIsNone(self.p.handle(event("!incident")))

    def test_replay_approval_is_not_executed(self):
        action = self.open()
        self.p.handle(event("!approve " + action, mid="m2"))
        self.assertIsNone(self.p.handle(event("!approve " + action, mid="m2")))
        self.assertIn("no pending", self.p.handle(event("!approve " + action, mid="m3")))

    def test_expired_approval(self):
        action = self.open()
        self.now[0] += 601
        result = self.p.handle(event("!approve " + action, mid="m2"))
        self.assertIn("expired", result)
        self.assertEqual(self.p.state["synthetic-camera-a"], "degraded")

    def test_action_mismatch(self):
        self.open()
        self.assertIn("mismatch", self.p.handle(event("!approve fake", mid="m2")))
        self.assertEqual(self.p.state["synthetic-camera-a"], "degraded")

    def test_no_action_without_open_incident(self):
        self.assertIn("BLOCKED", self.p.handle(event("!approve anything", mid="m2")))

    def test_non_message_events_ignored(self):
        self.assertIsNone(self.p.handle({"event": "room_join", "data": {}}))

    def test_missing_identity_ignored(self):
        bad = event("!incident")
        bad["data"]["payload"].pop("sender")
        self.assertIsNone(self.p.handle(bad))

    def test_expired_reject_is_blocked(self):
        action = self.open()
        self.now[0] += 601
        self.assertIn("expired", self.p.handle(event("!deny " + action, mid="m2")))

    def test_config_denies_insecure_remote(self):
        env={"SWITCH_URL": "http://host.example:8000", "SWITCH_AGENT_ID": "demo",
             "SWITCH_AGENT_API_KEY":"fake", "SWITCH_ROOM_ID": ROOM,"SWITCH_APPROVER_ID":HUMAN}
        with patch.dict(os.environ, env):
            with self.assertRaises(ValueError): SwitchConfig.from_env()

    def test_connection_state_persistence_and_resume(self):
        with TemporaryDirectory() as d:
            path=Path(d)/"conn.json"
            cfg=SwitchConfig("http://127.0.0.1:8000","agent","fake",ROOM,HUMAN,path)
            a=ConnectionState(cfg)
            a.cursor=123
            a.generation=7
            a.persist()
            b=ConnectionState(cfg)
            self.assertEqual(b.connection_id,a.connection_id)
            self.assertIn("start_from=123",b.ws_url())
            self.assertIn("expected_generation=7",b.ws_url())
            self.assertNotIn("fake",path.read_text())


if __name__ == "__main__": unittest.main()