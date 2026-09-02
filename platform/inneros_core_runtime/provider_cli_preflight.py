"""Canonical, secret-safe CLI and authentication preflight for external providers.

The provider detector and the execution worker must agree on the exact binary
that will be launched. Presence of a credential file is not treated as proof
that the credential is currently usable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def provider_exec_env() -> dict[str, str]:
    env = os.environ.copy()
    home = Path.home()
    user_paths = [
        str(home / ".local" / "bin"),
        str(home / ".local" / "npm-global" / "bin"),
    ]
    env["PATH"] = os.pathsep.join(user_paths + [env.get("PATH", "")])
    return env


def provider_path_candidates(provider: str) -> list[Path]:
    home = Path.home()
    return [
        home / ".local" / "bin" / provider,
        home / ".local" / "npm-global" / "bin" / provider,
    ]


def canonical_cli(provider: str) -> str:
    """Resolve the owner-scoped CLI first, then the same PATH used for execution."""
    provider = (provider or "").strip().lower()
    if not provider:
        return ""
    for candidate in provider_path_candidates(provider):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which(provider, path=provider_exec_env().get("PATH", "")) or ""


def _run(argv: list[str], timeout: int = 8) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            timeout=max(1, min(int(timeout or 8), 30)),
            env=provider_exec_env(),
        )
        return {"ok": proc.returncode == 0, "returncode": proc.returncode}
    except Exception as exc:
        return {"ok": False, "returncode": None, "error_type": type(exc).__name__}


def provider_auth_probe(provider: str, cli_path: str = "") -> dict[str, Any]:
    provider = (provider or "").strip().lower()
    cli = (cli_path or canonical_cli(provider)).strip()
    if provider != "codex":
        return {
            "auth_ready": False,
            "auth_markers": {},
            "auth_failure_reason": "no_supported_headless_auth_probe",
            "secret_policy": "presence only; secret values are never read or returned",
        }

    codex_home = Path(os.getenv("CODEX_HOME") or Path.home() / ".codex").expanduser()
    auth_file = codex_home / "auth.json"
    config_file = codex_home / "config.toml"
    api_key_present = bool(os.getenv("OPENAI_API_KEY"))
    login_probe = _run([cli, "login", "status"]) if cli else {"ok": False, "returncode": None}
    login_ok = bool(login_probe.get("ok"))
    ready = bool(api_key_present or login_ok)
    return {
        "auth_ready": ready,
        "auth_markers": {
            "codex_auth_file_present": auth_file.is_file(),
            "codex_config_file_present": config_file.is_file(),
            "openai_api_key_env_present": api_key_present,
            "codex_login_status_checked": bool(cli),
            "codex_login_status_ok": login_ok,
            "codex_login_status_returncode": login_probe.get("returncode"),
        },
        "auth_failure_reason": "" if ready else "codex_login_status_failed",
        "secret_policy": "presence only; secret values are never read or returned",
    }


def codex_preflight() -> dict[str, Any]:
    cli = canonical_cli("codex")
    auth = provider_auth_probe("codex", cli)
    return {
        "ok": bool(cli and auth.get("auth_ready")),
        "provider": "codex",
        "cli_path": cli,
        "auth_ready": bool(auth.get("auth_ready")),
        "auth": auth,
        "blocker": "" if (cli and auth.get("auth_ready")) else ("cli_not_installed" if not cli else "auth_not_ready"),
    }


def classify_provider_failure(stdout: str = "", stderr: str = "") -> str:
    text = f"{stdout}\n{stderr}".lower()
    auth_markers = (
        "token_expired",
        "token is expired",
        "authentication token is expired",
        "provided authentication token is expired",
        "could not be refreshed",
        "please log out and sign in again",
        "401 unauthorized",
        "http 401",
    )
    if any(marker in text for marker in auth_markers):
        return "auth_expired"
    return "provider_execution_failed"
