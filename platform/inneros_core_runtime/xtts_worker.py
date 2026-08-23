#!/usr/bin/env python3
"""Worker XTTS-v2 — ejecutar dentro del contenedor Docker (Python 3.11)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _resolve_reference_wavs(manifest_path: Path, refs: list[str]) -> list[str]:
    """Resuelve rutas de refs: acepta paths del host, del contenedor o solo nombre."""
    manifest_dir = manifest_path.parent
    resolved: list[str] = []
    for ref in refs:
        p = Path(ref)
        if p.is_file():
            resolved.append(str(p))
            continue
        by_name = manifest_dir / "refs" / p.name
        if by_name.is_file():
            resolved.append(str(by_name))
            continue
        if ref.startswith("/models/"):
            container = Path(ref)
            if container.is_file():
                resolved.append(str(container))
                continue
        parts = p.parts
        if "voice_models" in parts:
            idx = parts.index("voice_models")
            container = Path("/models") / Path(*parts[idx + 1 :])
            if container.is_file():
                resolved.append(str(container))
                continue
        print(json.dumps({"ok": False, "error": f"ref_not_found: {ref}"}))
        return []
    return resolved


def _patch_torch_load() -> None:
    """PyTorch >=2.6 exige weights_only=True; checkpoints XTTS requieren False."""
    try:
        import torch

        _orig = torch.load

        def _load(*args, **kwargs):
            if "weights_only" not in kwargs:
                kwargs["weights_only"] = False
            return _orig(*args, **kwargs)

        torch.load = _load  # type: ignore[assignment]
    except Exception:
        pass


def _patch_transformers() -> None:
    """Compatibilidad TTS 0.22 con transformers recientes."""
    try:
        import transformers
        from transformers.generation import BeamSearchScorer

        if not hasattr(transformers, "BeamSearchScorer"):
            transformers.BeamSearchScorer = BeamSearchScorer  # type: ignore[attr-defined]
    except ImportError:
        pass


def cmd_synthesize(args: argparse.Namespace, *, tts=None) -> int:
    _patch_torch_load()
    _patch_transformers()
    from TTS.api import TTS

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    refs = _resolve_reference_wavs(manifest_path, manifest.get("reference_wavs") or [])
    if not refs:
        return 1
    lang = args.language or manifest.get("default_language") or "es"
    if tts is None:
        device = "cuda" if args.gpu else "cpu"
        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tts.tts_to_file(
        text=args.text,
        file_path=str(out),
        speaker_wav=refs[:4],
        language=lang,
        split_sentences=True,
        speed=1.0,
    )
    print(json.dumps({"ok": True, "path": str(out), "language": lang}))
    return 0


def cmd_clone_test(args: argparse.Namespace) -> int:
    phrases = {
        "es": "Hola, soy Rafael. Esta es mi voz clonada en español.",
        "en": "Hello, this is my cloned voice in English.",
        "de": "Hallo, das ist meine geklonte Stimme auf Deutsch.",
        "fr": "Bonjour, ceci est ma voix clonée en français.",
        "it": "Ciao, questa è la mia voce clonata in italiano.",
        "pt": "Olá, esta é a minha voz clonada em português.",
    }
    primary = args.language or "es"
    if args.languages:
        langs = [l.strip() for l in args.languages.split(",") if l.strip()]
    else:
        langs = [primary]
    if not langs:
        langs = [primary]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _patch_torch_load()
    _patch_transformers()
    from TTS.api import TTS

    device = "cuda" if args.gpu else "cpu"
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

    for lang in langs:
        out = out_dir / f"test_{lang}.wav"
        ns = argparse.Namespace(
            manifest=args.manifest,
            text=phrases.get(lang, phrases.get("en", phrases["es"])),
            output=str(out),
            language=lang,
            gpu=args.gpu,
        )
        rc = cmd_synthesize(ns, tts=tts)
        if rc != 0:
            return rc
    print(json.dumps({"ok": True, "languages": langs, "primary": primary}))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("synthesize")
    s.add_argument("--manifest", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--output", required=True)
    s.add_argument("--language", default="es")
    s.add_argument("--gpu", action="store_true")

    t = sub.add_parser("clone-test")
    t.add_argument("--manifest", required=True)
    t.add_argument("--out-dir", required=True)
    t.add_argument("--language", default="es")
    t.add_argument("--languages", default="", help="Idiomas de salida separados por coma (ej. es,en)")
    t.add_argument("--gpu", action="store_true")

    args = p.parse_args()
    if args.cmd == "synthesize":
        return cmd_synthesize(args)
    if args.cmd == "clone-test":
        return cmd_clone_test(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
