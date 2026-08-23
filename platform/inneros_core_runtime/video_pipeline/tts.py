"""Text-to-speech Video Studio — XTTS clonada (default) → Piper → espeak (solo fallback)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

PIPER_BIN = Path(os.getenv("PIPER_BIN", "/home/rlopez/data/piper/piper"))
PIPER_MODEL = Path(
    os.getenv(
        "PIPER_MODEL",
        "/home/rlopez/data/piper/voices/es_ES-sharvard-medium.onnx",
    )
)
PIPER_CONFIG = Path(
    os.getenv(
        "PIPER_CONFIG",
        "/home/rlopez/data/piper/voices/es_ES-sharvard-medium.onnx.json",
    )
)
PIPER_LENGTH_SCALE = float(os.getenv("PIPER_LENGTH_SCALE", "1.12"))
PIPER_NOISE_SCALE = float(os.getenv("PIPER_NOISE_SCALE", "0.72"))
PIPER_NOISE_W = float(os.getenv("PIPER_NOISE_W", "0.78"))
XTTS_CHUNK = int(os.getenv("VIDEO_XTTS_CHUNK_CHARS", "1800"))
XTTS_SENTENCE_MODE = os.getenv("XTTS_SENTENCE_MODE", "1").strip().lower() in ("1", "true", "yes")


def tts_health() -> dict[str, Any]:
    piper_ok = PIPER_BIN.is_file() and PIPER_MODEL.is_file()
    espeak_ok = shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None
    piper_py = model_exists = PIPER_MODEL.is_file()
    try:
        import piper  # noqa: F401

        piper_py = True
    except ImportError:
        piper_py = False

    xtts_ready = False
    xtts_voices: list[str] = []
    try:
        from raphiia_openai import voice_xtts

        xtts_ready = voice_xtts.docker_image_ready()
        xtts_voices = [v["id"] for v in voice_xtts.list_cloned_voices()]
    except Exception:
        pass

    return {
        "piper_ready": piper_ok,
        "piper_python": piper_py,
        "piper_model": str(PIPER_MODEL),
        "piper_bin": str(PIPER_BIN),
        "xtts_ready": xtts_ready,
        "xtts_voices": xtts_voices,
        "espeak_fallback": espeak_ok,
        "ready": xtts_ready or piper_ok or (piper_py and model_exists) or espeak_ok,
        "default_engine": "xtts-v2" if xtts_voices else ("piper" if (piper_ok or model_exists) else "espeak"),
    }


def prepare_speech_text(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(r"```[\s\S]*?```", " ", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"__([^_]+)__", r"\1", t)
    t = re.sub(r"_([^_]+)_", r"\1", t)
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*•·]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*\d+\.\s+", "", t, flags=re.M)
    t = t.replace("*", " ").replace("#", " ").replace("|", " ")
    t = t.replace('"', " ").replace("'", " ")
    t = re.sub(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF]+", " ", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _resolve_active_xtts(voice_id: str | None) -> tuple[str | None, str | None]:
    try:
        from raphiia_openai import voice_xtts

        kind, speaker = voice_xtts.resolve_voice_id(voice_id)
        if kind == "xtts" and speaker:
            return kind, speaker
        if not voice_id or voice_id in ("auto", "default"):
            for sp, job in voice_xtts._load_jobs().items():
                if job.get("status") == "ready" and job.get("active"):
                    return "xtts", sp
            for sp, job in voice_xtts._load_jobs().items():
                if job.get("status") == "ready":
                    return "xtts", sp
    except Exception:
        pass
    return None, None


def _synthesize_xtts(text: str, output_wav: Path, *, speaker: str, language: str | None) -> dict[str, Any]:
    from raphiia_openai import voice_xtts

    syn = voice_xtts.synthesize(text, output_wav, speaker=speaker, language=language)
    if syn.get("ok") and output_wav.is_file() and output_wav.stat().st_size > 100:
        return {
            "ok": True,
            "provider": "xtts-v2",
            "voice_id": f"xtts:{speaker}",
            "path": str(output_wav),
            "duration_sec": _wav_duration(output_wav),
            "language": syn.get("language"),
        }
    return {"ok": False, "error": syn.get("error") or "xtts_failed", "detail": syn}


def _synthesize_piper(text: str, output_wav: Path, *, voice: str | None) -> dict[str, Any]:
    model_path = Path(voice) if voice and voice not in ("espeak", "auto", "default") else PIPER_MODEL
    last_err = ""

    if PIPER_BIN.is_file() and model_path.is_file():
        cmd = [str(PIPER_BIN), "--model", str(model_path), "--output_file", str(output_wav)]
        if PIPER_CONFIG.is_file() and model_path == PIPER_MODEL:
            cmd.extend(["--config", str(PIPER_CONFIG)])
        proc = subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True, timeout=120, check=False)
        if proc.returncode == 0 and output_wav.is_file() and output_wav.stat().st_size > 0:
            return {"ok": True, "provider": "piper", "path": str(output_wav), "duration_sec": _wav_duration(output_wav)}

    if model_path.is_file():
        try:
            from piper import PiperVoice
            from piper.config import SynthesisConfig

            piper_voice = PiperVoice.load(
                str(model_path),
                config_path=str(PIPER_CONFIG) if PIPER_CONFIG.is_file() else None,
            )
            syn_config = SynthesisConfig(
                length_scale=PIPER_LENGTH_SCALE,
                noise_scale=PIPER_NOISE_SCALE,
                noise_w_scale=PIPER_NOISE_W,
            )
            with wave.open(str(output_wav), "wb") as wav_file:
                piper_voice.synthesize_wav(text, wav_file, syn_config=syn_config)
            if output_wav.is_file() and output_wav.stat().st_size > 0:
                return {
                    "ok": True,
                    "provider": "piper-tts",
                    "path": str(output_wav),
                    "duration_sec": _wav_duration(output_wav),
                }
        except Exception as exc:
            last_err = str(exc)

    return {"ok": False, "error": "piper_failed", "detail": last_err}


def _synthesize_espeak(text: str, output_wav: Path) -> dict[str, Any]:
    for cmd_base in (["espeak-ng", "-v", "es", "-s", "150"], ["espeak", "-v", "es", "-s", "150"]):
        if not shutil.which(cmd_base[0]):
            continue
        proc = subprocess.run(
            [*cmd_base, "-w", str(output_wav), text],
            capture_output=True,
            timeout=120,
            check=False,
        )
        if proc.returncode == 0 and output_wav.is_file():
            return {"ok": True, "provider": cmd_base[0], "path": str(output_wav), "duration_sec": _wav_duration(output_wav)}
    return {"ok": False, "error": "espeak_unavailable"}


def _concat_wavs(parts: list[Path], output_wav: Path, *, crossfade_ms: int = 80) -> dict[str, Any]:
    if not parts:
        return {"ok": False, "error": "no_wav_parts"}
    valid = [p for p in parts if p.is_file()]
    if not valid:
        return {"ok": False, "error": "no valid wav parts"}
    if len(valid) == 1:
        polished = _polish_wav(valid[0], output_wav)
        return polished

    fade = max(0.03, crossfade_ms / 1000.0)
    inputs: list[str] = []
    for p in valid:
        inputs.extend(["-i", str(p)])
    if len(valid) == 2:
        fc = f"[0:a][1:a]acrossfade=d={fade}:c1=tri:c2=tri[aout]"
    else:
        chain = f"[0:a][1:a]acrossfade=d={fade}:c1=tri:c2=tri[a01]"
        last = "a01"
        for i in range(2, len(valid)):
            nxt = f"a{i:02d}" if i < len(valid) - 1 else "aout"
            chain += f"; [{last}][{i}:a]acrossfade=d={fade}:c1=tri:c2=tri[{nxt}]"
            last = nxt
        fc = chain

    tmp = output_wav.with_suffix(".merged.wav")
    proc = subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[aout]", "-ar", "22050", "-ac", "1", str(tmp)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0 or not tmp.is_file():
        list_file = output_wav.with_suffix(".concat.txt")
        list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in valid) + "\n", encoding="utf-8")
        proc2 = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-ar", "22050", "-ac", "1", str(tmp)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        list_file.unlink(missing_ok=True)
        if proc2.returncode != 0 or not tmp.is_file():
            return {"ok": False, "error": (proc.stderr or proc2.stderr or "wav merge failed")[-400:]}
    return _polish_wav(tmp, output_wav)


def _polish_wav(src: Path, dest: Path) -> dict[str, Any]:
    """Normaliza, reduce clicks/ruido y suaviza inicio/fin."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    target = dest.with_suffix(".polish.tmp.wav") if src.resolve() == dest.resolve() else dest
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-af",
            "highpass=f=80,compand=attacks=0.1:decays=0.4:points=-80/-80|-20/-15|0/-5,alimiter=limit=0.95,afade=t=in:st=0:d=0.03,areverse,afade=t=in:st=0:d=0.03,areverse",
            "-ar",
            "22050",
            "-ac",
            "1",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if src != dest and src.is_file() and src.name.endswith(".merged.wav"):
        src.unlink(missing_ok=True)
    if proc.returncode != 0 or not target.is_file():
        if src.is_file() and src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        elif src.is_file():
            return {"ok": True, "path": str(src), "duration_sec": _wav_duration(src), "warning": "polish_skipped"}
        return {"ok": False, "error": (proc.stderr or "polish failed")[-400:]}
    if target.resolve() != dest.resolve():
        target.replace(dest)
    return {"ok": True, "path": str(dest), "duration_sec": _wav_duration(dest)}


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    return parts if parts else [text]


