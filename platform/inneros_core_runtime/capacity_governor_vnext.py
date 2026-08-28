"""Capacity Governor vNext for InnerOS local runtimes.

Classifies load as BASELINE / WORKLOAD / ANOMALY so always-on model
residency does not look like worker pressure. The functions are pure enough for
unit tests; side-effect helpers are bounded and only run on the matching node.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASELINE = "BASELINE"
WORKLOAD = "WORKLOAD"
ANOMALY = "ANOMALY"
UNKNOWN = "UNKNOWN"
VERSION = "capacity_governor_vnext_20260826"
INTEL_BASELINE_MODELS = {"qwen2.5vl:7b"}
AMD_BASELINE_MODELS = {"QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ"}
WATCHDOG_STATE = Path("/tmp/inneros_capacity_governor_watchdog.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hostname() -> str:
    return socket.gethostname().lower()


def is_intel_node() -> bool:
    host = _hostname()
    return "ver-10" in host or "intel" in host or os.getenv("INNEROS_GPU_ROLE") == "ollama-primary"


def is_amd_node() -> bool:
    host = _hostname()
    return "amd" in host or os.getenv("INNEROS_GPU_ROLE") == "vllm-primary"


def _as_ratio(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except Exception:
        return 0.0


def classify_process(name: str, model: str = "", command: str = "") -> str:
    hay = " ".join([name or "", model or "", command or ""]).lower()
    if any(model.lower() == item.lower() for item in INTEL_BASELINE_MODELS):
        return BASELINE
    if any(item.lower() in hay for item in AMD_BASELINE_MODELS):
        return BASELINE
    if "qwen2.5vl:7b" in hay:
        return BASELINE
    if "vllm" in hay and "qwen3-coder" in hay:
        return BASELINE
    if "ollama" in hay:
        return WORKLOAD
    if any(term in hay for term in ("dev_swarm", "local_model_worker", "npm", "pytest", "compileall", "codex", "worker_")):
        return WORKLOAD
    if any(term in hay for term in ("python", "node", "docker")):
        return UNKNOWN
    return UNKNOWN


def classify_capacity(
    *,
    cpu_load_ratio: float,
    ram_used_ratio: float,
    vram_used_ratio: float = 0.0,
    active_worker_count: int = 0,
    baseline_vram_ratio: float = 0.0,
    unknown_vram_ratio: float = 0.0,
    sustained_samples: int = 1,
) -> dict[str, Any]:
    cpu = _as_ratio(cpu_load_ratio)
    ram = _as_ratio(ram_used_ratio)
    vram = _as_ratio(vram_used_ratio)
    baseline_vram = _as_ratio(baseline_vram_ratio)
    unknown_vram = _as_ratio(unknown_vram_ratio)
    sustained = max(1, int(sustained_samples or 1))
    hard_reasons: list[str] = []
    soft_reasons: list[str] = []
    anomaly_reasons: list[str] = []

    if cpu >= 0.98:
        hard_reasons.append("cpu_critical")
    elif cpu >= 0.88 and sustained >= 3:
        soft_reasons.append("cpu_sustained_high")
    elif cpu >= 0.88:
        soft_reasons.append("cpu_spike_observed_no_throttle")

    if ram >= 0.96:
        hard_reasons.append("ram_critical")
    elif ram >= 0.88 and sustained >= 3:
        soft_reasons.append("ram_sustained_high")

    effective_vram = max(0.0, vram - min(vram, baseline_vram))
    if vram >= 0.97 and unknown_vram >= 0.20:
        hard_reasons.append("vram_unknown_critical")
        anomaly_reasons.append("unknown_vram_high")
    elif effective_vram >= 0.22 and sustained >= 3:
        soft_reasons.append("workload_vram_sustained")
    elif unknown_vram >= 0.12:
        anomaly_reasons.append("unknown_vram_reported")

    if active_worker_count > 0:
        state = WORKLOAD
    elif anomaly_reasons or hard_reasons:
        state = ANOMALY
    elif baseline_vram > 0 and effective_vram < 0.10 and not soft_reasons:
        state = BASELINE
    else:
        state = BASELINE if not soft_reasons else WORKLOAD

    base_workers = 4
    if hard_reasons:
        budget = 0
    elif soft_reasons and all(reason.endswith("no_throttle") for reason in soft_reasons):
        budget = base_workers
    elif soft_reasons:
        budget = max(1, min(base_workers, 2))
    else:
        budget = base_workers

    return {
        "version": VERSION,
        "state": state,
        "budget": {
            "recommended_workers": budget,
            "baseline_does_not_count_as_worker": True,
            "active_worker_count": active_worker_count,
            "admittable_now": max(0, budget - active_worker_count),
        },
        "ratios": {
            "cpu_load": round(cpu, 3),
            "ram_used": round(ram, 3),
            "vram_used": round(vram, 3),
            "baseline_vram": round(baseline_vram, 3),
            "effective_workload_vram": round(effective_vram, 3),
            "unknown_vram": round(unknown_vram, 3),
        },
        "hysteresis": {
            "sustained_samples_required": 3,
            "observed_samples": sustained,
            "brief_spikes_throttle": False,
            "hard_stop_only_for_critical": True,
        },
        "reasons": hard_reasons + [r for r in soft_reasons if not r.endswith("no_throttle")] + anomaly_reasons,
        "observations": [r for r in soft_reasons if r.endswith("no_throttle")],
    }


def _parse_int(text: str) -> int:
    try:
        return int(float(str(text).strip().replace("MiB", "").replace("MB", "")))
    except Exception:
        return 0


def nvidia_processes() -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            capture_output=True,
            timeout=6,
            check=False,
        )
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 3:
            name = parts[1]
            model = ""
            rows.append({
                "pid": parts[0],
                "process_name": name,
                "model": model,
                "used_vram_mb": _parse_int(parts[2]),
                "class": classify_process(name, model),
            })
    return rows


def ollama_loaded_models(base_url: str = "http://127.0.0.1:11434") -> list[dict[str, Any]]:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/ps", timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
    except Exception:
        return []
    models = []
    for item in data.get("models") or []:
        name = str(item.get("model") or item.get("name") or "")
        size_vram = int(item.get("size_vram") or item.get("size") or 0)
        models.append({
            "model": name,
            "used_vram_mb": round(size_vram / (1024 * 1024), 1) if size_vram else 0,
            "expires_at": item.get("expires_at"),
            "class": BASELINE if name in INTEL_BASELINE_MODELS else WORKLOAD,
        })
    return models


def _gpu_vram_ratio(snapshot: dict[str, Any]) -> float:
    gpu = snapshot.get("gpu") or {}
    for row in gpu.get("gpus") or []:
        total = float(row.get("vram_total_mb") or row.get("memory_total_mb") or 0)
        used = float(row.get("vram_used_mb") or row.get("memory_used_mb") or 0)
        if total > 0:
            return max(0.0, min(used / total, 1.0))
    raw = str(gpu.get("raw") or "")
    # rocm-smi --json in this stack exposes allocated percentage directly.
    import re
    match = re.search(r'GPU Memory Allocated \(VRAM%\)"?\s*(?::|=)\s*"?(\d+(?:\.\d+)?)"?', raw)
    if match:
        return max(0.0, min(float(match.group(1)) / 100.0, 1.0))
    return 0.0


def enrich_capacity_snapshot(snapshot: dict[str, Any], *, active_worker_count: int | None = None, sustained_samples: int = 1) -> dict[str, Any]:
    node = str(snapshot.get("node") or _hostname()).lower()
    active = max(0, int(active_worker_count or 0))
    cpu = float(((snapshot.get("cpu") or {}).get("load_ratio") or 0.0))
    ram = float(((snapshot.get("memory") or {}).get("used_ratio") or 0.0))
    vram = _gpu_vram_ratio(snapshot)
    telemetry: dict[str, Any] = {
        "node": node,
        "processes": [],
        "models": [],
        "unknown_load": {"vram_mb": 0, "processes": []},
    }
    baseline_vram_mb = 0.0
    unknown_vram_mb = 0.0
    if is_intel_node() or ".4" in node or "intel" in node or "ver-10" in node:
        telemetry["models"] = ollama_loaded_models()
        for model in telemetry["models"]:
            if model.get("class") == BASELINE:
                baseline_vram_mb += float(model.get("used_vram_mb") or 0)
            else:
                unknown_vram_mb += float(model.get("used_vram_mb") or 0)
        telemetry["processes"] = nvidia_processes()
    elif is_amd_node() or ".5" in node or "amd" in node:
        # The current AMD baseline is one vLLM Qwen3 service using most VRAM by design.
        baseline_vram_mb = vram * 32768 if vram else 0.0
        telemetry["models"] = [{"model": next(iter(AMD_BASELINE_MODELS)), "class": BASELINE, "used_vram_ratio": round(vram, 3)}]
    total_mb = 12288 if (is_intel_node() or "intel" in node or "ver-10" in node) else 32768
    baseline_ratio = min(baseline_vram_mb / total_mb, vram) if total_mb and baseline_vram_mb else (vram if is_amd_node() else 0.0)
    unknown_ratio = min(unknown_vram_mb / total_mb, vram) if total_mb and unknown_vram_mb else 0.0
    classification = classify_capacity(
        cpu_load_ratio=cpu,
        ram_used_ratio=ram,
        vram_used_ratio=vram,
        active_worker_count=active,
        baseline_vram_ratio=baseline_ratio,
        unknown_vram_ratio=unknown_ratio,
        sustained_samples=sustained_samples,
    )
    telemetry["unknown_load"]["vram_mb"] = round(unknown_vram_mb, 1)
    snapshot["capacity_governor_vnext"] = classification
    snapshot["telemetry"] = telemetry
    rec = snapshot.setdefault("recommendation", {})
    rec["recommended_concurrency_total"] = classification["budget"]["recommended_workers"]
    rec["admittable_now"] = classification["budget"]["admittable_now"]
    rec["state"] = classification["state"]
    rec["baseline_does_not_count_as_worker"] = True
    rec["reasons"] = classification["reasons"]
    rec["observations"] = classification["observations"]
    return snapshot


def enforce_ollama_baseline(*, baseline: set[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    baseline = baseline or INTEL_BASELINE_MODELS
    if not is_intel_node():
        return {"ok": True, "skipped": "not_intel_node"}
    loaded = ollama_loaded_models()
    stopped = []
    kept = []
    for item in loaded:
        model = str(item.get("model") or "")
        if not model:
            continue
        if model in baseline:
            kept.append(model)
            continue
        if dry_run:
            stopped.append({"model": model, "dry_run": True})
            continue
        api_res = _http_json(
            "http://127.0.0.1:11434/api/generate",
            method="POST",
            body={"model": model, "prompt": "", "stream": False, "keep_alive": 0},
            timeout=30,
        )
        if api_res.get("ok"):
            stopped.append({"model": model, "ok": True, "method": "api_keep_alive_0"})
            continue
        proc = subprocess.run(["ollama", "stop", model], text=True, capture_output=True, timeout=30, check=False)
        stopped.append({"model": model, "ok": proc.returncode == 0, "method": "cli_stop", "api_error": api_res.get("error"), "stderr": (proc.stderr or "")[-500:]})
    return {"ok": all(item.get("ok", True) for item in stopped), "baseline": sorted(baseline), "kept": kept, "stopped": stopped}


def _http_json(url: str, *, method: str = "GET", body: dict[str, Any] | None = None, timeout: int = 8) -> dict[str, Any]:
    try:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return {"ok": True, "data": json.loads(raw) if raw else None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def amd_vllm_watchdog_tick(*, endpoint: str = "http://127.0.0.1:8000", model: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    if not is_amd_node():
        return {"ok": True, "skipped": "not_amd_node"}
    model = model or next(iter(AMD_BASELINE_MODELS))
    models = _http_json(f"{endpoint.rstrip('/')}/v1/models", timeout=5)
    infer = {"ok": False, "skipped": "models_failed"}
    if models.get("ok"):
        infer = _http_json(
            f"{endpoint.rstrip('/')}/v1/chat/completions",
            method="POST",
            body={"model": model, "messages": [{"role": "user", "content": "Return exactly: WATCHDOG_OK"}], "max_tokens": 8, "temperature": 0, "stream": False},
            timeout=45,
        )
    healthy = bool(models.get("ok") and infer.get("ok"))
    state = {"first_failure_ts": None, "fail_count": 0, "last_action": None}
    if WATCHDOG_STATE.exists():
        try:
            state.update(json.loads(WATCHDOG_STATE.read_text(encoding="utf-8")))
        except Exception:
            pass
    now_ts = time.time()
    if healthy:
        state.update({"first_failure_ts": None, "fail_count": 0, "last_healthy_at": _now(), "last_action": "healthy"})
        WATCHDOG_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return {"ok": True, "healthy": True, "models": models, "inference": {"ok": True}}
    first = float(state.get("first_failure_ts") or now_ts)
    state["first_failure_ts"] = first
    state["fail_count"] = int(state.get("fail_count") or 0) + 1
    elapsed = now_ts - first
    action = "observe"
    command: dict[str, Any] | None = None
    if elapsed >= 120 and state["fail_count"] <= 3:
        action = "restart_vllm"
        if not dry_run:
            proc = subprocess.run(["systemctl", "--user", "restart", "inneros-vllm-qwen3-coder-30b-awq.service"], text=True, capture_output=True, timeout=90, check=False)
            command = {"ok": proc.returncode == 0, "returncode": proc.returncode, "stderr": (proc.stderr or "")[-1000:]}
    elif elapsed >= 120 and state["fail_count"] > 3:
        action = "stop_vllm_and_fallback_intel"
        if not dry_run:
            proc = subprocess.run(["systemctl", "--user", "stop", "inneros-vllm-qwen3-coder-30b-awq.service"], text=True, capture_output=True, timeout=90, check=False)
            command = {"ok": proc.returncode == 0, "returncode": proc.returncode, "stderr": (proc.stderr or "")[-1000:]}
    state.update({"last_action": action, "last_failure_at": _now(), "models": models, "inference": infer})
    WATCHDOG_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return {"ok": action == "observe", "healthy": False, "action": action, "elapsed_failure_seconds": round(elapsed, 1), "state": state, "command": command}
