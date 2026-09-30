"""Durable local model queue worker.

Runs under the InnerOS platform venv for Mongo access and delegates the actual
Hugging Face download to the AMD vLLM/ROCm venv, which already has
`huggingface_hub` installed.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

JOBS_COL = "ralfia_local_model_jobs"
REGISTRY_KEY = "local_model_registry"
ROUTER_KEY = "local_model_router_defaults"
DEFAULT_STORE = Path("/home/rlopez/inneros/inneros_core/var/local_models")
VLLM_PYTHON = Path("/home/rlopez/data/venvs/vllm-rocm/bin/python")
VLLM_DOCKER_IMAGE = "rocm/vllm:rocm7.12.0_gfx120X-all_ubuntu24.04_py3.12_pytorch_2.9.1_vllm_0.16.0"
WORKER_LOCK = DEFAULT_STORE / "_worker.lock"
WORKER_HEARTBEAT_KEY = "local_model_worker_amd_heartbeat"
JOB_RE = re.compile(r"^lmjob_[0-9]+_[a-f0-9]{6}$")
MODEL_REF_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:@[A-Za-z0-9_.-]+)?$")
ALIAS_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _event(job_id: str, event: str, **data: Any) -> None:
    _db()[JOBS_COL].update_one(
        {"job_id": job_id},
        {
            "$set": {"updated_at": _now()},
            "$push": {"events": {"ts": _now(), "event": event, **data}},
        },
    )


def _set_status(job_id: str, status: str, **fields: Any) -> None:
    patch = {"status": status, "updated_at": _now(), **fields}
    _db()[JOBS_COL].update_one({"job_id": job_id}, {"$set": patch})


def _target_path(model_ref: str, target_store: str | None) -> Path:
    store = Path(target_store or DEFAULT_STORE).expanduser()
    if not str(store).startswith(str(DEFAULT_STORE)):
        raise ValueError("target_store_not_allowlisted")
    target = store / model_ref.replace("/", "__")
    if not str(target).startswith(str(DEFAULT_STORE) + "/"):
        raise ValueError("target_path_not_allowlisted")
    return target


def _download_script() -> str:
    return r"""
import json
import os
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

payload = json.loads(os.environ["INNEROS_MODEL_DOWNLOAD_PAYLOAD"])
repo_id = payload["model_ref"]
target = Path(payload["target_path"])
target.mkdir(parents=True, exist_ok=True)

path = snapshot_download(
    repo_id=repo_id,
    revision=payload.get("revision") or None,
    local_dir=str(target),
    local_dir_use_symlinks=False,
    resume_download=True,
)

