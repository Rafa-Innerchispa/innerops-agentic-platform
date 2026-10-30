"""Execute claimed Cursor ops via SDK (local worktree) or Cloud Agents API (machine)."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from inneros_core_runtime import cursor_api_credentials as cac
from inneros_core_runtime import cursor_ops_runner as cor
from inneros_core_runtime.execution_resource_guard import guard_execution

PINNED = cor.CURSOR_PINNED_MODEL
API_BASE = os.getenv("CURSOR_CLOUD_API_BASE", "https://api.cursor.com").rstrip("/")


def _model_for_sdk(pinned: str) -> str:
    base = (pinned or PINNED).strip().lower()
    if "composer-2.5" in base or "composer-2" in base:
        return "composer-2.5"
    return base.split("-fast")[0].replace("_", "-") or "composer-2.5"


def _model_for_cloud(pinned: str) -> dict[str, Any]:
    mid = _model_for_sdk(pinned)
    params: list[dict[str, str]] = []
    if "fast" in (pinned or PINNED).lower():
        params.append({"id": "fast", "value": "true"})
    return {"id": mid, "params": params} if params else {"id": mid}


def execute_local_sdk(
    *,
    prompt: str,
    cwd: Path,
    pinned_model: str = "",
) -> dict[str, Any]:
    cred = cac.resolve_cursor_api_key()
    if not cred.get("present"):
        return {"ok": False, "error": "cursor_api_key_missing", **{k: cred.get(k) for k in ("source", "hint")}}

    api_key = str(cred.get("key") or "")
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError:
        return {"ok": False, "error": "cursor_sdk_not_installed", "hint": "pip install cursor-sdk in platform venv"}

    model = _model_for_sdk(pinned_model or PINNED)
    try:
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=str(cwd)),
            ),
        )
        text = str(getattr(result, "result", None) or getattr(result, "output", None) or "")[:12000]
        status = str(getattr(result, "status", None) or "unknown")
        return {"ok": True, "mode": "local_sdk", "status": status, "result": text, "model": model}
    except Exception as exc:
        return {"ok": False, "mode": "local_sdk", "error": str(exc)[:500]}


def execute_cloud_agent(
    *,
    prompt: str,
    repo_url: str,
    starting_ref: str = "main",
    pinned_model: str = "",
    machine_name: str = "",
) -> dict[str, Any]:
    cred = cac.resolve_cursor_api_key()
    if not cred.get("present"):
        return {"ok": False, "error": "cursor_api_key_missing"}

    api_key = str(cred.get("key") or "")
    machine = (machine_name or os.getenv("INNEROS_CURSOR_MACHINE_NAME") or "ralfiia-amd").strip()
    body = {
        "prompt": {"text": prompt[:12000]},
        "model": _model_for_cloud(pinned_model or PINNED),
        "repos": [{"url": repo_url, "startingRef": starting_ref or "main"}],
        "env": {"type": "machine", "name": machine},
    }
    req = urllib.request.Request(
        f"{API_BASE}/v1/agents",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    import base64

    token = base64.b64encode(f"{api_key}:".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return {"ok": True, "mode": "cloud_agent", "agent": payload}
    except Exception as exc:
        err = str(exc)
        try:
            if hasattr(exc, "read"):
                err = exc.read().decode()[:800]  # type: ignore[union-attr]
        except Exception:
            pass
        return {"ok": False, "mode": "cloud_agent", "error": err[:800]}


def git_head_sha(cwd: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return ""


@guard_execution("cursor", "claim")
def execute_claimed_task(
    claim: dict[str, Any],
    *,
    objective_extra: str = "",
) -> dict[str, Any]:
    """Run SDK/cloud for a claim dict from cursor_ops_runner.claim_ops_task."""
    if not claim.get("ok"):
        return {"ok": False, "error": "invalid_claim"}

    cwd = Path(str(claim.get("worktree") or ".")).expanduser()
    pinned = str(claim.get("pinned_model") or PINNED)
    objective = str(claim.get("objective") or claim.get("title") or "")
    prompt = (
        f"InnerOS ops task {claim.get('task_id')}. Usa modelo {pinned}.\n"
        f"Objetivo:\n{objective}\n{objective_extra}\n"
        "Haz commits en el worktree si aplica. Resume qué hiciste."
    )

    mode = (os.getenv("INNEROS_CURSOR_DISPATCH_MODE") or "auto").strip().lower()
    out: dict[str, Any] = {"task_id": claim.get("task_id"), "worktree": str(cwd)}

    if mode in {"local", "auto", "sdk"}:
        local = execute_local_sdk(prompt=prompt, cwd=cwd, pinned_model=pinned)
        out["local"] = local
        if local.get("ok"):
            out["ok"] = True
            out["primary"] = "local_sdk"
            out["sha"] = git_head_sha(cwd)
            return out

    if mode in {"cloud", "auto"}:
        repo = str(claim.get("repo") or "")
        if repo.startswith("Rafa-Innerchispa/") or "/" in repo and not repo.startswith("http"):
            repo = f"https://github.com/{repo.replace(' ', '')}"
        if repo.startswith("http"):
            cloud = execute_cloud_agent(
                prompt=prompt,
                repo_url=repo,
                starting_ref=str(claim.get("work_branch") or "main"),
                pinned_model=pinned,
            )
            out["cloud"] = cloud
            if cloud.get("ok"):
                out["ok"] = True
                out["primary"] = "cloud_agent"
                return out

    out["ok"] = False
    out["error"] = out.get("local", {}).get("error") or out.get("cloud", {}).get("error") or "dispatch_failed"
    return out
