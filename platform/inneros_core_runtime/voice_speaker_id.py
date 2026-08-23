"""Identificación de hablante local (Resemblyzer) — Rafael, Héctor, Eliu."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

VOICE_SAMPLES_ROOT = Path(os.getenv("VOICE_SAMPLES_ROOT", "/home/rlopez/data/ralfia/voice_samples"))
PROFILES_PATH = Path(
    os.getenv("SPEAKER_PROFILES_PATH", "/home/rlopez/data/ralfia/voice_models/speaker_profiles.json")
)
MIN_SAMPLES = int(os.getenv("VOICE_SPEAKER_ID_MIN_SAMPLES", "3"))
THRESHOLD = float(os.getenv("SPEAKER_ID_THRESHOLD", "0.72"))
AUDIO_EXTS = {".wav", ".webm", ".mp3", ".m4a", ".ogg"}

SPEAKER_LABELS: dict[str, str] = {
    "rafael": "Rafael",
    "hector": "Héctor",
    "eliu": "Eliu",
    "rafagye": "Rafael",
}

_encoder = None
_backend: str | None = None


class SpeakerIdUnavailable(Exception):
    pass


def _embed_file_librosa(path: Path) -> np.ndarray:
    import librosa

    y, sr = librosa.load(str(path), sr=16000, mono=True, duration=30)
    if y.size < 1600:
        raise ValueError("audio_demasiado_corto")
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
    delta = librosa.feature.delta(mfcc)
    feat = np.concatenate([mfcc.mean(axis=1), delta.mean(axis=1), mfcc.std(axis=1)])
    return (feat / (np.linalg.norm(feat) + 1e-9)).astype(np.float32)


def _init_backend() -> str:
    global _backend, _encoder
    if _backend:
        return _backend
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav  # noqa: F401

        _encoder = VoiceEncoder()
        _backend = "resemblyzer"
        logger.info("Speaker ID backend: resemblyzer")
    except Exception as exc:
        logger.warning("Resemblyzer no disponible (%s) — usando librosa MFCC", exc)
        try:
            import librosa  # noqa: F401

            _backend = "librosa"
            logger.info("Speaker ID backend: librosa")
        except ImportError as lib_exc:
            raise SpeakerIdUnavailable("Instala librosa o resemblyzer") from lib_exc
    return _backend


def _require_resemblyzer():
    _init_backend()


def _get_encoder():
    _init_backend()
    if _backend != "resemblyzer":
        return None
    return _encoder


def speaker_label(speaker_id: str | None) -> str:
    if not speaker_id:
        return "Desconocido"
    return SPEAKER_LABELS.get(speaker_id.lower(), speaker_id.title())


def _ffmpeg_to_wav16(path: Path) -> Path:
    out = path.with_name(path.stem + "._16k.wav")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-ar", "16000", "-ac", "1", "-f", "wav", str(out)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-400:] if proc.stderr else "ffmpeg failed")
    return out


def _bytes_to_wav_path(raw: bytes, mime: str) -> Path:
    ext = ".webm" if "webm" in (mime or "").lower() else ".wav"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(raw)
        inp = Path(f.name)
    try:
        if ext == ".wav":
            return _ffmpeg_to_wav16(inp)
        return _ffmpeg_to_wav16(inp)
    finally:
        inp.unlink(missing_ok=True)


def _embed_file(path: Path) -> np.ndarray:
    backend = _init_backend()
    if backend == "resemblyzer":
        from resemblyzer import preprocess_wav

        encoder = _get_encoder()
        wav = preprocess_wav(path)
        return encoder.embed_utterance(wav)
    wav16 = path if path.suffix == ".wav" and "_16k" in path.name else _ffmpeg_to_wav16(path)
    try:
        return _embed_file_librosa(wav16)
    finally:
        if wav16 != path:
            wav16.unlink(missing_ok=True)


def _embed_bytes(raw: bytes, mime: str = "audio/webm") -> np.ndarray:
    wav_path = _bytes_to_wav_path(raw, mime)
    try:
        return _embed_file(wav_path)
    finally:
        wav_path.unlink(missing_ok=True)


def _list_sample_files(speaker_dir: Path) -> list[Path]:
    if not speaker_dir.is_dir():
        return []
    return sorted(p for p in speaker_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS)


def rebuild_profiles() -> dict[str, Any]:
    """Recalcula embeddings por carpeta en voice_samples/."""
    _init_backend()
    profiles: dict[str, Any] = {}
    warnings: list[str] = []
    merged: dict[str, list[np.ndarray]] = {}

    if not VOICE_SAMPLES_ROOT.is_dir():
        return {"ok": False, "error": "samples_root_missing", "speakers": {}}

    for speaker_dir in sorted(VOICE_SAMPLES_ROOT.iterdir()):
        if not speaker_dir.is_dir():
            continue
        raw_name = speaker_dir.name.lower()
        canonical = "rafael" if raw_name == "rafagye" else raw_name
        files = _list_sample_files(speaker_dir)
        if len(files) < MIN_SAMPLES:
            warnings.append(f"{canonical}: {len(files)}/{MIN_SAMPLES} muestras (insuficiente)")
            continue
        for f in files:
            try:
                if f.suffix.lower() == ".wav":
                    emb = _embed_file(_ffmpeg_to_wav16(f))
                else:
                    emb = _embed_bytes(f.read_bytes(), "audio/webm")
                merged.setdefault(canonical, []).append(emb)
            except Exception as exc:
                warnings.append(f"{canonical}/{f.name}: {exc}")

    for sp, embeds in merged.items():
        if len(embeds) < MIN_SAMPLES:
            warnings.append(f"{sp}: solo {len(embeds)} embeddings válidos")
            continue
        arr = np.mean(np.stack(embeds), axis=0)
        arr = arr / (np.linalg.norm(arr) + 1e-9)
        profiles[sp] = {
            "label": speaker_label(sp),
            "sample_count": len(embeds),
            "embedding": arr.tolist(),
        }

    payload: dict[str, Any] = {
        "ok": bool(profiles),
        "speakers": profiles,
        "threshold": THRESHOLD,
        "min_samples": MIN_SAMPLES,
        "warnings": warnings,
    }
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Speaker profiles: %s", list(profiles.keys()))
    return payload


def load_profiles() -> dict[str, Any]:
    if not PROFILES_PATH.is_file():
        return {"ok": False, "speakers": {}, "error": "no_profiles"}
    try:
        return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "speakers": {}, "error": str(exc)}


def identify(raw: bytes, mime: str = "audio/webm") -> dict[str, Any]:
    data = load_profiles()
    speakers: dict[str, Any] = data.get("speakers") or {}
    if not speakers:
        return {"ok": False, "available": False, "error": "no_profiles", "matched": False}
    try:
        emb = _embed_bytes(raw, mime)
    except SpeakerIdUnavailable as exc:
        return {"ok": False, "available": False, "error": str(exc), "matched": False}
    except Exception as exc:
        return {"ok": False, "available": True, "error": str(exc), "matched": False}

    scores: dict[str, float] = {}
    best_sp: str | None = None
    best_score = -1.0
    for sp, info in speakers.items():
        ref = np.array(info["embedding"], dtype=np.float32)
        score = float(np.dot(emb, ref) / (np.linalg.norm(emb) * np.linalg.norm(ref) + 1e-9))
        scores[sp] = round(score, 4)
        if score > best_score:
            best_score = score
            best_sp = sp

    threshold = float(data.get("threshold") or THRESHOLD)
    matched = best_score >= threshold
    return {
        "ok": True,
        "available": True,
        "speaker": best_sp if matched else None,
        "speaker_label": speaker_label(best_sp) if matched else "Desconocido",
        "confidence": round(best_score, 4),
        "threshold": threshold,
        "matched": matched,
        "scores": scores,
    }


def status() -> dict[str, Any]:
    lib_ok = False
    lib_error = None
    backend = None
    try:
        backend = _init_backend()
        lib_ok = True
    except SpeakerIdUnavailable as exc:
        lib_error = str(exc)

    data = load_profiles()
    speakers = data.get("speakers") or {}
    sample_counts: dict[str, int] = {}
    if VOICE_SAMPLES_ROOT.is_dir():
        for d in VOICE_SAMPLES_ROOT.iterdir():
            if d.is_dir():
                name = "rafael" if d.name.lower() == "rafagye" else d.name.lower()
                sample_counts[name] = sample_counts.get(name, 0) + len(_list_sample_files(d))

    return {
        "ok": True,
        "library_ok": lib_ok,
        "library_error": lib_error,
        "backend": backend,
        "available": bool(speakers) and lib_ok,
        "enrolled": {sp: info.get("sample_count", 0) for sp, info in speakers.items()},
        "sample_counts": sample_counts,
        "threshold": data.get("threshold", THRESHOLD),
        "min_samples": MIN_SAMPLES,
        "profiles_path": str(PROFILES_PATH),
    }


def maybe_auto_calibrate(speaker: str) -> dict[str, Any] | None:
    """Recalibra si la persona alcanza MIN_SAMPLES."""
    sp = speaker.lower()
    if sp == "rafagye":
        sp = "rafael"
    folder = VOICE_SAMPLES_ROOT / sp
    if not folder.is_dir() and sp == "rafael":
        folder = VOICE_SAMPLES_ROOT / "rafagye"
    if len(_list_sample_files(folder)) >= MIN_SAMPLES:
        try:
            return rebuild_profiles()
        except Exception as exc:
            logger.warning("Auto-calibrate failed: %s", exc)
    return None
