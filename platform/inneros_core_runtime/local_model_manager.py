"""Safe local model management primitives for InnerOS.

The module exposes provider-neutral operations for ChatGPT/Ralphi without
accepting arbitrary shell commands. Heavy actions default to dry-run and are
tracked as durable jobs in Mongo so a chat can disconnect safely.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai import mongo_store

CAPABILITY = "local_model_manager"
VERSION = "local_model_manager_v1"
JOBS_COL = "ralfia_local_model_jobs"
REGISTRY_KEY = "local_model_registry"
ROUTER_KEY = "local_model_router_defaults"
DEFAULT_STORE = Path("/home/rlopez/inneros/inneros_core/var/local_models")
VLLM_RUNTIME_CANDIDATES = ["/home/rlopez/data/venvs/vllm-rocm/bin/python", "python3"]
NODE_HOSTS = {"amd": "192.168.1.5", "local-amd-5": "192.168.1.5", "intel": "192.168.1.4", "local-intel-4": "192.168.1.4"}
ALLOWED_BACKENDS = {"vllm", "ollama"}
MODEL_REF_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:@[A-Za-z0-9_.-]+)?$")
ALIAS_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
JOB_ID_RE = re.compile(r"^lmjob_[0-9]+_[a-f0-9]{6}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return mongo_store.get_db()


def _node(node: str | None) -> str:
    value = (node or "amd").strip().lower()
    if value in {"amd", "local-amd-5", "192.168.1.5", ".5"}:
        return "amd"
    if value in {"intel", "primary", "local-intel-4", "192.168.1.4", ".4"}:
        return "intel"
    raise ValueError("node_not_allowlisted")


def _safe_backend(backend: str | None) -> str:
    value = (backend or "vllm").strip().lower()
    if value not in ALLOWED_BACKENDS:
        raise ValueError("backend_not_allowlisted")
    return value


def _safe_model_ref(model_ref: str) -> str:
    value = (model_ref or "").strip()
    if not MODEL_REF_RE.match(value):
        raise ValueError("model_ref_must_be_hf_owner_repo")
    return value


def _safe_alias(alias: str | None, model_ref: str) -> str:
    value = (alias or model_ref.replace("/", "__")).strip()
    if not ALIAS_RE.match(value):
        raise ValueError("alias_not_allowlisted")
    return value


def _run(argv: list[str], *, timeout: int = 30) -> dict[str, Any]:
    try:
        proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-8000:],
            "stderr": (proc.stderr or "")[-4000:],
            "argv": argv,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "argv": argv}


def _node_run(node: str, argv: list[str], *, timeout: int = 30) -> dict[str, Any]:
    safe_node = _node(node)
    if safe_node == "amd":
        host = NODE_HOSTS["amd"]
    else:
        host = NODE_HOSTS["intel"]
    local_ips = set()
    try:
        local_ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass
    try:
        ip_probe = subprocess.run(["hostname", "-I"], text=True, capture_output=True, timeout=3, check=False)
        local_ips.update((ip_probe.stdout or "").split())
    except Exception:
        pass
    if host in local_ips:
        return _run(argv, timeout=timeout)
    # Commands are fixed argv from this module. No caller-controlled shell.
    return _run(["ssh", f"rlopez@{host}", *argv], timeout=timeout)


def _parse_bytes(text: str) -> int | None:
    match = re.search(r"(\d+)", text or "")
    return int(match.group(1)) if match else None


def _disk_free(node: str, path: str) -> dict[str, Any]:
    out = _node_run(node, ["df", "-B1", path], timeout=15)
    if not out.get("ok"):
        return {"ok": False, "error": out.get("stderr") or out.get("error"), "raw": out}
    lines = (out.get("stdout") or "").splitlines()
    if len(lines) < 2:
        return {"ok": False, "error": "df_output_unexpected", "raw": out}
    parts = lines[-1].split()
    return {"ok": True, "path": path, "total_bytes": int(parts[1]), "used_bytes": int(parts[2]), "free_bytes": int(parts[3])}


def _gpu_info(node: str) -> dict[str, Any]:
    rocm = _node_run(node, ["bash", "-lc", "command -v rocm-smi >/dev/null && rocm-smi --showproductname --showmeminfo vram --json || true"], timeout=20)
    rocminfo = _node_run(node, ["bash", "-lc", "command -v rocminfo >/dev/null && rocminfo | grep -E 'Name:|Marketing Name' | head -20 || true"], timeout=20)
    return {"ok": bool(rocm.get("ok") or rocminfo.get("ok")), "rocm_smi": rocm, "rocminfo_preview": (rocminfo.get("stdout") or "")[:3000]}


def _active_vllm_container(node: str) -> dict[str, Any]:
    script = r"""
