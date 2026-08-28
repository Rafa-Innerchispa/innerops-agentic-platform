from __future__ import annotations

import unittest
from unittest import mock

from raphiia_openai import local_discord_plane as discord


class LocalDiscordPlaneTests(unittest.TestCase):
    def test_redact_removes_bot_token_and_webhook(self) -> None:
        text = "Authorization: Bot abc.def.ghi https://discord.com/api/webhooks/123/secret"
        redacted = discord._redact(text)
        self.assertNotIn("abc.def.ghi", redacted)
        self.assertNotIn("/123/secret", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_status_without_token_or_webhook_is_configured_not_active(self) -> None:
        with mock.patch.object(discord, "_secret", return_value=("", "missing")):
            status = discord.discord_status()
        self.assertTrue(status["ok"])
        self.assertFalse(status["auth_ok"])
        self.assertFalse(status["bot_token_present"])
        self.assertFalse(status["webhook_present"])

    def test_send_channel_message_dry_run_does_not_require_token(self) -> None:
        with mock.patch.object(discord, "_config", return_value={"default_channel_id": "123", "default_guild_id": "", "application_id": "app", "public_key": "pub", "updated_at": None}):
            result = discord.send_channel_message(content="hello", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["channel_id"], "123")

    def test_list_channels_requires_guild_id(self) -> None:
        with mock.patch.object(discord, "_config", return_value={"default_channel_id": "", "default_guild_id": "", "application_id": "app", "public_key": "pub", "updated_at": None}):
            result = discord.list_channels()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "guild_id_required")

    def test_create_text_channel_dry_run_sanitizes_name(self) -> None:
        with mock.patch.object(discord, "_config", return_value={"default_channel_id": "", "default_guild_id": "guild", "application_id": "app", "public_key": "pub", "updated_at": None}):
            result = discord.create_text_channel("Novedades Ralphi IA!", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["channel"]["name"], "novedades-ralphi-ia")

    def test_list_channel_messages_requires_channel_id(self) -> None:
        with mock.patch.object(discord, "_config", return_value={"default_channel_id": "", "default_guild_id": "guild", "application_id": "app", "public_key": "pub", "updated_at": None}):
            result = discord.list_channel_messages()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "channel_id_required")

    def test_resolve_channel_uses_configured_map(self) -> None:
        cfg = {"default_channel_id": "1", "default_guild_id": "guild", "application_id": "app", "public_key": "pub", "channels": {"novedades": "2"}, "updated_at": None}
        with mock.patch.object(discord, "_config", return_value=cfg):
            result = discord.resolve_channel("novedades")
        self.assertTrue(result["ok"])
        self.assertEqual(result["channel_id"], "2")

    def test_search_channel_messages_matches_content(self) -> None:
        data = {"ok": True, "channel_id": "c", "messages": [{"content": "Hackathon update", "author": "RalphiIA"}]}
        with mock.patch.object(discord, "list_channel_messages", return_value=data):
            result = discord.search_channel_messages(channel_id="c", query="hackathon")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)

    def test_create_channel_webhook_dry_run_resolves_alias(self) -> None:
        with mock.patch.object(discord, "resolve_channel", return_value={"ok": True, "channel_id": "2"}):
            result = discord.create_channel_webhook("novedades", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["channel_id"], "2")

    def test_create_thread_requires_name(self) -> None:
        with mock.patch.object(discord, "resolve_channel", return_value={"ok": True, "channel_id": "2"}):
            result = discord.create_thread("novedades", "", dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "thread_name_required")

    def test_register_guild_commands_dry_run(self) -> None:
        cfg = {"default_channel_id": "1", "default_guild_id": "guild", "application_id": "app", "public_key": "pub", "channels": {}, "updated_at": None}
        with mock.patch.object(discord, "_config", return_value=cfg):
            result = discord.register_guild_commands(dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertGreaterEqual(len(result["commands"]), 4)

    def test_set_interactions_endpoint_url_dry_run(self) -> None:
        cfg = {"default_channel_id": "1", "default_guild_id": "guild", "application_id": "app", "public_key": "pub", "channels": {}, "updated_at": None}
        with mock.patch.object(discord, "_config", return_value=cfg):
            result = discord.set_interactions_endpoint_url("https://mcp.pcdoctor.ai/discord/interactions", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["endpoint_url"], "https://mcp.pcdoctor.ai/discord/interactions")

    def test_set_interactions_endpoint_url_rejects_non_interactions_url(self) -> None:
        cfg = {"default_channel_id": "1", "default_guild_id": "guild", "application_id": "app", "public_key": "pub", "channels": {}, "updated_at": None}
        with mock.patch.object(discord, "_config", return_value=cfg):
            result = discord.set_interactions_endpoint_url("http://example.com/anything", dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "https_discord_interactions_url_required")

    def test_add_reaction_requires_fields(self) -> None:
        result = discord.add_reaction("", "m", "✅", dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "channel_message_emoji_required")

    def test_resource_provider_is_not_model_runtime(self) -> None:
        with mock.patch.object(discord, "discord_status", return_value={"auth_ok": False, "webhook_present": False, "bot_user": None}):
            provider = discord.resource_provider_document()
        self.assertEqual(provider["provider_id"], "discord-ops")
        self.assertEqual(provider["cost_policy"], "external_messaging_only_no_model_spend")
        self.assertIn("approval_requests", provider["capabilities"])


if __name__ == "__main__":
    unittest.main()
