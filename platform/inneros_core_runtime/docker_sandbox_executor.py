"""Docker Ephemeral Sandbox Executor for InnerOS Agents.

Executes tests, linters, and commands inside isolated, unprivileged, resource-bounded
Docker containers to prevent host contamination or damage.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = os.environ.get("INNEROS_SANDBOX_IMAGE", "inneros-sandbox:latest")
DEFAULT_MEMORY_LIMIT = os.environ.get("INNEROS_SANDBOX_MEMORY", "2g")
DEFAULT_CPUS_LIMIT = os.environ.get("INNEROS_SANDBOX_CPUS", "1.5")
DEFAULT_TIMEOUT_SEC = int(os.environ.get("INNEROS_SANDBOX_TIMEOUT", "60"))


class DockerSandboxExecutor:
    """Safely runs commands inside an ephemeral Docker container."""

    def __init__(
        self,
        image: str = SANDBOX_IMAGE,
        memory_limit: str = DEFAULT_MEMORY_LIMIT,
        cpus_limit: str = DEFAULT_CPUS_LIMIT,
        network: str = "none",
        timeout: int = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self.image = image
        self.memory_limit = memory_limit
        self.cpus_limit = cpus_limit
        self.network = network
        self.timeout = timeout
        self._docker_available: Optional[bool] = None

    def is_available(self) -> bool:
        if self._docker_available is not None:
            return self._docker_available
        docker_path = shutil.which("docker")
        if not docker_path:
            self._docker_available = False
            return False
        try:
            res = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self._docker_available = res.returncode == 0
        except Exception as e:
            logger.warning(f"Docker availability check failed: {e}")
            self._docker_available = False
        return self._docker_available

    def run_command(
        self,
        cmd: List[str] | str,
        worktree_path: str | Path,
        env_vars: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        allow_network: bool = False,
    ) -> Dict[str, Any]:
        """Runs a command inside an ephemeral container.

        Args:
            cmd: Command to execute (list or string).
            worktree_path: Absolute host path to mount as /workspace.
            env_vars: Environment variables to pass into container.
            timeout: Command timeout in seconds.
            allow_network: If True, allows container network access; otherwise network is isolated.

        Returns:
            Dict with 'ok', 'exit_code', 'stdout', 'stderr', 'timeout', and 'sandboxed'.
        """
        worktree = Path(worktree_path).resolve()
        if not worktree.exists():
            return {
                "ok": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Worktree path does not exist: {worktree}",
                "timeout": False,
                "sandboxed": False,
            }

        effective_timeout = timeout or self.timeout

        if not self.is_available():
            logger.warning("Docker sandbox not available; executing fallback with host isolation warning.")
            return self._run_fallback(cmd, worktree, env_vars, effective_timeout)

        docker_cmd = [
            "docker", "run", "--rm",
            "--read-only",
            "--tmpfs", "/tmp:rw,size=256m",
            "--tmpfs", "/home/sandboxuser/.cache:rw,size=256m",
            "--user", "1000:1000",
            "--security-opt", "no-new-privileges:true",
            f"--memory={self.memory_limit}",
            f"--cpus={self.cpus_limit}",
            f"--network={'bridge' if allow_network else self.network}",
            "-v", f"{worktree}:/workspace:rw",
            "-w", "/workspace",
        ]

        if env_vars:
            for k, v in env_vars.items():
                docker_cmd.extend(["-e", f"{k}={v}"])

        docker_cmd.append(self.image)

        if isinstance(cmd, list):
            docker_cmd.extend(cmd)
        else:
            docker_cmd.extend(["/bin/bash", "-c", cmd])

        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
            return {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "timeout": False,
                "sandboxed": True,
            }
        except subprocess.TimeoutExpired as te:
            return {
                "ok": False,
                "exit_code": -1,
                "stdout": te.stdout or "" if isinstance(te.stdout, str) else "",
                "stderr": f"Command timed out after {effective_timeout}s: {te}",
                "timeout": True,
                "sandboxed": True,
            }
        except Exception as e:
            return {
                "ok": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Sandbox execution error: {e}",
                "timeout": False,
                "sandboxed": True,
            }

    def _run_fallback(
        self,
        cmd: List[str] | str,
        worktree: Path,
        env_vars: Optional[Dict[str, str]],
        timeout: int,
    ) -> Dict[str, Any]:
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)
        shell = isinstance(cmd, str)
        try:
            proc = subprocess.run(
                cmd,
                cwd=worktree,
                env=env,
                shell=shell,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "timeout": False,
                "sandboxed": False,
            }
        except subprocess.TimeoutExpired as te:
            return {
                "ok": False,
                "exit_code": -1,
                "stdout": te.stdout or "",
                "stderr": f"Fallback execution timed out: {te}",
                "timeout": True,
                "sandboxed": False,
            }
        except Exception as e:
            return {
                "ok": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Fallback execution error: {e}",
                "timeout": False,
                "sandboxed": False,
            }
