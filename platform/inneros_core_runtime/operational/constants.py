"""Operational Layer PC Doctor — constantes y enums (F1+)."""

from __future__ import annotations

# Mongo collections — prefijo ops_ para no colisionar con Swarm legacy
COL_OPS_CLIENTS = "ops_clients"
COL_OPS_SITES = "ops_sites"
COL_OPS_CONTACTS = "ops_contacts"
COL_OPS_WHATSAPP_GROUPS = "ops_whatsapp_groups"
COL_OPS_FIELD_VISITS = "ops_field_visits"
COL_OPS_FIELD_VISIT_EVENTS = "ops_field_visit_events"
COL_OPS_EQUIPMENT_ASSETS = "ops_equipment_assets"
COL_OPS_EQUIPMENT_CHANGES = "ops_equipment_changes"
COL_OPS_TECHNICAL_REPORTS = "ops_technical_reports"
COL_OPS_QUOTE_DRAFTS = "ops_quote_drafts"
COL_OPS_QUOTE_DELIVERIES = "ops_quote_deliveries"
COL_OPS_QUOTE_LINKS = "ops_quote_links"
COL_OPS_INVOICE_RECORDS = "ops_invoice_records_internal"
COL_OPS_TASKS_FOLLOWUP = "ops_tasks_followup"
COL_OPS_TECHNICIAN_DAILY_LOGS = "ops_technician_daily_logs"
COL_OPS_OPERATIONAL_MEMORY = "ops_operational_memory"
COL_OPS_AUDIT_LOG = "ops_audit_log"

# CRM kernel (party identity)
COL_CRM_PARTIES = "crm_parties"
COL_CRM_IDENTITY_MAP = "crm_identity_map"

# MOD-ACCOUNTING
COL_ACCOUNTING_PAYABLES = "accounting_payables"
COL_ACCOUNTING_RECEIVABLES = "accounting_receivables"
COL_ACCOUNTING_PAYMENTS = "accounting_payments"

# MOD-PROCUREMENT + MOD-INVENTORY
COL_PROCUREMENT_ORDERS = "procurement_orders"
COL_INVENTORY_ITEMS = "inventory_items"
COL_INVENTORY_OFFERS = "inventory_offers"
COL_INVENTORY_MOVEMENTS = "inventory_movements"

# Agent registry (control plane)
COL_AGENT_REGISTRY = "ralfia_agent_registry"

# Fases de implementación — colecciones activas por fase
PHASE_ACTIVE_COLLECTIONS: dict[int, tuple[str, ...]] = {
    1: (
        COL_OPS_CLIENTS,
        COL_OPS_SITES,
        COL_OPS_FIELD_VISITS,
        COL_OPS_FIELD_VISIT_EVENTS,
        COL_OPS_EQUIPMENT_ASSETS,
        COL_OPS_AUDIT_LOG,
    ),
    2: (COL_OPS_TECHNICAL_REPORTS, COL_OPS_EQUIPMENT_CHANGES),
    3: (COL_OPS_QUOTE_DRAFTS, COL_OPS_TASKS_FOLLOWUP),
    4: (),  # Notion sync — metadata only
    5: (COL_OPS_OPERATIONAL_MEMORY, COL_OPS_TECHNICIAN_DAILY_LOGS),
    6: (),  # Gemini vision — optional
}

VISIBILITY_PRIVATE = "PRIVATE"
VISIBILITY_INTERNAL = "INTERNAL"
VISIBILITY_TEAM = "TEAM"
VISIBILITY_PUBLIC = "PUBLIC"

VISIBILITY_LEVELS = (
    VISIBILITY_PRIVATE,
    VISIBILITY_INTERNAL,
    VISIBILITY_TEAM,
    VISIBILITY_PUBLIC,
)
