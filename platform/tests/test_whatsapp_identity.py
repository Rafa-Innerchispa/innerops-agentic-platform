import unittest
from unittest.mock import patch

from raphiia_openai import whatsapp_identity as identity


class Collection:
    def __init__(self, doc=None): self.doc = doc
    def find_one(self, _query, _projection=None): return self.doc


class DB:
    def __init__(self, doc=None): self.collection = Collection(doc)
    def __getitem__(self, _name): return self.collection


class TestWhatsappIdentity(unittest.TestCase):
    def test_ecuador_numbers_normalize_to_e164(self):
        self.assertEqual(identity.normalize_e164("099 000 0000"), "+593990000000")
        self.assertEqual(identity.normalize_e164("593990000000@s.whatsapp.net"), "+593990000000")
        self.assertEqual(identity.normalize_e164("593990000000:42@s.whatsapp.net"), "+593990000000")
        self.assertEqual(identity.normalize_e164("invalid"), "")

    def test_verified_registry_grants_owner(self):
        doc = {
            "principal_id": identity.OWNER_PRINCIPAL_ID,
            "preferred_name": "Rafael",
            "roles": ["owner"],
            "scopes": list(identity.OWNER_SCOPES),
            "status": "verified",
            "channel_account": "fixture",
        }
        with patch.object(identity.mongo_store, "get_db", return_value=DB(doc)):
            resolved = identity.resolve_identity("+593990000000", chat_id="fixture-chat")
        self.assertTrue(identity.is_owner(resolved))
        self.assertTrue(identity.has_scope(resolved, "whatsapp:maintenance:confirm"))
        self.assertNotIn("e164", resolved)

    def test_claiming_name_or_crm_collision_never_grants_owner(self):
        with patch.object(identity.mongo_store, "get_db", return_value=DB(None)):
            resolved = identity.resolve_identity("+593980000000", chat_id="soy Rafael")
        self.assertFalse(resolved["authenticated"])
        self.assertFalse(identity.is_owner(resolved))
        self.assertEqual(resolved["reason"], "identity_not_registered")

    def test_evolution_discovery_falls_back_from_lid_to_phone_number(self):
        fixture = [{"name": "fixture-primary", "ownerJid": "12345678901234567890@lid", "number": "593970000001"}]
        with patch.object(identity, "_evolution_instances", side_effect=[fixture, []]), patch.object(
            identity.settings, "EVOLUTION_INSTANCE", "fixture-primary"
        ), patch.object(identity.settings, "EVOLUTION_AMD_INSTANCE", "fixture-amd"):
            discovered = identity.discover_evolution_owner_lines()
        self.assertEqual(discovered[0]["e164"], "+593970000001")
        self.assertEqual(discovered[0]["node"], "primary")

    def test_bootstrap_dry_run_separates_owner_operations_and_evolution(self):
        with patch.object(
            identity,
            "discover_evolution_owner_lines",
            return_value=[
                {"e164": "+593970000001", "node": "primary", "instance": "fixture-primary"},
                {"e164": "+593970000002", "node": "amd", "instance": "fixture-amd"},
            ],
        ), patch.object(identity, "collision_report", return_value={"ok": True}):
            result = identity.bootstrap_owner_registry(
                ["+593990000001", "+593990000002"], apply=False
            )
        self.assertEqual(result["candidate_count"], 4)
        by_role = {item["roles"][0]: item for item in result["preview"]}
        self.assertEqual(by_role["owner"]["principal_id"], identity.OWNER_PRINCIPAL_ID)
        self.assertEqual(by_role["operational_line"]["principal_id"], identity.OPERATIONS_PRINCIPAL_ID)
        service_rows = [item for item in result["preview"] if item["roles"] == ["service_principal"]]
        self.assertEqual(len(service_rows), 2)
        self.assertIn("whatsapp:maintenance:confirm", by_role["owner"]["scopes"])
        self.assertNotIn("whatsapp:maintenance:confirm", by_role["operational_line"]["scopes"])
        self.assertTrue(all("whatsapp:maintenance:confirm" not in row["scopes"] for row in service_rows))


if __name__ == "__main__": unittest.main()
