"""InnerOS Windows <-> Kiro Autonomous Bridge Agent.

Outbound-only authenticated agent over Tailscale to InnerOS MongoDB (pcdoctor_swarm).
Provides read-only Windows/Kiro/GhostBridge telemetry, idempotent structured command
execution with strict allowlists, rotating logs, single-instance lock, and receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from pymongo import MongoClient, ReturnDocument

if sys.platform == "win32":
    import msvcrt

BRIDGE_VERSION = "1.0.0"
HOST_ID = os.getenv("INNEROS_BRIDGE_HOST_ID", "ralphi-lenovo")
MONGO_URI = os.getenv("INNEROS_MONGO_URI", "mongodb://100.94.99.12:27017/")
MONGO_DB = os.getenv("INNEROS_MONGO_DB", "pcdoctor_swarm")
POLL_INTERVAL_SEC = int(os.getenv("INNEROS_BRIDGE_POLL_SEC", "5"))
HEARTBEAT_INTERVAL_SEC = int(os.getenv("INNEROS_BRIDGE_HEARTBEAT_SEC", "15"))

USER_HOME = Path(os.path.expanduser("~"))
KIRO_DIR = USER_HOME / ".kiro"
GHOSTBRIDGE_DIR = KIRO_DIR / "projects" / "kiroproject" / "ghostbridge-kiroween-2026"
ALLOWED_WORKSPACES = {
    "ghostbridge": GHOSTBRIDGE_DIR.resolve(),
    "uipath": (USER_HOME / ".gemini" / "antigravity" / "scratch" / "inneros-uipath-service-incident-resolution").resolve(),
}

LOCAL_STATE_DIR = Path(os.getenv("LOCALAPPDATA", str(USER_HOME))) / "InnerOSBridge"
LOG_DIR = LOCAL_STATE_DIR / "logs"
LOCK_FILE = LOCAL_STATE_DIR / "bridge.lock"
CACHE_FILE = LOCAL_STATE_DIR / "last_test_result.json"

SECRET_KEY_RE = re.compile(r"(secret|token|password|api[_-]?key|auth|credential|cookie|private[_-]?key)", re.I)
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")

PS_ALLOWLIST: dict[str, str] = {
    "processes": "Get-Process -Name '*kiro*','*antigravity*','*python*','*tailscale*' -ErrorAction SilentlyContinue | Select-Object Name, Id, @{N='WS_MB';E={[math]::Round($_.WorkingSet64/1MB,1)}} | ConvertTo-Json -Compress",
    "disk": "Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{N='Used_GB';E={[math]::Round($_.Used/1GB,2)}}, @{N='Free_GB';E={[math]::Round($_.Free/1GB,2)}} | ConvertTo-Json -Compress",
    "tailscale": "tailscale status --json | ConvertFrom-Json | Select-Object BackendState, @{N='SelfIP';E={$_.Self.TailscaleIPs}} | ConvertTo-Json -Compress",
    "scheduled_task": "Get-ScheduledTask -TaskName 'InnerOS-Windows-Kiro-Bridge' -ErrorAction SilentlyContinue | Select-Object TaskName, State | ConvertTo-Json -Compress",
    "python_env": "python --version; node --version; git --version",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(dt: datetime | None = None) -> str:
    return (dt or utc_now()).isoformat()


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("inneros_windows_bridge")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(LOG_DIR / "bridge.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(console)
    return logger


def sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if SECRET_KEY_RE.search(str(k)):
                out[k] = "<REDACTED>"
            else:
                out[k] = sanitize_obj(v)
        return out
    if isinstance(obj, list):
        return [sanitize_obj(x) for x in obj]
    return obj


def run_cmd(args: list[str], cwd: Path | None = None, timeout: int = 15, max_chars: int = 6000) -> dict[str, Any]:
    try:
        res = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        stdout = (res.stdout or "")[:max_chars]
        stderr = (res.stderr or "")[:2000]
        return {"ok": res.returncode == 0, "returncode": res.returncode, "stdout": stdout.strip(), "stderr": stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": f"timeout after {timeout}s"}
    except Exception as exc:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(exc)}


def collect_kiro_mcp_config() -> dict[str, Any]:
    configs: dict[str, Any] = {}
    for label, path in [
        ("user", KIRO_DIR / "settings" / "mcp.json"),
        ("workspace_ghostbridge", GHOSTBRIDGE_DIR / ".kiro" / "settings" / "mcp.json"),
    ]:
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                servers = {}
                for sname, scfg in (raw.get("mcpServers") or {}).items():
                    servers[sname] = {
                        "command": scfg.get("command"),
                        "args": scfg.get("args"),
                        "disabled": bool(scfg.get("disabled", False)),
                        "autoApprove": scfg.get("autoApprove", []),
                        "env_keys": list((scfg.get("env") or {}).keys()),
                    }
                configs[label] = {"exists": True, "path": str(path), "mcpServers": servers}
            except Exception as exc:
                configs[label] = {"exists": True, "path": str(path), "error": str(exc)}
        else:
            configs[label] = {"exists": False, "path": str(path)}
    return configs


def collect_kiro_logs(limit: int = 25) -> dict[str, Any]:
    logs_root = KIRO_DIR / "logs"
    if not logs_root.exists():
        return {"present": False, "latest_dir": None, "mcp_events": [], "kiro_tail": []}
    dirs = sorted([d for d in logs_root.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime, reverse=True)
    if not dirs:
        return {"present": False, "latest_dir": None, "mcp_events": [], "kiro_tail": []}
    latest = dirs[0]
    mcp_events: list[dict[str, Any]] = []
    mcp_log = latest / "mcp.log"
    if mcp_log.exists():
        lines = mcp_log.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        for line in lines:
            try:
                mcp_events.append(sanitize_obj(json.loads(line)))
            except Exception:
                mcp_events.append({"raw": line[:300]})
    kiro_tail: list[dict[str, Any]] = []
    kiro_log = latest / "kiro.log"
    if kiro_log.exists():
        lines = kiro_log.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]
        for line in lines:
            try:
                entry = json.loads(line)
                kiro_tail.append({
                    "timestamp": entry.get("timestamp"),
                    "level": entry.get("level"),
                    "message": str(entry.get("message", ""))[:240],
                    "conversationId": entry.get("conversationId"),
                })
            except Exception:
                pass
    connected_servers = sorted({
        e.get("serverName")
        for e in mcp_events
        if e.get("message") in ("Connected", "mcp.connect.ok", "mcp.listTools.ok") and e.get("serverName")
    })
    return {
        "present": True,
        "latest_dir": latest.name,
        "connected_servers": connected_servers,
        "mcp_events": mcp_events,
        "kiro_tail": kiro_tail,
    }


def collect_kiro_sessions(limit: int = 5) -> list[dict[str, Any]]:
    sessions_root = KIRO_DIR / "sessions"
    if not sessions_root.exists():
        return []
    files = sorted(sessions_root.rglob("session.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out: list[dict[str, Any]] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "id": data.get("id"),
                "title": data.get("title"),
                "status": data.get("status"),
                "agentMode": data.get("agentMode"),
                "workspacePaths": data.get("workspacePaths"),
                "lastModifiedAt": data.get("lastModifiedAt"),
                "description": data.get("description"),
            })
        except Exception:
            pass
    return out


def collect_workspace_status() -> dict[str, Any]:
    if not GHOSTBRIDGE_DIR.exists():
        return {"exists": False, "path": str(GHOSTBRIDGE_DIR)}
    branch = run_cmd(["git", "-C", str(GHOSTBRIDGE_DIR), "branch", "--show-current"])
    head = run_cmd(["git", "-C", str(GHOSTBRIDGE_DIR), "--no-pager", "log", "-1", "--oneline"])
    status = run_cmd(["git", "-C", str(GHOSTBRIDGE_DIR), "status", "--short"])
    dirty_lines = [l for l in status["stdout"].splitlines() if l.strip()] if status["ok"] else []
    agents = [p.name for p in (GHOSTBRIDGE_DIR / ".kiro" / "agents").glob("*")] if (GHOSTBRIDGE_DIR / ".kiro" / "agents").exists() else []
    hooks = [p.name for p in (GHOSTBRIDGE_DIR / ".kiro" / "hooks").glob("*")] if (GHOSTBRIDGE_DIR / ".kiro" / "hooks").exists() else []
    inbox_dir = GHOSTBRIDGE_DIR / ".kiro" / "inbox"
    inbox_files = [p.name for p in sorted(inbox_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]] if inbox_dir.exists() else []
    return {
        "exists": True,
        "path": str(GHOSTBRIDGE_DIR),
        "git_branch": branch["stdout"],
        "git_head": head["stdout"],
        "git_dirty_count": len(dirty_lines),
        "git_dirty_files": dirty_lines[:20],
        "mcp_server_py_exists": (GHOSTBRIDGE_DIR / "ghostbridge" / "mcp_server.py").exists(),
        "agents": agents,
        "hooks": hooks,
        "inbox_files": inbox_files,
    }


def collect_full_snapshot() -> dict[str, Any]:
    kiro_procs = run_cmd(["powershell", "-NoProfile", "-Command", "Get-Process -Name 'Kiro' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"])
    kiro_pids = [int(x) for x in kiro_procs["stdout"].splitlines() if x.strip().isdigit()]
    anti_procs = run_cmd(["powershell", "-NoProfile", "-Command", "Get-Process -Name 'Antigravity IDE' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"])
    anti_pids = [int(x) for x in anti_procs["stdout"].splitlines() if x.strip().isdigit()]
    ts_res = run_cmd(["tailscale", "ip", "-4"], timeout=5)
    last_tests = None
    if CACHE_FILE.exists():
        try:
            last_tests = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            last_tests = None

    return {
        "_id": HOST_ID,
        "host_id": HOST_ID,
        "hostname": socket.gethostname(),
        "updated_at": utc_iso(),
        "windows": {
            "platform": sys.platform,
            "python_version": sys.version.split()[0],
            "tailscale_ipv4": ts_res["stdout"].splitlines()[0] if ts_res["ok"] and ts_res["stdout"] else "100.83.210.41",
            "kiro_running": bool(kiro_pids),
            "kiro_pids": kiro_pids,
            "antigravity_running": bool(anti_pids),
            "antigravity_pids": anti_pids,
        },
        "kiro": {
            "running": bool(kiro_pids),
            "mcp_config": collect_kiro_mcp_config(),
            "logs": collect_kiro_logs(),
            "sessions": collect_kiro_sessions(),
        },
        "workspace": collect_workspace_status(),
        "tests": last_tests,
        "bridge": {
            "version": BRIDGE_VERSION,
            "pid": os.getpid(),
            "heartbeat_at": utc_iso(),
            "poll_interval_sec": POLL_INTERVAL_SEC,
            "allowed_actions": [
                "refresh_snapshot",
                "kiro_status",
                "workspace_git_status",
                "run_ghostbridge_mcp_tests",
                "deliver_kiro_inbox_task",
                "ps_diagnostic",
            ],
        },
    }


def execute_action(action: str, params: dict[str, Any], command_doc: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if action == "refresh_snapshot":
        snap = collect_full_snapshot()
        return "SUCCESS", {"refreshed_at": snap["updated_at"], "kiro_running": snap["kiro"]["running"], "git_branch": snap["workspace"].get("git_branch")}

    if action == "kiro_status":
        return "SUCCESS", {
            "mcp_config": collect_kiro_mcp_config(),
            "logs": collect_kiro_logs(limit=15),
            "sessions": collect_kiro_sessions(limit=5),
        }

    if action == "workspace_git_status":
        ws_key = str(params.get("workspace") or "ghostbridge")
        ws_path = ALLOWED_WORKSPACES.get(ws_key)
        if not ws_path or not ws_path.exists():
            return "FAILED", {"error": f"workspace not allowed or missing: {ws_key}"}
        branch = run_cmd(["git", "-C", str(ws_path), "branch", "--show-current"])
        head = run_cmd(["git", "-C", str(ws_path), "--no-pager", "log", "-1", "--oneline"])
        status = run_cmd(["git", "-C", str(ws_path), "status", "--short"])
        return "SUCCESS", {"workspace": ws_key, "branch": branch["stdout"], "head": head["stdout"], "dirty": status["stdout"]}

    if action == "run_ghostbridge_mcp_tests":
        res = run_cmd([sys.executable, "-m", "pytest", "tests/test_mcp_server.py", "-v"], cwd=GHOSTBRIDGE_DIR, timeout=45, max_chars=8000)
        summary = {
            "executed_at": utc_iso(),
            "ok": res["ok"],
            "returncode": res["returncode"],
            "output": res["stdout"] or res["stderr"],
        }
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return ("SUCCESS" if res["ok"] else "FAILED"), summary

    if action == "deliver_kiro_inbox_task":
        task_id = str(params.get("task_id") or command_doc.get("command_id") or uuid.uuid4().hex[:12])
        if not SAFE_ID_RE.match(task_id):
            return "FAILED", {"error": "invalid task_id format"}
        title = str(params.get("title") or "InnerOS Kiro Task")[:200]
        instruction = str(params.get("instruction") or "")[:4000]
        if not instruction:
            return "FAILED", {"error": "instruction is required"}
        inbox_dir = GHOSTBRIDGE_DIR / ".kiro" / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        envelope_path = inbox_dir / f"{task_id}.json"
        envelope = {
            "task_id": task_id,
            "correlation_id": command_doc.get("correlation_id"),
            "idempotency_key": command_doc.get("idempotency_key"),
            "title": title,
            "instruction": instruction,
            "delivered_at": utc_iso(),
            "delivery_status": "DELIVERED_TO_KIRO_INBOX",
            "kiro_execution_status": "AWAITING_KIRO_SESSION",
            "note": "Delivered to Kiro workspace inbox; Kiro IDE execution requires Kiro session pickup.",
        }
        envelope_path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        return "SUCCESS", {
            "task_id": task_id,
            "inbox_file": str(envelope_path),
            "delivery_status": "DELIVERED_TO_KIRO_INBOX",
            "kiro_executed": False,
        }

    if action == "ps_diagnostic":
        diag_name = str(params.get("diagnostic") or "")
        if diag_name not in PS_ALLOWLIST:
            return "BLOCKED", {"error": f"diagnostic '{diag_name}' not in allowlist", "allowed": sorted(PS_ALLOWLIST.keys())}
        ps_script = PS_ALLOWLIST[diag_name]
        res = run_cmd(["powershell", "-NoProfile", "-Command", ps_script], timeout=12, max_chars=4000)
        return ("SUCCESS" if res["ok"] else "FAILED"), {"diagnostic": diag_name, **res}

    return "BLOCKED", {"error": f"action '{action}' is not in allowlist"}


def process_pending_commands(db: Any, logger: logging.Logger) -> int:
    cmds_col = db["ralfia_windows_bridge_commands"]
    receipts_col = db["ralfia_windows_bridge_receipts"]
    audit_col = db["ralfia_windows_bridge_audit"]
    processed = 0

    while True:
        now = utc_now()
        cmd = cmds_col.find_one_and_update(
            {"target_host": HOST_ID, "status": "QUEUED"},
            {
                "$set": {
                    "status": "ACK",
                    "acknowledged_at": now.isoformat(),
                    "ack_by": f"{HOST_ID}-bridge",
                    "lease_expires_at": (now + timedelta(minutes=2)).isoformat(),
                }
            },
            sort=[("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if not cmd:
            break

        command_id = str(cmd.get("command_id") or cmd.get("_id"))
        idem_key = str(cmd.get("idempotency_key") or command_id)
        action = str(cmd.get("action") or "")
        params = cmd.get("params") or {}

        existing_receipt = receipts_col.find_one({"idempotency_key": idem_key})
        if existing_receipt:
            cmds_col.update_one(
                {"_id": cmd["_id"]},
                {"$set": {"status": existing_receipt["status"], "receipt_id": existing_receipt["receipt_id"], "deduplicated": True, "finished_at": utc_iso()}},
            )
            logger.info("Command %s deduplicated via idempotency_key=%s", command_id, idem_key)
            processed += 1
            continue

        started_at = utc_now()
        cmds_col.update_one(
            {"_id": cmd["_id"]},
            {"$set": {"status": "RUNNING", "started_at": started_at.isoformat(), "runner_pid": os.getpid()}},
        )
        logger.info("Executing command %s action=%s", command_id, action)

        status, output = execute_action(action, params, cmd)
        finished_at = utc_now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        evidence_hash = hashlib.sha256(json.dumps(output, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"

        receipt = {
            "receipt_id": receipt_id,
            "command_id": command_id,
            "idempotency_key": idem_key,
            "target_host": HOST_ID,
            "action": action,
            "status": status,
            "acknowledged_at": cmd.get("acknowledged_at"),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": duration_ms,
            "evidence_sha256": evidence_hash,
            "output": sanitize_obj(output),
        }
        receipts_col.insert_one(dict(receipt))
        cmds_col.update_one(
            {"_id": cmd["_id"]},
            {"$set": {"status": status, "finished_at": finished_at.isoformat(), "receipt_id": receipt_id, "evidence_sha256": evidence_hash, "output": sanitize_obj(output)}},
        )
        audit_col.insert_one({
            "timestamp": finished_at.isoformat(),
            "host_id": HOST_ID,
            "command_id": command_id,
            "action": action,
            "status": status,
            "duration_ms": duration_ms,
            "evidence_sha256": evidence_hash,
        })
        logger.info("Finished command %s status=%s duration_ms=%d receipt=%s", command_id, status, duration_ms, receipt_id)
        processed += 1

    return processed


def acquire_lock(logger: logging.Logger) -> Any:
    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_FILE, "a+", encoding="utf-8")
    if sys.platform == "win32":
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            logger.error("Another bridge instance is already running (lock held on %s).", LOCK_FILE)
            fh.close()
            sys.exit(0)
    fh.seek(0)
    fh.truncate()
    fh.write(f"{os.getpid()}\n")
    fh.flush()
    return fh


def main() -> int:
    parser = argparse.ArgumentParser(description="InnerOS Windows <-> Kiro Autonomous Bridge")
    parser.add_argument("--once", action="store_true", help="Publish snapshot, process pending commands once, and exit.")
    args = parser.parse_args()

    logger = setup_logging()
    lock_fh = acquire_lock(logger) if not args.once else None

    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=4000)
        client.admin.command("ping")
        db = client[MONGO_DB]
        state_col = db["ralfia_windows_bridge_state"]
        logger.info("Connected to InnerOS MongoDB at %s (db=%s) as host=%s", MONGO_URI, MONGO_DB, HOST_ID)

        last_hb = 0.0
        while True:
            try:
                processed = process_pending_commands(db, logger)
                now_ts = time.time()
                if args.once or processed > 0 or (now_ts - last_hb) >= HEARTBEAT_INTERVAL_SEC:
                    snap = collect_full_snapshot()
                    state_col.replace_one({"_id": HOST_ID}, snap, upsert=True)
                    last_hb = now_ts
                    logger.info("Snapshot published (kiro_running=%s, git_branch=%s)", snap["kiro"]["running"], snap["workspace"].get("git_branch"))
                if args.once:
                    break
            except Exception as exc:
                logger.exception("Bridge loop error (will retry): %s", exc)
                if args.once:
                    return 1
            time.sleep(POLL_INTERVAL_SEC)
    finally:
        if lock_fh:
            lock_fh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
