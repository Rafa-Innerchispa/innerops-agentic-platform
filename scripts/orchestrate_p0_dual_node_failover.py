#!/usr/bin/env python3
"""Self-contained isolated Intel→AMD MCP failover canary with cleanup."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from typing import Any

EXPECTED_ACK = "I_UNDERSTAND_SELF_CONTAINED_DUAL_NODE_CANARY"
if (
    os.environ.get("INNEROS_P0_DUAL_NODE_ACK") != EXPECTED_ACK
    and EXPECTED_ACK not in sys.argv[1:]
):
    raise SystemExit(f"REFUSED: set INNEROS_P0_DUAL_NODE_ACK={EXPECTED_ACK}")

AMD_HOST = os.environ.get("RALFIA_AMD_HOST", "100.72.153.124")
AMD_TARGET = "/home/rlopez/inneros-p0-amd-canary-20260930"
PRODUCTION_PYTHON = "/home/rlopez/inneros/inneros_core/platform/venv/bin/python"
BRANCH = "repair/coordination-recovery-20260929"
ROOT = Path(__file__).resolve().parent.parent


def listening(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket() as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def choose_free_port(candidates: list[int]) -> int:
    for port in candidates:
        if not listening("127.0.0.1", port):
            return port
    raise RuntimeError(f"no free local port among {candidates}")


def ssh(command: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            f"rlopez@{AMD_HOST}", command,
        ],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def remote(command: str, timeout: int = 120) -> str:
    result = ssh(command, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"AMD command failed ({result.returncode}): {command}\n"
            f"stdout={result.stdout[-1000:]}\nstderr={result.stderr[-1000:]}"
        )
    return result.stdout.strip()


def remote_port_free(port: int) -> bool:
    code = (
        "import socket; s=socket.socket(); s.settimeout(.5); "
        f"raise SystemExit(0 if s.connect_ex(('127.0.0.1',{port})) != 0 else 1)"
    )
    return ssh(f"python3 -c {shlex.quote(code)}", timeout=15).returncode == 0


def wait_http(url: str, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.5)
    raise RuntimeError(f"timeout waiting for {url}: {last_error}")


def rpc(base: str, method: str, params: dict[str, Any] | None, call_id: int) -> dict[str, Any]:
    request = urllib.request.Request(
        base,
        data=json.dumps({
            "jsonrpc": "2.0",
            "id": call_id,
            "method": method,
            "params": params or {},
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def terminate_process(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    require(listening("127.0.0.1", 8102), "Intel production MCP 8102 is not listening")
    require((ROOT / ".git").exists(), f"not a Git checkout: {ROOT}")
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True
    ).strip()
    require(branch == BRANCH, f"unexpected Intel branch: {branch}")

    remote(
        f"cd {shlex.quote(AMD_TARGET)} && "
        f"test \"$(git branch --show-current)\" = {shlex.quote(BRANCH)} && "
        "test -z \"$(git status --porcelain)\" && git pull --ff-only",
        timeout=180,
    )

    remote_port = next(
        (port for port in range(18202, 18210) if remote_port_free(port)),
        None,
    )
    require(remote_port is not None, "no free AMD canary port in 18202-18209")
    tunnel_port = choose_free_port(list(range(18212, 18220)))
    gateway_port = choose_free_port(list(range(18113, 18120)))
    dead_primary_port = choose_free_port(list(range(18991, 19000)))

    amd_log = f"{AMD_TARGET}/.canary/amd-mcp-{remote_port}.log"
    amd_pid: int | None = None
    tunnel: subprocess.Popen[Any] | None = None
    gateway: subprocess.Popen[Any] | None = None
    gateway_log_handle = None

    try:
        start_command = " ".join([
            f"cd {shlex.quote(AMD_TARGET)} &&",
            "mkdir -p .canary/coordination &&",
            "nohup env",
            f"PYTHONPATH={shlex.quote(AMD_TARGET + '/platform')}",
            "MCP_HOST=127.0.0.1",
            f"MCP_PORT={remote_port}",
            f"MCP_PUBLIC_URL=http://127.0.0.1:{remote_port}",
            f"MCP_LAN_URL=http://127.0.0.1:{remote_port}",
            "MCP_TOOL_PROFILE=contifico_analytics",
            "MONGO_URI=mongodb://127.0.0.1:27017/",
            "MONGO_URI_PRIMARY=mongodb://127.0.0.1:27017/",
            "MONGO_URI_LOCAL=mongodb://127.0.0.1:27017/",
            "MONGO_DB=pcdoctor_swarm_canary",
            "INNEROS_MONGO_DB=pcdoctor_swarm_canary",
            f"AI_COORDINATION_ROOT={shlex.quote(AMD_TARGET + '/.canary/coordination')}",
            "INNEROS_TEMPORAL_ADDRESS=127.0.0.1:7233",
            "INNEROS_TEMPORAL_NAMESPACE=default",
            "INNEROS_TEMPORAL_TASK_QUEUE=inneros-p0-amd-canary",
            "INNEROS_NATS_ENABLED=false",
            "INNEROS_OTEL_ENABLED=false",
            shlex.quote(PRODUCTION_PYTHON),
            "scripts/launch_p0_mcp_canary.py",
            f"> {shlex.quote(amd_log)} 2>&1 < /dev/null & echo $!",
        ])
        try:
            start_output = remote(start_command, timeout=30)
        except subprocess.TimeoutExpired as exc:
            captured = exc.output or b""
            if isinstance(captured, bytes):
                captured = captured.decode("utf-8", errors="replace")
            require(bool(captured.strip()), "AMD start timed out without returning a PID")
            start_output = captured
        amd_pid = int(start_output.splitlines()[-1])

        tunnel = subprocess.Popen(
            [
                "ssh", "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-L", f"127.0.0.1:{tunnel_port}:127.0.0.1:{remote_port}",
                f"rlopez@{AMD_HOST}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.time() + 20
        while time.time() < deadline and not listening("127.0.0.1", tunnel_port):
            if tunnel.poll() is not None:
                raise RuntimeError(f"SSH tunnel exited: {tunnel.stderr.read()[-1000:]}")
            time.sleep(0.25)
        require(listening("127.0.0.1", tunnel_port), "SSH tunnel did not open")

        amd_version = wait_http(f"http://127.0.0.1:{tunnel_port}/version", timeout=45)
        require(amd_version.get("ok"), f"AMD canary /version failed: {amd_version}")

        config_dir = ROOT / ".canary"
        config_dir.mkdir(exist_ok=True)
        config_path = config_dir / "self-contained-failover.json"
        config_path.write_text(json.dumps({
            "default_profile": "profile_minimal",
            "allow_admin_profile": False,
            "profiles": {
                "profile_minimal": {
                    "label": "P0 Failover Read Only",
                    "allow_all": False,
                    "max_tools": 15,
                    "tools": [
                        "mcp_version", "diagnose_mcp_session",
                        "get_coordination_live", "list_ops_tasks",
                        "a2a_status", "a2a_agent_cards",
                        "dev_swarm_scheduler_status",
                    ],
                    "sandboxing": {"enabled": True, "read_only": True, "allowed_paths": []},
                },
                "profile_admin": {
                    "label": "Admin Full", "allow_all": True,
                    "max_tools": 1000, "requires_auth": True, "tools": [],
                },
            },
            "backends": {
                "dead_primary": {
                    "name": "Intel Primary Deliberately Unavailable",
                    "url": f"http://127.0.0.1:{dead_primary_port}/mcp",
                    "default": True,
                    "prefixes": ["*"],
                    "timeout_sec": 2,
                },
                "amd_tunnel": {
                    "name": "AMD Clean Canary via SSH Tunnel",
                    "url": f"http://127.0.0.1:{tunnel_port}/mcp",
                    "default": False,
                    "prefixes": [],
                    "timeout_sec": 10,
                },
            },
        }, indent=2), encoding="utf-8")

        gateway_log = config_dir / "self-contained-failover-gateway.log"
        gateway_log_handle = gateway_log.open("w", encoding="utf-8")
        gateway_env = dict(os.environ)
        gateway_env.update({
            "PYTHONPATH": str(ROOT / "platform"),
            "INNEROS_MCP_FAILOVER_ENABLED": "true",
        })
        gateway = subprocess.Popen(
            [
                PRODUCTION_PYTHON, "-m", "inneros_core_runtime.mcp_gateway.server",
                "--host", "127.0.0.1", "--port", str(gateway_port),
                "--profile", "profile_minimal", "--config", str(config_path),
            ],
            cwd=ROOT,
            env=gateway_env,
            stdout=gateway_log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wait_http(f"http://127.0.0.1:{gateway_port}/health", timeout=30)

        base = f"http://127.0.0.1:{gateway_port}/mcp"
        initialized = rpc(base, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "self-contained-p0", "version": "1.0"},
        }, 1)
        require("result" in initialized, f"initialize failover failed: {initialized}")

        listed = rpc(base, "tools/list", {}, 2)
        tools = listed.get("result", {}).get("tools", [])
        require(1 <= len(tools) <= 15, f"invalid compact tool count: {len(tools)}")

        invoked = rpc(base, "tools/call", {
            "name": "invoke_capability",
            "arguments": {"capability_id": "mcp_version", "arguments": {}},
        }, 3)
        require("result" in invoked, f"safe tool failover failed: {invoked}")

        denied = rpc(base, "tools/call", {
            "name": "invoke_capability",
            "arguments": {
                "capability_id": "create_agent_message",
                "arguments": {"target_agent": "nobody", "title": "must-not-run", "body": "must-not-run"},
            },
        }, 4)
        require(denied.get("error", {}).get("code") == -32003, f"mutation not denied: {denied}")
        require(listening("127.0.0.1", 8102), "production MCP changed during canary")
        require(not listening("127.0.0.1", dead_primary_port), "dead primary became available")

        report = {
            "ok": True,
            "mode": "self_contained_dual_node_mcp_failover_canary",
            "intel_gateway_port": gateway_port,
            "dead_primary_port": dead_primary_port,
            "amd_remote_port": remote_port,
            "amd_tunnel_port": tunnel_port,
            "amd_pid": amd_pid,
            "amd_version": amd_version,
            "exposed_tool_count": len(tools),
            "initialize_failover": "pass",
            "tools_list_failover": "pass",
            "safe_tool_call_failover": "pass",
            "unlisted_mutation": "denied_fail_closed",
            "production_port_8102": "listening_untouched",
            "production_mutated": False,
            "production_restarted": False,
            "workflow_started": False,
        }
        print(json.dumps(report, indent=2))
    finally:
        terminate_process(gateway)
        if gateway_log_handle is not None:
            gateway_log_handle.close()
        terminate_process(tunnel)
        if amd_pid is not None:
            cleanup = (
                f"test \"$(readlink -f /proc/{amd_pid}/cwd 2>/dev/null || true)\" = "
                f"{shlex.quote(AMD_TARGET)} && kill {amd_pid} 2>/dev/null || true"
            )
            ssh(cleanup, timeout=30)
        require(listening("127.0.0.1", 8102), "production MCP unavailable after cleanup")


if __name__ == "__main__":
    main()
