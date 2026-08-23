"""Orquestación CrewAI — flujo de inspección PC Doctor."""

import json
import re
import uuid
from typing import Any

from crewai import Agent, Crew, Process, Task

from agents.roles import build_agents, get_llm
from tools.crew_tools import get_inspection_context
from tools.mongo import (
    create_client,
    ensure_indexes,
    lookup_client_by_ruc,
    save_report,
    seed_inventory_if_empty,
    update_inspection,
)
from tools.pdf_generator import export_quote, export_technical_report
from tools.ruc_api import lookup_ruc
from tools.workflow_v2 import (
    finalize_field_flow,
    get_flow_context,
    register_document,
    save_quote_v2,
    save_technical_report_v2,
    start_field_visit,
    sync_findings_to_visit,
)


def _extract_ruc(text: str) -> str | None:
    m = re.search(r"\b\d{13}\b", text)
    return m.group(0) if m else None


def _agent_from_spec(spec: dict) -> Agent:
    return Agent(
        role=spec["role"],
        goal=spec["goal"],
        backstory=spec["backstory"],
        tools=spec.get("tools") or [],
        llm=spec["llm"],
        verbose=spec.get("verbose", True),
        allow_delegation=False,
    )


def _parse_json_block(text: str, fallback: dict) -> dict:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        pass
    return fallback


def _fallback_quote(findings: list[dict]) -> dict:
    lines = []
    for f in findings:
        item = f.get("item", "Servicio técnico")
        qty = float(f.get("qty", 1))
        price = float(f.get("estimated_unit_price", 25.0))
        lines.append({"name": item, "qty": qty, "unit_price": price})
    if not lines:
        lines = [{"name": "Inspección y diagnóstico", "qty": 1, "unit_price": 45.0}]
    subtotal = sum(l["qty"] * l["unit_price"] for l in lines)
    iva = round(subtotal * 0.15, 2)
    return {
        "scope": "Trabajos derivados de inspección en campo",
        "lines": lines,
        "subtotal": round(subtotal, 2),
        "iva": iva,
        "total": round(subtotal + iva, 2),
    }


