"""Shadow-only Streamable HTTP JSON/SSE MCP proxy. No monolith imports or mutations."""
from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from .policy import Denied, Federation, Throttle, profile_tools, validate_paths, validate_projection

LOG = logging.getLogger("inneros.mcp_router")
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
CONFIG = Path(__file__).parent
from mcp.types import LATEST_PROTOCOL_VERSION
VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18", LATEST_PROTOCOL_VERSION}
MAX_BODY = 1024*1024
MAX_BACKEND = 16*1024*1024

@dataclass
class Session:
    client: str
    profile: str
    scopes: tuple
    allowed: tuple
    auth: dict
    upstream_id: str | None = None
    protocol: str = "2024-11-05"
    ready: bool = False
    catalog: dict = field(default_factory=dict)
    pin: str = ""
    deadline: float = 0.
    touched: float = field(default_factory=time.monotonic)
    catalog_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    listed_pin: str = ""

class Router:
    def __init__(self, backend_url="http://127.0.0.1:8102/mcp", identities=None,
                 roots=("/workspace",), ttl=60., client=None, allow_admin=False,
                 max_sessions=128, throttle=None, backends=None):
        if not 0 < ttl <= 300:
            raise ValueError("catalog TTL must be in (0,300]")
        validate_projection()
        self.backend_url, self.identities, self.roots = backend_url, identities or {}, roots
        self.ttl, self.allow_admin, self.max_sessions = ttl, allow_admin, max_sessions
        self.sessions, self.throttle = {}, throttle or Throttle()
        self.http = client or httpx.AsyncClient(timeout=20., follow_redirects=False, trust_env=False)
        self.federation = Federation(backends or json.loads((CONFIG/"backends.json").read_text()))
        if any(v.get("enabled") for k,v in self.federation.backends.items() if k != self.federation.default):
            raise ValueError("micro-backend transport disabled pending live parity")
        self.counters = {"denied_calls":0, "forwarded_calls":0}
        self.backend_reachable = False
        self.failures, self.open_until = 0, 0.
        self.metrics = []
        self._policies = {}
        for digest, conf in self.identities.items():
            profile = conf.get("profile", "profile_minimal")
            scopes = tuple(conf.get("scopes", ["ralfia:read"]))
            allowed = profile_tools(profile, scopes, admin_enabled=self.allow_admin,
                                    admin_authorized=conf.get("admin_authorized") is True)
            self._policies[digest] = (profile, scopes, allowed)

    def identity(self, request):
        auth = request.headers.get("authorization", "")
        if not auth or len(auth) > 8192:
            raise Denied("AuthenticationRequired", -32003)
        digest = hashlib.sha256(auth.encode()).hexdigest()
        conf = self.identities.get(digest)
        if not conf:
            raise Denied("AuthenticationRequired", -32003)
        profile, scopes, allowed = self._policies[digest]
        # Profile headers/queries never select privileges.
        override = request.headers.get("x-mcp-profile") or request.query_params.get("profile")
        if override and override != profile:
            raise Denied("UnauthorizedProfileError", -32003)
        if "admin_secret" in request.query_params:
            raise Denied("UnsafeCredentialTransport", -32003)
        return digest, profile, scopes, allowed, {"Authorization":auth}

    async def upstream(self, session, payload):
        if time.monotonic() < self.open_until:
            raise Denied("BackendCircuitOpen", -32006)
        headers = {"Accept":"application/json, text/event-stream", **session.auth}
        if session.upstream_id:
            headers["Mcp-Session-Id"] = session.upstream_id
        if payload.get("method") != "initialize":
            headers["MCP-Protocol-Version"] = session.protocol
        started = time.perf_counter()
        try:
            async with self.http.stream("POST", self.backend_url, json=payload, headers=headers) as response:
                if response.status_code >= 500:
                    raise httpx.TransportError("backend unavailable")
                if response.status_code >= 400:
                    raise Denied("BackendRejectedRequest", -32006)
                if response.status_code == 202:
                    self.backend_reachable = True
                    return None, (time.perf_counter()-started)*1000
                sid = response.headers.get("mcp-session-id")
                if sid:
                    if payload.get("method") != "initialize" and sid != session.upstream_id:
                        raise Denied("BackendSessionMismatch", -32006)
                    session.upstream_id = sid
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BACKEND:
                        raise Denied("BackendResponseTooLarge", -32006)
                    if "text/event-stream" in response.headers.get("content-type",""):
                        text = raw.decode("utf-8").replace("\r\n","\n")
                        while "\n\n" in text:
                            event, text = text.split("\n\n",1)
                            data = "\n".join(line[5:].lstrip() for line in event.splitlines() if line.startswith("data:"))
                            if not data:
                                continue
                            item = json.loads(data)
                            if item.get("method") == "notifications/tools/list_changed":
                                session.deadline = 0
                            if "id" in item and item["id"] == payload.get("id"):
                                self.backend_reachable, self.failures = True, 0
                                return item, (time.perf_counter()-started)*1000
                        raw = bytearray(text.encode())
                item = json.loads(raw)
                if not isinstance(item, dict) or item.get("id") != payload.get("id"):
                    raise Denied("InvalidBackendResponse", -32006)
                self.backend_reachable, self.failures = True, 0
                return item, (time.perf_counter()-started)*1000
        except httpx.TransportError:
            self.backend_reachable = False
            self.failures += 1
            if self.failures >= 3:
                self.open_until = time.monotonic()+5
            raise Denied("BackendTransportError", -32006) from None
        except (ValueError, UnicodeError):
            raise Denied("InvalidBackendResponse", -32006) from None

    async def catalog(self, session):
        if session.catalog and time.monotonic() < session.deadline:
            return True, 0.
        async with session.catalog_lock:
            if session.catalog and time.monotonic() < session.deadline:
                return True, 0.
            session.deadline = 0
            found, cursor, seen, elapsed = {}, None, set(), 0.
            for page in range(32):
                payload = {"jsonrpc":"2.0","id":"catalog-"+secrets.token_hex(8),"method":"tools/list",
                           "params":({"cursor":cursor} if cursor else {})}
                result, ms = await self.upstream(session, payload)
                elapsed += ms
                if not result or "error" in result:
                    raise Denied("CatalogUnavailable", -32005)
                result = result.get("result", {})
                if not isinstance(result.get("tools"), list):
                    raise Denied("InvalidCatalog", -32005)
                for tool in result["tools"]:
                    if not isinstance(tool, dict) or not NAME.fullmatch(str(tool.get("name",""))):
                        raise Denied("InvalidCatalog", -32005)
                    name = tool["name"]
                    if name in found or not isinstance(tool.get("inputSchema"),dict):
                        raise Denied("InvalidCatalog", -32005)
                    found[name] = tool
                if len(found)>10000:
                    raise Denied("CatalogTooLarge", -32005)
                cursor = result.get("nextCursor")
                if not cursor:
                    break
                if not isinstance(cursor,str) or cursor in seen:
                    raise Denied("InvalidCatalogCursor", -32005)
                seen.add(cursor)
            else:
                raise Denied("CatalogTooLarge", -32005)
            if not set(session.allowed).issubset(found):
                session.catalog = {}
                raise Denied("CatalogProfileMismatch", -32005)
            pin = hashlib.sha256(json.dumps(found,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            session.catalog, session.pin = found, pin
            session.deadline = time.monotonic()+self.ttl
            return False, elapsed

    async def handle(self, request: Request):
        msg_id, session, backend_ms, cache_hit = None, None, 0., False
        method, error_class = None, None
        started = time.perf_counter()
        try:
            host = request.headers.get("host","").split(":")[0]
            if host not in {"127.0.0.1","localhost","testserver"}:
                raise Denied("InvalidHost", -32003)
            origin = request.headers.get("origin")
            if origin and origin not in {"http://127.0.0.1:8103","http://localhost:8103"}:
                raise Denied("InvalidOrigin", -32003)
            ident, profile, scopes, allowed, auth = self.identity(request)
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > MAX_BODY:
                    raise Denied("RequestTooLarge", -32600)
            try:
                body = json.loads(raw)
            except ValueError:
                raise Denied("ParseError", -32700) from None
            if not isinstance(body,dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"),str):
                raise Denied("InvalidRequest", -32600)
            msg_id, method = body.get("id"), body["method"]
            if "id" in body and (isinstance(msg_id,bool) or not isinstance(msg_id,(str,int))):
                raise Denied("InvalidRequest", -32600)
            params = body.get("params",{})
            if not isinstance(params,dict):
                raise Denied("InvalidParams", -32602)
            sid = request.headers.get("mcp-session-id")
            if method == "initialize":
                if sid or "id" not in body or params.get("protocolVersion") not in VERSIONS:
                    raise Denied("InvalidInitialize", -32602)
                for old, item in list(self.sessions.items()):
                    if time.monotonic()-item.touched > 900:
                        del self.sessions[old]
                if len(self.sessions) >= self.max_sessions:
                    raise Denied("SessionLimit", -32004)
                session = Session(ident,profile,scopes,allowed,auth)
                result, backend_ms = await self.upstream(session,body)
                if not result or "error" in result:
                    return JSONResponse(result or {"jsonrpc":"2.0","id":msg_id,"error":{"code":-32006,"message":"BackendInitializeFailed"}})
                init = result.get("result",{})
                if init.get("protocolVersion") not in VERSIONS:
                    raise Denied("UnsupportedBackendProtocol", -32006)
                session.protocol = init["protocolVersion"]
                init["capabilities"] = {"tools":{"listChanged":False}}
                init["serverInfo"] = {"name":"InnerOS Shadow MCP Router","version":"0.1.0"}
                sid = secrets.token_urlsafe(32)
                self.sessions[sid] = session
                return JSONResponse(result,headers={"Mcp-Session-Id":sid})
            session = self.sessions.get(sid)
            if not session or session.client != ident or session.profile != profile or session.allowed != allowed:
                raise Denied("InvalidSession", -32003)
            session.touched = time.monotonic()
            if method == "notifications/initialized":
                if "id" in body:
                    raise Denied("InvalidRequest", -32600)
                _, backend_ms = await self.upstream(session,body)
                session.ready = True
                return Response(status_code=202)
            if "id" not in body:
                raise Denied("UnsupportedNotification", -32600)
            if not session.ready:
                raise Denied("SessionNotInitialized", -32003)
            if method == "ping":
                result, backend_ms = await self.upstream(session, body)
                return JSONResponse(result)
            if method not in {"tools/list","tools/call"}:
                raise Denied("MethodNotFound", -32601)
            if method == "tools/call":
                name = params.get("name")
                if not isinstance(name,str) or not NAME.fullmatch(name) or name not in session.allowed:
                    self.counters["denied_calls"] += 1
                    raise Denied("ToolNotAllowedError")
                validate_paths(name, params.get("arguments",{}),self.roots)
            async with self.throttle.acquire(ident,profile):
                cache_hit, backend_ms = await self.catalog(session)
                if method == "tools/list":
                    if params.get("cursor"):
                        raise Denied("InvalidCursor", -32602)
                    session.listed_pin = session.pin
                    result = {"jsonrpc":"2.0","id":msg_id,"result":{
                        "tools":[session.catalog[n] for n in session.allowed]}}
                else:
                    if not session.listed_pin or session.listed_pin != session.pin:
                        raise Denied("CatalogChangedRelistRequired", -32005)
                    self.counters["forwarded_calls"] += 1
                    result, ms = await self.upstream(session,body)
                    backend_ms += ms
                return JSONResponse(result)
        except Denied as exc:
            error_class = exc.kind
            return JSONResponse({"jsonrpc":"2.0","id":msg_id,"error":{
                "code":exc.code,"message":exc.kind,"data":{"error_class":exc.kind}}})
        except Exception:
            error_class = "InternalError"
            LOG.error("router_internal_error")
            return JSONResponse({"jsonrpc":"2.0","id":msg_id,"error":{"code":-32603,"message":"InternalError"}})
        finally:
            elapsed = (time.perf_counter()-started)*1000
            metric = {"method":method if method in {"initialize","ping","tools/list","tools/call","notifications/initialized"} else "other",
                      "profile":session.profile if session else None,"backend":"monolith",
                      "client_id_hash":session.client[:16] if session else None,
                      "backend_latency_ms":backend_ms,"gateway_latency_ms":max(0,elapsed-backend_ms),
                      "error_class":error_class,"cache_hit":cache_hit,"catalog_pin":session.pin if session else None,
                      "tools_list_backend_count":len(session.catalog) if session else 0,
                      "tools_list_exposed_count":len(session.allowed) if session else 0, **self.counters}
            self.metrics.append(metric)
            self.metrics = self.metrics[-1000:]
            LOG.info(json.dumps(metric))

    def app(self):
        async def health(request):
            return JSONResponse({"gateway_up":True,"shadow_mode":True,
                "backend_reachable":self.backend_reachable,
                "catalog_loaded":any(s.catalog for s in self.sessions.values()),
                "profile_valid":any(s.catalog and time.monotonic() < s.deadline and set(s.allowed).issubset(s.catalog) for s in self.sessions.values()),
                "federation_backends":{k:bool(v.get("enabled")) for k,v in self.federation.backends.items()}})
        @asynccontextmanager
        async def lifespan(app):
            yield
            await self.http.aclose()
        return Starlette(routes=[Route("/mcp",self.handle,methods=["POST"]),
                                Route("/health",health)],lifespan=lifespan)

def main():
    import uvicorn
    # Identity file contains SHA256 of full Authorization header and server-assigned policy.
    identities = json.loads(Path(os.environ["MCP_ROUTER_IDENTITIES_FILE"]).read_text())
    roots = tuple(json.loads(os.environ.get("MCP_ROUTER_ALLOWED_ROOTS",'["/workspace"]')))
    router = Router(backend_url=os.environ.get("MCP_ROUTER_BACKEND_URL","http://127.0.0.1:8102/mcp"),
                    identities=identities,roots=roots,allow_admin=os.environ.get("ALLOW_ADMIN_PROFILE")=="true")
    uvicorn.run(router.app(),host="127.0.0.1",port=int(os.environ.get("MCP_ROUTER_PORT","8103")),
                access_log=False)

if __name__ == "__main__":
    main()
