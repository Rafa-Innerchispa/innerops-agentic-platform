"""Un tick autónomo: WA guardian + correo GitLab + ContributorOps watch + notificaciones."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PLATFORM = Path(__file__).resolve().parents[1]
AGENT = Path("/home/rlopez/inneros/inneros_core/workspaces/gitlab-contributorops-agent")
MANIFEST = AGENT / "contributions.json"
STATE_DIR = Path(os.environ.get("INNEROS_CORE_ROOT", "/home/rlopez/inneros/inneros_core")) / "var" / "gitlab_contributorops"


def _python() -> Path:
    venv = PLATFORM / "venv" / "bin" / "python3"
    return venv if venv.is_file() else Path(sys.executable)


def run_autonomous_tick(*, poll_email: bool = True, watch_gitlab: bool = True) -> dict[str, Any]:
    os.environ.setdefault("CONTRIBUTOROPS_INNEROS_BRIDGE", "1")
    os.environ.setdefault("GITLAB_CONTRIBUTOROPS_AUTOPILOT", "1")
    os.environ.setdefault("CONTRIBUTOROPS_EMAIL_INGRESS", "1")
    os.environ.setdefault("INNEROS_GMAIL_INTEGRATION", "1")
    os.environ.setdefault("GITLAB_CONTRIBUTOROPS_AUTO_REREVIEW", "1")
    out: dict[str, Any] = {"ok": True, "steps": {}}

    try:
        from inneros_core_runtime import evolution_session_guardian as esg

        out["steps"]["evolution_guardian"] = esg.run_guardian_cycle(
            request_qr=True,
            email_owner=os.environ.get("EVOLUTION_GUARDIAN_EMAIL_OWNER", "1") != "0",
        )
    except Exception as exc:
        out["steps"]["evolution_guardian"] = {"ok": False, "error": str(exc)[:200]}

    if poll_email and os.environ.get("INNEROS_GMAIL_INTEGRATION", "1") not in {"0", "false", "no"}:
        try:
            from inneros_core_runtime.notifications import email_ag25_integration as gmail

            out["steps"]["gmail"] = gmail.run_gmail_ag25_tick(cycle=0, force_poll=poll_email)
        except Exception as exc:
            out["steps"]["gmail"] = {"ok": False, "error": str(exc)[:200]}

    try:
        from inneros_core_runtime import gitlab_contributorops_manifest_sync as ms

        out["steps"]["manifest_sync"] = ms.sync_manifest_from_email_and_api(limit=20)
    except Exception as exc:
        out["steps"]["manifest_sync"] = {"ok": False, "error": str(exc)[:200]}

    if watch_gitlab and MANIFEST.is_file():
        env = {
            **os.environ,
            "PYTHONPATH": f"{AGENT / 'src'}:{PLATFORM}",
            "CONTRIBUTOROPS_INNEROS_BRIDGE": "1",
            "GITLAB_CONTRIBUTOROPS_AUTOPILOT": "1",
            "CONTRIBUTOROPS_EMAIL_INGRESS": "1",
        }
        proc = subprocess.run(
            [
                str(_python()),
                "-m",
                "contributorops.cli",
                "watch-once",
                "--manifest",
                str(MANIFEST),
                "--limit",
                "100",
            ],
            cwd=str(AGENT),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if proc.stdout.strip():
            try:
                out["steps"]["watch_once"] = json.loads(proc.stdout)
            except json.JSONDecodeError:
                out["steps"]["watch_once"] = {"ok": proc.returncode == 0, "raw": proc.stdout[:4000]}
        else:
            out["steps"]["watch_once"] = {"ok": False, "stderr": (proc.stderr or "")[:500]}

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "last-autonomous-tick.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    out["ok"] = all(
        (step.get("ok", True) if isinstance(step, dict) else True)
        for key, step in out["steps"].items()
        if key != "watch_once" or isinstance(step, dict)
    )
    return out


if __name__ == "__main__":
    print(json.dumps(run_autonomous_tick(), indent=2, default=str)[:12000])
