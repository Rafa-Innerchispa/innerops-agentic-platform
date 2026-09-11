import unittest
from pathlib import Path
from unittest.mock import patch

import raphiia_openai

# The installed editable package points at the live workspace. Force this focused
# test to load submodules from this isolated worktree so it cannot produce a
# false PASS against older live code.
_worktree_runtime = Path(__file__).resolve().parents[1] / "inneros_core_runtime"
if str(_worktree_runtime) not in raphiia_openai.__path__:
    raphiia_openai.__path__.insert(0, str(_worktree_runtime))

from raphiia_openai import voiceops_guardian_bridge as bridge
from raphiia_openai import whatsapp_evolution_parse as evo


def quoted_audio_payload(caption: str) -> dict:
    return {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": "owner@s.whatsapp.net", "fromMe": False, "id": "m1"},
            "message": {
                "audioMessage": {"mimetype": "audio/ogg; codecs=opus"},
                "messageContextInfo": {
                    "quotedMessage": {"imageMessage": {"caption": caption}}
                },
            },
        },
    }


class TestVoiceOpsGuardianBridge(unittest.TestCase):
    def setUp(self):
        self.event = {
            "event_id": "evt_guardian_123",
            "source_id": "camera-2",
            "event_type": "zone.person.dwell",
            "severity": "high",
            "occurred_at": "2026-09-11T13:00:00+00:00",
            "tenant_id": "pcdoctor",
            "site_id": "pcdoctor-lab",
            "zone_id": "door",
            "confidence": 0.93,
        }

    def test_extract_quoted_caption_and_event_ref(self):
        payload = quoted_audio_payload("Physical Guardian\nRef: evt_guardian_123")
        quoted = evo.extract_quoted_text(payload)
        self.assertEqual(bridge.extract_event_ref(quoted), "evt_guardian_123")

    def test_exact_quoted_event_is_submitted_and_becomes_pending(self):
        payload = quoted_audio_payload("Physical Guardian\nRef: evt_guardian_123")
        pending = {}

        def pending_get(ref):
            return pending.get(ref)

        def pending_set(ref, event):
            pending[ref] = {"event_id": event["event_id"], "event": event}

        with patch.object(bridge, "_pending_get", side_effect=pending_get), patch.object(
            bridge, "_pending_set", side_effect=pending_set
        ), patch.object(bridge, "_pending_clear"):
            result = bridge.route_owner_voice_reply(
                payload,
                "Revisa y dime qué recomiendas",
                canonical_conversation_id="owner:fixture:whatsapp",
                fetcher=lambda event_id: self.event if event_id == self.event["event_id"] else {},
                submitter=lambda event, transcript: {
                    "bridge_status": "approval_required",
                    "last_result": {"status": "approval_required"},
                    "production_writes": False,
                },
            )
        self.assertTrue(result["applicable"])
        self.assertEqual(result["event_id"], self.event["event_id"])
        self.assertEqual(result["status"], "approval_required")
        self.assertTrue(pending)

    def test_pending_event_carries_explicit_approval_without_quote(self):
        pending_row = {"event_id": self.event["event_id"], "event": self.event}
        cleared = []
        with patch.object(bridge, "_pending_get", return_value=pending_row), patch.object(
            bridge, "_pending_clear", side_effect=lambda ref: cleared.append(ref)
        ):
            result = bridge.route_owner_voice_reply(
                {"data": {"message": {"audioMessage": {}}}},
                "Sí, autorizo",
                canonical_conversation_id="owner:fixture:whatsapp",
                submitter=lambda event, transcript: {
                    "bridge_status": "completed",
                    "last_result": {"status": "completed"},
                    "action": {"action_id": "WO-DEMO-1234"},
                    "production_writes": False,
                },
            )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["action_id"], "WO-DEMO-1234")
        self.assertTrue(cleared)

    def test_event_switch_while_pending_is_blocked(self):
        payload = quoted_audio_payload("Physical Guardian\nRef: evt_other")
        with patch.object(
            bridge,
            "_pending_get",
            return_value={"event_id": self.event["event_id"], "event": self.event},
        ):
            result = bridge.route_owner_voice_reply(
                payload,
                "Sí, autorizo",
                canonical_conversation_id="owner:fixture:whatsapp",
                fetcher=lambda event_id: self.fail("fetcher must not run when switching events"),
            )
        self.assertEqual(result["status"], "event_switch_blocked")
        self.assertEqual(result["event_id"], self.event["event_id"])

    def test_unrelated_voice_note_is_not_claimed(self):
        with patch.object(bridge, "_pending_get", return_value=None):
            result = bridge.route_owner_voice_reply(
                {"data": {"message": {"audioMessage": {}}}},
                "Recuérdame llamar mañana",
                canonical_conversation_id="owner:fixture:whatsapp",
            )
        self.assertFalse(result["applicable"])

    def test_private_transport_material_is_rejected(self):
        unsafe = dict(self.event)
        unsafe["evidence_refs"] = ["rtsp://secret-camera/private"]
        with self.assertRaises(ValueError):
            bridge._sanitize_event(unsafe)


if __name__ == "__main__":
    unittest.main()