set -e
cid=$(docker ps --filter name=inneros-vllm --filter status=running --format '{{.Names}}' | head -1)
if [ -z "$cid" ]; then
  cid=$(docker ps --filter publish=8000 --filter status=running --format '{{.Names}}' | head -1)
fi
if [ -z "$cid" ]; then
  exit 1
fi
docker inspect "$cid" --format 'name={{.Name}} image={{.Config.Image}} pid={{.State.Pid}} args={{json .Args}}'
"""
    out = _node_run(node, ["bash", "-lc", script], timeout=15)
    return {"ok": bool(out.get("ok") and (out.get("stdout") or "").strip()), "result": out}


def _runtime_versions(node: str) -> dict[str, Any]:
    docker_probe = r"""
set -e
cid=$(docker ps --filter name=inneros-vllm --filter status=running --format '{{.Names}}' | head -1)
if [ -z "$cid" ]; then
  cid=$(docker ps --filter publish=8000 --filter status=running --format '{{.Names}}' | head -1)
fi
if [ -z "$cid" ]; then
  exit 1
fi
echo "container=$cid"
docker exec "$cid" python -c 'import importlib.metadata as m, sys; print("python=" + sys.executable); print("python_version=" + sys.version.split()[0]);
try:
 import torch; print("torch_version=" + str(torch.__version__)); print("torch_hip=" + str(getattr(torch.version, "hip", None)))
except Exception as exc:
 print("torch_error=" + type(exc).__name__ + ":" + str(exc))
for pkg in ("vllm", "transformers", "huggingface_hub"):

    try: print(pkg + "_version=" + m.version(pkg))
    except Exception: print(pkg + "_version=missing")'
"""
    vllm_probe = r"""
for py in /home/rlopez/data/venvs/vllm-rocm/bin/python python3; do
  if [ -x "$py" ] || command -v "$py" >/dev/null 2>&1; then
    echo "python=$py"
    "$py" - <<'PYVENV'
import importlib.metadata as m
for pkg in ("vllm", "torch", "transformers", "huggingface_hub"):
    try:
        print(f"{pkg}_version={m.version(pkg)}")
    except Exception:
        print(f"{pkg}_version=missing")
PYVENV
    exit 0
  fi
