#!/usr/bin/env python3
"""Verificación E2E MCP — party, PC Doctor, MOD-ACCOUNTING AP+AR."""

from __future__ import annotations

import asyncio
import sys

from raphiia_openai.mcp_catalog import tool_catalog as tc
import raphiia_openai.mcp_server as mcp
from raphiia_openai.mongo_store import get_db


def cleanup(db):
    db.ops_clients.delete_many({"tax_id": "7770001112001"})
    db.ops_sites.delete_many({"name": "E2E_SITE_MCP"})
    db.accounting_payables.delete_many({"supplier_name": "E2E_SUPPLIER_MCP"})
    db.accounting_receivables.delete_many({"client_name": "E2E_CLIENT_AR"})
    db.accounting_payments.delete_many({"notes": "e2e_full_mcp"})


def run_flow() -> None:
    db = get_db()
    cleanup(db)
    errors: list[str] = []

    def check(name: str, cond: bool, detail: str = ""):
        if cond:
            print(f"  OK  {name}")
        else:
            errors.append(f"{name}: {detail}")
            print(f"  FAIL {name} — {detail}")

    print("=== MCP VERSION ===")
    v = mcp.mcp_version()
    check("catalog_version", v.get("catalog_version") == tc.MCP_VERSION, v)
    check("tool_count", v.get("runtime_tool_count") == len(tc.ALL_MCP_TOOL_NAMES), v)

    print("\n=== PARTY ===")
    rp = mcp.resolve_party("UArtes")
    check("resolve_party", rp.get("count", 0) >= 1, str(rp))

    print("\n=== PC DOCTOR (idempotente) ===")
    cp = {"display_name": "E2E_CLIENT_MCP", "tax_id": "7770001112001", "entity_ids": ["ent_pcdoctor"]}
    c1 = mcp.create_client_draft(cp)
    c2 = mcp.create_client_draft(cp)
    check("client idempotent", c2.get("reused") and c1["draft_id"] == c2["draft_id"], str(c2))
    uc = mcp.upsert_client({"client_draft_id": c1["draft_id"]})
    client_id = uc.get("client_id", "")
    check("upsert_client", bool(client_id), str(uc))
    sp = {"client_id": client_id, "name": "E2E_SITE_MCP", "address": "Test 1"}
    s1 = mcp.create_site_draft(sp)
    s2 = mcp.create_site_draft(sp)
    check("site idempotent", s2.get("reused") and s1["draft_id"] == s2["draft_id"], str(s2))

    print("\n=== ACCOUNTING AP ===")
    pp = {
        "supplier_name": "E2E_SUPPLIER_MCP",
        "tax_id": "8880001113001",
        "amount": 999,
        "due_date": "2026-07-25",
        "check_number": "E2E-CHK-99",
        "entity_id": "ent_pcdoctor",
    }
    p1 = mcp.create_payable_draft(pp)
    p2 = mcp.create_payable_draft(pp)
    check("payable idempotent", p2.get("reused") and p1["draft_id"] == p2["draft_id"], str(p2))
    up = mcp.upsert_payable({"payable_draft_id": p1["draft_id"], "status": "approved"})
    pid = up.get("payable_id", "")
    pay = mcp.record_payment({"payable_id": pid, "method": "check", "notes": "e2e_full_mcp"})
    check("record_payment", pay.get("payable", {}).get("status") == "paid", str(pay))

    wa = mcp.create_payable_from_whatsapp("cheque: WhatsApp Test 500 vence 2026-07-30")
    check("whatsapp payable", wa.get("ok") and wa.get("draft_id"), str(wa))

    print("\n=== ACCOUNTING AR ===")
    rp2 = {
        "client_name": "E2E_CLIENT_AR",
        "amount": 1200,
        "due_date": "2026-08-01",
        "quote_id": "quotedraft_e2e_test",
        "entity_id": "ent_pcdoctor",
    }
    r1 = mcp.create_receivable_draft(rp2)
    r2 = mcp.create_receivable_draft(rp2)
    check("receivable idempotent", r2.get("reused") and r1["draft_id"] == r2["draft_id"], str(r2))
    ur = mcp.upsert_receivable({"receivable_draft_id": r1["draft_id"], "status": "sent"})
    rid = ur.get("receivable_id", "")
    col = mcp.record_collection({"receivable_id": rid, "amount": 1200, "notes": "e2e_full_mcp"})
    check("record_collection", col.get("receivable", {}).get("status") == "paid", str(col))
    lo = mcp.list_receivables_open(entity_id="ent_pcdoctor")
    check("list_receivables_open", lo.get("ok"), str(lo))

    print("\n=== SUMMARY ===")
    sm = mcp.accounting_summary(entity_id="ent_pcdoctor")
    check("accounting_summary", sm.get("phase") == "AP_AR_v2" and sm.get("ok"), str(sm))

    print("\n=== DIAGNOSE STALE ===")
    dg = mcp.diagnose_mcp_session(client_tool_count=85, client_catalog_version="2.16.0")
    check("server 2.21 expected", dg.get("expected_catalog_version") == tc.MCP_VERSION, str(dg.get("expected_catalog_version")))

    cleanup(db)
    db.accounting_payables.delete_many({"supplier_name": {"$regex": "WhatsApp Test"}})

    if errors:
        print("\nFAILED:", len(errors))
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("\n=== ALL E2E PASSED ===")


async def verify_tools():
    tools = await mcp.mcp.list_tools()
    runtime = sorted(t.name for t in tools)
    catalog = sorted(tc.ALL_MCP_TOOL_NAMES)
    if runtime != catalog:
        missing = set(catalog) - set(runtime)
        extra = set(runtime) - set(catalog)
        print("CATALOG MISMATCH missing", missing, "extra", extra)
        sys.exit(1)
    print(f"Runtime tools: {len(runtime)} == catalog {len(catalog)}")


if __name__ == "__main__":
    asyncio.run(verify_tools())
    run_flow()