def _silence_wav(path: Path, *, duration_ms: int = 120, sample_rate: int = 22050) -> None:
    import wave

    frames = int(sample_rate * duration_ms / 1000)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * frames)


def _merge_with_pauses(parts: list[Path], output_wav: Path, *, pause_ms: int = 130) -> dict[str, Any]:
    if not parts:
        return {"ok": False, "error": "no parts"}
    if len(parts) == 1:
        return _polish_wav(parts[0], output_wav)
    work = output_wav.parent / "_tts_merge"
    work.mkdir(parents=True, exist_ok=True)
    silence = work / "silence.wav"
    _silence_wav(silence, duration_ms=pause_ms)
    expanded: list[Path] = []
    for i, p in enumerate(parts):
        expanded.append(p)
        if i < len(parts) - 1:
            expanded.append(silence)
    return _concat_wavs(expanded, output_wav, crossfade_ms=40)


def _split_for_xtts(text: str, max_chars: int = XTTS_CHUNK) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    buf = ""
    for part in parts:
        if len(part) > max_chars:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            for i in range(0, len(part), max_chars):
                chunks.append(part[i : i + max_chars].strip())
            continue
        candidate = f"{buf} {part}".strip() if buf else part
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                chunks.append(buf.strip())
            buf = part
    if buf:
        chunks.append(buf.strip())
    return [c for c in chunks if c]


