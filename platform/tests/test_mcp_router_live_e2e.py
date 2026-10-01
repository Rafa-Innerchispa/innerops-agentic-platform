"""Real MCP SDK shadow client against the live monolith, temporary isolated listener."""
import asyncio
import hashlib
import json
import secrets
import socket
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import os
import pytest
pytestmark = pytest.mark.skipif(os.getenv('MCP_ROUTER_RUN_LIVE') != '1', reason='Explicit live shadow test opt-in required')
import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from inneros_core_runtime.mcp_router.server import Router
from inneros_core_runtime.mcp_router.policy import Throttle

def test_real_mcp_shadow_e2e():
    auth="Bearer "+secrets.token_urlsafe(32)
    digest=hashlib.sha256(auth.encode()).hexdigest()
    router=Router(identities={digest:{"profile":"profile_coding","scopes":["ralfia:read","ralfia:agents"]}},
                  throttle=Throttle(rate=100,burst=200))
    sock=socket.socket()
    sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
    sock.bind(("127.0.0.1",0))
    port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(router.app(),log_level="error",access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True)
    thread.start()
    for _ in range(100):
        if server.started: break
        time.sleep(.02)
    assert server.started
    async def run():
        async with streamable_http_client("http://127.0.0.1:8102/mcp") as (r,w,_):
            async with ClientSession(r,w) as direct:
                di=await direct.initialize()
                dl=await direct.list_tools()
                from inneros_core_runtime.mcp_router.policy import profile_tools
                expected=set(profile_tools("profile_coding",["ralfia:read","ralfia:agents"]))
                names={t.name for t in dl.tools}
                print("LIVE_CATALOG",json.dumps({"count":len(names),"missing_canonical_tools":sorted(expected-names), "gitlab_tools":sorted(n for n in names if n.startswith("local_gitlab_")), "docker_tools":sorted(n for n in names if "docker" in n)}))
                dp=await direct.send_ping()
                dc=await direct.call_tool("local_exec_inspect_repo",{"repo":"Rafa-Innerchispa/innerops-agentic-platform"})
                async with httpx.AsyncClient(headers={"Authorization":auth}) as http:
                    async with streamable_http_client("http://127.0.0.1:"+str(port)+"/mcp",http_client=http) as (rr,ww,_):
                        async with ClientSession(rr,ww) as shadow:
                            si=await shadow.initialize()
                            sl=await shadow.list_tools()
                            assert len(sl.tools)<=25
                            assert {t.name for t in sl.tools}.issubset({t.name for t in dl.tools})
                            sc=await shadow.call_tool("local_exec_inspect_repo",{"repo":"Rafa-Innerchispa/innerops-agentic-platform"})
                            assert sc.model_dump()==dc.model_dump()
                            before=router.counters["forwarded_calls"]
                            try:
                                await shadow.call_tool("unapproved_canary",{})
                            except Exception as exc:
                                assert "ToolNotAllowedError" in str(exc)
                            else: raise AssertionError("denied call accepted")
                            assert router.counters["forwarded_calls"]==before
                            await shadow.send_ping()
                            listing=[]
                            for _ in range(20):
                                start=time.perf_counter()
                                await shadow.list_tools()
                                listing.append((time.perf_counter()-start)*1000)
                            direct_times=[]
                            shadow_times=[]
                            for _ in range(10):
                                start=time.perf_counter()
                                await direct.call_tool("local_exec_inspect_repo",{"repo":"Rafa-Innerchispa/innerops-agentic-platform"})
                                direct_times.append((time.perf_counter()-start)*1000)
                                start=time.perf_counter()
                                await shadow.call_tool("local_exec_inspect_repo",{"repo":"Rafa-Innerchispa/innerops-agentic-platform"})
                                shadow_times.append((time.perf_counter()-start)*1000)
                            def pct(values,p): return sorted(values)[min(len(values)-1,int(len(values)*p))]
                            overhead=[m["gateway_latency_ms"] for m in router.metrics if m["method"]=="tools/call"]
                            evidence={"profile":"profile_coding","port":port,"production_cutover":False,"backend_count":len(dl.tools),
                                "exposed_count":len(sl.tools),"direct_bytes":len(dl.model_dump_json().encode()),
                                "filtered_bytes":len(sl.model_dump_json().encode()),"call_parity":True,
                                "denied_not_forwarded":True,"session_survives":True,
                                "cached_list_p50_ms":pct(listing,.5),"cached_list_p95_ms":pct(listing,.95),
                                "direct_call_p50_ms":pct(direct_times,.5),"direct_call_p95_ms":pct(direct_times,.95),
                                "router_call_p50_ms":pct(shadow_times,.5),"router_call_p95_ms":pct(shadow_times,.95),
                                "gateway_overhead_p95_ms":pct(overhead,.95)}
                            print("SHADOW_E2E",json.dumps(evidence))
                            assert evidence["cached_list_p95_ms"]<=50
                            assert evidence["gateway_overhead_p95_ms"]<=20
    try:
        asyncio.run(run())
    finally:
        server.should_exit=True
        thread.join(5)
        sock.close()
    assert not thread.is_alive()
    print("ROLLBACK temporary router stopped; production services unchanged")
