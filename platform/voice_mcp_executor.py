"""Ejecutor MCP para voice gateway — herramientas reales (in-process + HTTP MCP)."""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from raphiia_openai.voice_user_profile import is_rafael

MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8102/mcp").rstrip("/")
MCP_API_KEY = os.getenv("MCP_API_KEY", "")


def _mcp_urls_for_tool(tool_name: str) -> list[str]:
    try:
        from raphiia_openai import mcp_fleet

        return mcp_fleet.get_mcp_urls_ordered(tool_name=tool_name)
    except Exception:
        return [MCP_URL.rstrip("/")]

# Lectura segura para operadores; Rafael/admin tiene acceso ampliado
OPERATOR_TOOLS = frozenset(
    {
        "hybrid_search",
        "get_context_summary",
        "get_unified_stack_status",
        "get_server_status",
        "get_infrastructure_status",
        "fleet_overview",
        "bootstrap_context",
        "get_operational_runbooks",
        "resolve_client",
        "list_clients",
        "resolve_party",
        "list_ops_tasks",
        "mcp_version",
    }
)

RAFAEL_EXTRA_TOOLS = frozenset(
    {
        "poll_agent_inbox",
        "route_mcp_tools",
        "quoteops_start_or_continue_mission",
        "quoteops_get_mission",
        "get_whatsapp_status",
        "send_whatsapp_message",
        "send_whatsapp_draft",
        "create_quote_draft",
        "update_quote_draft",
        "generate_quote_intro",
        "fetch",
        "user_memory_search",
        "trigger_email_poll",
        "list_monitored_emails",
        "ha_list_entities",
        "ha_get_entity",
        "ha_turn_on_light",
        "ha_turn_off_light",
        "ha_call_service",
        "ha_home_status",
        "resolve_client",
    }
)


def allowed_tools(user: dict[str, Any]) -> frozenset[str]:
    if is_rafael(user) or user.get("is_admin"):
        return OPERATOR_TOOLS | RAFAEL_EXTRA_TOOLS
    return OPERATOR_TOOLS


def _in_process_call(name: str, args: dict[str, Any]) -> dict[str, Any] | None:
    try:
        if name == "hybrid_search":
            from raphiia_openai import hybrid_context

            return hybrid_context.hybrid_search(
                str(args.get("query") or ""),
                limit=int(args.get("limit") or 8),
                entity_id=args.get("entity_id"),
            )
        if name == "get_unified_stack_status":
            from raphiia_openai import hybrid_context, mongo_store
            from raphiia_openai.notifications.evolution_client import dual_whatsapp_status

            return {
                "ok": True,
                "mongo": mongo_store.mongo_connection_info(),
                "mongo_ping": mongo_store.ping_mongo(),
                "qdrant": hybrid_context.qdrant_health(),
                "whatsapp": dual_whatsapp_status(),
                "summary": mongo_store.get_context_summary(),
            }
        if name == "fleet_overview":
            from raphiia_openai.fleet_overview import fleet_overview

            return fleet_overview()
        if name == "get_server_status":
            from raphiia_openai import mcp_server  # noqa: PLC0415

            return mcp_server.get_server_status()
        if name == "get_infrastructure_status":
            from raphiia_openai.infrastructure_runtime import get_infrastructure_status

            return get_infrastructure_status()
        if name == "get_context_summary":
            from raphiia_openai import mongo_store

            return mongo_store.get_context_summary()
        if name == "poll_agent_inbox":
            from raphiia_openai.memory import agent_messages as am

            return am.poll_agent_inbox(
                str(args.get("agent") or "ralfia_voice"),
                limit=int(args.get("limit") or 8),
                auto_ack=bool(args.get("auto_ack", False)),
            )
        if name == "bootstrap_context":
            from raphiia_openai import mongo_store

            return mongo_store.get_context_summary()
        if name == "list_ops_tasks":
            from raphiia_openai import coordination_live

            return coordination_live.list_ops_tasks(
                assignee=args.get("assignee"),
                status=args.get("status"),
                limit=int(args.get("limit") or 12),
            )
        if name == "trigger_email_poll":
            from raphiia_openai.notifications import email_monitor

            return email_monitor.trigger_email_poll()
        if name == "list_monitored_emails":
            from raphiia_openai.notifications import email_monitor

            return {
                "ok": True,
                **email_monitor.list_monitored_accounts(),
                "recent_messages": email_monitor.list_recent_emails(
                    importance=str(args.get("importance") or "alta"),
                    limit=int(args.get("limit") or 8),
                ).get("messages", []),
            }
        if name == "ha_list_entities":
            from raphiia_openai import homeassistant_client as ha

            return ha.list_states(domain=args.get("domain"), limit=int(args.get("limit") or 40))
        if name == "ha_turn_on_light":
            from raphiia_openai import homeassistant_client as ha

            return ha.turn_on_light(str(args.get("name_or_entity") or ""))
        if name == "ha_turn_off_light":
            from raphiia_openai import homeassistant_client as ha

            return ha.turn_off_light(str(args.get("name_or_entity") or ""))
        if name == "ha_get_entity":
            from raphiia_openai import homeassistant_client as ha

            return ha.get_state(str(args.get("entity_id") or args.get("name_or_entity") or ""))
        if name == "ha_call_service":
            from raphiia_openai import homeassistant_client as ha

            return ha.call_service(
                str(args.get("domain") or ""),
                str(args.get("service") or ""),
                entity_id=args.get("entity_id"),
                data=args.get("data"),
            )
        if name == "ha_home_status":
            from raphiia_openai import homeassistant_client as ha

            return ha.home_status(limit=int(args.get("limit") or 40))
        if name == "resolve_client":
            from raphiia_openai import pcdoctor_store

            return pcdoctor_store.resolve_client(
                str(args.get("identifier") or args.get("query") or ""),
                limit=int(args.get("limit") or 10),
            )
        if name == "list_clients":
            from raphiia_openai import pcdoctor_store

            return pcdoctor_store.list_clients(limit=int(args.get("limit") or 25))
        if name == "create_quote_draft":
            from raphiia_openai import mcp_server  # noqa: PLC0415

            return mcp_server.create_quote_draft(
                {
                    "client_name": str(args.get("client_name") or "Cliente"),
                    "notes": str(args.get("notes") or args.get("text") or ""),
                }
            )
    except ImportError:
        return None
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return None


