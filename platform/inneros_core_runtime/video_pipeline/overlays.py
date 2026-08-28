"""Overlays — QR, logo, texto (local, sin cloud)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def generate_qr_png(data: str, output: Path, *, size: int = 320) -> dict[str, Any]:
    text = (data or "").strip()
    if not text:
        return {"ok": False, "error": "empty_qr_data"}
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        import qrcode

        qr = qrcode.QRCode(box_size=8, border=2)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img = img.resize((size, size))
        img.save(output)
        return {"ok": True, "path": str(output), "provider": "qrcode"}
    except ImportError:
        pass

    if _which("qrencode"):
        proc = subprocess.run(
            ["qrencode", "-o", str(output), "-s", "8", text],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode == 0 and output.is_file():
            return {"ok": True, "path": str(output), "provider": "qrencode"}

    try:
        from PIL import Image, ImageDraw

        output.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (size, size), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, size - 10, size - 10], outline="black", width=3)
        draw.text((20, size // 2 - 10), "QR", fill="black")
        img.save(output)
        return {"ok": True, "path": str(output), "provider": "placeholder_qr", "warning": "install qrcode for real QR"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def overlay_image_on_video(
    video: Path,
    overlay: Path,
    output: Path,
    *,
    position: str = "bottom_right",
    margin: int = 40,
    scale: float = 0.18,
) -> dict[str, Any]:
    if not video.is_file() or not overlay.is_file():
        return {"ok": False, "error": "missing video or overlay"}
    output.parent.mkdir(parents=True, exist_ok=True)

    pos_map = {
        "bottom_right": f"W-w-{margin}:H-h-{margin}",
        "bottom_left": f"{margin}:H-h-{margin}",
        "top_right": f"W-w-{margin}:{margin}",
        "top_left": f"{margin}:{margin}",
    }
    xy = pos_map.get(position, pos_map["bottom_right"])
    vf = f"[1:v]scale=iw*{scale}:-1[ov];[0:v][ov]overlay={xy}"

    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-i", str(overlay), "-filter_complex", vf, "-c:a", "copy", str(output)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if proc.returncode != 0 or not output.is_file():
        return {"ok": False, "error": (proc.stderr or "overlay failed")[-500:]}
    return {"ok": True, "path": str(output)}


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)
