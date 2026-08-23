#!/usr/bin/env python3
"""Cotización FEMAR con precios reales (PVD ZC + mercado) y envío WhatsApp a Rafael."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "platform"
sys.path.insert(0, str(ROOT))

from raphiia_openai import mongo_store
from raphiia_openai.operational import inventory_store, pcdoctor_store
from raphiia_openai.operational.quote_delivery import generate_quote_intro, send_quote_delivery
from raphiia_openai.operational.quote_renderer import render_quote_html

SOURCE = "femar_real_pricing_2026-08-05"
CLIENT_ID = "client_6a73aaecf8906347e436916b"
RAFAEL_PHONE = "593999059000"

# PVD real ZC Mayoristas jun-2026 + hardware estimado vs competencia (Telalca ~$424 InBio retail)
# Regla: PVP competitivo vs PDF validado; margen mínimo 18% hardware, licencias según PVD real
LINES = [
    {
        "sku": "ZKT-INBIO460PLUS",
        "item_id": "invitem_6a73c9d3b817d652a997798d",
        "description": "Controladora ZKTeco InBio Pro 460 Plus — 4 puertas, TCP/IP, RS-485, Wiegand",
        "quantity": 2,
        "unit_cost": 210.00,
        "unit_price": 299.00,
        "cost_source": "est. distribuidor (Telalca retail $424 c/IVA; PVD integrador ~70%)",
        "competition_ref": "Telalca EC $424.35 c/IVA",
        "brand": "ZKTeco",
        "category": "access_control",
    },
    {
        "sku": "ZK-SPEEDFACE-V3L-QR-ID",
        "item_id": "invitem_6a54e6d03450afc5a6f3f58c",
        "description": "Terminal ZKTeco SpeedFace V3L QR/ID — rostro, QR dinámico, tarjeta RFID 125 kHz",
        "quantity": 1,
        "unit_cost": 125.00,
        "unit_price": 179.00,
        "cost_source": "est. distribuidor ZC",
        "competition_ref": "mercado EC $165–220",
        "brand": "ZKTeco",
        "category": "access_control",
    },
    {
        "sku": "ZKT-FR1200-ID",
        "item_id": "invitem_6a73c9d3b817d652a997799b",
        "description": "Lectora biométrica ZKTeco FR1200-ID — huella + tarjeta, esclava RS-485",
        "quantity": 6,
        "unit_cost": 48.00,
        "unit_price": 74.00,
        "cost_source": "est. distribuidor ZC",
        "competition_ref": "mercado EC $65–85",
        "brand": "ZKTeco",
        "category": "access_control",
    },
    {
        "sku": "ZKT-RFID-125",
        "item_id": "invitem_6a73c9d3b817d652a99779a2",
        "description": "Tarjeta RFID ID 125 kHz — credencial proximidad",
        "quantity": 30,
        "unit_cost": 0.35,
        "unit_price": 0.60,
        "cost_source": "PVD ZC Mayoristas",
        "brand": "ZKTeco",
        "category": "access_control",
    },
    {
        "sku": "ZKT0301",
        "description": "Licencia ZKBio CVSecurity Access Control P10 — hasta 10 puertas",
        "quantity": 1,
        "unit_cost": 249.00,
        "unit_price": 269.00,
        "cost_source": "PVD ZC Mayoristas jun-2026 (real)",
        "brand": "ZKTeco",
        "category": "license",
    },
    {
        "sku": "VIS-P1-5K",
        "description": "Licencia ZKBio CVSecurity Visitor P1-5K — visitantes y QR temporales",
        "quantity": 1,
        "unit_cost": 465.00,
        "unit_price": 485.00,
        "cost_source": "PVD ZC Mayoristas jun-2026 (real)",
        "brand": "ZKTeco",
        "category": "license",
    },
    {
        "description": "Instalación física de controladoras y terminales",
        "quantity": 1,
        "unit_cost": 140.00,
        "unit_price": 350.00,
        "cost_source": "mano de obra interna",
        "category": "service",
    },
    {
        "description": "Configuración y parametrización del sistema (software, puertas, usuarios, visitantes)",
        "quantity": 1,
        "unit_cost": 80.00,
        "unit_price": 250.00,
        "cost_source": "mano de obra interna",
        "category": "service",
    },
    {
        "description": "Pruebas y puesta en marcha — 6 puertas + acceso principal QR",
        "quantity": 1,
        "unit_cost": 45.00,
        "unit_price": 125.00,
        "cost_source": "mano de obra interna",
        "category": "service",
    },
    {
        "description": "Capacitación y documentación básica al personal administrador",
        "quantity": 1,
        "unit_cost": 30.00,
        "unit_price": 75.00,
        "cost_source": "mano de obra interna",
        "category": "service",
    },
    {
        "description": "Materiales menores de instalación (terminales, conectores, fijaciones)",
        "quantity": 1,
        "unit_cost": 18.00,
        "unit_price": 50.00,
        "cost_source": "consumibles",
        "category": "service",
    },
]


def _resolve_item_id(sku: str) -> str | None:
    db = mongo_store.get_db()
    it = db.inventory_items.find_one({"sku": sku, "entity_id": "ent_pcdoctor"})
    return it.get("item_id") if it else None


def _margin(lines: list[dict]) -> dict:
    rev = sum(float(l["quantity"]) * float(l["unit_price"]) for l in lines)
    cost = sum(float(l["quantity"]) * float(l["unit_cost"]) for l in lines)
    m = round(rev - cost, 2)
    return {"subtotal": round(rev, 2), "cost": round(cost, 2), "margin": m, "margin_pct": round(m / rev * 100, 1) if rev else 0}


def main() -> None:
    db = mongo_store.get_db()

    # Resolver item_ids reales para licencias del catálogo ZC
    for line in LINES:
        if not line.get("item_id") and line.get("sku"):
            line["item_id"] = _resolve_item_id(line["sku"])

    # Sitio y visita existentes (últimos de simulación)
    site = db.ops_site_drafts.find_one({"client_id": CLIENT_ID}, sort=[("created_at", -1)])
    visit = db.ops_service_visits.find_one({"client_id": CLIENT_ID}, sort=[("created_at", -1)])
    site_ref = site.get("site_draft_id") or site.get("draft_id") if site else None
    visit_id = visit.get("visit_id") if visit else None

    line_items = []
    for line in LINES:
        item = {
            "description": line["description"],
            "quantity": line["quantity"],
            "unit_price": line["unit_price"],
            "unit_cost": line["unit_cost"],
            "sku": line.get("sku", ""),
            "item_id": line.get("item_id", ""),
            "brand": line.get("brand", ""),
            "category": line.get("category", ""),
        }
        line_items.append(item)
        if line.get("sku") and line.get("category") != "service":
            inventory_store.upsert_inventory_offer({
                "sku": line["sku"],
                "item_id": line.get("item_id") or "",
                "party_name": "ZC MAYORISTAS S.A.",
                "price": line["unit_cost"],
                "currency": "USD",
                "source_doc": line.get("cost_source", "femar_real_pricing"),
                "entity_id": "ent_pcdoctor",
            })

    margin = _margin(LINES)
    tax_rate = 0.15
    tax = round(margin["subtotal"] * tax_rate, 2)
    total = round(margin["subtotal"] + tax, 2)

    quote_res = pcdoctor_store.create_quote_draft({
        "client_id": CLIENT_ID,
        "site_ref": site_ref,
        "visit_id": visit_id,
        "title": "FEMAR — Control de acceso ZKTeco 6 puertas (precio real PC Doctor)",
        "entity_id": "ent_pcdoctor",
        "tax_rate": tax_rate,
        "currency": "USD",
        "display_number": "COT-202608-001",
        "valid_until": "2026-08-15",
        "notes": (
            "Precios validados vs PVD ZC Mayoristas jun-2026 y competencia local (Telalca). "
            "60% anticipo / 40% contra entrega. Validez 10 días."
        ),
        "source": SOURCE,
        "line_items": line_items,
        "status": "ready_for_review",
        "intro_md": (
            "Propuesta PC Doctor para *FEMAR S.A.*: modernización del control de acceso en las seis puertas "
            "del edificio Xima (oficina 505), migrando a plataforma ZKTeco con terminal facial + QR en acceso "
            "principal y lectoras biométricas en puertas internas.\n\n"
            "Incluye equipos, licencias ZKBio CVSecurity, instalación, configuración, pruebas y capacitación. "
            "Precios alineados al mercado ecuatoriano con equipamiento certificado."
        ),
    })
    if not quote_res.get("ok"):
        print(json.dumps(quote_res, indent=2))
        sys.exit(1)

    quote_id = quote_res["quote_id"]
    if quote_res.get("reused"):
        pcdoctor_store.update_quote_draft({
            "quote_id": quote_id,
            "line_items": line_items,
            "status": "ready_for_review",
            "display_number": "COT-202608-001",
            "intro_md": quote_res.get("quote_draft", {}).get("intro_md") or LINES[0],
            "tax_rate": tax_rate,
        })

    intro = generate_quote_intro(quote_id, visit_id=visit_id)
    rendered = render_quote_html(quote_id)

    delivery = send_quote_delivery(
        quote_id,
        channels=["whatsapp"],
        phone=RAFAEL_PHONE,
        intro_md=(
            "Propuesta PC Doctor para FEMAR S.A. — control de acceso ZKTeco (6 puertas). "
            f"Total ${total:,.2f} incl. IVA. Enviado a Rafael para revisión previa."
        ),
    )

    summary = {
        "ok": True,
        "quote_id": quote_id,
        "display_number": "COT-202608-001",
        "client": "FEMAR S.A.",
        "subtotal": margin["subtotal"],
        "iva_15": tax,
        "total": total,
        "cost_total": margin["cost"],
        "margin_gross": margin["margin"],
        "margin_pct": margin["margin_pct"],
        "line_count": len(line_items),
        "intro_ok": intro.get("ok"),
        "render_ok": rendered.get("ok"),
        "delivery": delivery,
        "preview_local": f"http://127.0.0.1:8101/api/v1/quotes/{quote_id}/document",
        "lines": [
            {
                "n": i + 1,
                "desc": l["description"][:55],
                "qty": l["quantity"],
                "pvp": l["unit_price"],
                "pvd": l["unit_cost"],
                "sub": round(l["quantity"] * l["unit_price"], 2),
            }
            for i, l in enumerate(LINES)
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not delivery.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
