#!/usr/bin/env python3
"""Read-only live dependency preflight for the P0 coordination canary."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
from typing import Any


HOST = "127.0.0.1"
PORTS = {
    "mcp_production": 8102,
    "mcp_canary": 18102,
    "temporal": 7233,
    "mongo": 27017,
    "nats": 4222,
}


def tcp_probe(port: int, timeout: float = 1.0) -> dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        code = sock.connect_ex((HOST, port))
    return {"host": HOST, "port": port, "listening": code == 0}


async def temporal_probe() -> dict[str, Any]:
    try:
        from temporalio.client import Client

        client = await asyncio.wait_for(
            Client.connect(
                os.getenv("INNEROS_TEMPORAL_ADDRESS", "127.0.0.1:7233"),
                namespace=os.getenv("INNEROS_TEMPORAL_NAMESPACE", "default"),
            ),
            timeout=3,
        )
        return {
            "ok": True,
            "namespace": client.namespace,
            "service_client": type(client.service_client).__name__,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def mongo_probe() -> dict[str, Any]:
    try:
        from pymongo import MongoClient

        uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
        with MongoClient(uri, serverSelectionTimeoutMS=2000) as client:
            result = client.admin.command("ping")
        return {"ok": bool(result.get("ok"))}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def docker_snapshot() -> dict[str, Any]:
    if not shutil.which("docker"):
        return {"available": False, "containers": []}
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Ports}}"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        rows = [line for line in proc.stdout.splitlines() if line.strip()]
        return {
            "available": True,
            "ok": proc.returncode == 0,
            "containers": rows,
            "error": proc.stderr.strip()[:300] or None,
        }
    except Exception as exc:
        return {"available": True, "ok": False, "containers": [], "error": str(exc)[:300]}


def git_snapshot() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.check_output(["git", *args], text=True).strip()

    return {
        "branch": run("branch", "--show-current"),
        "head": run("rev-parse", "HEAD"),
        "status": [
            line
            for line in run("status", "--porcelain").splitlines()
            if ".venv-p0-canary/" not in line
        ],
    }


async def main() -> None:
    ports = {name: tcp_probe(port) for name, port in PORTS.items()}
    report = {
        "ok": True,
        "mode": "read_only_preflight",
        "git": git_snapshot(),
        "ports": ports,
        "temporal": await temporal_probe(),
        "mongo": mongo_probe(),
        "nats_tcp": ports["nats"],
        "canary_port_free": not ports["mcp_canary"]["listening"],
        "production_mcp_untouched": True,
        "docker": docker_snapshot(),
    }
    report["ready_for_isolated_canary"] = bool(
        report["temporal"]["ok"]
        and report["mongo"]["ok"]
        and report["canary_port_free"]
        and not report["git"]["status"]
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())