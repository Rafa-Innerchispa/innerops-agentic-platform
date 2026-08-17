#!/usr/bin/env python3
"""Configura email_settings Mongo + prueba WhatsApp Evolution."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import mongo_store  # noqa: E402
from raphiia_openai.notifications.evolution_client import connection_open, evolution_available, send_whatsapp  # noqa: E402
from raphiia_openai.notifications.settings import (  # noqa: E402
    EVOLUTION_INSTANCE,
    NOTIFY_WHATSAPP_TO,
)


def setup_email_settings() -> dict:
    db = mongo_store.get_db()
    doc = db.email_settings.find_one({"_id": "global"})
    patch = {
        "notify_on_high": True,
        "whatsapp_numbers": [NOTIFY_WHATSAPP_TO] if NOTIFY_WHATSAPP_TO else [],
        "keywords_important": [
            "urgente", "factura", "pago", "vencido", "cotización", "cotizacion",
            "reclamo", "falla", "caído", "caido", "contrato", "proforma",
            "transferencia", "sri", "retención", "retencion", "ruc",
            "depósito", "deposito", "deposit", "invoice", "cobro", "extracto",
            "licitación", "licitacion", "importación", "exportación", "aduana",
            "estado de cuenta", "irs", "aviso de vencimiento", "hosting",
        ],
        "trusted_domains": [
            "sri.gob.ec", "irs.gov", "pichincha.com", "produbanco.com", "bancoguayaquil.com",
            "bancointernacional.com", "bolivariano.com", "pacifico.fin.ec", "jep.coop",
            "deuna.com", "payphone", "pcdoctor.com.ec", "netlife.info.ec", "contifico.com",
            "prime-host", "stripe.com",
        ],
        "evolution_instance": EVOLUTION_INSTANCE,
        "email_view_base_url": "http://192.168.1.4:5173/email",
    }
    if doc:
        db.email_settings.update_one({"_id": "global"}, {"$set": patch})
    else:
        db.email_settings.insert_one({"_id": "global", **patch})
    n_accounts = db.email_accounts.count_documents({"enabled": True})
    return {"whatsapp_numbers": patch["whatsapp_numbers"], "enabled_accounts": n_accounts}


def main() -> None:
    print("=== RalfIA Notifications Setup ===")
    print(f"Evolution up: {evolution_available()}")
    print(f"WhatsApp open: {connection_open()}")
    print(f"Destino: {NOTIFY_WHATSAPP_TO}")
    email_cfg = setup_email_settings()
    print(f"Email settings: {email_cfg}")
    if "--test" in sys.argv:
        res = send_whatsapp("🧠 Ralphi IA — notificaciones Evolution OK (sin n8n)")
        print("Test send:", res)


if __name__ == "__main__":
    main()
