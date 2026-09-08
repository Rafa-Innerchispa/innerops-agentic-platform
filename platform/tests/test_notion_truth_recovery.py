import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import raphiia_openai
from raphiia_openai import hybrid_context


class NotionTruthRecoveryTests(unittest.TestCase):
    def _install_fake_notion_bridge(self, pages):
        fake = types.SimpleNamespace(search_notion_pages=mock.Mock(return_value={"ok": True, "pages": pages}))
        old_module = sys.modules.get("raphiia_openai.notion_bridge")
        old_attr = getattr(raphiia_openai, "notion_bridge", None)
        had_attr = hasattr(raphiia_openai, "notion_bridge")
        sys.modules["raphiia_openai.notion_bridge"] = fake
        setattr(raphiia_openai, "notion_bridge", fake)
        return fake, old_module, old_attr, had_attr

    def _restore_fake_notion_bridge(self, old_module, old_attr, had_attr):
        if old_module is None:
            sys.modules.pop("raphiia_openai.notion_bridge", None)
        else:
            sys.modules["raphiia_openai.notion_bridge"] = old_module
        if had_attr:
            setattr(raphiia_openai, "notion_bridge", old_attr)
        else:
            try:
                delattr(raphiia_openai, "notion_bridge")
            except AttributeError:
                pass

    def test_hybrid_search_uses_notion_api_when_qdrant_has_no_hits(self):
        fake, old_module, old_attr, had_attr = self._install_fake_notion_bridge([
            {
                "id": "page-1",
                "title": "Conversation Memory Autopilot v1 - implementacion focalizada",
                "url": "https://app.notion.com/p/page-1",
                "doc_id": "DRAFT-memory",
                "last_edited_time": "2026-09-06T00:00:00.000Z",
            }
        ])
        try:
            with mock.patch.object(hybrid_context.mongo_store, "search_memory", return_value=[]), \
                mock.patch.object(hybrid_context.mongo_store, "search", return_value=[]), \
                mock.patch.object(hybrid_context, "qdrant_health", return_value={"ok": True, "points_count": 99011}), \
                mock.patch.object(hybrid_context, "qdrant_search", return_value=[]):
                result = hybrid_context.hybrid_search(
                    "Conversation Memory Autopilot save_conversation_batch finalize_conversation",
                    limit=5,
                )
        finally:
            self._restore_fake_notion_bridge(old_module, old_attr, had_attr)
        self.assertTrue(result["ok"])
        self.assertEqual(result["results"][0]["source"], "notion_api")
        self.assertEqual(result["results"][0]["notion_page_id"], "page-1")
        fake.search_notion_pages.assert_called_once()

    def test_hybrid_search_does_not_call_notion_api_when_qdrant_has_hits(self):
        fake, old_module, old_attr, had_attr = self._install_fake_notion_bridge([])
        try:
            with mock.patch.object(hybrid_context.mongo_store, "search_memory", return_value=[]), \
                mock.patch.object(hybrid_context.mongo_store, "search", return_value=[]), \
                mock.patch.object(hybrid_context, "qdrant_health", return_value={"ok": True, "points_count": 99011}), \
                mock.patch.object(hybrid_context, "qdrant_search", return_value=[{
                    "source": "qdrant",
                    "score": 12.0,
                    "title": "Indexed result",
                    "text": "local indexed content",
                }]):
                result = hybrid_context.hybrid_search("indexed query", limit=5)
        finally:
            self._restore_fake_notion_bridge(old_module, old_attr, had_attr)
        self.assertTrue(result["ok"])
        self.assertEqual(result["results"][0]["source"], "qdrant")
        fake.search_notion_pages.assert_not_called()

    def test_settings_loads_central_runtime_env_candidate(self):
        source = Path("platform/inneros_core_runtime/settings.py").read_text()
        self.assertIn("INNEROS_RUNTIME_ENV", source)
        self.assertIn("/home/rlopez/inneros/inneros_core/platform/.env", source)
        self.assertIn("override=False", source)


if __name__ == "__main__":
    unittest.main()
