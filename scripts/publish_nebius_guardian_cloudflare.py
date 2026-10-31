#!/usr/bin/env python3
"""Idempotent branded Guardian deployment through existing AG-44 Cloudflare tunnel.
Run from Intel host 1.4 with PYTHONPATH=platform; --apply explicitly mutates.
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOST="guardian.creatorcore.ai"
ZONE="creatorcore.ai"
ORIGIN="http://127.0.0.1:18886"
RELEASE="guardian-voiceops-visual-v2"

def fail(reason, details=None):
    print(json.dumps({"ok":False,"blocked":reason,"details":details},ensure_ascii=True))
    raise SystemExit(2)

def probe(url, marker):
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"InnerOS-Guardian-Release/1.0"}),timeout=10) as r:
            body=r.read(120000).decode("utf-8","replace")
            return {"ok":r.status==200 and marker in body,"status":r.status,"marker":marker in body}
    except Exception as exc:
        return {"ok":False,"error":str(exc)[:150]}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--apply",action="store_true",help="Modify only guardian.creatorcore.ai")
    args=ap.parse_args()
    from inneros_core_runtime import settings
    from inneros_core_runtime.agents import ag44_cloud_deployer as ag44
    cfg=Path(settings.CLOUDFLARE_TUNNEL_CONFIG)
    if not cfg.is_file():fail("named_tunnel_config_missing",str(cfg))
    content=cfg.read_text(encoding="utf-8")
    m=re.search(r"^\s*tunnel:\s*['\"]?([a-f0-9-]{36})['\"]?\s*$",content,re.M|re.I)
    if not m:fail("tunnel_id_missing")
    tunnel_id=m.group(1)
    if tunnel_id!=settings.CLOUDFLARE_TUNNEL_ID:fail("tunnel_id_mismatch")
    if "- service: http_status:404" not in content:fail("missing_ingress_catchall")
    service=settings.CLOUDFLARE_TUNNEL_SERVICE
    proc=subprocess.run(["systemctl","--user","is-active",service],capture_output=True,text=True,timeout=12)
    if proc.returncode or proc.stdout.strip()!="active":fail("named_tunnel_service_inactive",service)
    origin_checks={
      "html":probe(ORIGIN+"/",RELEASE),
      "api":probe(ORIGIN+"/api/guardian/overview","guardian.v1"),
      "receipt":probe(ORIGIN+"/examples/nebius-live-receipt.json",'"REAL"')}
    if not all(v["ok"] for v in origin_checks.values()):fail("origin_not_ready",origin_checks)
    records=ag44.cloudflare_dns_delete(HOST,record_type="",zone_name=ZONE,dry_run=True)
    if not records.get("ok"):fail("dns_read_failed",records.get("error"))
    target=tunnel_id+".cfargotunnel.com"
    conflicts=[{"type":r.get("type"),"content":r.get("content")} for r in records.get("matches",[])
      if r.get("type","").upper()!="CNAME" or str(r.get("content","")).lower().rstrip(".")!=target.lower()]
    if conflicts:fail("dns_hostname_conflict",conflicts)
    preview=ag44.cloudflare_tunnel_ingress_upsert(HOST,ORIGIN,dry_run=True)
    if not preview.get("ok"):fail("ingress_dryrun_failed",preview.get("error"))
    status={"ok":True,"hostname":HOST,"target":target,"service":service,"origin":ORIGIN,"dry_run":not args.apply}
    if not args.apply:
        print(json.dumps(status,ensure_ascii=True));return
    ingress=ag44.cloudflare_tunnel_ingress_upsert(HOST,ORIGIN,dry_run=False)
    if not ingress.get("ok") or ingress.get("tunnel_active")!="active":fail("ingress_apply_failed",{k:ingress.get(k) for k in ("error","stderr","tunnel_active")})
    dns=ag44.cloudflare_dns_upsert(HOST,"CNAME",target,proxied=True,zone_name=ZONE,dry_run=False)
    if not dns.get("ok"):fail("dns_apply_failed",dns.get("error"))
    public_checks={}
    for _ in range(6):
        public_checks={"html":probe("https://"+HOST+"/",RELEASE),
          "api":probe("https://"+HOST+"/api/guardian/overview","guardian.v1"),
          "receipt":probe("https://"+HOST+"/examples/nebius-live-receipt.json",'"REAL"')}
        if all(v["ok"] for v in public_checks.values()):break
        time.sleep(3)
    if not all(v["ok"] for v in public_checks.values()):fail("public_https_not_verified",public_checks)
    print(json.dumps({**status,"dry_run":False,"public_http_verified":True,"url":"https://"+HOST+"/","checks":public_checks},ensure_ascii=True))

if __name__=="__main__":
    main()
