"""Read-only service identity probe; never touches service state."""
import httpx
def test_identify_existing_8103():
    for path in ("/health","/.well-known/oauth-authorization-server"):
        r=httpx.get("http://127.0.0.1:8103"+path,timeout=5)
        data={}
        if "application/json" in r.headers.get("content-type",""):
            j=r.json()
            if isinstance(j,dict):
                data={k:j[k] for k in ("service","status","name","issuer","authorization_endpoint","token_endpoint") if k in j}
        print("PORT_8103",path,r.status_code,data)
