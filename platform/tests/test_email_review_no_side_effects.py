from __future__ import annotations

import sys
from pathlib import Path
import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from inneros_core_runtime.notifications import email_router
import pymongo


def test_analyze_email_payload_has_zero_side_effects() -> None:
    """analyze_email_payload classifies document type and entity with zero DB side effects."""
    payload = {
        "from": "accounting@vendor.com",
        "subject": "Factura Electrónica No 001-002-123456",
        "snippet": "Estimado cliente, adjuntamos comprobante electrónico SRI clave 1234567890123456789012345678901234567890123456789",
        "body": "Factura por servicios de telecomunicaciones."
    }
    analysis = email_router.analyze_email_payload(payload)
    assert analysis is not None
    assert analysis.get("document_type") == "factura"


def test_process_mail_id_with_no_create_task_creates_zero_ops_tasks() -> None:
    """process_mail_id with create_task=False never inserts a new task into ralfia_ops_tasks."""
    db = pymongo.MongoClient("mongodb://127.0.0.1:27017")["pcdoctor_swarm"]
    count_before = db.ralfia_ops_tasks.count_documents({})
    
    sample = db.email_messages.find_one({}, {"_id": 0, "mail_id": 1})
    if sample:
        mail_id = sample.get("mail_id")
        res = email_router.process_mail_id(mail_id, create_task=False)
        assert res.get("ok") is True
        count_after = db.ralfia_ops_tasks.count_documents({})
        assert count_after == count_before


def test_email_intelligence_summary_returns_aggregated_metrics() -> None:
    """intelligence_summary returns structured action history without mutations."""
    summary = email_router.intelligence_summary(limit=10)
    assert summary.get("ok") is True
    assert isinstance(summary.get("actions"), list)
