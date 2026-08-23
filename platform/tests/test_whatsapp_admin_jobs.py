import unittest
from unittest.mock import patch

from raphiia_openai import whatsapp_admin_jobs as jobs


def match(doc, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(match(doc, part) for part in expected):
                return False
            continue
        actual = doc.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$gte" in expected and not (actual and actual >= expected["$gte"]):
                return False
        elif actual != expected:
            return False
    return True


class Result:
    def __init__(self, modified=1): self.modified_count = modified


class Collection:
    def __init__(self): self.docs = []
    def insert_one(self, doc): self.docs.append(dict(doc)); return Result()
    def find_one(self, query, _projection=None, sort=None):
        rows = [doc for doc in self.docs if match(doc, query)]
        if sort and rows:
            field, direction = sort[0]
            rows.sort(key=lambda item: item.get(field, ""), reverse=direction < 0)
        return rows[0] if rows else None
    def count_documents(self, query): return sum(1 for doc in self.docs if match(doc, query))
    def update_one(self, query, update, upsert=False):
        doc = self.find_one(query)
        if doc is None and upsert:
            doc = {key: value for key, value in query.items() if not key.startswith("$") and not isinstance(value, dict)}
            self.docs.append(doc)
        if doc is None: return Result(0)
        doc.update(update.get("$set", {}))
        return Result(1)
    def delete_one(self, query):
        self.docs[:] = [doc for doc in self.docs if not match(doc, query)]


class DB:
    def __init__(self): self.cols = {}
    def __getitem__(self, name): return self.cols.setdefault(name, Collection())


def owner_identity(sender, chat_id=None):
    digits = "".join(char for char in sender if char.isdigit())
    return {
        "authenticated": True,
        "principal_id": "principal_rafael_owner",
        "preferred_name": "Rafael",
        "roles": ["owner"],
        "scopes": list(jobs.whatsapp_identity.OWNER_SCOPES),
        "sender_hash": f"hash-{digits[-4:]}",
    }


def operations_identity(sender, chat_id=None):
    digits = "".join(char for char in sender if char.isdigit())
    return {
        "authenticated": True,
        "principal_id": "principal_pcdoctor_operations",
        "preferred_name": "PC Doctor",
        "roles": ["operational_line"],
        "scopes": list(jobs.whatsapp_identity.OPS_SCOPES),
        "sender_hash": f"hash-{digits[-4:]}",
    }


class TestAdminJobs(unittest.TestCase):
    def setUp(self): self.db = DB()

    def test_confirmation_is_bound_to_same_sender_and_chat(self):
        before = {"ok": True, "healthy": False, "system_state": "inactive", "health": "down"}
        with patch.object(jobs.mongo_store, "get_db", return_value=self.db), patch.object(
            jobs, "_identity", side_effect=owner_identity
        ), patch.object(jobs.whatsapp_service_ops, "service_status", return_value=before):
            pending = jobs.request_service_action(
                "593000000111",
                chat_id="chat-owner-a",
                service="mcp",
                node="amd",
                action="recover",
                trace={"correlation_id": "fixture-op-1"},
            )
            self.assertEqual(pending["status"], "pending_confirmation")
            self.assertEqual(pending["interactive"]["kind"], "buttons")
            self.assertTrue(pending["interactive"]["buttons"][0]["id"].startswith("maint.confirm."))
            self.assertEqual(
                jobs.confirm_job("593000000222", pending["challenge"], chat_id="chat-owner-a")["error"],
                "sender_mismatch",
            )
            self.assertEqual(
                jobs.confirm_job("593000000111", pending["challenge"], chat_id="chat-owner-b")["error"],
                "chat_mismatch",
            )
            approved = jobs.confirm_job("593000000111", pending["challenge"], chat_id="chat-owner-a")
            self.assertEqual(approved["status"], "approved")
            self.assertEqual(
                jobs.confirm_job("593000000111", pending["challenge"], chat_id="chat-owner-a")["error"],
                "job_not_pending",
            )

    def test_cancellation_is_one_time_and_bound_to_same_chat(self):
        before = {"ok": True, "healthy": False, "system_state": "inactive", "health": "down"}
        with patch.object(jobs.mongo_store, "get_db", return_value=self.db), patch.object(
            jobs, "_identity", side_effect=owner_identity
        ), patch.object(jobs.whatsapp_service_ops, "service_status", return_value=before):
            pending = jobs.request_service_action(
                "593000000111", chat_id="chat-owner-a", service="mcp", node="amd", action="recover"
            )
            self.assertEqual(
                jobs.cancel_job("593000000111", pending["job_id"], chat_id="chat-owner-b")["error"],
                "chat_mismatch",
            )
            cancelled = jobs.cancel_job("593000000111", pending["job_id"], chat_id="chat-owner-a")
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(
                jobs.cancel_job("593000000111", pending["job_id"], chat_id="chat-owner-a")["error"],
                "job_not_pending",
            )

    def test_healthy_recovery_is_skipped_without_challenge(self):
        healthy = {"ok": True, "healthy": True, "system_state": "active", "health": "up"}
        with patch.object(jobs.mongo_store, "get_db", return_value=self.db), patch.object(
            jobs, "_identity", side_effect=owner_identity
        ), patch.object(jobs.whatsapp_service_ops, "service_status", return_value=healthy):
            result = jobs.request_service_action(
                "593000000111", chat_id="chat", service="portal", node="primary", action="recover"
            )
        self.assertTrue(result["skipped"])
        self.assertEqual(self.db[jobs.COLLECTION].docs, [])

    def test_operational_line_can_request_but_only_owner_can_confirm(self):
        before = {"ok": True, "healthy": False, "system_state": "inactive", "health": "down"}

        def resolve(sender, chat_id=None):
            return owner_identity(sender, chat_id) if sender.endswith("111") else operations_identity(sender, chat_id)

        with patch.object(jobs.mongo_store, "get_db", return_value=self.db), patch.object(
            jobs, "_identity", side_effect=resolve
        ), patch.object(jobs.whatsapp_service_ops, "service_status", return_value=before), patch.object(
            jobs, "_notify_owner_for_approval", return_value=[{"ok": True}]
        ):
            pending = jobs.request_service_action(
                "593000000222",
                chat_id="chat-operations",
                service="mcp",
                node="amd",
                action="recover",
                trace={"correlation_id": "fixture-cross-principal"},
            )
            self.assertEqual(pending["status"], "pending_confirmation")
            self.assertNotIn("interactive", pending)
            self.assertEqual(
                jobs.confirm_job("593000000222", pending["challenge"], chat_id="chat-operations")["error"],
                "unauthorized_principal",
            )
            approved = jobs.confirm_job(
                "593000000111", pending["challenge"], chat_id="chat-owner"
            )
            self.assertEqual(approved["status"], "approved")
            stored = self.db[jobs.COLLECTION].docs[0]
            self.assertEqual(stored["principal_id"], "principal_pcdoctor_operations")
            self.assertEqual(stored["approval_principal_id"], jobs.whatsapp_identity.OWNER_PRINCIPAL_ID)

    def test_arbitrary_service_and_action_are_denied(self):
        with patch.object(jobs.mongo_store, "get_db", return_value=self.db), patch.object(
            jobs, "_identity", side_effect=owner_identity
        ):
            unknown = jobs.request_service_action(
                "593000000111", chat_id="chat", service="ssh", node="primary", action="restart"
            )
            forbidden = jobs.request_service_action(
                "593000000111", chat_id="chat", service="mcp", node="primary", action="shell"
            )
        self.assertEqual(unknown["error"], "service_not_allowlisted")
        self.assertEqual(forbidden["error"], "action_not_allowlisted")

    def test_install_never_requests_or_executes_sudo_password(self):
        with patch.object(jobs.mongo_store, "get_db", return_value=self.db), patch.object(
            jobs, "_identity", side_effect=owner_identity
        ):
            pending = jobs.request_install("593000000111", chat_id="chat")
        self.assertIn("no enviaré ni pediré", pending["text"])
        self.assertEqual(self.db[jobs.COLLECTION].docs[0]["execution"], "disabled_until_sudo_policy")

    def test_recent_completed_operation_enforces_cooldown(self):
        self.db[jobs.COLLECTION].docs.append(
            {
                "job_id": "fixture-completed",
                "principal_id": "principal_rafael_owner",
                "node": "amd",
                "service": "mcp",
                "status": "completed",
                "finished_at": jobs._now(),
                "created_at": jobs._now(),
            }
        )
        before = {"ok": True, "healthy": False, "system_state": "inactive", "health": "down"}
        with patch.object(jobs.mongo_store, "get_db", return_value=self.db), patch.object(
            jobs, "_identity", side_effect=owner_identity
        ), patch.object(jobs.whatsapp_service_ops, "service_status", return_value=before):
            result = jobs.request_service_action(
                "593000000111",
                chat_id="chat",
                service="mcp",
                node="amd",
                action="restart",
                trace={"message_id": "fixture-new-message"},
            )
        self.assertEqual(result["error"], "maintenance_cooldown")
        self.assertEqual(result["job_id"], "fixture-completed")


if __name__ == "__main__": unittest.main()
