import hashlib
import unittest
from unittest.mock import MagicMock, patch
from inneros_core_runtime import oauth_store
from inneros_core_runtime.oauth_metadata import authorization_server_metadata


class TestUnifiedSSO(unittest.TestCase):
    def test_scrypt_password_hashing_and_verification(self):
        password = "SecureTestPassword2026!"
        hashed = oauth_store.hash_password(password)
        self.assertTrue(hashed.startswith("scrypt$N=16384"))
        self.assertTrue(oauth_store.verify_password(hashed, password))
        self.assertFalse(oauth_store.verify_password(hashed, "WrongPassword"))

    def test_sha256_auto_migration(self):
        password = "LegacyPassword123"
        legacy_hash = hashlib.sha256(password.encode()).hexdigest()

        mock_db = MagicMock()
        user_doc = {
            "_id": "mock_id_123",
            "username": "test_legacy_user",
            "password_hash": legacy_hash,
        }

        # Verify legacy hash works and triggers database upgrade
        valid = oauth_store.verify_and_upgrade_password(user_doc, password, db=mock_db)
        self.assertTrue(valid)
        mock_db.users.update_one.assert_called_once()
        args, kwargs = mock_db.users.update_one.call_args
        updated_hash = kwargs["$set"]["password_hash"] if "$set" in kwargs else args[1]["$set"]["password_hash"]
        self.assertTrue(updated_hash.startswith("scrypt$"))

    def test_sso_session_lifecycle(self):
        with patch("inneros_core_runtime.oauth_store.get_db") as mock_get_db:
            fake_db = MagicMock()
            mock_get_db.return_value = fake_db

            sess = oauth_store.create_sso_session("rafagye", role="admin", display_name="Rafael Lopez")
            self.assertTrue(sess["session_id"].startswith("sso_"))
            self.assertEqual(sess["username"], "rafagye")
            self.assertEqual(sess["role"], "admin")
            fake_db[oauth_store.COL_SSO_SESSIONS].insert_one.assert_called_once()

    def test_pkce_authorization_code_flow(self):
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        challenge = oauth_store._pkce_s256(verifier)
        self.assertTrue(len(challenge) > 20)

    def test_redirect_uri_allowlist(self):
        self.assertTrue(oauth_store.redirect_uri_allowed("https://chatgpt.com/auth/callback"))
        self.assertTrue(oauth_store.redirect_uri_allowed("https://sub.chatgpt.com/callback"))
        self.assertFalse(oauth_store.redirect_uri_allowed("https://evil-hacker.com/callback"))

    def test_oidc_metadata_endpoints(self):
        meta = authorization_server_metadata("auth.pcdoctor.ai")
        self.assertIn("userinfo_endpoint", meta)
        self.assertIn("introspection_endpoint", meta)
        self.assertIn("jwks_uri", meta)
        self.assertIn("openid", meta["scopes_supported"])


if __name__ == "__main__":
    unittest.main()
