"""MCP Router & Dynamic Capability Broker Gateway Core Engine."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import time
from typing import Any

import httpx

from .federation import BackendEndpoint, FederationManager
from .profiles import ProfileManager, UnauthorizedProfileError
from .sandboxing import validate_tool_call_safety
from .throttling import ThrottlingManager, ToolThrottledError

try:
    from inneros_core_runtime.mcp_catalog import tool_catalog
except ImportError:
    try:
        from raphiia_openai.mcp_catalog import tool_catalog
    except ImportError:
        tool_catalog = None

logger = logging.getLogger("mcp_gateway")

# Fixed public contract for compact on-demand discovery and execution (<= 15 tools)
PUBLIC_BROKER_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_capabilities",
        "description": "Busca herramientas y capacidades en el catálogo completo de InnerOS por palabra clave o categoría bajo demanda.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Término de búsqueda (ej. 'git', 'docker', 'contifico', 'repo', 'ticket')"},
                "category": {"type": "string", "description": "Categoría opcional (ej. 'dev', 'finance', 'system', 'ai')"},
                "limit": {"type": "integer", "description": "Máximo de resultados a devolver (default 10, max 25)", "default": 10}
            },
            "required": ["query"]
        }
    },
    {
        "name": "describe_capability",
        "description": "Obtiene la definición detallada, esquema de parámetros JSON Schema, nivel de riesgo y versión de una capacidad específica por su ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "capability_id": {"type": "string", "description": "Nombre/ID exacto de la capacidad a consultar"}
            },
            "required": ["capability_id"]
        }
    },
    {
        "name": "invoke_capability",
        "description": "Ejecuta de forma directa y estructurada una capacidad autorizada de InnerOS con sus parámetros, aplicando validación server-side, sandboxing y auditoría.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "capability_id": {"type": "string", "description": "ID de la capacidad autorizada a ejecutar"},
                "arguments": {"type": "object", "description": "Diccionario de argumentos según el esquema de la capacidad"}
            },
            "required": ["capability_id", "arguments"]
        }
    },
    {
        "name": "get_coordination_status",
        "description": "Consulta el estado vivo de la coordinación de agentes, tareas activas y salud de la plataforma.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "detail_level": {"type": "string", "enum": ["summary", "full"], "default": "summary"}
            }
        }
    },
    {
        "name": "bootstrap_context",
        "description": "Carga el contexto inicial del ecosistema InnerOS, proyectos registrados y lineamientos.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "poll_agent_inbox",
        "description": "Consulta mensajes y notificaciones dirigidos al agente en su buzón de entrada.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10}
            }
        }
    },
    {
        "name": "create_agent_message",
        "description": "Envía un mensaje estructurado hacia otro agente o hacia el log de coordinación.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_agent": {"type": "string", "description": "Agente destino (ej. ralfia, chatgpt, antigravity)"},
                "title": {"type": "string", "description": "Título o asunto del mensaje"},
                "body": {"type": "string", "description": "Cuerpo del mensaje"},
                "payload": {"type": "object", "description": "Metadatos adicionales"}
            },
            "required": ["target_agent", "title", "body"]
        }
    },
    {
        "name": "list_ops_tasks",
        "description": "Lista tareas operativas registradas en pcdoctor_swarm.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filtrar por estado (in_progress, proposed, verification, blocked, completed)"},
                "limit": {"type": "integer", "default": 10}
            }
        }
    },
    {
        "name": "dev_swarm_launch_task",
        "description": "Propone o lanza una tarea técnica para ejecución por el enjambre de desarrollo local.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "task_class": {"type": "string"},
                "repo": {"type": "string"},
                "requirements": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["title", "task_class", "repo"]
        }
    },
    {
        "name": "dev_swarm_scheduler_status",
        "description": "Consulta el estado del scheduler de desarrollo local y capacidad de cómputo.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "diagnose_mcp_session",
        "description": "Diagnostica la sesión MCP, transporte y perfiles activos.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "mcp_version",
        "description": "Retorna la versión de la pasarela y del servidor MCP.",
        "inputSchema": {"type": "object", "properties": {}}
    }
]


class MCPGateway:
    def __init__(
        self,
        profile_manager: ProfileManager | None = None,
        federation_manager: FederationManager | None = None,
        throttling_manager: ThrottlingManager | None = None,
        tool_cache_ttl_sec: float = 300.0,
    ) -> None:
        self.profile_mgr = profile_manager or ProfileManager()
        self.federation_mgr = federation_manager or FederationManager(self.profile_mgr.config.get("backends"))
        self.throttling_mgr = throttling_manager or ThrottlingManager()
        self.tool_cache_ttl_sec = tool_cache_ttl_sec

        # In-memory catalog cache with fingerprinting
        self._tool_catalog_cache: dict[str, Any] = {}
        self._catalog_fingerprint: str = ""
        self._cache_timestamp: float = 0.0
        self._lock = asyncio.Lock()

    def compute_catalog_fingerprint(self, tools_dict: dict[str, Any]) -> str:
        """Calculate SHA-256 fingerprint of the upstream tool catalog."""
        encoded = json.dumps(tools_dict, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _get_local_catalog_tools(self) -> dict[str, dict[str, Any]]:
        """Extract tool definitions directly from local catalog."""
        tools: dict[str, dict[str, Any]] = {}
        if tool_catalog:
            names = getattr(tool_catalog, "ALL_MCP_TOOL_NAMES", [])
            for name in names:
                try:
                    desc = tool_catalog.describe_tool(name)
                    if desc and isinstance(desc, dict):
                        tools[name] = desc
                    else:
                        tools[name] = {"name": name, "description": f"Tool {name}"}
                except Exception:
                    tools[name] = {"name": name, "description": f"Tool {name}"}
        return tools

    async def fetch_all_upstream_tools(self) -> tuple[list[dict[str, Any]], str, bool]:
        """Fetch and aggregate tools from backends, returning (tools, fingerprint, from_cache)."""
        now = time.time()
        if self._tool_catalog_cache and (now - self._cache_timestamp) < self.tool_cache_ttl_sec:
            return list(self._tool_catalog_cache.values()), self._catalog_fingerprint, True

        async with self._lock:
            if self._tool_catalog_cache and (now - self._cache_timestamp) < self.tool_cache_ttl_sec:
                return list(self._tool_catalog_cache.values()), self._catalog_fingerprint, True

            aggregated: dict[str, dict[str, Any]] = {}

            # Populate from local catalog
            local_tools = self._get_local_catalog_tools()
            if local_tools:
                aggregated.update(local_tools)

            # Query registered micro-backends
            for backend_name, backend in self.federation_mgr.backends.items():
                if backend.is_default and local_tools:
                    continue
                req = {
                    "jsonrpc": "2.0",
                    "id": "gateway_tools_list_sync",
                    "method": "tools/list",
                    "params": {},
                }
                try:
                    res = await self.federation_mgr.forward_jsonrpc_post(backend, req)
                    tools = res.get("result", {}).get("tools", [])
                    for t in tools:
                        t_name = t.get("name")
                        if t_name:
                            aggregated[t_name] = t
                except Exception as e:
                    logger.debug("Upstream tool fetch notice for %s: %s", backend_name, e)

            new_fingerprint = self.compute_catalog_fingerprint(aggregated)
            if aggregated or not self._tool_catalog_cache:
                self._tool_catalog_cache = aggregated
                self._catalog_fingerprint = new_fingerprint
                self._cache_timestamp = now

            return list(self._tool_catalog_cache.values()), self._catalog_fingerprint, False

    def search_catalog_capabilities(self, query: str, category: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Search capabilities in the full live catalog by query string and category."""
        q = query.lower().strip()
        results: list[dict[str, Any]] = []
        max_results = min(max(1, limit), 25)

        for name, tool in self._tool_catalog_cache.items():
            desc = (tool.get("description") or "").lower()
            name_lower = name.lower()

            match = False
            if q in name_lower or q in desc:
                match = True
            elif any(part in name_lower for part in q.split()):
                match = True

            if category:
                cat_lower = category.lower()
                if cat_lower not in name_lower and cat_lower not in desc:
                    match = False

            if match:
                results.append({
                    "capability_id": name,
                    "description": tool.get("description", ""),
                    "category": category or "general",
                    "inputSchema_preview": list((tool.get("inputSchema") or {}).get("properties", {}).keys()),
                })
                if len(results) >= max_results:
                    break

        return results

    def describe_catalog_capability(self, capability_id: str) -> dict[str, Any]:
        """Describe a specific capability with full inputSchema, description, and metadata."""
        tool = self._tool_catalog_cache.get(capability_id)
        if not tool:
            if tool_catalog and hasattr(tool_catalog, "describe_tool"):
                try:
                    tool = tool_catalog.describe_tool(capability_id)
                except Exception:
                    tool = None

        if not tool:
            return {
                "ok": False,
                "error": f"CapabilityNotFoundError: Capability '{capability_id}' not found in live catalog.",
            }

        return {
            "ok": True,
            "capability_id": capability_id,
            "description": tool.get("description", ""),
            "inputSchema": tool.get("inputSchema", {}),
            "version": tool.get("version", "1.0.0"),
        }

    async def handle_jsonrpc(
        self,
        request: dict[str, Any],
        client_profile: str | None = None,
        headers: dict[str, str] | None = None,
        admin_secret: str | None = None,
    ) -> dict[str, Any]:
        """Handle incoming MCP JSON-RPC message, apply profile access control, throttling, and sandboxing."""
        method = request.get("method")
        msg_id = request.get("id")
        params = request.get("params", {}) or {}

        hdrs = headers or {}
        secret = admin_secret or hdrs.get("X-MCP-Admin-Secret") or hdrs.get("x-mcp-admin-secret")

        # 1. Validate Profile Access
        try:
            active_profile = self.profile_mgr.validate_profile_access(client_profile, client_secret=secret)
        except UnauthorizedProfileError as e:
            logger.warning("Rejected unauthorized profile request '%s': %s", client_profile, e.message)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": e.error_code,
                    "message": e.message,
                    "data": {"requested_profile": client_profile},
                },
            }

        prof_config = self.profile_mgr.get_profile(active_profile)

        # 2. Initialize Handshake
        if method == "initialize":
            default_backend = self.federation_mgr.get_default_backend()
            try:
                res = await self.federation_mgr.forward_jsonrpc_post(default_backend, request, hdrs)
                if "result" in res and isinstance(res["result"], dict):
                    server_info = res["result"].get("serverInfo", {})
                    server_info["gateway"] = "MCP-Broker-Gateway/2.0"
                    server_info["active_profile"] = active_profile
                    res["result"]["serverInfo"] = server_info
                return res
            except Exception:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {"listChanged": True}},
                        "serverInfo": {
                            "name": "MCP-Broker-Gateway",
                            "version": "2.0.0",
                            "active_profile": active_profile,
                        },
                    },
                }

        # 3. tools/list - Returns compact Broker Contract (<= 15 tools)
        if method == "tools/list":
            all_tools, fingerprint, cached = await self.fetch_all_upstream_tools()

            if active_profile == "profile_admin" and self.profile_mgr.allow_admin_profile:
                # Admin profile gets full catalog if authorized
                filtered = all_tools
            else:
                # Minimal / Broker default: returns fixed compact broker interface (<= 15 tools)
                filtered = list(PUBLIC_BROKER_TOOLS)

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": filtered,
                    "_profile": active_profile,
                    "_catalog_fingerprint": fingerprint,
                    "_from_cache": cached,
                    "_total_upstream_tools": len(all_tools),
                    "_exposed_tools": len(filtered),
                },
            }

        # 4. tools/call
        if method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {}) or {}

            if not tool_name:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32602,
                        "message": "InvalidParams: 'name' is required for tools/call",
                    },
                }

            # --- A. Built-in Dynamic Broker Tools ---
            if tool_name == "search_capabilities":
                await self.fetch_all_upstream_tools()
                q = tool_args.get("query", "")
                cat = tool_args.get("category")
                limit = int(tool_args.get("limit", 10))
                matches = self.search_catalog_capabilities(query=q, category=cat, limit=limit)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{
                            "type": "text",
                            "text": json.dumps({
                                "ok": True,
                                "query": q,
                                "total_catalog_size": len(self._tool_catalog_cache),
                                "matched_count": len(matches),
                                "capabilities": matches
                            }, indent=2)
                        }]
                    }
                }

            if tool_name == "describe_capability":
                await self.fetch_all_upstream_tools()
                cap_id = tool_args.get("capability_id", "")
                desc = self.describe_catalog_capability(cap_id)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{
                            "type": "text",
                            "text": json.dumps(desc, indent=2)
                        }]
                    }
                }

            if tool_name == "invoke_capability":
                target_cap_id = tool_args.get("capability_id")
                target_args = tool_args.get("arguments", {})
                if not target_cap_id:
                    return {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32602,
                            "message": "InvalidParams: 'capability_id' is required for invoke_capability",
                        }
                    }
                # Forward to target capability execution with sandboxing and authorization
                return await self._execute_capability(
                    capability_id=target_cap_id,
                    arguments=target_args,
                    msg_id=msg_id,
                    active_profile=active_profile,
                    prof_config=prof_config,
                    headers=hdrs,
                )

            if tool_name == "get_coordination_status":
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{
                            "type": "text",
                            "text": json.dumps({
                                "ok": True,
                                "status": "coordination_active",
                                "mcp_gateway": "online",
                                "active_profile": active_profile,
                                "catalog_size": len(self._tool_catalog_cache),
                                "throttling": self.throttling_mgr.get_stats()
                            }, indent=2)
                        }]
                    }
                }

            # --- B. Direct Tool Execution (Fallback / Native calls) ---
            return await self._execute_capability(
                capability_id=tool_name,
                arguments=tool_args,
                msg_id=msg_id,
                active_profile=active_profile,
                prof_config=prof_config,
                headers=hdrs,
            )

        # 5. Transparent Proxy for generic methods
        default_backend = self.federation_mgr.get_default_backend()
        try:
            return await self.federation_mgr.forward_jsonrpc_post(default_backend, request, hdrs)
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": f"GatewayProxyError: Failed forwarding method '{method}': {e}",
                },
            }

    async def _execute_capability(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        msg_id: Any,
        active_profile: str,
        prof_config: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Execute a capability with server-side sandboxing, throttling, and backend routing."""
        # 1. Sandboxing and Path Validation
        sb_check = validate_tool_call_safety(
            capability_id,
            arguments,
            prof_config.get("sandboxing"),
        )
        if not sb_check.allowed:
            logger.warning("Capability '%s' blocked by sandbox: %s", capability_id, sb_check.error_message)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": sb_check.error_code,
                    "message": sb_check.error_message,
                    "data": {"capability_id": capability_id, "arguments": arguments},
                },
            }

        # 2. Concurrency Throttling & Upstream Dispatch
        try:
            async with self.throttling_mgr.acquire(active_profile):
                backend = self.federation_mgr.resolve_backend_for_tool(capability_id)
                forward_req = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "method": "tools/call",
                    "params": {
                        "name": capability_id,
                        "arguments": sb_check.sanitized_args if sb_check.sanitized_args is not None else arguments
                    }
                }
                res = await self.federation_mgr.forward_jsonrpc_post(backend, forward_req, headers)
                return res
        except ToolThrottledError as e:
            logger.warning("Throttled capability '%s' under profile '%s': %s", capability_id, active_profile, e.message)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": e.error_code,
                    "message": e.message,
                    "data": {"profile": e.profile, "concurrency_limit": e.limit},
                },
            }
        except httpx.HTTPStatusError as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": f"UpstreamBackendError: HTTP {e.response.status_code} from {backend.name}",
                    "data": str(e),
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": f"UpstreamExecutionError: Failed to reach {backend.name}: {e}",
                },
            }