files = [p for p in target.rglob("*") if p.is_file()]
size = sum(p.stat().st_size for p in files)
manifest = {
    "repo_id": repo_id,
    "local_dir": str(target),
    "snapshot_path": path,
    "file_count": len(files),
    "total_bytes": size,
}
(target / ".inneros_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps(manifest))
"""


def _safe_alias(alias: str | None, model_ref: str) -> str:
    value = (alias or model_ref.replace("/", "__")).strip()
    if not ALIAS_RE.match(value):
        raise ValueError("alias_not_allowlisted")
    return value


def _http_json(url: str, timeout: int = 5) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return {"ok": True, "data": json.loads(raw) if raw else None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _serve_job(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    payload = dict(job.get("payload") or {})
    model_ref = str(payload.get("model_ref") or "")
    if not MODEL_REF_RE.match(model_ref):
        _set_status(job_id, "failed", error="invalid_model_ref")
        _event(job_id, "failed", error="invalid_model_ref")
        return {"ok": False, "error": "invalid_model_ref", "job_id": job_id}
    alias = _safe_alias(payload.get("alias"), model_ref)
    model_path = _target_path(model_ref, str(DEFAULT_STORE))
    if not (model_path / "config.json").exists():
        _set_status(job_id, "failed", error="model_not_downloaded", model_path=str(model_path))
        _event(job_id, "serve_failed", error="model_not_downloaded", model_path=str(model_path))
        return {"ok": False, "error": "model_not_downloaded", "model_path": str(model_path)}

    unit = f"inneros-vllm-{alias}.service"
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    log_dir = DEFAULT_STORE / "_logs"
    unit_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{unit}.log"
    context_length = max(512, min(int(payload.get("context_length") or 8192), 262144))
    gpu_memory = max(0.1, min(float(payload.get("gpu_memory_utilization") or 0.85), 0.95))
    unit_path = unit_dir / unit
    container_name = f"inneros-vllm-{alias}"
    unit_text = f"""[Unit]
Description=InnerOS vLLM Docker {alias}
After=docker.service network-online.target

[Service]
Type=simple
ExecStartPre=-/usr/bin/docker rm -f {container_name}
ExecStart=/usr/bin/docker run --rm --name {container_name} --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --network host -v {DEFAULT_STORE}:/models {VLLM_DOCKER_IMAGE} python3 -m vllm.entrypoints.openai.api_server --model /models/{model_ref.replace("/", "__")} --served-model-name {model_ref} --host 127.0.0.1 --port 8000 --max-model-len {context_length} --gpu-memory-utilization {gpu_memory} --dtype float16 --trust-remote-code
ExecStop=/usr/bin/docker stop {container_name}
Restart=on-failure
RestartSec=10
StandardOutput=append:{log_path}
StandardError=append:{log_path}

[Install]
WantedBy=default.target
"""
    unit_path.write_text(unit_text, encoding="utf-8")
    _set_status(job_id, "running", worker_pid=os.getpid(), unit=unit, unit_path=str(unit_path), log_path=str(log_path), model_path=str(model_path))
    _event(job_id, "serve_unit_written", unit=unit, unit_path=str(unit_path), model_path=str(model_path))
    for argv in (
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", unit],
    ):
        proc = subprocess.run(argv, text=True, capture_output=True, timeout=60, check=False)
        if proc.returncode != 0:
            _set_status(job_id, "failed", error="systemd_failed", unit=unit, stderr=proc.stderr[-2000:])
            _event(job_id, "serve_failed", error="systemd_failed", unit=unit, stderr=proc.stderr[-1000:])
            return {"ok": False, "error": "systemd_failed", "unit": unit, "stderr": proc.stderr}
    _event(job_id, "serve_started", unit=unit, endpoint="http://127.0.0.1:8000/v1", model_ref=model_ref)

    health = {"ok": False}
    for _ in range(90):
        health = _http_json("http://127.0.0.1:8000/v1/models", timeout=3)
        if health.get("ok") and model_ref in json.dumps(health.get("data") or {}):
            break
        subprocess.run(["sleep", "2"], check=False)
    if not health.get("ok") or model_ref not in json.dumps(health.get("data") or {}):
        log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:] if log_path.exists() else ""
        _set_status(job_id, "failed", error="serve_health_failed", unit=unit, health=health, log_tail=log_tail)
        _event(job_id, "serve_health_failed", unit=unit, health=health, log_tail=log_tail[-1000:])
        return {"ok": False, "error": "serve_health_failed", "unit": unit, "health": health, "log_tail": log_tail}

    router_doc = mongo_store.get_coordination_state(ROUTER_KEY)
    router = dict(router_doc.get("state") or {}) if router_doc.get("ok") else {}
    router.pop("_id", None)
    router.setdefault("defaults", {})
    for task_class in ("coding", "heavy_reasoning", "code_review", "refactor"):
        router["defaults"][task_class] = {"model_ref": model_ref, "provider_id": "local-amd-5", "node": "amd", "updated_at": _now()}
    router["version"] = "worker_serve_v1"
    router["updated_at"] = _now()
    mongo_store.upsert_coordination_state(key=ROUTER_KEY, data=router)
    result = {"unit": unit, "endpoint": "http://127.0.0.1:8000/v1", "model_ref": model_ref, "model_path": str(model_path), "health": health.get("data")}
    _set_status(job_id, "completed", result=result)
    _event(job_id, "serve_health_pass", **result)
    return {"ok": True, "job_id": job_id, "status": "completed", **result}


def process_job(job_id: str) -> dict[str, Any]:
    if not JOB_RE.match(job_id or ""):
        return {"ok": False, "error": "invalid_job_id"}
    db = _db()
    job = db[JOBS_COL].find_one({"job_id": job_id})
    if not job:
        return {"ok": False, "error": "job_not_found", "job_id": job_id}
    if job.get("kind") == "serve":
        return _serve_job(job_id, job)
    if job.get("kind") != "download":
        return {"ok": False, "error": "job_kind_not_supported", "kind": job.get("kind")}
    if job.get("status") not in {"queued", "running"}:
        return {"ok": True, "job_id": job_id, "status": job.get("status"), "skipped": True}

    payload = dict(job.get("payload") or {})
    model_ref = str(payload.get("model_ref") or "")
    if not MODEL_REF_RE.match(model_ref):
        _set_status(job_id, "failed", error="invalid_model_ref")
        _event(job_id, "failed", error="invalid_model_ref")
        return {"ok": False, "error": "invalid_model_ref", "job_id": job_id}

    target = _target_path(model_ref, payload.get("target_store"))
    log_dir = DEFAULT_STORE / "_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{job_id}.log"
    target.mkdir(parents=True, exist_ok=True)

    _set_status(job_id, "running", worker_pid=os.getpid(), target_path=str(target), log_path=str(log_path))
    _event(job_id, "download_started", model_ref=model_ref, target_path=str(target), log_path=str(log_path))

    env = dict(os.environ)
    env["INNEROS_MODEL_DOWNLOAD_PAYLOAD"] = json.dumps(
        {
            "model_ref": model_ref,
            "revision": payload.get("revision"),
            "target_path": str(target),
        }
    )
    with log_path.open("ab") as log:
        proc = subprocess.run(
            [str(VLLM_PYTHON), "-c", _download_script()],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            timeout=None,
            check=False,
        )

    log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:] if log_path.exists() else ""
    if proc.returncode != 0:
        _set_status(job_id, "failed", error="download_failed", returncode=proc.returncode, log_tail=log_tail)
        _event(job_id, "download_failed", returncode=proc.returncode, log_tail=log_tail[-1000:])
        return {"ok": False, "job_id": job_id, "status": "failed", "returncode": proc.returncode, "log_tail": log_tail}

    manifest_path = target / ".inneros_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"local_dir": str(target)}
    state_doc = mongo_store.get_coordination_state(REGISTRY_KEY)
    state = dict(state_doc.get("state") or {}) if state_doc.get("ok") else {}
    state.pop("_id", None)
    state.setdefault("models", {})
    state["models"][model_ref] = {"model_ref": model_ref, "node": payload.get("node") or "amd", "path": str(target), "manifest": manifest, "updated_at": _now()}
    state["updated_at"] = _now()
    mongo_store.upsert_coordination_state(key=REGISTRY_KEY, data=state)
    _set_status(job_id, "completed", result=manifest)
    _event(job_id, "download_completed", manifest=manifest)
    return {"ok": True, "job_id": job_id, "status": "completed", "manifest": manifest}


def next_queued_job() -> str | None:
    doc = _db()[JOBS_COL].find_one({"kind": {"$in": ["download", "serve"]}, "status": "queued"}, sort=[("created_at", 1)])
    return str(doc.get("job_id")) if doc else None


def _heartbeat(state: str, **fields: Any) -> None:
    data = {"state": state, "pid": os.getpid(), "updated_at": _now(), **fields}
    mongo_store.upsert_coordination_state(key=WORKER_HEARTBEAT_KEY, data=data)


def _process_next() -> dict[str, Any]:
    job_id = next_queued_job()
    if not job_id:
        _heartbeat("idle")
        return {"ok": True, "idle": True}
    _heartbeat("processing", job_id=job_id)
    result = process_job(job_id)
    _heartbeat("idle" if result.get("ok") else "error", job_id=job_id, last_result=result)
    return result


def run_loop(interval: float) -> int:
    DEFAULT_STORE.mkdir(parents=True, exist_ok=True)
    with WORKER_LOCK.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"ok": True, "already_running": True, "lock": str(WORKER_LOCK)}))
            return 0
        lock.write(str(os.getpid()))
        lock.flush()
        _heartbeat("started", lock=str(WORKER_LOCK))
        while True:
            result = _process_next()
            print(json.dumps(result, default=str), flush=True)
            time.sleep(max(1.0, min(float(interval or 5), 300.0)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", default="")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    if args.loop:
        return run_loop(args.interval)
    job_id = args.job_id or next_queued_job()
    if not job_id:
        print(json.dumps({"ok": True, "idle": True}))
        return 0
    result = process_job(job_id)
    print(json.dumps(result, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
