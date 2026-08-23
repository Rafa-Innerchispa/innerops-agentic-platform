"""Montaje ffmpeg — imágenes Ken Burns + audio + subtítulos → MP4."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


def _run(cmd: list[str], *, timeout: float = 600.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def probe_duration(path: Path) -> float:
    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        timeout=30,
    )
    if proc.returncode != 0:
        return 0.0
    try:
        data = json.loads(proc.stdout or "{}")
        return float(data.get("format", {}).get("duration", 0) or 0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def image_to_clip(
    image: Path,
    output: Path,
    *,
    duration_sec: float,
    width: int,
    height: int,
    fps: int = 30,
) -> dict[str, Any]:
    if not image.is_file():
        return {"ok": False, "error": f"image missing: {image}"}
    output.parent.mkdir(parents=True, exist_ok=True)
    dur = max(1.5, float(duration_sec))
    frames = max(int(dur * fps), fps * 2)
    # Ken Burns suave — evita slideshow estático sin temblor agresivo.
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},"
        f"zoompan=z='min(zoom+0.00045,1.07)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={width}x{height}:fps={fps},"
        f"eq=contrast=1.08:brightness=0.015:saturation=1.12:gamma=1.02,format=yuv420p"
    )
    proc = _run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(image),
            "-vf",
            vf,
            "-t",
            str(dur),
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "14",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output),
        ],
        timeout=max(120, dur * 10),
    )
    if proc.returncode != 0 or not output.is_file():
        return {"ok": False, "error": (proc.stderr or proc.stdout or "ffmpeg failed")[-500:]}
    return {"ok": True, "path": str(output), "duration_sec": dur}


def concat_clips(clips: list[Path], output: Path, *, transition: str = "none", fps: int = 30) -> dict[str, Any]:
    if not clips:
        return {"ok": False, "error": "no clips"}
    output.parent.mkdir(parents=True, exist_ok=True)
    valid = [c for c in clips if c.is_file()]
    if not valid:
        return {"ok": False, "error": "no valid clips"}

    if transition in ("fade", "smooth") and len(valid) >= 2:
        xfade_type = "dissolve" if transition == "smooth" else "fade"
        return _concat_xfade(valid, output, fps=fps, fade_sec=0.55 if transition == "smooth" else 0.85, xfade=xfade_type)

    list_file = output.with_suffix(".txt")
    lines = [f"file '{c.resolve()}'" for c in valid]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = _run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output)],
        timeout=300,
    )
    list_file.unlink(missing_ok=True)
    if proc.returncode != 0 or not output.is_file():
        return {"ok": False, "error": (proc.stderr or "concat failed")[-500:]}
    return {"ok": True, "path": str(output)}


def _concat_xfade(
    clips: list[Path],
    output: Path,
    *,
    fps: int = 30,
    fade_sec: float = 0.55,
    xfade: str = "dissolve",
) -> dict[str, Any]:
    """Crossfade fluido entre escenas (dissolve/fade sin flash negro)."""
    if len(clips) < 2:
        return concat_clips(clips, output)
    durs = [max(probe_duration(c), 2.0) for c in clips]
    fade = min(fade_sec, min(durs) / 4)
    inputs: list[str] = []
    for c in clips:
        inputs.extend(["-i", str(c)])
    parts: list[str] = []
    offset = durs[0] - fade
    parts.append(f"[0:v][1:v]xfade=transition={xfade}:duration={fade}:offset={offset}[v01]")
    last = "v01"
    for i in range(2, len(clips)):
        offset += durs[i - 1] - fade
        nxt = f"v{i:02d}"
        parts.append(f"[{last}][{i}:v]xfade=transition={xfade}:duration={fade}:offset={offset}[{nxt}]")
        last = nxt
    fc = ";".join(parts)
    proc = _run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", f"[{last}]", "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p", str(output)],
        timeout=900,
    )
    if proc.returncode != 0 or not output.is_file():
        return concat_clips(clips, output, transition="none")
    return {"ok": True, "path": str(output), "transition": "fade"}


def mux_audio_video(
    video: Path,
    audio: Path,
    output: Path,
    *,
    srt: Path | None = None,
    subtitles: Path | None = None,
) -> dict[str, Any]:
    if not video.is_file() or not audio.is_file():
        return {"ok": False, "error": "video or audio missing"}
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(video), "-i", str(audio)]
    sub = subtitles if subtitles and subtitles.is_file() else srt
    if sub and sub.is_file():
        sub_path = str(sub.resolve()).replace(":", "\\:")
        cmd += ["-vf", f"ass={sub_path}"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "15",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output),
    ]
    proc = _run(cmd, timeout=600)
    if proc.returncode != 0 or not output.is_file():
        return {"ok": False, "error": (proc.stderr or "mux failed")[-500:]}
    return {"ok": True, "path": str(output), "duration_sec": probe_duration(output)}


def build_slideshow_video(
    images: list[Path],
    audio: Path,
    output: Path,
    *,
    aspect: str = "9:16",
    scene_durations: list[float] | None = None,
    srt: Path | None = None,
    subtitles: Path | None = None,
    work_dir: Path | None = None,
    transition: str = "none",
) -> dict[str, Any]:
    if not images:
        return {"ok": False, "error": "no images"}
    w, h = ASPECT_PRESETS.get(aspect, ASPECT_PRESETS["9:16"])
    work = work_dir or output.parent / "_work"
    work.mkdir(parents=True, exist_ok=True)

    audio_dur = probe_duration(audio) or max(len(images) * 4.0, 10.0)
    per_scene = scene_durations or []
    if not per_scene:
        per_scene = [max(2.5, audio_dur / len(images))] * len(images)

    clips: list[Path] = []
    for idx, (img, dur) in enumerate(zip(images, per_scene, strict=False)):
        clip_path = work / f"scene_{idx:03d}.mp4"
        step = image_to_clip(img, clip_path, duration_sec=dur, width=w, height=h)
        if not step.get("ok"):
            return step
        clips.append(clip_path)

    silent = work / "silent.mp4"
    cat = concat_clips(clips, silent, transition=transition)
    if not cat.get("ok"):
        return cat

    mux = mux_audio_video(silent, audio, output, srt=srt, subtitles=subtitles)
    if not mux.get("ok"):
        return mux

    return {
        "ok": True,
        "path": str(output),
        "duration_sec": mux.get("duration_sec"),
        "aspect": aspect,
        "resolution": f"{w}x{h}",
        "scenes": len(clips),
    }
