import unittest
from unittest.mock import patch

from raphiia_openai import oauth_store


class Collection:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("Result", (), {"inserted_id": "fixture"})()


class DB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, Collection())


class TestOAuthChatGPTScopes(unittest.TestCase):
    def test_chatgpt_registration_gets_memory_and_agent_scopes_not_admin(self):
        db = DB()
        with patch.object(oauth_store, "ensure_indexes"), patch.object(
            oauth_store, "get_db", return_value=db
        ), patch.object(oauth_store, "redirect_uri_allowed", return_value=True):
            client = oauth_store.create_client(
                {
                    "client_name": "ChatGPT",
                    "redirect_uris": ["https://chatgpt.com/fixture"],
                    "scope": "ralfia:read ralfia:write",
                }
            )
        scopes = set(client["scope"].split())
        self.assertIn("ralfia:agents", scopes)
        self.assertIn("ralfia:private_memory", scopes)
        self.assertIn("ralfia:memory:read", scopes)
        self.assertIn("ralfia:memory:write", scopes)
        self.assertIn("ralfia:memory:finalize", scopes)
        self.assertNotIn("ralfia:admin", scopes)

    def test_generic_client_keeps_least_privilege(self):
        db = DB()
        with patch.object(oauth_store, "ensure_indexes"), patch.object(
            oauth_store, "get_db", return_value=db
        ), patch.object(oauth_store, "redirect_uri_allowed", return_value=True):
            client = oauth_store.create_client(
                {
                    "client_name": "Fixture client",
                    "redirect_uris": ["https://example.test/fixture"],
                    "scope": "ralfia:read ralfia:write",
                }
            )
        scopes = set(client["scope"].split())
        self.assertEqual(scopes, {"ralfia:read", "ralfia:write"})


if __name__ == "__main__":
    unittest.main()
