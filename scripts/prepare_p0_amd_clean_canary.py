#!/usr/bin/env python3
"""Create and validate a clean parallel AMD checkout without touching live runtime."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

EXPECTED_ACK = "I_UNDERSTAND_CREATE_PARALLEL_AMD_CANARY"
if os.environ.get("INNEROS_P0_AMD_CANARY_ACK") != EXPECTED_ACK:
    raise SystemExit(f"REFUSED: set INNEROS_P0_AMD_CANARY_ACK={EXPECTED_ACK}")

AMD_HOSTS = tuple(dict.fromkeys(filter(None, (
    os.getenv("RALFIA_AMD_HOST", "100.72.153.124"),
    os.getenv("RALFIA_AMD_LAN_HOST", "192.168.1.5"),
))))
LIVE_REPO = "/home/rlopez/inneros/inneros_core"
TARGET = "/home/rlopez/inneros-p0-amd-canary-20260930"
BRANCH = "repair/coordination-recovery-20260929"
REPO_URL = "https://github.com/Rafa-Innerchispa/innerops-agentic-platform.git"
PRODUCTION_PYTHON = f"{LIVE_REPO}/platform/venv/bin/python"


def ssh(host: str, command: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            f"rlopez@{host}", command,
        ],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def first_reachable() -> tuple[str, list[dict[str, Any]]]:
    attempts = []
    for host in AMD_HOSTS:
        result = ssh(host, "printf ready", timeout=15)
        ok = result.returncode == 0 and result.stdout == "ready"
        attempts.append({"host": host, "ok": ok, "error": result.stderr.strip()[:200] or None})
        if ok:
            return host, attempts
    raise SystemExit(json.dumps({"ok": False, "attempts": attempts}, indent=2))


def run(host: str, command: str, timeout: int = 600) -> str:
    result = ssh(host, command, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"remote command failed ({result.returncode}): {command}\n"
            f"stdout={result.stdout[-1000:]}\nstderr={result.stderr[-1000:]}"
        )
    return result.stdout


def main() -> None:
    host, attempts = first_reachable()
    q_target = shlex.quote(TARGET)
    q_branch = shlex.quote(BRANCH)
    q_repo = shlex.quote(REPO_URL)
    q_python = shlex.quote(PRODUCTION_PYTHON)

    preflight = run(
        host,
        f"test ! -e {q_target} && test -x {q_python} && "
        f"git -C {shlex.quote(LIVE_REPO)} status --porcelain >/dev/null && printf preflight_ok",
        timeout=30,
    ).strip()
    if preflight != "preflight_ok":
        raise RuntimeError(f"unexpected preflight result: {preflight}")

    clone_output = run(
        host,
        f"git clone --branch {q_branch} --single-branch --no-tags {q_repo} {q_target}",
        timeout=600,
    )

    test_commands = [
        "platform/tests/test_coordination_recovery_p0.py",
        "platform/tests/test_dual_node_parity_p0.py",
        "platform/tests/test_mcp_gateway_security_p0.py",
        "platform/tests/test_temporal_canary_isolation_p0.py",
    ]
    test_results = []
    for test_path in test_commands:
        command = (
            f"cd {q_target} && env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH={q_target}/platform "
            f"{q_python} {shlex.quote(test_path)} -v"
        )
        result = ssh(host, command, timeout=180)
        test_results.append({
            "test": test_path,
            "ok": result.returncode == 0,
            "stdout_tail": result.stdout[-1200:],
            "stderr_tail": result.stderr[-1200:],
        })

    head = run(host, f"git -C {q_target} rev-parse HEAD", timeout=30).strip()
    branch = run(host, f"git -C {q_target} branch --show-current", timeout=30).strip()
    status = run(host, f"git -C {q_target} status --porcelain", timeout=30).strip()
    ports = run(
        host,
        "ss -ltn | awk 'NR == 1 || /:8102|:18102|:18112|:18202|:18212/'",
        timeout=30,
    )

    report = {
        "ok": all(item["ok"] for item in test_results) and not status,
        "mode": "parallel_clean_amd_canary_checkout",
        "production_mutated": False,
        "production_restarted": False,
        "live_repo_touched": False,
        "host": host,
        "attempts": attempts,
        "target": TARGET,
        "branch": branch,
        "head": head,
        "clean": not bool(status),
        "status": status,
        "tests": test_results,
        "ports": ports,
        "clone_output_tail": clone_output[-500:],
        "next_gate": "start isolated AMD MCP canary on a free loopback port; do not switch production",
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