def run_inspection_flow(raw_input: str, inspection_id: str | None = None) -> dict[str, Any]:
    """
    Ejecuta el flujo multi-agente.
    MVP: cliente → campo → informe → cotización → revisión → comunicaciones.
    """
    ensure_indexes()
    seed_inventory_if_empty()

    ruc = _extract_ruc(raw_input)
    visit_info = start_field_visit(raw_input, inspection_id=inspection_id, ruc=ruc)
    inspection_id = visit_info["inspection_id"]
    sri_data = lookup_ruc(ruc) if ruc else {}
    client = lookup_client_by_ruc(ruc) if ruc else None

    specs = build_agents(get_llm())

    # --- Fase 1: Cliente (si hay RUC) ---
    client_summary = client or sri_data
    if ruc and not client:
        cliente_agent = _agent_from_spec(specs["cliente"])
        t_cliente = Task(
            description=(
                f"RUC detectado: {ruc}. Consulta SRI, verifica si existe en MongoDB "
                f"y crea/actualiza el cliente. Input de campo: {raw_input}"
            ),
            expected_output="JSON del cliente guardado en MongoDB",
            agent=cliente_agent,
        )
        crew_cliente = Crew(agents=[cliente_agent], tasks=[t_cliente], process=Process.sequential, verbose=True)
        client_result = crew_cliente.kickoff()
        client_summary = _parse_json_block(str(client_result), sri_data)
        save_ruc = (client_summary.get("ruc") or ruc or "").strip()
        if len(save_ruc) >= 10:
            create_client(
                {
                    "ruc": save_ruc,
                    "name": client_summary.get("name", sri_data.get("name", "")),
                    "address": client_summary.get("address", ""),
                    "city": client_summary.get("city", ""),
                }
            )

    client_doc = lookup_client_by_ruc(ruc) if ruc else None
    client_id = (client_doc or {}).get("client_id")
    if client_id:
        from tools.mongo import get_db

        get_db().sop_visits.update_one(
            {"legacy_inspection_id": inspection_id},
            {"$set": {"client_id": client_id, "ruc": ruc}},
        )

    # --- Fase 2: Campo + hallazgos ---
    campo_agent = _agent_from_spec(specs["campo"])
    t_campo = Task(
        description=(
            f"Inspección ID: {inspection_id}. Analiza: {raw_input}. "
            "Extrae hallazgos técnicos (cámaras, cables, switches, rack) y tareas pendientes. "
            f"Usa save_inspection_findings_tool con inspection_id={inspection_id}. "
            'findings_json: array de objetos {{"item","severity","detail","qty"}}. '
            'pending_json: array de strings.'
        ),
        expected_output="Hallazgos guardados en MongoDB",
        agent=campo_agent,
    )
    crew_campo = Crew(agents=[campo_agent], tasks=[t_campo], process=Process.sequential, verbose=True)
    crew_campo.kickoff()
    sync_findings_to_visit(inspection_id)

    ctx = get_inspection_context(inspection_id)
    findings = ctx.get("findings", [])

    # --- Fase 3: Informe técnico ---
    informes_agent = _agent_from_spec(specs["informes"])
    t_informe = Task(
        description=(
            f"Redacta informe técnico para inspección {inspection_id}. "
            f"Cliente: {json.dumps(client_summary, ensure_ascii=False)}. "
            f"Hallazgos: {json.dumps(findings, ensure_ascii=False)}. "
            "Guarda con save_report_tool un JSON con: summary, location, technician, "
            "findings_text, work_done, final_status, recommendations."
        ),
        expected_output="Informe guardado en MongoDB",
        agent=informes_agent,
    )
    crew_informe = Crew(agents=[informes_agent], tasks=[t_informe], process=Process.sequential, verbose=True)
    informe_result = crew_informe.kickoff()

    report = _parse_json_block(
        str(informe_result),
        {
            "summary": "Inspección de infraestructura en campo",
            "location": client_summary.get("address", ""),
            "technician": "Por confirmar",
            "findings_text": "; ".join(f.get("detail", "") for f in findings),
            "work_done": "Diagnóstico visual y levantamiento de hallazgos",
            "final_status": "Pendiente de aprobación de cotización",
            "recommendations": "Ejecutar trabajos cotizados y reordenar cableado",
        },
    )
    save_report(inspection_id, report)
    report_v2 = save_technical_report_v2(inspection_id, report, client_id=client_id)

    # --- Fase 4: Cotización ---
    cotizador_agent = _agent_from_spec(specs["cotizador"])
    t_cot = Task(
        description=(
            f"Cotiza inspección {inspection_id}. Busca ítems en inventario según hallazgos: "
            f"{json.dumps(findings, ensure_ascii=False)}. "
            "Calcula subtotal, IVA 15%, total. Guarda con save_quote_tool."
        ),
        expected_output="Cotización guardada en MongoDB",
        agent=cotizador_agent,
    )
    crew_cot = Crew(agents=[cotizador_agent], tasks=[t_cot], process=Process.sequential, verbose=True)
    cot_result = crew_cot.kickoff()
    quote = _parse_json_block(str(cot_result), _fallback_quote(findings))
    if ruc:
        quote["client_ruc"] = ruc
    quote_v2 = save_quote_v2(inspection_id, quote, client_id=client_id)

    # --- Fase 5: Revisión ---
    revisor_agent = _agent_from_spec(specs["revisor"])
    t_rev = Task(
        description=(
            f"Revisa informe y cotización. Reporte: {json.dumps(report, ensure_ascii=False)}. "
            f"Cotización: {json.dumps(quote, ensure_ascii=False)}. "
            "Lista problemas (placeholders, campos vacíos). Responde JSON: "
            '{"approved": bool, "issues": [str], "notes": str}'
        ),
        expected_output="JSON de revisión con approved true/false",
        agent=revisor_agent,
    )
    crew_rev = Crew(agents=[revisor_agent], tasks=[t_rev], process=Process.sequential, verbose=True)
    rev_result = crew_rev.kickoff()
    review = _parse_json_block(str(rev_result), {"approved": True, "issues": [], "notes": "MVP"})

    # --- Fase 6: Comunicaciones ---
    comm_agent = _agent_from_spec(specs["comunicaciones"])
    t_comm = Task(
        description=(
            f"Redacta borrador de correo para el cliente y aviso interno WhatsApp. "
            f"Cliente: {client_summary.get('name', '')}. Total cotización: {quote.get('total')}."
        ),
        expected_output="Texto de correo + mensaje WhatsApp corto",
        agent=comm_agent,
    )
    crew_comm = Crew(agents=[comm_agent], tasks=[t_comm], process=Process.sequential, verbose=True)
    comm_result = crew_comm.kickoff()

    client_doc = lookup_client_by_ruc(ruc) if ruc else client_summary
    report_path = export_technical_report(
        inspection_id, report, client_doc or {}, code=report_v2.get("code")
    )
    quote_path = export_quote(
        inspection_id, quote_v2, client_doc or {}, code=quote_v2.get("code")
    )

    doc_report = register_document(
        report_path, "technical_report", report_v2["report_id"], client_id=client_id
    )
    doc_quote = register_document(quote_path, "quote", quote_v2["quote_id"], client_id=client_id)

    final = finalize_field_flow(inspection_id, client_id=client_id)
    v2_ctx = get_flow_context(inspection_id)

    return {
        "inspection_id": inspection_id,
        "flow": "campo_pc_doctor_v2",
        "visit": v2_ctx.get("visit"),
        "client": client_doc,
        "findings": findings,
        "report": report,
        "report_v2": report_v2,
        "quote": quote_v2,
        "review": review,
        "communications_draft": str(comm_result),
        "exports": {"report_md": report_path, "quote_md": quote_path},
        "documents": [doc_report, doc_quote],
        "gates": final.get("gates"),
        "codes": {
            "visit": visit_info.get("code"),
            "report": report_v2.get("code"),
            "quote": quote_v2.get("code"),
        },
        "status": "completed",
    }


