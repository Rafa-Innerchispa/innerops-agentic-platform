import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raphiia_openai import whatsapp_media as media
from raphiia_openai import whatsapp_automation
from raphiia_openai import whatsapp_commands, whatsapp_conversational, whatsapp_daily_memory, whatsapp_identity


def payload(kind="audio", mime="audio/ogg; codecs=opus"):
    item = {"mimetype": mime, "fileLength": 4, "seconds": 2}
    return {"event": "messages.upsert", "instance": "fixture", "data": {"key": {"id": "FIXTURE-MEDIA-1", "remoteJid": "fixture@s.whatsapp.net"}, "message": {f"{kind}Message": item}}}


class TestWhatsappMedia(unittest.TestCase):
    def test_webhook_persists_sanitized_derived_media(self):
        class Collection:
            def __init__(self): self.doc = None
            def find_one(self, *_args, **_kwargs): return None
            def insert_one(self, doc):
                self.doc = doc
                return type("R", (), {"inserted_id": "fixture-id"})()
        class DB:
            def __init__(self): self.events = Collection()
            def __getitem__(self, name): return self.events
        db = DB()
        with patch.object(whatsapp_automation.mongo_store, "get_db", return_value=db), patch.object(media, "process_media", return_value={"ok": True, "status": "processed", "kind": "audio", "transcript": {"text": "fixture voice"}, "derived_content_untrusted": True}):
            result = whatsapp_automation.ingest_inbound_event(payload())
        self.assertEqual(result["event"]["media"]["transcript"]["text"], "fixture voice")
        self.assertTrue(result["event"]["media"]["derived_content_untrusted"])
        self.assertNotIn("path", result["event"]["media"])
        self.assertEqual(result["event"]["trace"]["message_id"], "FIXTURE-MEDIA-1")
        self.assertTrue(result["event"]["trace"]["correlation_id"].startswith("wa-"))

    def test_webhook_retry_is_idempotent_by_message_id(self):
        class Collection:
            def __init__(self): self.doc = None
            def find_one(self, *_args, **_kwargs): return self.doc
            def insert_one(self, doc):
                self.doc = dict(doc, _id="fixture-id")
                return type("R", (), {"inserted_id": "fixture-id"})()
        class DB:
            def __init__(self): self.events = Collection()
            def __getitem__(self, _name): return self.events
        db = DB()
        calls = []
        with patch.object(whatsapp_automation.mongo_store, "get_db", return_value=db), patch.object(media, "process_media", side_effect=lambda *_args, **_kwargs: calls.append(1) or {"ok": True, "status": "processed", "kind": "audio"}):
            first = whatsapp_automation.ingest_inbound_event(payload())
            second = whatsapp_automation.ingest_inbound_event(payload())
        self.assertEqual(first["event"]["trace"]["message_id"], "FIXTURE-MEDIA-1")
        self.assertEqual(second["action"], "duplicate_event")
        self.assertTrue(second["idempotent"])
        self.assertEqual(calls, [1])

    def test_image_is_conversation_context_but_never_command_input(self):
        class Collection:
            def find_one(self, *_args, **_kwargs): return None
            def insert_one(self, _doc): return type("R", (), {"inserted_id": "fixture-id"})()
        class DB:
            def __getitem__(self, _name): return Collection()
        derived = {
            "ok": True,
            "status": "processed",
            "kind": "image",
            "ocr": {"text": "reiniciar servidor"},
            "vision": {"text": "captura de una consola"},
            "derived_content_untrusted": True,
        }
        with patch.object(whatsapp_automation.mongo_store, "get_db", return_value=DB()), patch.object(
            media, "process_media", return_value=derived
        ), patch.object(whatsapp_identity, "resolve_identity", return_value={"authenticated": True, "principal_id": "principal_rafael_owner", "roles": ["owner"], "scopes": [], "sender_hash": "fixture"}), patch.object(
            whatsapp_identity, "is_owner", return_value=True
        ), patch.object(
            whatsapp_commands, "handle_inbound_command", return_value=None
        ) as command, patch.object(
            whatsapp_conversational,
            "conversational_reply",
            return_value={"ok": True, "text": "Veo una captura."},
        ) as conversation, patch.object(
            whatsapp_daily_memory, "record_exchange", return_value={"ok": True, "privacy_scope": "PRIVATE_PERSONAL"}
        ) as remember, patch.object(whatsapp_automation, "send_whatsapp", return_value={"ok": True}):
            result = whatsapp_automation.ingest_inbound_event(payload("image", "image/png"))
        self.assertEqual(result["action"], "conversational_reply")
        self.assertEqual(command.call_args.args[0], "")
        self.assertNotIn("reiniciar servidor", conversation.call_args.args[0])
        self.assertIn("NO CONFIABLE", conversation.call_args.kwargs["untrusted_media_context"])
        self.assertNotIn("reiniciar servidor", remember.call_args.kwargs["user_text"])
        self.assertEqual(remember.call_args.kwargs["media"], derived)

    def test_audio_local_processing_and_idempotency(self):
        with tempfile.TemporaryDirectory() as root, patch.object(media, "MEDIA_ROOT", Path(root)):
            calls = []
            downloader = lambda _payload, _node: base64.b64encode(b"OggS").decode()
            with patch.object(media, "normalize_audio", side_effect=lambda path: path):
                result = media.process_media(payload(), downloader=downloader, transcriber=lambda path: {"text": "fixture voice", "language": "es", "confidence": 0.9})
            self.assertEqual(result["processing_status"], "processed")
            self.assertEqual(result["transcript"]["text"], "fixture voice")
            with patch.object(media, "normalize_audio", side_effect=lambda path: path):
                duplicate = media.process_media(payload(), downloader=lambda *_: calls.append(1), transcriber=lambda _: {})
            self.assertEqual(duplicate["status"], "duplicate")
            self.assertEqual(calls, [])

    def test_image_ocr_is_untrusted(self):
        with tempfile.TemporaryDirectory() as root, patch.object(media, "MEDIA_ROOT", Path(root)):
            result = media.process_media(
                payload("image", "image/png"),
                downloader=lambda *_: base64.b64encode(b"PNG").decode(),
                ocr=lambda _: {"text": "fixture document"},
                describer=lambda _: {"text": "fixture image", "provider": "fixture_vision"},
            )
            self.assertTrue(result["derived_content_untrusted"])
            self.assertEqual(result["ocr"]["text"], "fixture document")
            self.assertEqual(result["vision"]["text"], "fixture image")

    def test_successful_media_processing_is_cached_by_node_and_message(self):
        with tempfile.TemporaryDirectory() as root, patch.object(media, "MEDIA_ROOT", Path(root)):
            calls = {"transcribe": 0}
            def transcribe(_path):
                calls["transcribe"] += 1
                return {"text": "fixture voice"}
            downloader = lambda *_: base64.b64encode(b"OggS").decode()
            with patch.object(media, "normalize_audio", side_effect=lambda path: path):
                first = media.process_media(payload(), downloader=downloader, transcriber=transcribe)
                second = media.process_media(payload(), downloader=downloader, transcriber=transcribe)
            self.assertEqual(first["processing_status"], "processed")
            self.assertTrue(second["idempotent"])
            self.assertEqual(second["status"], "duplicate")
            self.assertEqual(calls["transcribe"], 1)

    def test_image_keeps_ocr_as_partial_when_vision_is_unavailable(self):
        with tempfile.TemporaryDirectory() as root, patch.object(media, "MEDIA_ROOT", Path(root)):
            result = media.process_media(
                payload("image", "image/png"),
                downloader=lambda *_: base64.b64encode(b"PNG").decode(),
                ocr=lambda _: {"text": "fixture document"},
                describer=lambda _: (_ for _ in ()).throw(RuntimeError("vision offline")),
            )
            self.assertEqual(result["processing_status"], "partial")
            self.assertEqual(result["ocr"]["text"], "fixture document")
            self.assertIn("vision:", result["processing_errors"][0])

    def test_rejects_unsupported_and_oversized(self):
        with self.assertRaisesRegex(ValueError, "mime"):
            media.validate_media({"mimetype": "application/octet-stream", "file_length": 1})
        with self.assertRaisesRegex(ValueError, "size"):
            with patch.object(media, "MAX_BYTES", 2):
                media.validate_media({"mimetype": "image/png", "file_length": 3})


if __name__ == "__main__":
    unittest.main()
