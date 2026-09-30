import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raphiia_openai import document_vault
from raphiia_openai.operational import pcdoctor_store


class _Cursor(list):
    def sort(self, *args, **kwargs):
        return self

    def limit(self, limit):
        return _Cursor(self[:limit])


class _Collection:
    def __init__(self):
        self.docs = []

    def find_one(self, query, sort=None):
        found = list(self.find(query))
        if sort:
            for key, direction in reversed(sort):
                found.sort(key=lambda doc: doc.get(key) or 0, reverse=direction < 0)
        return dict(found[0]) if found else None

    def insert_one(self, doc):
        self.docs.append(dict(doc))

    def update_one(self, query, update):
        matched = 0
        modified = 0
        for doc in self.docs:
            if self._match(doc, query):
                matched = 1
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
                for key, inc in update.get("$inc", {}).items():
                    doc[key] = int(doc.get(key) or 0) + int(inc)
                for key, value in update.get("$push", {}).items():
                    doc.setdefault(key, []).append(value)
                modified = 1
                break
        return type("Result", (), {"matched_count": matched, "modified_count": modified})()

    def find(self, query):
        return _Cursor([dict(doc) for doc in self.docs if self._match(doc, query)])

    def count_documents(self, query):
        return len(list(self.find(query)))

    def _match(self, doc, query):
        for key, expected in query.items():
            if key == "$or":
                if not any(self._match(doc, item) for item in expected):
                    return False
                continue
            actual = doc.get(key)
            if isinstance(expected, dict) and "$ne" in expected:
                if actual == expected["$ne"]:
                    return False
                continue
            if isinstance(expected, dict) and "$regex" in expected:
                import re

                if not re.search(expected["$regex"], str(actual or ""), re.I):
                    return False
                continue
            if actual != expected:
                return False
        return True


class DocumentVaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "vault"
        self.collection = _Collection()
        self.collection_patch = patch("raphiia_openai.document_vault._collection", return_value=self.collection)
        self.root_patch = patch.object(document_vault, "ROOT", self.root)
        self.collection_patch.start()
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.collection_patch.stop()
        self.tmp.cleanup()

    def _source(self, name="proposal.pdf", body=b"v1"):
        path = Path(self.tmp.name) / name
        path.write_bytes(body)
        return path

    def test_ingest_dedupe_search_get_export(self):
        source = self._source()
        result = document_vault.document_vault_ingest(
            local_path=str(source),
            entity_type="client",
            entity_ref="Fixture Client X",
            category="commercial",
            title="Executive Proposal",
            make_canonical=True,
            tags=["FEMAR", "final"],
        )
        self.assertTrue(result["ok"])
        doc_id = result["document_id"]
        self.assertTrue(Path(result["document"]["file_ref"]["path"]).is_file())

        reused = document_vault.document_vault_ingest(
            local_path=str(source),
            entity_type="client",
            entity_ref="Fixture Client X",
            category="commercial",
            title="Executive Proposal",
        )
        self.assertTrue(reused["reused"])

        search = document_vault.document_vault_search("Executive Proposal")
        self.assertEqual(search["count"], 1)
        got = document_vault.document_vault_get(natural_query="Executive Proposal")
        self.assertEqual(got["document"]["document_id"], doc_id)
        exported = document_vault.document_vault_export_file(doc_id)
        self.assertTrue(exported["ok"])
        self.assertEqual(exported["file_ref"]["document_id"], doc_id)

    def test_new_canonical_supersedes_previous(self):
        first = document_vault.document_vault_ingest(
            local_path=str(self._source("deck.pdf", b"first")),
            entity_type="client",
            entity_ref="Fixture Client X",
            category="commercial",
            title="Executive Deck",
            make_canonical=True,
        )["document"]
        second = document_vault.document_vault_ingest(
            local_path=str(self._source("deck2.pdf", b"second")),
            entity_type="client",
            entity_ref="Fixture Client X",
            category="commercial",
            title="Executive Deck",
            make_canonical=True,
        )["document"]
        versions = document_vault.document_vault_versions(document_id=second["document_id"])
        statuses = {doc["document_id"]: doc["status"] for doc in versions["versions"]}
        self.assertEqual(statuses[first["document_id"]], "superseded")
        self.assertEqual(statuses[second["document_id"]], "canonical")

    def test_client_document_wrapper_uses_vault_for_local_files(self):
        with patch("raphiia_openai.operational.pcdoctor_store._list_visit_events", return_value=[]):
            result = pcdoctor_store.register_client_document(
                {
                    "client_id": "client_fixture_x",
                    "local_path": str(self._source("client.pdf", b"client")),
                    "title": "Client Contract",
                    "make_canonical": True,
                }
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["document"]["is_canonical"])
            listed = pcdoctor_store.list_client_documents("client_fixture_x")
            self.assertEqual(listed["source"], "document_vault")
            self.assertEqual(listed["count"], 1)


if __name__ == "__main__":
    unittest.main()