def _run_async(coro: Any) -> Any:
    """Ejecuta coroutine MCP aunque ya haya event loop (FastAPI/uvicorn)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _call_mcp_http(name: str, args: dict[str, Any]) -> dict[str, Any]:
    async def _run_url(mcp_url: str) -> dict[str, Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        headers = {"X-API-Key": MCP_API_KEY} if MCP_API_KEY else {}
        async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, args)
                if result.structuredContent is not None:
                    return result.structuredContent if isinstance(result.structuredContent, dict) else {"data": result.structuredContent}
                texts = [getattr(c, "text", str(c)) for c in (result.content or [])]
                return {"ok": True, "text": "\n".join(texts)[:4000]}

    errors: list[str] = []
    for mcp_url in _mcp_urls_for_tool(name):
        try:
            return _run_async(_run_url(mcp_url))
        except Exception as exc:
            errors.append(f"{mcp_url}: {exc}")
            continue
    return {"ok": False, "error": "mcp_failover_exhausted", "attempts": errors[:3]}


def call_tool(user: dict[str, Any], name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    name = (name or "").strip()
    if name not in allowed_tools(user):
        return {"ok": False, "error": "tool_not_allowed", "tool": name}
    payload = dict(args or {})
    local = _in_process_call(name, payload)
    if local is not None:
        return local
    return _call_mcp_http(name, payload)


def _extract_search_query(text: str) -> str:
    t = (text or "").strip()
    for pat in (
        r"(?:busca(?:r)?|encuentra|search)\s+(?:sobre\s+)?(.{3,120})",
        r"(?:qué sabes de|info(?:rmación)? de)\s+(.{3,120})",
    ):
        m = re.search(pat, t, re.I)
        if m:
            return m.group(1).strip().rstrip("?.")
    return t[:120]


_CLIENT_LIST_RE = re.compile(
    r"\b(clientes?\s+(?:registrados?|activos?|que\s+tengo|de\s+pc\s*doctor)|"
    r"mis\s+clientes?|lista\s+de\s+clientes?|cu[aá]ntos\s+clientes?)\b",
    re.I,
)
_CLIENT_STOPWORDS = {
    "registrados", "registrado", "activos", "activo", "tengo", "mis", "lista", "listado",
    "cliente", "clientes", "particular", "especifico", "específico",
}

_BARE_CLIENT_SKIP = frozenset({
    "hola", "hello", "hi", "hey", "ok", "okay", "vale", "gracias", "thanks", "thank",
    "si", "sí", "no", "buenos", "dias", "días", "tarde", "noches", "noche", "buenas",
    "que", "qué", "como", "cómo", "donde", "dónde", "cuando", "cuándo", "por", "para",
    "the", "and", "pero", "pero", "solo", "please", "porfavor", "por favor",
    "estado", "servidor", "servidores", "server", "health", "del", "de", "la", "el", "los", "las",
    "ambos", "informacion", "información", "local", "guardado", "guardada", "leer", "puedes",
})


def _extract_bare_client_name(text: str) -> str | None:
    """Nombre corto tipo «Cafecom» / «Riverfront» sin decir «cliente»."""
    raw = (text or "").strip()
    if len(raw) < 2 or len(raw) > 40:
        return None
    words = raw.split()
    if not 1 <= len(words) <= 3:
        return None
    cleaned: list[str] = []
    for word in words:
        token = word.strip("?.!," )
        if not token or not re.fullmatch(r"[\w\-]+", token, flags=re.UNICODE):
            return None
        low = token.lower()
        if low in _BARE_CLIENT_SKIP or low in _CLIENT_STOPWORDS:
            return None
        cleaned.append(token)
    ident = " ".join(cleaned).strip()
    if len(ident) < 2:
        return None
    if _CLIENT_LIST_RE.search(raw):
        return None
    return ident


def _extract_client_identifier(text: str) -> str | None:
    t = (text or "").strip()
    if _CLIENT_LIST_RE.search(t):
        return None
    for pat in (
        r"(?:busca(?:r)?|encuentra|info(?:rmación)?(?:\s+de)?|datos?\s+de|dame)\s+(?:cliente\s+)?(.{2,80})",
        r"(?:cliente|clientes)\s+(?:de\s+)?(.{2,80})",
        r"(?:quién es|quien es)\s+(?:el\s+)?cliente\s+(.{2,80})",
        r"(?:busca(?:r)?|encuentra)\s+(?:al?\s+)?(.{2,60})\s+(?:en\s+)?(?:clientes?|pc\s*doctor)",
    ):
        m = re.search(pat, t, re.I)
        if m:
            ident = m.group(1).strip().rstrip("?.")
            ident = re.sub(r"\b(pc\s*doctor|pcdoctor)\b", "", ident, flags=re.I).strip()
            if ident and len(ident) >= 2 and ident.lower() not in _CLIENT_STOPWORDS:
                return ident
    return None


_HA_KW = (
    r"wifikong|sp3s|zhi_neng|socket|enchufe|cocina|estudio|bodega|entrada|sombrilla|cinta|living|comedor|"
    r"sala|dormitorio|ba[ñn]o|garage|patio|oficina|office|pasillo|terraza|cuarto|habitaci[oó]n"
)


def _is_ha_intent(t: str) -> bool:
    return bool(
        re.search(
            rf"\b(enciende|prende|activa|apaga|apagar|desactiva|casa|dom[oó]tica|home assistant|"
            rf"luces|estado de la casa|qu[eé] luces|interruptores|{_HA_KW})\b",
            t,
            re.I,
        )
    )


def _is_client_intent(t: str) -> bool:
    return bool(re.search(r"\b(cliente|clientes)\b", t, re.I))


def detect_tool_calls(user: dict[str, Any], text: str) -> list[tuple[str, dict[str, Any]]]:
    """Heurística de intención → herramientas MCP."""
    t = (text or "").lower()
    calls: list[tuple[str, dict[str, Any]]] = []
    perms = allowed_tools(user)
    ha_intent = _is_ha_intent(t)
    client_intent = _is_client_intent(t)
    _ha_query = ha_intent

    if perms & {"poll_agent_inbox"} and re.search(r"\b(pendiente|inbox|mensajes?\s+agente)\b", t):
        calls.append(("poll_agent_inbox", {"agent": "ralfia_voice", "limit": 8, "auto_ack": False}))

    if "get_server_status" in perms and re.search(
        r"\b(servidor(es)?|server|conecta(r)?(\s+a)?(\s+mi)?(\s+servidor)?|ssh|gpu|rocm|vllm|whisper|comfyui)\b", t
    ):
        calls.append(("get_server_status", {}))

    if "get_unified_stack_status" in perms and re.search(
        r"\b(estado|stack|salud|health|qdrant|mongo)\b", t
    ) and not _ha_query and not re.search(r"\b(servidor|server|fleet|gpu)\b", t):
        calls.append(("get_unified_stack_status", {}))

    if re.search(r"\b(fleet|flota|nodos?|intel|amd|192\.168\.1\.[45]|servicios?\s+(ok|ca[ií]dos?))\b", t):
        if "fleet_overview" in perms:
            calls.append(("fleet_overview", {}))

    if "get_infrastructure_status" in perms and re.search(
        r"\b(infra(estructura)?|snapshot|hostname|procesos|memoria\s+ram|disco)\b", t
    ):
        calls.append(("get_infrastructure_status", {}))

    if "list_ops_tasks" in perms and re.search(r"\b(tareas?\s+ops|ops\s+tasks|mis\s+tareas)\b", t):
        calls.append(("list_ops_tasks", {"limit": 10}))

    if "get_whatsapp_status" in perms and re.search(r"\b(whatsapp|wsp|evolution)\b", t):
        calls.append(("get_whatsapp_status", {"dual": True}))

    if "list_clients" in perms and client_intent:
        ident = _extract_client_identifier(text)
        if ident:
            if "resolve_client" in perms:
                calls.append(("resolve_client", {"identifier": ident, "limit": 8}))
        elif _CLIENT_LIST_RE.search(t) or re.search(r"\bclientes?\b", t):
            calls.append(("list_clients", {"limit": 40}))

    if (
        "resolve_client" in perms
        and not ha_intent
        and not client_intent
        and not any(name == "resolve_client" for name, _ in calls)
    ):
        bare = _extract_bare_client_name(text)
        if bare:
            calls.append(("resolve_client", {"identifier": bare, "limit": 8}))

    if "hybrid_search" in perms and not ha_intent and not client_intent and (
        re.search(r"\b(busca|encuentra|search|qué sabes|informaci[oó]n)\b", t)
        or (len(text.strip()) > 20 and not re.search(r"\b(enciende|apaga|prende|luces?|casa)\b", t))
    ):
        calls.append(("hybrid_search", {"query": _extract_search_query(text), "limit": 8}))

    if "route_mcp_tools" in perms and re.search(r"\b(cotiz|quote|presupuesto)\b", t):
        calls.append(
            (
                "route_mcp_tools",
                {"title": text[:200], "body": text, "requested_profile": "quoter", "max_risk": "medium"},
            )
        )
        if re.search(r"\b(inicia|crea|nueva|empezar)\b", t):
            calls.append(
                (
                    "create_quote_draft",
                    {"client_name": "Por voz", "notes": text[:500]},
                )
            )

    if "get_operational_runbooks" in perms and re.search(r"\b(runbook|procedimiento|cómo\s+cotiz)\b", t):
        calls.append(("get_operational_runbooks", {}))

    if (
        "get_context_summary" in perms
        and not client_intent
        and re.search(r"\b(resumen|contexto|pipeline|clientes)\b", t)
    ):
        calls.append(("get_context_summary", {}))

    if "trigger_email_poll" in perms and re.search(r"\b(correo|email|buz[oó]n|mail|imap)\b", t):
        if re.search(r"\b(revisa|poll|actualiza|nuevo)\b", t):
            calls.append(("trigger_email_poll", {}))
        else:
            calls.append(("list_monitored_emails", {"limit": 8, "importance": "alta"}))

    if "ha_turn_on_light" in perms and re.search(r"\b(enciende|prende|activa|abre)\b", t):
        km = re.search(rf"\b({_HA_KW})\b", t, re.I)
        if km or re.search(r"\b(luz|luces|light|interruptor|enchufe|switch)\b", t):
            target = km.group(1) if km else (re.search(r"\b(?:la|el|del|de la)\s+([a-záéíóúñ0-9 _-]{2,40})", t, re.I) or [None, "living"])[1]
            calls.append(("ha_turn_on_light", {"name_or_entity": str(target).strip()}))

    if "ha_turn_off_light" in perms and re.search(r"\b(apaga|apagar|desactiva|cierra)\b", t):
        km = re.search(rf"\b({_HA_KW})\b", t, re.I)
        if km or re.search(r"\b(luz|luces|light|interruptor|enchufe|switch)\b", t):
            target = km.group(1) if km else (re.search(r"\b(?:la|el|del|de la)\s+([a-záéíóúñ0-9 _-]{2,40})", t, re.I) or [None, "living"])[1]
            calls.append(("ha_turn_off_light", {"name_or_entity": str(target).strip()}))

    if "ha_get_entity" in perms and re.search(rf"\b(estado|c[oó]mo est[aá])\b.*\b({_HA_KW}|luz|living|cocina)\b", t, re.I):
        km = re.search(rf"\b({_HA_KW})\b", t, re.I)
        if km:
            calls.append(("ha_get_entity", {"name_or_entity": km.group(1)}))

    if "ha_home_status" in perms and _ha_query and re.search(
        r"\b(estado|c[oó]mo est[aá]|qu[eé] (luces|interruptores)|resumen)\b", t
    ):
        calls.insert(0, ("ha_home_status", {"limit": 35}))

    if "ha_list_entities" in perms and re.search(
        r"\b(casa|dom[oó]tica|home assistant|luces|estado de la casa|qu[eé] luces|interruptores)\b", t
    ):
        dom = "switch" if re.search(r"\b(interruptor|enchufe|switch)\b", t) else "light"
        if not any(c[0] == "ha_home_status" for c in calls):
            calls.append(("ha_list_entities", {"domain": dom, "limit": 30}))

    # Priorizar domótica y clientes sobre stack/RAG genérico
    _priority = {
        "ha_turn_on_light": 0,
        "ha_turn_off_light": 0,
        "ha_home_status": 0,
        "ha_get_entity": 1,
        "ha_list_entities": 1,
        "get_server_status": 1,
        "get_unified_stack_status": 2,
        "fleet_overview": 2,
        "resolve_client": 3,
        "list_clients": 3,
        "get_context_summary": 4,
        "hybrid_search": 8,
    }
    calls.sort(key=lambda item: _priority.get(item[0], 5))

    seen: set[str] = set()
    out: list[tuple[str, dict[str, Any]]] = []
    for name, args in calls:
        if name not in seen:
            seen.add(name)
            out.append((name, args))
    return out[:4]


def execute_for_message(user: dict[str, Any], text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, args in detect_tool_calls(user, text):
        result = call_tool(user, name, args)
        results.append({"tool": name, "args": args, "result": result})
    return results


def format_tool_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = ["=== Resultados herramientas MCP (ejecutadas) ==="]
    lines.append(
        "IMPORTANTE: Estos datos ya fueron obtenidos en vivo. Responde con cifras y hechos concretos; "
        "NO digas «voy a conectar», «intentaré» ni describas pasos futuros."
    )
    for item in results:
        name = item.get("tool")
        result = item.get("result") or {}
        if name == "ha_home_status" and result.get("summary"):
            lines.append(f"**{name}**:\n{result['summary']}")
            continue
        if name in ("resolve_client", "list_clients") and result.get("matches"):
            brief = []
            for m in (result.get("matches") or [])[:8]:
                brief.append(
                    f"- {m.get('display_name') or m.get('name') or m.get('client_name') or m.get('client_id', '?')}"
                    f" ({m.get('phone') or m.get('email') or 'sin contacto'})"
                )
            total_legacy = result.get("total_legacy")
            total_ops = result.get("total_ops")
            extra = ""
            if total_legacy is not None or total_ops is not None:
                extra = f" [legacy={total_legacy}, ops={total_ops}]"
            label = "coincidencias" if name == "resolve_client" else "clientes"
            lines.append(f"**{name}** ({result.get('count', 0)} {label}{extra}):\n" + "\n".join(brief))
            continue
        snippet = json.dumps(result, ensure_ascii=False, default=str)[:1800]
        lines.append(f"**{name}**:\n{snippet}")
    return "\n\n".join(lines)[:6000]


def tools_summary_for_user(user: dict[str, Any]) -> list[str]:
    return sorted(allowed_tools(user))
