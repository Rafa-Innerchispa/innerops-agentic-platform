#!/usr/bin/env python3
"""Simula flujo E2E de cotización PC Doctor — FEMAR (acceso) y Bellini (CCTV).

Basado en PDFs en ~/data/media/pcdoctor/quotes/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "platform"
sys.path.insert(0, str(ROOT))

from raphiia_openai.operational import inventory_store, pcdoctor_store
from raphiia_openai.operational.quote_renderer import render_quote_html
from raphiia_openai.operational.quote_delivery import generate_quote_intro

TAG = "simulate_quote_flows_2026-08-05"
SOURCE = "cursor_simulation"
SUPPLIER = "ZC Mayoristas"
# Coste estimado ≈ 65% del PVP cuando no hay PVD en catálogo (margen ~35%)
COST_RATIO = 0.65


def _line(desc: str, qty: float, sell: float, sku: str = "", brand: str = "", model: str = "", category: str = ""):
    cost = round(sell * COST_RATIO, 2)
    return {
        "description": desc,
        "quantity": qty,
        "unit_price": sell,
        "unit_cost": cost,
        "sku": sku,
        "brand": brand,
        "model": model,
        "category": category,
    }


def _ensure_inventory_from_lines(lines: list[dict]) -> list[str]:
    item_ids = []
    for line in lines:
        sku = (line.get("sku") or "").strip()
        if not sku or line.get("category") == "service":
            continue
        inv = inventory_store.upsert_inventory_item({
            "sku": sku,
            "name": line["description"][:120],
            "brand": line.get("brand", ""),
            "model": line.get("model", ""),
            "category": line.get("category", "catalog"),
            "entity_id": "ent_pcdoctor",
            "source": SOURCE,
            "tags": [TAG],
        })
        item_id = inv.get("item_id")
        if item_id:
            inventory_store.upsert_inventory_offer({
                "item_id": item_id,
                "party_name": SUPPLIER,
                "price": line.get("unit_cost", 0),
                "currency": "USD",
                "source_doc": "simulated_pvd",
                "notes": f"PVD estimado ({int((1-COST_RATIO)*100)}% margen sobre PVP cotizado)",
            })
            item_ids.append(item_id)
    return item_ids


def _margin_summary(lines: list[dict]) -> dict:
    revenue = sum(float(l["quantity"]) * float(l["unit_price"]) for l in lines)
    cost = sum(float(l["quantity"]) * float(l.get("unit_cost", 0)) for l in lines)
    margin = round(revenue - cost, 2)
    pct = round((margin / revenue * 100) if revenue else 0, 1)
    return {"revenue": round(revenue, 2), "cost": round(cost, 2), "margin": margin, "margin_pct": pct}


FEMAR_LINES = [
    _line("Controladora ZKTeco InBio Pro 460 Plus", 2, 299.00, "ZKT-INBIO460PLUS", "ZKTeco", "InBio Pro 460 Plus", "access_control"),
    _line("Terminal ZKTeco SpeedFace V3L QR/ID", 1, 179.00, "ZKT-SPEEDFACE-V3L", "ZKTeco", "SpeedFace V3L", "access_control"),
    _line("Lectora biométrica ZKTeco FR1200-ID", 6, 74.00, "ZKT-FR1200-ID", "ZKTeco", "FR1200-ID", "access_control"),
    _line("Tarjeta RFID ID 125 kHz", 30, 0.60, "ZKT-RFID-125", "ZKTeco", "", "access_control"),
    _line("Licencia ZKBio CVSecurity Access Control P10", 1, 269.00, "ZKBIO-AC-P10", "ZKTeco", "CVSecurity P10", "license"),
    _line("Licencia ZKBio CVSecurity Visitor P1-5K", 1, 485.00, "ZKBIO-VIS-5K", "ZKTeco", "Visitor P1-5K", "license"),
    _line("Instalación física de controladoras y terminales", 1, 350.00, category="service"),
    _line("Configuración y parametrización del sistema", 1, 250.00, category="service"),
    _line("Pruebas y puesta en marcha", 1, 125.00, category="service"),
    _line("Capacitación y documentación básica", 1, 75.00, category="service"),
    _line("Materiales menores de instalación", 1, 50.00, category="service"),
]

BELLINI_LINES = [
    _line("TELEVISOR BLAUPUNKT 43\" BLA43FLB01", 1, 290.00, "TELVBL-BLA43FLB01", "BLAUPUNKT", "BLA43FLB01", "display"),
    _line("Cámara IP PoE 4MP Hikvision DS-2CD1043G2-LIU", 4, 89.00, "CAMADS-2CD1043G2-LIU", "Hikvision", "DS-2CD1043G2-LIU", "cctv"),
    _line("Switch Gigabit PoE+ Hikvision DS-3E1505P-EI/M", 1, 85.00, "SWPO-DS-3E1505P-EI/M", "Hikvision", "DS-3E1505P-EI/M", "network"),
    _line("Soporte de Televisión fijo 32-55\"", 1, 39.00, "SOTVXT-FIJO55-70", "Xtech", "XTA-325", "accessory"),
    _line("Computador Servidor Monitoreo Ryzen 7 5700G 480GB 8GB W11", 1, 735.00, "PCXTR5C480-W11", "Custom", "Ryzen7-5700G", "compute"),
    _line("Tarjeta gráfica ASUS Dual RTX 3050 6GB", 1, 390.00, "DUAL-RTX3050-O6G", "ASUS", "RTX3050-O6G", "compute"),
    _line("Materiales Varios de Red e instalación", 1, 500.00, "MAVASM-MATERIALES-VARIOS", category="service"),
    _line("Instalación de Punto Eléctrico", 1, 45.00, "INST-PTO-ELECT", category="service"),
    _line("Instalación de Cámara Complejidad Media", 4, 65.00, "INSTAL-CAMARA-MED", category="service"),
    _line("Tendido y reconexiones varias", 1, 500.00, "RECONX-TENDIDO", category="service"),
    _line("Instalación y configuración software VMS", 1, 150.00, "SOFTVM-INST", category="service"),
    _line("Configuración y puesta en marcha de cámaras", 1, 90.00, "CFGCAM-CONFIG", category="service"),
    _line("Router Wi-Fi Grandstream GWN7052F", 1, 75.00, "ROWI-GWN7052F", "Grandstream", "GWN7052F", "network"),
]


def run_femar() -> dict:
    print("\n" + "=" * 70 + "\nFLUJO FEMAR — Control de acceso ZKTeco\n" + "=" * 70)
    client_res = pcdoctor_store.upsert_client({
        "display_name": "FEMAR S.A.",
        "legal_name": "FEMAR S.A.",
        "ruc": "0992364866001",
        "city": "Guayaquil",
        "address": "Vía a Samborondón, Edificio Xima, piso 5 oficina 505",
        "contact_name": "Ing. Fausto Camino",
        "phone": "+593983939756",
        "status": "active",
        "source": SOURCE,
        "tags": [TAG, "femar", "access_control"],
    })
    client_id = client_res["client_id"]

    site_res = pcdoctor_store.create_site_draft({
        "client_ref": client_id,
        "name": "FEMAR — Xima oficina 505",
        "address": "Vía a Samborondón, Edificio Xima Centro de Negocios, piso 5, oficina 505",
        "city": "Guayaquil",
        "source": SOURCE,
        "tags": [TAG],
    })
    site_ref = site_res.get("site_id") or site_res.get("draft_id")

    visit_res = pcdoctor_store.log_service_visit({
        "client_id": client_id,
        "site_ref": site_ref,
        "visit_type": "inspection",
        "status": "completed",
        "summary": "Inspección control de acceso — 6 puertas, migración Honeywell/Northern a ZKTeco",
        "findings": [
            "2 controladoras Northern/Honeywell N-1000-IV-X operativas pero obsoletas",
            "6 lectoras existentes — evaluar compatibilidad Wiegand",
            "Entrada principal requiere terminal facial + QR",
        ],
        "recommendations": [
            "2× InBio Pro 460 Plus (8 puertas capacidad)",
            "1× SpeedFace V3L en acceso principal",
            "6× FR1200-ID en puertas internas",
            "Licencias ZKBio CVSecurity + Visitantes",
        ],
        "source": SOURCE,
        "tags": [TAG],
    })
    visit_id = visit_res.get("visit_id")

    asset_ids = []
    for asset in [
        {"category": "access_control", "brand": "Honeywell", "model": "N-1000-IV-X", "status": "legacy", "location_text": "Controladoras actuales"},
        {"category": "access_control", "brand": "Northern", "model": "PCI3", "status": "legacy", "location_text": "Panel existente"},
        {"category": "access_control", "brand": "Generic", "model": "Wiegand Reader", "status": "operational", "location_text": "6 lectoras existentes"},
    ]:
        ar = pcdoctor_store.upsert_asset({
            "client_id": client_id, "site_ref": site_ref, **asset,
            "source": SOURCE, "tags": [TAG],
        })
        asset_ids.append(ar.get("asset_id"))

    inv_ids = _ensure_inventory_from_lines(FEMAR_LINES)

    quote_res = pcdoctor_store.create_quote_draft({
        "client_id": client_id,
        "site_ref": site_ref,
        "visit_id": visit_id,
        "title": "FEMAR — Suministro e implementación control de acceso ZKTeco (6 puertas)",
        "entity_id": "ent_pcdoctor",
        "tax_rate": 0.15,
        "currency": "USD",
        "display_number": "COT-202607-001",
        "valid_until": "2026-08-10",
        "notes": "Basado en PDF Cotizacion_FEMAR_Control_Acceso_PC_Doctor. 60% anticipo / 40% contra entrega.",
        "source": SOURCE,
        "line_items": FEMAR_LINES,
        "status": "ready_for_review",
    })
    quote_id = quote_res.get("quote_id")

    intro = generate_quote_intro(quote_id, visit_id=visit_id)
    rendered = render_quote_html(quote_id)

    margin = _margin_summary(FEMAR_LINES)
    subtotal = margin["revenue"]
    tax = round(subtotal * 0.15, 2)
    total = round(subtotal + tax, 2)

    return {
        "flow": "FEMAR",
        "client_id": client_id,
        "site_ref": site_ref,
        "visit_id": visit_id,
        "asset_ids": asset_ids,
        "inventory_item_ids": inv_ids,
        "quote_id": quote_id,
        "pdf_reference_total": 3269.45,
        "simulated_subtotal": subtotal,
        "simulated_tax": tax,
        "simulated_total": total,
        "margin": margin,
        "intro_ok": intro.get("ok"),
        "render_ok": rendered.get("ok"),
        "html_length": len(rendered.get("html") or ""),
    }


def run_bellini() -> dict:
    print("\n" + "=" * 70 + "\nFLUJO BELLINI — Centro monitoreo lobby CCTV\n" + "=" * 70)
    client_res = pcdoctor_store.upsert_client({
        "display_name": "EDIFICIO TORRES BELLINI III-IV",
        "legal_name": "EDIFICIO TORRES BELLINI III-IV",
        "ruc": "0992992050001",
        "city": "Guayaquil",
        "address": "Av. Pedro Menéndez Gilbert PB TM",
        "phone": "(04) 3886364",
        "status": "active",
        "source": SOURCE,
        "tags": [TAG, "bellini", "cctv"],
    })
    client_id = client_res["client_id"]

    site_res = pcdoctor_store.create_site_draft({
        "client_ref": client_id,
        "name": "Torres Bellini — Lobby monitoreo centralizado",
        "address": "Av. Pedro Menéndez Gilbert PB TM, Guayaquil",
        "city": "Guayaquil",
        "source": SOURCE,
        "tags": [TAG],
    })
    site_ref = site_res.get("site_id") or site_res.get("draft_id")

    visit_res = pcdoctor_store.log_service_visit({
        "client_id": client_id,
        "site_ref": site_ref,
        "visit_type": "inspection",
        "status": "completed",
        "summary": "Centro monitoreo lobby — visualización 100+ cámaras en TV 43\"",
        "findings": [
            "Lobby requiere TV 43\" con soporte y punto eléctrico dedicado",
            "4 cámaras adicionales en área lobby/recepción",
            "Gabinetes piso 0 y administración desordenados",
            "Switch y cables visibles en recepción",
        ],
        "recommendations": [
            "TV 43\" 4K + soporte reforzado",
            "4× cámara IP 4MP PoE Hikvision",
            "PC servidor Ryzen 7 + RTX 3050 para VMS",
            "Reorganización gabinetes y unificación de red",
        ],
        "source": SOURCE,
        "tags": [TAG],
    })
    visit_id = visit_res.get("visit_id")

    asset_ids = []
    for cam in [
        {"brand": "Hikvision", "model": "DS-2CD1043G2-LIU", "location_text": "Lobby cámara 1", "status": "planned"},
        {"brand": "Hikvision", "model": "DS-2CD1043G2-LIU", "location_text": "Lobby cámara 2", "status": "planned"},
        {"brand": "Hikvision", "model": "DS-2CD1043G2-LIU", "location_text": "Lobby cámara 3", "status": "planned"},
        {"brand": "Hikvision", "model": "DS-2CD1043G2-LIU", "location_text": "Lobby cámara 4", "status": "planned"},
    ]:
        ar = pcdoctor_store.upsert_asset({
            "client_id": client_id, "site_ref": site_ref,
            "category": "cctv", "subtype": "ip_camera", **cam,
            "source": SOURCE, "tags": [TAG],
        })
        asset_ids.append(ar.get("asset_id"))

    inv_ids = _ensure_inventory_from_lines(BELLINI_LINES)

    quote_res = pcdoctor_store.create_quote_draft({
        "client_id": client_id,
        "site_ref": site_ref,
        "visit_id": visit_id,
        "title": "Bellini — Centro monitoreo lobby + cámaras IP + reorganización red",
        "entity_id": "ent_pcdoctor",
        "tax_rate": 0.15,
        "currency": "USD",
        "display_number": "COT-202607000206",
        "notes": "Basado en DocumentoCOT 202607000206. Forma de pago: contado.",
        "source": SOURCE,
        "line_items": BELLINI_LINES,
        "status": "ready_for_review",
    })
    quote_id = quote_res.get("quote_id")

    intro = generate_quote_intro(quote_id, visit_id=visit_id)
    rendered = render_quote_html(quote_id)

    margin = _margin_summary(BELLINI_LINES)
    subtotal = margin["revenue"]
    tax = round(subtotal * 0.15, 2)
    total = round(subtotal + tax, 2)

    return {
        "flow": "BELLINI",
        "client_id": client_id,
        "site_ref": site_ref,
        "visit_id": visit_id,
        "asset_ids": asset_ids,
        "inventory_item_ids": inv_ids,
        "quote_id": quote_id,
        "pdf_reference_total": 4042.25,
        "simulated_subtotal": subtotal,
        "simulated_tax": tax,
        "simulated_total": total,
        "margin": margin,
        "intro_ok": intro.get("ok"),
        "render_ok": rendered.get("ok"),
        "html_length": len(rendered.get("html") or ""),
    }


def main() -> None:
    results = [run_femar(), run_bellini()]
    print("\n" + "=" * 70 + "\nRESUMEN SIMULACIÓN\n" + "=" * 70)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    for r in results:
        print(f"\n--- {r['flow']} ---")
        print(f"  quote_id: {r['quote_id']}")
        print(f"  PDF total ref: ${r['pdf_reference_total']}")
        print(f"  Simulado total: ${r['simulated_total']} (sub ${r['simulated_subtotal']} + IVA ${r['simulated_tax']})")
        m = r["margin"]
        print(f"  Coste est.: ${m['cost']} | Margen bruto: ${m['margin']} ({m['margin_pct']}%)")
        print(f"  HTML render: {'OK' if r['render_ok'] else 'FAIL'} ({r['html_length']} chars)")
        print(f"  Preview: http://127.0.0.1:8102/api/v1/quotes/{r['quote_id']}/document")


if __name__ == "__main__":
    main()
