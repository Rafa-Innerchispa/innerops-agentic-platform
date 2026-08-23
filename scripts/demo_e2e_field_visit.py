#!/usr/bin/env python3
"""Demo E2E local — visita de campo + cotización (sin APIs OpenAI pagas).

Uso:
  python demo_e2e_field_visit.py
  python demo_e2e_field_visit.py --execute --client-name "Nombre Cliente Real"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "platform"
sys.path.insert(0, str(ROOT))

from raphiia_openai.operational import inventory_store, pcdoctor_store, party_store
from raphiia_openai.operational import accounting_store

DEMO_TAG = "demo_e2e_field_visit_2026-08-05"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-") or "cliente"


def _print_step(n: int, title: str) -> None:
    print(f"\n{'='*60}\nPaso {n}: {title}\n{'='*60}")


def run_demo(*, execute: bool, client_name: str, with_receivable: bool) -> dict:
    results: dict = {"ok": True, "execute": execute, "refs": {}}
    client_slug = _slug(client_name)

    if not execute:
        print("MODO PREVIEW — usar --execute --client-name \"...\" para crear datos en Mongo")
        return results

    source = "demo_e2e_field_visit"

    _print_step(1, f"Cliente: {client_name}")
    party_store.resolve_party(client_name, roles=["client"])
    client_res = pcdoctor_store.upsert_client({
        "display_name": client_name,
        "legal_name": client_name,
        "city": "Guayaquil",
        "status": "active",
        "tags": [DEMO_TAG, "demo", client_slug],
        "source": source,
        "notes": "Demo E2E — cámaras dañadas + panel PAC",
    })
    if not client_res.get("ok"):
        return {"ok": False, "error": "upsert_client failed", "detail": client_res}
    client_id = client_res["client_id"]
    results["refs"]["client_id"] = client_id

    site_res = pcdoctor_store.create_site_draft({
        "client_ref": client_id,
        "name": f"{client_name} — Sede principal",
        "city": "Guayaquil",
        "site_code": f"{client_slug.upper()[:12]}-01",
        "source": source,
        "tags": [DEMO_TAG],
    })
    site_ref = site_res.get("site_id") or site_res.get("draft_id") or (site_res.get("site_draft") or {}).get("draft_id")
    results["refs"]["site_ref"] = site_ref

    visit_res = pcdoctor_store.log_service_visit({
        "client_id": client_id,
        "site_ref": site_ref,
        "visit_type": "inspection",
        "status": "completed",
        "summary": "Inspección — cámaras dañadas, panel incendio ausente",
        "findings": ["2 cámaras IP destruidas", "Sin panel PAC certificado"],
        "recommendations": ["Reemplazar cámaras", "Instalar panel Notifier NFS2-3030"],
        "source": source,
        "tags": [DEMO_TAG],
    })
    visit_id = visit_res.get("visit_id")
    results["refs"]["visit_id"] = visit_id

    asset_ids = []
    for cam in [
        {"brand": "Hikvision", "model": "DS-2CD2143G2-I", "location_text": "Entrada principal"},
        {"brand": "Dahua", "model": "IPC-HFW2431T-ZS", "location_text": "Estacionamiento"},
    ]:
        asset_res = pcdoctor_store.upsert_asset({
            "client_id": client_id, "site_ref": site_ref,
            "category": "cctv", "subtype": "ip_camera",
            "brand": cam["brand"], "model": cam["model"],
            "status": "faulty", "location_text": cam["location_text"],
            "source": source, "tags": [DEMO_TAG],
        })
        asset_ids.append(asset_res.get("asset_id"))
    results["refs"]["asset_ids"] = asset_ids

    inv_res = inventory_store.upsert_inventory_item({
        "sku": f"PAC-NFS2-3030-{client_slug.upper()[:8]}",
        "name": "Panel incendio Notifier NFS2-3030",
        "brand": "Notifier", "model": "NFS2-3030",
        "category": "fire_alarm", "entity_id": "ent_pcdoctor",
        "source": source, "tags": [DEMO_TAG],
    })
    results["refs"]["inventory_item_id"] = inv_res.get("item_id") or (inv_res.get("item") or {}).get("item_id")

    quote_res = pcdoctor_store.create_quote_draft({
        "client_id": client_id, "site_ref": site_ref, "visit_id": visit_id,
        "title": f"{client_name} — Reemplazo cámaras + panel PAC",
        "entity_id": "ent_pcdoctor", "tax_rate": 0.15, "currency": "USD",
        "source": source,
        "line_items": [
            {"description": "Cámara Hikvision DS-2CD2143G2-I", "quantity": 1, "unit_price": 185.00},
            {"description": "Cámara Dahua IPC-HFW2431T-ZS", "quantity": 1, "unit_price": 165.00},
            {"description": "Panel Notifier NFS2-3030", "quantity": 1, "unit_price": 2800.00},
            {"description": "Instalación", "quantity": 1, "unit_price": 450.00},
        ],
    })
    if not quote_res.get("ok"):
        return {"ok": False, "error": "create_quote_draft failed", "detail": quote_res}
    quote_id = quote_res.get("quote_id")
    results["refs"]["quote_id"] = quote_id

    report_res = pcdoctor_store.generate_supervisor_report(client_id, site_id=site_ref, visit_id=visit_id)
    if report_res.get("ok"):
        results["refs"]["report_id"] = report_res.get("report_id")

    if with_receivable and quote_id:
        results["refs"]["receivable"] = accounting_store.create_receivable_from_quote(quote_id, entity_id="ent_pcdoctor")

    print(json.dumps(results["refs"], ensure_ascii=False, indent=2))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo E2E visita de campo")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--client-name", help="Nombre del cliente (obligatorio con --execute)")
    parser.add_argument("--with-receivable", action="store_true")
    args = parser.parse_args()
    if args.execute and not (args.client_name or "").strip():
        parser.error("--client-name es obligatorio con --execute")
    result = run_demo(execute=args.execute, client_name=(args.client_name or "").strip(), with_receivable=args.with_receivable)
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
