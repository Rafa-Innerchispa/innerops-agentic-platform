"""Tests del pipeline de vídeo."""

from __future__ import annotations

from raphiia_openai.video_pipeline.pipeline import split_script


def test_split_script_paragraphs():
    script = "Primera escena.\n\nSegunda escena.\n\nTercera escena."
    parts = split_script(script, max_scenes=6)
    assert len(parts) == 3
    assert "Primera" in parts[0]


def test_split_script_sentences():
    script = "Uno. Dos. Tres. Cuatro."
    parts = split_script(script, max_scenes=4)
    assert len(parts) >= 2


def test_split_script_empty():
    assert split_script("") == []
