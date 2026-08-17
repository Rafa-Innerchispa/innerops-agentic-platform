"""Clonación de voz local con XTTS-v2 vía Docker (Python 3.11 — el host usa 3.14)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VOICE_SAMPLES_ROOT = Path(os.getenv("VOICE_SAMPLES_ROOT", "/home/rlopez/data/ralfia/voice_samples"))
VOICE_MODELS_ROOT = Path(os.getenv("VOICE_MODELS_ROOT", "/home/rlopez/data/ralfia/voice_models"))
CLONE_JOBS_PATH = VOICE_MODELS_ROOT / "clone_jobs.json"
XTTS_DOCKER_IMAGE = os.getenv("XTTS_DOCKER_IMAGE", "ralfia-xtts:latest")
AUDIO_EXTS = {".wav", ".webm", ".mp3", ".m4a", ".ogg"}
SUPPORTED_LANGUAGES = {
    "es": "Español",
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "it": "Italiano",
    "pt": "Português",
}

_jobs_lock = threading.Lock()
SPEAKER_LABELS = {"rafael": "Rafael", "hector": "Héctor", "eliu": "Eliu", "rafagye": "Rafael"}


def _safe_speaker(name: str) -> str:
    s = (name or "rafael").strip().lower()
    s = re.sub(r"[^a-z0-9_-]", "", s)
    if s == "rafagye":
        s = "rafael"
    return s[:40] or "rafael"


def _safe_language(lang: str | None) -> str:
    l = (lang or "es").strip().lower()[:5]
    return l if l in SUPPORTED_LANGUAGES else "es"


def _speaker_samples_dir(speaker: str) -> Path:
    sp = _safe_speaker(speaker)
    p = VOICE_SAMPLES_ROOT / sp
    if p.is_dir():
        return p
    if sp == "rafael":
        alt = VOICE_SAMPLES_ROOT / "rafagye"
        if alt.is_dir():
            return alt
    return p


def _clone_dir(speaker: str) -> Path:
    return VOICE_MODELS_ROOT / f"{_safe_speaker(speaker)}_xtts"


def _manifest_path(speaker: str) -> Path:
    return _clone_dir(speaker) / "manifest.json"


def _load_jobs() -> dict[str, Any]:
    if not CLONE_JOBS_PATH.is_file():
        return {}
    try:
        return json.loads(CLONE_JOBS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_jobs(jobs: dict[str, Any]) -> None:
    VOICE_MODELS_ROOT.mkdir(parents=True, exist_ok=True)
    CLONE_JOBS_PATH.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def _set_job(speaker: str, **fields: Any) -> dict[str, Any]:
    sp = _safe_speaker(speaker)
    with _jobs_lock:
        jobs = _load_jobs()
        job = jobs.get(sp, {})
        job.update(fields)
        job["speaker"] = sp
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        jobs[sp] = job
        _save_jobs(jobs)
        return job


def docker_image_ready() -> bool:
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", XTTS_DOCKER_IMAGE],
            capture_output=True,
            timeout=30,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _docker_run(args: list[str], timeout: int = 3600) -> dict[str, Any]:
    if not docker_image_ready():
        raise RuntimeError(
            "Imagen Docker XTTS no encontrada. En el servidor ejecuta una vez:\n"
            "  bash ~/projects/ralfiia-amd-standby/scripts/setup_xtts_docker.sh"
        )
    worker = Path(__file__).resolve().parent / "xtts_worker.py"
    use_gpu = os.getenv("XTTS_DOCKER_GPU", "0").strip().lower() in ("1", "true", "yes")
    use_rocm = os.getenv("XTTS_DOCKER_ROCM", "1").strip().lower() in ("1", "true", "yes")
    base = [
        "docker",
        "run",
        "--rm",
        "-e",
        "COQUI_TOS_AGREED=1",
        "-v",
        f"{VOICE_MODELS_ROOT.resolve()}:/models",
    ]
    if worker.is_file():
        base.extend(["-v", f"{worker.resolve()}:/app/xtts_worker.py:ro"])
    if use_gpu:
        base[2:2] = ["--gpus", "all"]
    elif use_rocm:
        for dev in ("/dev/kfd", "/dev/dri"):
            if Path(dev).exists():
                base.extend(["--device", dev])
        base.extend(["-e", "HSA_OVERRIDE_GFX_VERSION=11.0.0"])
    cmd = [*base, XTTS_DOCKER_IMAGE, *args]
    logger.info("XTTS docker: %s", " ".join(args[:4]))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "error docker")[-1200:]
        raise RuntimeError(err.strip())
    out = (proc.stdout or "").strip()
    if out:
        try:
            return json.loads(out.splitlines()[-1])
        except json.JSONDecodeError:
            return {"ok": True, "raw": out}
    return {"ok": True}


def _ffmpeg_to_wav(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", "22050", "-ac", "1", "-f", "wav", str(dest)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-300:] if proc.stderr else "ffmpeg error")


def prepare_reference_wavs(speaker: str, *, default_language: str = "es", max_refs: int = 12) -> list[str]:
    samples_dir = _speaker_samples_dir(speaker)
    if not samples_dir.is_dir():
        raise FileNotFoundError(f"Sin muestras para {speaker}")
    files = sorted(p for p in samples_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS)
    if not files:
        raise FileNotFoundError("Sin archivos de audio")
    sp = _safe_speaker(speaker)
    container_base = f"/models/{sp}_xtts"
    refs_dir = _clone_dir(speaker) / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    for old in refs_dir.glob("*.wav"):
        old.unlink(missing_ok=True)
    ref_paths: list[str] = []
    for i, f in enumerate(files[:max_refs]):
        dest = refs_dir / f"ref_{i:02d}.wav"
        _ffmpeg_to_wav(f, dest)
        ref_paths.append(f"{container_base}/refs/ref_{i:02d}.wav")
    lang = _safe_language(default_language)
    manifest = {
        "speaker": _safe_speaker(speaker),
        "label": SPEAKER_LABELS.get(_safe_speaker(speaker), speaker.title()),
        "reference_wavs": ref_paths,
        "sample_count": len(files),
        "reference_count": len(ref_paths),
        "default_language": lang,
        "languages": list(SUPPORTED_LANGUAGES.keys()),
        "voice_id": f"xtts:{_safe_speaker(speaker)}",
        "prepared_at": datetime.now(timezone.utc).isoformat(),
    }
    _manifest_path(speaker).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return ref_paths


def detect_language(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "es"
    if re.search(r"[äöüßÄÖÜ]", t):
        return "de"
    if re.search(r"[àâçéèêëîïôùûœæ]", t, re.I):
        return "fr"
    en_hits = len(re.findall(r"\b(the|and|you|hello|thanks|please|is|are|was)\b", t, re.I))
    es_hits = len(re.findall(r"\b(el|la|los|las|que|hola|gracias|por favor|es|está)\b", t, re.I))
    if en_hits > es_hits + 1:
        return "en"
    return "es"


def _move_output_wav(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.replace(dest)
    except OSError:
        shutil.copy2(src, dest)
        src.unlink(missing_ok=True)


def synthesize(
    text: str,
    output_wav: Path,
    *,
    speaker: str,
    language: str | None = None,
) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    manifest_path = _manifest_path(speaker)
    if not manifest_path.is_file():
        return {"ok": False, "error": "clone_not_ready", "detail": "Pulsa «Clonar voz» en el laboratorio."}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lang = _safe_language(language or manifest.get("default_language") or detect_language(text))
    container_manifest = f"/models/{_safe_speaker(speaker)}_xtts/manifest.json"
    container_out = f"/models/{_safe_speaker(speaker)}_xtts/out_{output_wav.name}"
    try:
        result = _docker_run(
            [
                "synthesize",
                "--manifest",
                container_manifest,
                "--text",
                text[:2000],
                "--output",
                container_out,
                "--language",
                lang,
            ] + (["--gpu"] if os.getenv("XTTS_DOCKER_GPU", "0").strip().lower() in ("1", "true", "yes") else []),
            timeout=600,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    host_out = _clone_dir(speaker) / f"out_{output_wav.name}"
    if host_out.is_file():
        _move_output_wav(host_out, output_wav)
    if not output_wav.is_file() or output_wav.stat().st_size < 100:
        return {"ok": False, "error": result.get("error") or "empty_output"}
    return {
        "ok": True,
        "provider": "xtts-v2-docker",
        "path": str(output_wav),
        "language": lang,
        "speaker": _safe_speaker(speaker),
        "voice_id": manifest.get("voice_id"),
    }


def clone_status(speaker: str) -> dict[str, Any]:
    sp = _safe_speaker(speaker)
    samples_dir = _speaker_samples_dir(sp)
    sample_count = len([p for p in samples_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS]) if samples_dir.is_dir() else 0
    manifest_path = _manifest_path(sp)
    job = _load_jobs().get(sp, {})
    cloned = manifest_path.is_file() and job.get("status") == "ready"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    msg = job.get("message", "")
    if job.get("status") == "error" and "pip" in msg.lower():
        msg = (
            "Coqui TTS no funciona en Python 3.14. Usa Docker: "
            "bash ~/projects/ralfiia-amd-standby/scripts/setup_xtts_docker.sh"
        )
    return {
        "ok": True,
        "speaker": sp,
        "label": SPEAKER_LABELS.get(sp, sp.title()),
        "sample_count": sample_count,
        "min_samples": int(os.getenv("VOICE_CLONE_MIN_SAMPLES", "15")),
        "ready_for_clone": sample_count >= int(os.getenv("VOICE_CLONE_MIN_SAMPLES", "15")),
        "cloned": cloned,
        "status": job.get("status", "idle"),
        "message": msg,
        "progress_pct": job.get("progress_pct", 100 if cloned else 0),
        "voice_id": manifest.get("voice_id") or f"xtts:{sp}",
        "default_language": manifest.get("default_language") or job.get("language") or "es",
        "languages": list(SUPPORTED_LANGUAGES.keys()),
        "language_labels": SUPPORTED_LANGUAGES,
        "docker_ready": docker_image_ready(),
        "active_in_ralfia": cloned and job.get("active", False),
    }


def _normalize_output_languages(language: str, output_languages: list[str] | None) -> list[str]:
    lang = _safe_language(language)
    if not output_languages:
        return [lang]
    seen: set[str] = set()
    out: list[str] = []
    for raw in output_languages:
        l = _safe_language(raw)
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out or [lang]


def _run_clone_worker(speaker: str, language: str, output_languages: list[str] | None = None) -> None:
    sp = _safe_speaker(speaker)
    lang = _safe_language(language)
    langs = _normalize_output_languages(lang, output_languages)
    lang_labels = ", ".join(SUPPORTED_LANGUAGES.get(l, l) for l in langs)
    try:
        _set_job(sp, status="preparing", message="Convirtiendo muestras a WAV…", progress_pct=15, language=lang)
        prepare_reference_wavs(sp, default_language=lang)
        _set_job(
            sp,
            status="loading_model",
            message=f"Cargando XTTS-v2 en Docker (muestras: {SUPPORTED_LANGUAGES.get(lang, lang)})…",
            progress_pct=40,
            language=lang,
        )
        container_manifest = f"/models/{sp}_xtts/manifest.json"
        container_out = f"/models/{sp}_xtts"
        _set_job(sp, status="synthesizing", message=f"Generando prueba en: {lang_labels}…", progress_pct=70)
        result = _docker_run(
            [
                "clone-test",
                "--manifest",
                container_manifest,
                "--out-dir",
                container_out,
                "--language",
                lang,
                "--languages",
                ",".join(langs),
            ],
            timeout=3600,
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "clone-test failed")
        _set_job(
            sp,
            status="ready",
            message=f"✓ Voz clonada ({lang_labels}). Pulsa «Activar en Ralphi IA».",
            progress_pct=100,
            active=False,
            voice_id=f"xtts:{sp}",
            language=lang,
            output_languages=langs,
        )
        logger.info("Clone ready for %s lang=%s", sp, lang)
    except Exception as exc:
        logger.exception("Clone failed for %s", sp)
        err = str(exc)
        if "pip" in err or "3.14" in err or "No matching distribution" in err:
            err = (
                "XTTS requiere Docker (Python 3.14 no soporta Coqui TTS). "
                "Ejecuta en el servidor: bash ~/projects/ralfiia-amd-standby/scripts/setup_xtts_docker.sh"
            )
        _set_job(sp, status="error", message=err[:600], progress_pct=0, language=lang)


def activate_speaker(speaker: str) -> dict[str, Any]:
    sp = _safe_speaker(speaker)
    job = _load_jobs().get(sp, {})
    if job.get("status") != "ready" or not _manifest_path(sp).is_file():
        return {"ok": False, "error": "clone_not_ready", **clone_status(sp)}
    with _jobs_lock:
        jobs = _load_jobs()
        for other, other_job in jobs.items():
            if other != sp and other_job.get("active"):
                other_job["active"] = False
        jobs.setdefault(sp, {})
        jobs[sp]["active"] = True
        jobs[sp]["status"] = "ready"
        jobs[sp]["message"] = "Voz activa en Ralphi IA (PWA y panel)."
        jobs[sp]["progress_pct"] = 100
        _save_jobs(jobs)
    return {"ok": True, **clone_status(sp)}


def start_clone(
    speaker: str,
    language: str = "es",
    output_languages: list[str] | None = None,
) -> dict[str, Any]:
    sp = _safe_speaker(speaker)
    lang = _safe_language(language)
    langs = _normalize_output_languages(lang, output_languages)
    st = clone_status(sp)
    if not st.get("ready_for_clone"):
        return {
            "ok": False,
            "error": "not_enough_samples",
            "detail": f"Necesitas al menos {st.get('min_samples')} muestras.",
        }
    if not docker_image_ready():
        return {
            "ok": False,
            "error": "docker_image_missing",
            "detail": (
                "Falta la imagen Docker XTTS. En el servidor AMD ejecuta:\n"
                "bash ~/projects/ralfiia-amd-standby/scripts/setup_xtts_docker.sh"
            ),
            **st,
        }
    job = _load_jobs().get(sp, {})
    if job.get("status") in ("preparing", "loading_model", "synthesizing", "queued"):
        return {"ok": True, "started": False, "message": "Clonación ya en curso…", **clone_status(sp)}
    lang_labels = ", ".join(SUPPORTED_LANGUAGES.get(l, l) for l in langs)
    _set_job(
        sp,
        status="queued",
        message=f"Cola de clonación — salida: {lang_labels}",
        progress_pct=5,
        active=False,
        language=lang,
        output_languages=langs,
    )
    t = threading.Thread(target=_run_clone_worker, args=(sp, lang, langs), daemon=True)
    t.start()
    return {
        "ok": True,
        "started": True,
        "message": f"Clonación iniciada ({lang_labels}). 5–15 min la primera vez.",
        **clone_status(sp),
    }


def list_cloned_voices() -> list[dict[str, str]]:
    voices: list[dict[str, str]] = []
    for sp, job in _load_jobs().items():
        if job.get("status") == "ready" and _manifest_path(sp).is_file():
            lang = job.get("language") or "es"
            label = SPEAKER_LABELS.get(sp, sp.title())
            voices.append(
                {
                    "id": f"xtts:{sp}",
                    "label": f"{label} (clonada · {SUPPORTED_LANGUAGES.get(lang, lang)})",
                    "provider": "xtts-v2",
                    "speaker": sp,
                    "language": lang,
                }
            )
    return voices


def resolve_voice_id(voice: str | None) -> tuple[str | None, str | None]:
    if not voice:
        return None, None
    v = voice.strip()
    if v.startswith("xtts:"):
        return "xtts", _safe_speaker(v.split(":", 1)[1])
    return None, None