done
echo "vllm_version=missing"
"""
    docker_versions = _node_run(node, ["bash", "-lc", docker_probe], timeout=45)
    fallback_versions = None if docker_versions.get("ok") else _node_run(node, ["bash", "-lc", vllm_probe], timeout=45)
    return {
        "python": _node_run(node, ["bash", "-lc", "python3 --version || true"], timeout=10),
        "vllm": docker_versions if docker_versions.get("ok") else fallback_versions,
        "vllm_source": "docker_active_container" if docker_versions.get("ok") else "legacy_venv_fallback",
        "active_container": _active_vllm_container(node),
        "huggingface_cli": _node_run(node, ["bash", "-lc", "command -v huggingface-cli || command -v hf || true"], timeout=10),
    }


def _hf_api(path: str, params: dict[str, Any] | None = None, timeout: float = 12.0) -> dict[str, Any]:
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")})
    url = f"https://huggingface.co/api/{path.lstrip('/')}" + (f"?{query}" if query else "")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InnerOS-local-model-manager/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {"ok": True, "status": getattr(resp, "status", 200), "url": url, "data": json.loads(raw)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "url": url, "error": exc.read().decode("utf-8", errors="replace")[:1000]}
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def local_model_catalog_search(query: str, source: str = "huggingface", filters: dict[str, Any] | None = None, limit: int = 10) -> dict[str, Any]:
    """Search public model catalog metadata without downloading models."""
    if (source or "huggingface").lower() != "huggingface":
        return {"ok": False, "error": "source_not_supported", "supported": ["huggingface"]}
    filt = filters or {}
    params = {
        "search": query or filt.get("search") or "coder",
        "limit": max(1, min(int(limit or 10), 25)),
        "sort": filt.get("sort") or "downloads",
        "direction": -1,
        "full": "true",
    }
    if filt.get("task"):
        params["pipeline_tag"] = filt["task"]
    res = _hf_api("models", params)
    if not res.get("ok"):
        return {**res, "capability": CAPABILITY}
    items = []
    for item in (res.get("data") or [])[: params["limit"]]:
        tags = item.get("tags") or []
        siblings = item.get("siblings") or []
        items.append({
            "model_ref": item.get("modelId") or item.get("id"),
            "downloads": item.get("downloads"),
            "likes": item.get("likes"),
            "last_modified": item.get("lastModified"),
            "pipeline_tag": item.get("pipeline_tag"),
            "private": item.get("private"),
            "gated": item.get("gated"),
            "tags": tags[:40],
            "safetensors_hint": any(str((s or {}).get("rfilename", "")).endswith(".safetensors") for s in siblings),
            "quantization_hints": [t for t in tags if any(q in str(t).lower() for q in ("awq", "gptq", "gguf", "fp8", "int4", "4bit"))],
        })
    return {"ok": True, "capability": CAPABILITY, "source": "huggingface", "query": params["search"], "count": len(items), "items": items}


def _hf_model_info(model_ref: str) -> dict[str, Any]:
    model = _safe_model_ref(model_ref).split("@", 1)[0]
    return _hf_api(f"models/{model}")


def local_model_preflight(model_ref: str, node: str = "amd", backend: str = "vllm", quantization: str = "", revision: str = "") -> dict[str, Any]:
    safe_node = _node(node)
    safe_backend = _safe_backend(backend)
    model = _safe_model_ref(model_ref)
    info = _hf_model_info(model)
    disk = _disk_free(safe_node, str(DEFAULT_STORE.parent))
    gpu = _gpu_info(safe_node)
    versions = _runtime_versions(safe_node)
    siblings = (info.get("data") or {}).get("siblings") or []
    total_size = sum(int(s.get("size") or 0) for s in siblings if isinstance(s, dict))
    has_safetensors = any(str((s or {}).get("rfilename", "")).endswith(".safetensors") for s in siblings)
    gated = (info.get("data") or {}).get("gated")
    risk: list[str] = []
    if gated:
        risk.append("hf_model_gated_or_license_required")
    if safe_backend == "vllm" and not has_safetensors:
        risk.append("no_safetensors_hint")
    if disk.get("ok") and total_size and disk.get("free_bytes", 0) < int(total_size * 1.25):
        risk.append("insufficient_disk_for_safe_download")
    vllm_stdout = versions.get("vllm", {}).get("stdout", "")
    if "vllm_version=missing" in vllm_stdout or not vllm_stdout.strip():
        risk.append("vllm_not_detected")
    elif "vllm_import_ok=false" in vllm_stdout:
        risk.append("vllm_import_failed")
    return {
        "ok": info.get("ok", False),
        "capability": CAPABILITY,
        "model_ref": model,
        "node": safe_node,
        "backend": safe_backend,
        "revision": revision or None,
        "quantization": quantization or None,
        "hf": {
            "ok": info.get("ok"),
            "gated": gated,
            "private": (info.get("data") or {}).get("private"),
            "pipeline_tag": (info.get("data") or {}).get("pipeline_tag"),
            "tags": ((info.get("data") or {}).get("tags") or [])[:50],
            "siblings_count": len(siblings),
            "estimated_known_file_bytes": total_size,
            "has_safetensors": has_safetensors,
        },
        "node_runtime": {"disk": disk, "gpu": gpu, "versions": versions},
        "risk": risk,
        "safe_to_download": bool(info.get("ok") and not gated and not risk),
        "blocker": risk[0] if risk else None,
    }


def _create_job(kind: str, payload: dict[str, Any], status: str = "planned") -> dict[str, Any]:
    job_id = f"lmjob_{int(time.time())}_{os.urandom(3).hex()}"
    doc = {"job_id": job_id, "kind": kind, "status": status, "created_at": _now(), "updated_at": _now(), "payload": payload, "events": []}
    _db()[JOBS_COL].insert_one(doc)
    doc.pop("_id", None)
    return doc


def local_model_download(model_ref: str, node: str = "amd", revision: str = "", quantization: str = "", target_store: str = "", dry_run: bool = True) -> dict[str, Any]:
    preflight = local_model_preflight(model_ref, node=node, backend="vllm", quantization=quantization, revision=revision)
    target = str(Path(target_store or DEFAULT_STORE).as_posix())
    payload = {"model_ref": _safe_model_ref(model_ref), "node": _node(node), "revision": revision or None, "quantization": quantization or None, "target_store": target, "dry_run": bool(dry_run), "preflight": preflight}
    if dry_run:
        job = _create_job("download", payload, status="dry_run")
        return {"ok": True, "capability": CAPABILITY, "dry_run": True, "job": job, "next_action": "Call local_model_download(..., dry_run=false) after owner/model selection."}
    if not preflight.get("safe_to_download"):
        job = _create_job("download", payload, status="blocked")
        return {"ok": False, "capability": CAPABILITY, "job": job, "error": "preflight_not_safe", "blocker": preflight.get("blocker"), "preflight": preflight}
    # Do not stream a large download in the MCP request. Record a durable job for a worker.
    job = _create_job("download", payload, status="queued")
    return {"ok": True, "capability": CAPABILITY, "job": job, "queued": True, "note": "Persistent job queued; worker implementation performs resumable download server-side."}


def local_model_download_status(job_id: str) -> dict[str, Any]:
    doc = _db()[JOBS_COL].find_one({"job_id": str(job_id or "")}, {"_id": 0})
    return {"ok": bool(doc), "capability": CAPABILITY, "job": doc, "error": None if doc else "job_not_found"}


def local_model_worker_start(job_id: str = "", node: str = "amd") -> dict[str, Any]:
    safe_node = _node(node)
    clean_job = (job_id or "").strip()
    if clean_job and not JOB_ID_RE.match(clean_job):
        return {"ok": False, "capability": CAPABILITY, "error": "invalid_job_id"}
    if clean_job:
        _db()[JOBS_COL].update_one(
            {"job_id": clean_job},
            {
                "$set": {"status": "running", "updated_at": _now(), "worker_launch_requested_at": _now()},
                "$push": {"events": {"ts": _now(), "event": "worker_launch_requested", "node": safe_node}},
            },
        )
    log_path = "/home/rlopez/inneros/inneros_core/var/local_models/_worker.log"
    script = "mkdir -p /home/rlopez/inneros/inneros_core/var/local_models && cd /home/rlopez/inneros/inneros_core/platform && (setsid venv/bin/python3 -m inneros_core_runtime.local_model_worker"
    if clean_job:
        script += f" --job-id {clean_job}"
    script += f" </dev/null >> {log_path} 2>&1 & echo $!)"
    res = _node_run(safe_node, ["bash", "-lc", script], timeout=10)
    return {"ok": bool(res.get("ok")), "capability": CAPABILITY, "node": safe_node, "job_id": clean_job or None, "launch": res}


def local_model_list(node: str = "", backend: str = "") -> dict[str, Any]:
    safe_node = _node(node or "amd")
    safe_backend = _safe_backend(backend or "vllm")
    listing = _node_run(safe_node, ["bash", "-lc", f"find {shlex_quote(str(DEFAULT_STORE))} -maxdepth 3 -type f \\( -name '*.safetensors' -o -name 'config.json' \\) 2>/dev/null | head -200"], timeout=20)
    registry = mongo_store.get_coordination_state(REGISTRY_KEY)
    return {"ok": True, "capability": CAPABILITY, "node": safe_node, "backend": safe_backend, "store": str(DEFAULT_STORE), "files_preview": (listing.get("stdout") or "").splitlines(), "registry": registry.get("state") if registry.get("ok") else {}}


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def local_model_runtime_status(node: str = "amd", backend: str = "vllm") -> dict[str, Any]:
    safe_node = _node(node)
    safe_backend = _safe_backend(backend)
    ports = _node_run(safe_node, ["bash", "-lc", "ss -ltnp 2>/dev/null | grep -E ':(8000|8001|11434) ' || true"], timeout=10)
    models = _node_run(safe_node, ["bash", "-lc", "curl -fsS http://127.0.0.1:8000/v1/models 2>/dev/null || true"], timeout=10) if safe_backend == "vllm" else _node_run(safe_node, ["bash", "-lc", "curl -fsS http://127.0.0.1:11434/api/tags 2>/dev/null || true"], timeout=10)
    units = _node_run(safe_node, ["bash", "-lc", "systemctl --user list-units 'inneros-vllm*' --no-pager --plain 2>/dev/null || true"], timeout=10)
    return {"ok": True, "capability": CAPABILITY, "node": safe_node, "backend": safe_backend, "ports": ports, "models": models, "systemd_units": units, "versions": _runtime_versions(safe_node), "gpu": _gpu_info(safe_node)}


def local_model_serve(model_ref: str, node: str = "amd", backend: str = "vllm", alias: str = "", context_length: int = 8192, gpu_memory_utilization: float = 0.85, dry_run: bool = True) -> dict[str, Any]:
    safe_node = _node(node)
    safe_backend = _safe_backend(backend)
    model = _safe_model_ref(model_ref)
    safe_alias = _safe_alias(alias, model)
    preflight = local_model_preflight(model, node=safe_node, backend=safe_backend)
    plan = {
        "unit": f"inneros-vllm-{safe_alias}.service",
        "node": safe_node,
        "backend": safe_backend,
        "model_ref": model,
        "alias": safe_alias,
        "private_endpoint": "http://127.0.0.1:8000/v1",
        "context_length": max(512, min(int(context_length or 8192), 262144)),
        "gpu_memory_utilization": max(0.1, min(float(gpu_memory_utilization or 0.85), 0.95)),
        "rollback": "keep previous unit until health passes",
        "preflight": preflight,
    }
    if dry_run:
        job = _create_job("serve", {**plan, "dry_run": True}, status="dry_run")
        return {"ok": True, "capability": CAPABILITY, "dry_run": True, "plan": plan, "job": job}
    if not preflight.get("safe_to_download"):
        return {"ok": False, "capability": CAPABILITY, "error": "preflight_not_safe", "plan": plan}
    job = _create_job("serve", {**plan, "dry_run": False}, status="queued")
    return {"ok": True, "capability": CAPABILITY, "queued": True, "job": job, "plan": plan}


def local_model_stop(alias: str = "", model_ref: str = "", node: str = "amd") -> dict[str, Any]:
    if not alias and not model_ref:
        return {"ok": False, "capability": CAPABILITY, "error": "alias_or_model_ref_required"}
    target = _safe_alias(alias or "", model_ref or "model/alias")
    safe_node = _node(node)
    # Safe fixture: only inneros-vllm units are targetable.
    unit = f"inneros-vllm-{target}.service"
    res = _node_run(safe_node, ["systemctl", "--user", "stop", unit], timeout=30)
    stderr = (res.get("stderr") or "").lower()
    idempotent_missing = any(text in stderr for text in ("not loaded", "not found", "could not be found"))
    return {"ok": bool(res.get("ok") or idempotent_missing), "capability": CAPABILITY, "node": safe_node, "unit": unit, "idempotent_missing": idempotent_missing, "result": res}


def local_model_delete(model_ref: str, node: str = "amd", dry_run: bool = True) -> dict[str, Any]:
    model = _safe_model_ref(model_ref)
    safe_node = _node(node)
    router = mongo_store.get_coordination_state(ROUTER_KEY)
    defaults = (router.get("state") or {}) if router.get("ok") else {}
    if model in json.dumps(defaults):
        return {"ok": False, "capability": CAPABILITY, "error": "model_is_router_default", "dry_run": dry_run}
    runtime = local_model_runtime_status(node=safe_node, backend="vllm")
    if model in (runtime.get("models", {}).get("stdout") or ""):
        return {"ok": False, "capability": CAPABILITY, "error": "model_is_serving", "dry_run": dry_run}
    safe_path = DEFAULT_STORE / model.replace("/", "__")
    if not str(safe_path).startswith(str(DEFAULT_STORE) + "/"):
        return {"ok": False, "capability": CAPABILITY, "error": "delete_path_outside_model_store"}
    plan = {"node": safe_node, "model_ref": model, "path": str(safe_path), "guards": ["not_router_default", "not_serving", "inside_model_store"]}
    if dry_run:
        return {"ok": True, "capability": CAPABILITY, "dry_run": True, "would_delete": plan}
    res = _node_run(safe_node, ["rm", "-rf", str(safe_path)], timeout=60)
    return {"ok": bool(res.get("ok")), "capability": CAPABILITY, "deleted": plan, "result": res}


def local_model_benchmark(model_ref: str = "", alias: str = "", prompt_suite: str = "format_contract", task_class: str = "coding", repo_context_ref: str = "") -> dict[str, Any]:
    target = alias or model_ref
    if target and "/" in target:
        _safe_model_ref(target)
    elif target:
        _safe_alias(target, "model/alias")
    runtime = local_model_runtime_status(node="amd", backend="vllm")
    return {
        "ok": True,
        "capability": CAPABILITY,
        "dry_run": True,
        "selected_node": "amd",
        "backend": "vllm",
        "target": target,
        "prompt_suite": prompt_suite,
        "task_class": task_class,
        "repo_context_ref": repo_context_ref,
        "runtime": runtime,
        "metrics": {"tokens_per_second": None, "ttft_ms": None, "vram_peak": None, "format_contract": "not_run_dry_fixture"},
        "next_action": "Run after local_model_serve health PASS.",
    }


def local_model_set_default(task_class: str, model_ref: str, provider_id: str = "local-amd-5") -> dict[str, Any]:
    task = re.sub(r"[^A-Za-z0-9_.-]", "_", (task_class or "coding").strip().lower())[:80]
    model = model_ref.strip()
    state_doc = mongo_store.get_coordination_state(ROUTER_KEY)
    state = dict(state_doc.get("state") or {}) if state_doc.get("ok") else {}
    state.pop("_id", None)
    state.setdefault("defaults", {})
    if not model:
        previous = state["defaults"].pop(task, None)
        state["version"] = VERSION
        state["updated_at"] = _now()
        mongo_store.upsert_coordination_state(key=ROUTER_KEY, data=state)
        return {"ok": True, "capability": CAPABILITY, "task_class": task, "unset": True, "previous": previous, "router_state": state}
    if "/" in model:
        _safe_model_ref(model)
    else:
        _safe_alias(model, "model/alias")
    state["defaults"][task] = {"model_ref": model, "provider_id": provider_id, "node": "amd" if provider_id == "local-amd-5" else provider_id, "updated_at": _now()}
    state["version"] = VERSION
    mongo_store.upsert_coordination_state(key=ROUTER_KEY, data=state)
    return {"ok": True, "capability": CAPABILITY, "task_class": task, "default": state["defaults"][task], "router_state": state}


def local_model_router_status(project_id: str = "", task_class: str = "") -> dict[str, Any]:
    state_doc = mongo_store.get_coordination_state(ROUTER_KEY)
    state = dict(state_doc.get("state") or {}) if state_doc.get("ok") else {"defaults": {}}
    selected = None
    if task_class:
        selected = (state.get("defaults") or {}).get(task_class)
    return {"ok": True, "capability": CAPABILITY, "project_id": project_id or None, "task_class": task_class or None, "state": state, "selected": selected}