def synthesize(
    text: str,
    output_wav: Path,
    *,
    voice: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    text = prepare_speech_text(text)
    if not text:
        return {"ok": False, "error": "empty text"}
    output_wav.parent.mkdir(parents=True, exist_ok=True)

    if voice == "espeak":
        return _synthesize_espeak(text, output_wav)

    kind, speaker = _resolve_active_xtts(voice if voice not in ("auto", "default") else None)
    if kind == "xtts" and speaker:
        if XTTS_SENTENCE_MODE:
            sentences = _split_sentences(text)
            if len(sentences) > 1 and all(len(s) < 400 for s in sentences):
                work = output_wav.parent / "_tts_sentences"
                work.mkdir(parents=True, exist_ok=True)
                parts: list[Path] = []
                for i, sent in enumerate(sentences):
                    part = work / f"sent_{i:03d}.wav"
                    step = _synthesize_xtts(sent, part, speaker=speaker, language=language)
                    if not step.get("ok"):
                        return step
                    parts.append(part)
                merged = _merge_with_pauses(parts, output_wav)
                if merged.get("ok"):
                    merged["provider"] = "xtts-v2"
                    merged["voice_id"] = f"xtts:{speaker}"
                    merged["mode"] = "sentence"
                    merged["sentences"] = len(sentences)
                return merged

        chunks = _split_for_xtts(text)
        if len(chunks) == 1:
            result = _synthesize_xtts(chunks[0], output_wav, speaker=speaker, language=language)
            if result.get("ok"):
                _polish_wav(output_wav, output_wav)
            return result
        part_paths: list[Path] = []
        work = output_wav.parent / "_tts_parts"
        work.mkdir(parents=True, exist_ok=True)
        for i, chunk in enumerate(chunks):
            part = work / f"part_{i:03d}.wav"
            step = _synthesize_xtts(chunk, part, speaker=speaker, language=language)
            if not step.get("ok"):
                return step
            part_paths.append(part)
        merged = _concat_wavs(part_paths, output_wav)
        if merged.get("ok"):
            merged["provider"] = "xtts-v2"
            merged["voice_id"] = f"xtts:{speaker}"
            merged["chunks"] = len(chunks)
        return merged

    piper_voice = voice if voice and Path(voice).is_file() else None
    result = _synthesize_piper(text, output_wav, voice=piper_voice)
    if result.get("ok"):
        return result

    health = tts_health()
    if health.get("espeak_fallback"):
        espeak = _synthesize_espeak(text, output_wav)
        if espeak.get("ok"):
            espeak["warning"] = "fallback_espeak_robotic"
            return espeak

    return {"ok": False, "error": "no TTS engine available", "health": health, "detail": result.get("detail")}


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())
    except Exception:
        return 0.0
