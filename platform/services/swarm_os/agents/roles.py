from crewai import LLM

from config import OLLAMA_BASE_URL, OLLAMA_MODEL
from tools.crew_tools import (
    find_client_tool,
    inventory_search_tool,
    save_inspection_findings_tool,
    save_quote_tool,
    save_report_tool,
    sri_lookup_tool,
    upsert_client_tool,
)


def get_llm() -> LLM:
    return LLM(model=f"ollama/{OLLAMA_MODEL}", base_url=OLLAMA_BASE_URL, temperature=0.2)


def load_global_agent_config(folder_name, agent_key):
    import yaml
    import os
    path = f"/home/rlopez/inneros_core/agents_pool/{folder_name}/config/agent.yaml"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and agent_key in data:
                    return data[agent_key]
        except Exception:
            pass
    return None


def build_agents(llm):
    cfg_campo = load_global_agent_config("AG-13_voice_inspection_extractor", "voice_inspection_extractor")
    cfg_cliente = load_global_agent_config("AG-14_crm_client_onboarder", "crm_client_onboarder")
    cfg_bitacora = load_global_agent_config("AG-02_context_memory", "context_memory")
    cfg_informes = load_global_agent_config("AG-04_markdown_docmaker", "markdown_docmaker")
    cfg_cotizador = load_global_agent_config("AG-16_quote_calculator", "quote_calculator")
    cfg_revisor = load_global_agent_config("AG-10_fiscal_signer", "fiscal_signer")
    cfg_comunicaciones = load_global_agent_config("AG-05_email_gatekeeper", "email_gatekeeper")

    director = {
        "role": "Director de Operaciones PC Doctor",
        "goal": "Coordinar el flujo de inspección de campo hasta informe y cotización",
        "backstory": "Supervisas técnicos en urbanizaciones y aseguras trazabilidad completa.",
        "tools": [],
        "llm": llm,
        "verbose": True,
    }

    campo = {
        "role": cfg_campo.get("role").strip() if cfg_campo else "Agente de Campo",
        "goal": cfg_campo.get("goal").strip() if cfg_campo else "Estructurar notas de visita, hallazgos y tareas pendientes",
        "backstory": cfg_campo.get("backstory").strip() if cfg_campo else "Interpretas dictados de técnicos sobre cables, cámaras y switches.",
        "tools": [save_inspection_findings_tool],
        "llm": llm,
        "verbose": True,
    }

    cliente = {
        "role": cfg_cliente.get("role").strip() if cfg_cliente else "Agente de Cliente",
        "goal": cfg_cliente.get("goal").strip() if cfg_cliente else "Validar RUC, consultar SRI y crear/actualizar cliente en MongoDB",
        "backstory": cfg_cliente.get("backstory").strip() if cfg_cliente else "Eres experto en onboarding de clientes institucionales en Ecuador.",
        "tools": [sri_lookup_tool, find_client_tool, upsert_client_tool],
        "llm": llm,
        "verbose": True,
    }

    bitacora = {
        "role": cfg_bitacora.get("role").strip() if cfg_bitacora else "Agente de Bitácora",
        "goal": cfg_bitacora.get("goal").strip() if cfg_bitacora else "Mantener registro ordenado de hallazgos y pendientes por inspección",
        "backstory": cfg_bitacora.get("backstory").strip() if cfg_bitacora else "Nada se pierde: cada observación queda documentada.",
        "tools": [save_inspection_findings_tool],
        "llm": llm,
        "verbose": True,
    }

    informes = {
        "role": cfg_informes.get("role").strip() if cfg_informes else "Agente de Informes Técnicos",
        "goal": cfg_informes.get("goal").strip() if cfg_informes else "Redactar informes formales según Playbook PC Doctor",
        "backstory": cfg_informes.get("backstory").strip() if cfg_informes else "Conviertes hallazgos de campo en informes listos para PDF-first.",
        "tools": [save_report_tool],
        "llm": llm,
        "verbose": True,
    }

    cotizador = {
        "role": cfg_cotizador.get("role").strip() if cfg_cotizador else "Agente Cotizador",
        "goal": cfg_cotizador.get("goal").strip() if cfg_cotizador else "Armar cotización con inventario, subtotal, IVA y total",
        "backstory": cfg_cotizador.get("backstory").strip() if cfg_cotizador else "Cruzas diagnóstico técnico con precios de materiales y servicios.",
        "tools": [inventory_search_tool, save_quote_tool],
        "llm": llm,
        "verbose": True,
    }

    revisor = {
        "role": cfg_revisor.get("role").strip() if cfg_revisor else "Agente Revisor (Gatekeeper)",
        "goal": cfg_revisor.get("goal").strip() if cfg_revisor else "Detectar campos vacíos, placeholders y inconsistencias antes de enviar",
        "backstory": cfg_revisor.get("backstory").strip() if cfg_revisor else "Aplicas gates del Playbook V2: sin @today, sin N/A inventado.",
        "tools": [],
        "llm": llm,
        "verbose": True,
    }

    comunicaciones = {
        "role": cfg_comunicaciones.get("role").strip() if cfg_comunicaciones else "Agente de Comunicaciones",
        "goal": cfg_comunicaciones.get("goal").strip() if cfg_comunicaciones else "Preparar resumen para correo y aviso operativo",
        "backstory": cfg_comunicaciones.get("backstory").strip() if cfg_comunicaciones else "Redactas mensajes claros para cliente y equipo interno.",
        "tools": [],
        "llm": llm,
        "verbose": True,
    }

    return {
        "director": director,
        "campo": campo,
        "cliente": cliente,
        "bitacora": bitacora,
        "informes": informes,
        "cotizador": cotizador,
        "revisor": revisor,
        "comunicaciones": comunicaciones,
    }