def _demo_findings(raw_input: str) -> list[dict]:
    """Hallazgos heurísticos para demo sin LLM tool-calling."""
    items: list[dict] = []
    lower = raw_input.lower()
    if "poe" in lower or "switch" in lower:
        items.append(
            {
                "item": "Switch PoE 16 puertos",
                "severity": "alta",
                "detail": "Infraestructura de cámaras requiere switch PoE",
                "qty": 1,
                "estimated_unit_price": 185.0,
            }
        )
    if "cámara" in lower or "camara" in lower:
        items.append(
            {
                "item": "Revisión circuito cámaras IP",
                "severity": "media",
                "detail": "Verificar alimentación y conectividad de cámaras",
                "qty": 1,
                "estimated_unit_price": 45.0,
            }
        )
    if not items:
        items.append(
            {
                "item": "Inspección y diagnóstico en campo",
                "severity": "media",
                "detail": raw_input[:200],
                "qty": 1,
                "estimated_unit_price": 45.0,
            }
        )
    return items


def run_inspection_demo(raw_input: str, inspection_id: str | None = None) -> dict[str, Any]:
    """
    Flujo determinista para demo hackathon cuando Ollama local no soporta tools CrewAI.
    Ejecuta tools reales (MongoDB, PDF, cotización) sin orquestación LLM.
    """
    ensure_indexes()
    seed_inventory_if_empty()

    ruc = _extract_ruc(raw_input)
    visit_info = start_field_visit(raw_input, inspection_id=inspection_id, ruc=ruc)
    inspection_id = visit_info["inspection_id"]
    findings = _demo_findings(raw_input)
    pending = ["Validar cotización con cliente", "Programar instalación switch PoE"]
    update_inspection(inspection_id, {"findings": findings, "pending_tasks": pending})
    sync_findings_to_visit(inspection_id)

    client_doc = lookup_client_by_ruc(ruc) if ruc else None
    client_id = (client_doc or {}).get("client_id")

    report = {
        "summary": "Inspección técnica — levantamiento de hallazgos en campo",
        "location": (client_doc or {}).get("address", "Torres de la Merced"),
        "technician": "Técnico PC Doctor",
        "findings_text": "; ".join(f.get("detail", "") for f in findings),
        "work_done": "Diagnóstico visual y levantamiento de infraestructura",
        "final_status": "Pendiente aprobación cotización",
        "recommendations": "Instalar switch PoE y reorganizar cableado según cotización",
    }
    save_report(inspection_id, report)
    report_v2 = save_technical_report_v2(inspection_id, report, client_id=client_id)

    quote = _fallback_quote(findings)
    if ruc:
        quote["client_ruc"] = ruc
    quote_v2 = save_quote_v2(inspection_id, quote, client_id=client_id)

    client_doc = client_doc or {"name": "Cliente demo", "ruc": ruc}
    report_path = export_technical_report(inspection_id, report, client_doc, code=report_v2.get("code"))
    quote_path = export_quote(inspection_id, quote_v2, client_doc, code=quote_v2.get("code"))

    doc_report = register_document(report_path, "technical_report", report_v2["report_id"], client_id=client_id)
    doc_quote = register_document(quote_path, "quote", quote_v2["quote_id"], client_id=client_id)

    final = finalize_field_flow(inspection_id, client_id=client_id)
    v2_ctx = get_flow_context(inspection_id)

    return {
        "inspection_id": inspection_id,
        "flow": "demo_deterministic_local",
        "visit": v2_ctx.get("visit"),
        "client": client_doc,
        "findings": findings,
        "report": report,
        "report_v2": report_v2,
        "quote": quote_v2,
        "review": {"approved": True, "issues": [], "notes": "Demo mode — sin CrewAI tool-calling"},
        "communications_draft": f"Cotización lista — total USD {quote_v2.get('total', quote.get('total'))}",
        "exports": {"report_md": report_path, "quote_md": quote_path},
        "documents": [doc_report, doc_quote],
        "gates": final.get("gates"),
        "codes": {
            "visit": visit_info.get("code"),
            "report": report_v2.get("code"),
            "quote": quote_v2.get("code"),
        },
        "status": "completed",
    }
