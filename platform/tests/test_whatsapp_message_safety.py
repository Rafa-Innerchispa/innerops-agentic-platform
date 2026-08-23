import unittest
from unittest.mock import patch

from raphiia_openai import (
    whatsapp_automation,
    whatsapp_conversational,
    whatsapp_evolution_parse,
    whatsapp_message_ledger,
)


def fixture_payload(text="Hola", *, from_me=False, message_id="fixture-message-1"):
    return {
        "event": "messages.upsert",
        "instance": "fixture-instance",
        "sender": "fixture-service-account",
        "data": {
            "key": {
                "id": message_id,
                "fromMe": from_me,
                "remoteJid": "fixture-human@s.whatsapp.net",
            },
            "message": {"conversation": text},
        },
    }


class TestWhatsappMessageSafety(unittest.TestCase):
    def test_from_me_is_never_routed(self):
        result = whatsapp_message_ledger.classify_inbound(fixture_payload(from_me=True))
        self.assertFalse(result["should_route"])
        self.assertEqual(result["reason"], "from_me")

    def test_known_automation_template_is_never_routed(self):
        payload = fixture_payload("AUTORESPUESTA FIXTURE", message_id="fixture-auto")
        fingerprint = whatsapp_message_ledger.text_fingerprint("AUTORESPUESTA FIXTURE")
        with patch.object(whatsapp_message_ledger, "automation_fingerprints", return_value={fingerprint}):
            result = whatsapp_message_ledger.classify_inbound(payload)
        self.assertFalse(result["should_route"])
        self.assertEqual(result["actor_type"], "automation")
        self.assertEqual(result["reason"], "automation_template")

    def test_blocked_classifier_stops_before_mongo_and_llm(self):
        class EmptyCollection:
            def find_one(self, *_args, **_kwargs):
                return None

        class EmptyDB:
            def __getitem__(self, _name):
                return EmptyCollection()

        classification = {
            "should_route": False,
            "actor_type": "automation",
            "reason": "automation_template",
            "message_id": "fixture-auto",
        }
        with patch.object(
            whatsapp_message_ledger, "classify_inbound", return_value=classification
        ), patch.object(
            whatsapp_message_ledger,
            "record_inbound",
            return_value={"ok": True, "ledger_id": "in:fixture-auto"},
        ), patch.object(whatsapp_automation.mongo_store, "get_db", return_value=EmptyDB()), patch.object(
            whatsapp_conversational, "conversational_reply"
        ) as conversation:
            result = whatsapp_automation.ingest_inbound_event(fixture_payload())
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "automation_template")
        conversation.assert_not_called()

    def test_interactive_confirmation_maps_to_existing_typed_command(self):
        payload = fixture_payload("")
        payload["data"]["message"] = {
            "buttonsResponseMessage": {"selectedButtonId": "maint.confirm.ABC123"}
        }
        self.assertEqual(whatsapp_evolution_parse.extract_message(payload), "confirmar ABC123")

    def test_untrusted_interactive_id_is_not_executable(self):
        payload = fixture_payload("")
        payload["data"]["message"] = {
            "buttonsResponseMessage": {"selectedButtonId": "shell.rm-rf"}
        }
        self.assertEqual(whatsapp_evolution_parse.extract_interactive_action(payload), "")

    def test_menu_buttons_map_only_to_typed_read_actions(self):
        payload = fixture_payload("")
        payload["data"]["message"] = {
            "buttonsResponseMessage": {"selectedButtonId": "menu.status"}
        }
        self.assertEqual(whatsapp_evolution_parse.extract_message(payload), "estado")
        payload["data"]["message"] = {
            "buttonsResponseMessage": {"selectedButtonId": "menu.custom"}
        }
        self.assertEqual(
            whatsapp_evolution_parse.extract_message(payload), "solicitud personalizada"
        )

    def test_owner_conversation_is_shared_across_lines(self):
        identity = {
            "authenticated": True,
            "principal_id": "principal_fixture_owner",
            "roles": ["owner"],
        }
        first = whatsapp_automation._canonical_conversation_id(
            "line-a@s.whatsapp.net", is_group=False, identity=identity
        )
        second = whatsapp_automation._canonical_conversation_id(
            "line-b@s.whatsapp.net", is_group=False, identity=identity
        )
        self.assertEqual(first, second)
        self.assertEqual(first, "owner:principal_fixture_owner:whatsapp")

    def test_groups_never_collapse_into_owner_conversation(self):
        identity = {
            "authenticated": True,
            "principal_id": "principal_fixture_owner",
            "roles": ["owner"],
        }
        result = whatsapp_automation._canonical_conversation_id(
            "fixture-group@g.us", is_group=True, identity=identity
        )
        self.assertEqual(result, "fixture-group@g.us")

    def test_security_hallucination_is_blocked_without_security_evidence(self):
        body, grounding = whatsapp_conversational._validate_grounded_response(
            "Revisé los registros y detecté malware por una actualización maliciosa.",
            [{"source": "health_snapshot", "evidence_ref": "health:fixture"}],
        )
        self.assertEqual(grounding["status"], "blocked")
        self.assertIn("evidencia técnica suficiente", body)
        self.assertNotIn("detecté malware", body)

    def test_negative_security_statement_remains_allowed(self):
        body, grounding = whatsapp_conversational._validate_grounded_response(
            "No hay evidencia de malware.", []
        )
        self.assertEqual(grounding["status"], "grounded")
        self.assertEqual(body, "No hay evidencia de malware.")


if __name__ == "__main__":
    unittest.main()
