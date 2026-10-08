"""WhatsApp two-step Cursor owner order."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest import mock

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import cursor_whatsapp_jobs as cwj


def test_request_pattern_accepts_procede_cursor_with_correlation():
    msg = "procede cursor inneros-core-autonomy-model-pin-20261008"
    assert cwj.REQUEST_RE.match(msg)
    with mock.patch.object(cwj.mongo_store, "get_db") as gdb:
        col = mock.MagicMock()
        gdb.return_value = {cwj.COL: col}
        out = cwj.request_order("593963782369", msg, chat_id="593963782369")
    assert out["ok"] is True
    assert out["job_id"].startswith("co_")
    assert "confirmar" in out["text"]
    col.insert_one.assert_called_once()


def test_confirm_job_calls_owner_order_execute():
    job = {
        "job_id": "co_deadbeef",
        "sender": "593963782369",
        "status": "pending",
        "correlation_id": "inneros-core-autonomy-model-pin-20261008",
        "task_id": None,
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    with mock.patch.object(cwj.mongo_store, "get_db") as gdb:
        col = mock.MagicMock()
        col.find_one.return_value = job
        gdb.return_value = {cwj.COL: col}
        with mock.patch(
            "inneros_core_runtime.cursor_whatsapp_jobs.owner_order_execute",
            return_value={"ok": True, "claim": {"task_id": "ops_x", "pinned_model": "composer-2.5-fast", "title": "t"}},
        ) as execute:
            out = cwj.confirm_job("593963782369", "co_deadbeef")
    execute.assert_called_once()
    assert out["ok"] is True
    assert "Cursor claim OK" in out["text"]


def test_whatsapp_commands_route_confirm_co_before_admin_jobs():
    from inneros_core_runtime import whatsapp_commands as wc

    with mock.patch.object(wc.whatsapp_identity, "resolve_identity", return_value={"verified": True}):
        with mock.patch.object(wc.whatsapp_identity, "is_owner", return_value=True):
            with mock.patch.object(wc.whatsapp_identity, "has_scope", return_value=True):
                with mock.patch(
                    "inneros_core_runtime.cursor_whatsapp_jobs.confirm_job",
                    return_value={"ok": True, "text": "ok"},
                ) as confirm:
                    with mock.patch.object(wc, "send_whatsapp", return_value={"ok": True}):
                        result = wc.handle_inbound_command(
                            "confirmar co_abcd1234",
                            "593963782369",
                            reply=False,
                        )
    confirm.assert_called_once_with("593963782369", "co_abcd1234")
    assert result["command"] == "cursor_ops_job"
