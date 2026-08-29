#!/usr/bin/env python3
"""ROCm 10 canary health API on :8001 — does not load LLM weights."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

CANARY_DIR = os.environ.get("ROCM_CANARY_DIR", "/home/rlopez/data/rocm10-canary")
ROCM10_INSTALL = os.environ.get(
    "ROCM10_INSTALL", f"{CANARY_DIR}/rocm-10-install/rocm/core-10.0"
)
PROD_URL = os.environ.get("VLLM_PROD_URL", "http://127.0.0.1:8000/v1/models")
PORT = int(os.environ.get("CANARY_HEALTH_PORT", "8001"))


def _probe_prod() -> dict:
    try:
        with urllib.request.urlopen(PROD_URL, timeout=3) as resp:
            body = resp.read(512).decode("utf-8", errors="replace")
            return {"ok": resp.status == 200, "status": resp.status, "snippet": body[:200]}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": str(exc)}


def _probe_torch() -> dict:
    try:
        import torch

        if not torch.cuda.is_available():
            return {"ok": False, "error": "torch.cuda not available"}
        x = torch.randn(256, 256, device="cuda", dtype=torch.float16)
        y = float((x @ x)[0, 0].item())
        return {
            "ok": True,
            "torch": torch.__version__,
            "hip": str(torch.version.hip),
            "device": torch.cuda.get_device_name(0),
            "matmul_sample": y,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _probe_rocm10_bind() -> dict:
    rocminfo = os.path.join(ROCM10_INSTALL, "bin", "rocminfo")
    ok = os.path.isfile(rocminfo) and os.access(rocminfo, os.X_OK)
    return {"ok": ok, "path": ROCM10_INSTALL}


def build_status() -> dict:
    torch_probe = _probe_torch()
    prod_probe = _probe_prod()
    bind_probe = _probe_rocm10_bind()
    overall = torch_probe.get("ok") and bind_probe.get("ok") and prod_probe.get("ok")
    return {
        "service": "inneros-rocm10-canary-health",
        "ts": datetime.now(timezone.utc).isoformat(),
        "port": PORT,
        "overall": "PASS" if overall else "PARTIAL",
        "rocm10_bind": bind_probe,
        "torch_gpu": torch_probe,
        "vllm_prod_8000": prod_probe,
        "note": "Full vLLM model on :8001 requires VRAM headroom; use smoke_vllm_docker.sh",
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

    def do_GET(self) -> None:
        if self.path not in ("/", "/health", "/v1/models"):
            self.send_response(404)
            self.end_headers()
            return
        payload = build_status()
        code = 200 if payload.get("overall") == "PASS" else 503
        body = json.dumps(payload, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    rocm_path = ROCM10_INSTALL
    if os.path.isdir(rocm_path):
        os.environ["ROCM_PATH"] = rocm_path
        os.environ["PATH"] = f"{rocm_path}/bin:" + os.environ.get("PATH", "")
        lib = f"{rocm_path}/lib:{rocm_path}/lib64"
        os.environ["LD_LIBRARY_PATH"] = lib + (
            f":{os.environ['LD_LIBRARY_PATH']}" if os.environ.get("LD_LIBRARY_PATH") else ""
        )
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"canary health listening on 127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
