#!/usr/bin/env python3
"""Smoke Contifico MCP capabilities (local gateway + optional live API)."""

from __future__ import annotations

import json
import sys

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inneros_core_runtime.capability_gateway import capability_describe, capability_invoke, capability_search


def main() -> int:
    report: dict = {"steps": []}

    def step(name: str, res: dict) -> None:
        report["steps"].append({"name": name, "ok": bool(res.get("ok")), "summary": {k: res.get(k) for k in ("ok", "error", "status") if k in res}})

    search = capability_search(query="contifico", max_results=15)
    step("capability_search", search)

    desc = capability_describe("contifico.connection.status.v1")
    step("capability_describe", desc)

    status = capability_invoke("contifico.connection.status.v1", {})
    step("capability_invoke_status", status)
    if status.get("entities"):
        report["entities"] = [
            {k: e.get(k) for k in ("entity_id", "configured", "connected", "expected_ruc", "connected_company_ruc", "message")}
            for e in status["entities"]
        ]

    cust = capability_invoke(
        "contifico.customer.search.v1",
        {"cedula": "0914832423", "max_pages": 5, "entity_id": "pcdoctor"},
    )
    step("customer_search_rafael", cust)

    draft = capability_invoke(
        "contifico.invoice.draft.v1",
        {
            "persona_id": "O8bYEj1Yks3WDb7j",
            "dry_run": True,
            "descripcion": "PRUEBA BORRADOR InnerOS MCP",
            "lines": [
                {"descripcion": "Prueba integración MCP", "cantidad": 1, "precio": 1.0, "porcentaje_iva": 15},
            ],
        },
    )
    step("invoice_draft_dry_run", draft)

    report["pass"] = all(s["ok"] for s in report["steps"])
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
