"""Security, protocol, transport and canonical-policy regression tests."""
import asyncio
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import pytest
from starlette.testclient import TestClient
from inneros_core_runtime.mcp_router.policy import Denied, Throttle, Federation, profile_tools, validate_paths
from inneros_core_runtime.mcp_router.server import Router

AUTH = "Bearer isolated-test-credential"
DIGEST = hashlib.sha256(AUTH.encode()).hexdigest()
IDENTITIES = {DIGEST:{"profile":"profile_minimal","scopes":["ralfia:read"]}}
INIT = {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
    "protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"shadow-test","version":"1"}}}

class Backend:
    def __init__(self, sse=False):
        self.calls=[]
        self.tools=[{"name":n,"description":n,"inputSchema":{"type":"object","properties":{}}}
                    for n in profile_tools("profile_minimal",["ralfia:read"])]
        self.sse=sse
        self.fail=False
    def __call__(self, request):
        body=json.loads(request.content)
        self.calls.append(body)
        if self.fail:
            raise httpx.ConnectError("test failure")
        method=body["method"]
        if method != "initialize":
            assert request.headers["mcp-session-id"] == "private-upstream-session"
        if method=="notifications/initialized":
            return httpx.Response(202)
        result={}
        if method=="initialize":
            result={"protocolVersion":"2025-03-26","capabilities":{"tools":{}},"serverInfo":{"name":"backend","version":"1"}}
        elif method=="tools/list":
            result={"tools":self.tools}
        elif method=="tools/call":
            result={"content":[{"type":"text","text":"canary"}],"isError":False}
        msg={"jsonrpc":"2.0","id":body["id"],"result":result}
        headers={"Mcp-Session-Id":"private-upstream-session"}
        if self.sse:
            headers["Content-Type"]="text/event-stream"
            return httpx.Response(200,content=("event: message\ndata: "+json.dumps(msg)+"\n\n").encode(),headers=headers)
        return httpx.Response(200,json=msg,headers=headers)

def fixture(sse=False):
    backend=Backend(sse)
    router=Router(identities=IDENTITIES,client=httpx.AsyncClient(transport=httpx.MockTransport(backend)),
                  throttle=Throttle(rate=1000,burst=1000))
    client=TestClient(router.app())
    headers={"Authorization":AUTH}
    response=client.post("/mcp",json=INIT,headers=headers)
    assert "result" in response.json(),response.text
    sid=response.headers["mcp-session-id"]
    assert sid!="private-upstream-session"
    headers["Mcp-Session-Id"]=sid
    assert client.post("/mcp",json={"jsonrpc":"2.0","method":"notifications/initialized"},headers=headers).status_code==202
    return backend,router,client,headers

def rpc(client,headers,method,params=None):
    return client.post("/mcp",headers=headers,json={"jsonrpc":"2.0","id":2,"method":method,"params":params or {}}).json()

@pytest.mark.parametrize("sse",[False,True])
def test_protocol_allowed_denied_and_session_survives(sse):
    backend,router,client,headers=fixture(sse)
    listing=rpc(client,headers,"tools/list")
    names={t["name"] for t in listing["result"]["tools"]}
    assert 0<len(names)<=15
    assert names==set(profile_tools("profile_minimal",["ralfia:read"]))
    before=len(backend.calls)
    denial=rpc(client,headers,"tools/call",{"name":"secret_unapproved","arguments":{"secret":"do-not-log"}})
    assert denial["error"]["message"]=="ToolNotAllowedError"
    assert len(backend.calls)==before
    assert "result" in rpc(client,headers,"ping")
    result=rpc(client,headers,"tools/call",{"name":"mcp_version","arguments":{}})
    assert result["result"]["content"][0]["text"]=="canary"
    assert "do-not-log" not in json.dumps(router.metrics)
    assert "result" in rpc(client,headers,"tools/list")
    assert sum(x["method"]=="tools/list" for x in backend.calls)==1

def test_auth_and_profile_elevation():
    backend,router,client,headers=fixture()
    before=len(backend.calls)
    assert "error" in client.post("/mcp",json=INIT).json()
    elevated={**headers,"X-MCP-Profile":"profile_admin"}
    assert rpc(client,elevated,"tools/list")["error"]["message"]=="UnauthorizedProfileError"
    assert len(backend.calls)==before
    assert "error" in rpc(client,{**headers,"Authorization":"Bearer other"},"tools/list")
    assert "error" in client.post("/mcp",headers={**headers,"Origin":"https://evil.example"},json=INIT).json()

def test_catalog_change_requires_relist_and_missing_tool_fails_closed():
    backend,router,client,headers=fixture()
    rpc(client,headers,"tools/list")
    session=next(iter(router.sessions.values()))
    old=session.pin
    backend.tools[0]["description"]="new schema revision"
    session.deadline=0
    result=rpc(client,headers,"tools/call",{"name":"mcp_version"})
    assert result["error"]["message"]=="CatalogChangedRelistRequired"
    assert session.pin!=old
    rpc(client,headers,"tools/list")
    assert "result" in rpc(client,headers,"tools/call",{"name":"mcp_version"})
    backend.tools.pop()
    session.deadline=0
    assert rpc(client,headers,"tools/list")["error"]["message"]=="CatalogProfileMismatch"

def test_backend_failure_does_not_fabricate_initialize():
    backend=Backend()
    backend.fail=True
    router=Router(identities=IDENTITIES,client=httpx.AsyncClient(transport=httpx.MockTransport(backend)))
    client=TestClient(router.app())
    assert client.post("/mcp",json=INIT,headers={"Authorization":AUTH}).json()["error"]["message"]=="BackendTransportError"
    assert not router.sessions

@pytest.mark.parametrize("path",["/etc/passwd","/workspace/../workspace/x","/workspace/x\x00","relative","/workspace-other/x"])
def test_path_denials(path):
    with pytest.raises(Denied):
        validate_paths("local_fs_read_file",{"nested":{"path":path}})

def test_symlink_escape_and_valid_path(tmp_path):
    root=tmp_path/"root"
    root.mkdir()
    (root/"escape").symlink_to(tmp_path)
    with pytest.raises(Denied):
        validate_paths("local_fs_read_file",{"path":str(root/"escape"/"secret")},[str(root)])
    validate_paths("local_fs_read_file",{"path":str(root/"safe")},[str(root)])
    with pytest.raises(Denied):
        validate_paths("local_fs_read_file",{"path":"/home/rlopez/x"},["/home/rlopez"])

def test_shell_surface_rejected():
    for command in ["echo test",["bash","-c","id"],["docker","ps"],["python3","-c","print(1)"]]:
        with pytest.raises(Denied):
            validate_paths("local_exec_run_command_allowlisted",{"command":command})

def test_canonical_profiles_and_admin_fail_closed():
    names=profile_tools("profile_coding",["ralfia:read","ralfia:agents"])
    assert len(names)<=25
    assert "local_exec_run_command_allowlisted" in names
    for kwargs in [{},{"admin_enabled":True},{"admin_authorized":True}]:
        with pytest.raises(Denied):
            profile_tools("profile_admin",["ralfia:admin"],**kwargs)
    with pytest.raises(Denied):
        profile_tools("unknown",["ralfia:admin"])

def test_rate_concurrency_isolation_and_recovery():
    async def run():
        clock=[0.]
        limiter=Throttle(rate=1,burst=2,concurrency=1,clock=lambda:clock[0])
        async with limiter.acquire("one","minimal"):
            with pytest.raises(Denied):
                async with limiter.acquire("one","minimal"): pass
            async with limiter.acquire("two","minimal"): pass
        async with limiter.acquire("one","minimal"): pass
        with pytest.raises(Denied):
            async with limiter.acquire("one","minimal"): pass
        clock[0]=2
        async with limiter.acquire("one","minimal"): pass
    asyncio.run(run())

def test_federation_disabled_and_collisions():
    base={"monolith":{"enabled":True,"default":True},
          "gitlab":{"enabled":False,"tools":["local_gitlab_status"],"prefixes":["local_gitlab_"]}}
    assert Federation(base).resolve("local_gitlab_status")=="monolith"
    with pytest.raises(ValueError):
        Federation({**base,"other":{"tools":["local_gitlab_status"]}})
    with pytest.raises(ValueError):
        Federation({**base,"other":{"prefixes":["local_gitlab_project_"]}})
    with pytest.raises(ValueError):
        Federation({**base,"docker":{"enabled":True,"parity_verified":False}})

def test_malformed_request_and_method_do_not_reach_backend():
    backend,router,client,headers=fixture()
    before=len(backend.calls)
    for body in [[],None,{},{"jsonrpc":"2.0","method":"tools/call","params":[]}]:
        assert "error" in client.post("/mcp",headers=headers,json=body).json()
    assert rpc(client,headers,"resources/read")["error"]["code"]==-32601
    assert len(backend.calls)==before
