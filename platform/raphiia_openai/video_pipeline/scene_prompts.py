"""Prompts visuales — fotorrealismo 2026, cinematográfico, sin look vintage."""

from __future__ import annotations

import re

MODERN_QUALITY = (
    " 2026 contemporary commercial cinematography, crisp digital clarity, high dynamic range, "
    "clean modern color grading, sharp focus, premium advertising production, "
    "NOT vintage, NOT retro, NOT film grain, NOT sepia, NOT washed out, NOT amateur snapshot."
)

NO_TEXT = (
    " Absolutely no text, letters, words, typography, watermark, logo, captions, signs, labels."
)

NO_FACE = (
    " No visible faces, no eyes toward camera, no close-up portraits, no facial details. "
    "People only as distant silhouettes, over-shoulder, or back view far from camera."
)

BLUEPRINTS_16_9: list[str] = [
    (
        "Ultra photorealistic wide 16:9 IMAX documentary still, state-of-the-art 2026 AI operations center "
        "at golden hour, floor-to-ceiling glass, rows of brand-new black server racks with cyan LED strips, "
        "AMD Radeon GPU servers with active cooling, curved ultrawide monitors showing soft abstract blue "
        "data glow (completely unreadable), polished reflective floor, volumetric god rays, "
        "shot on ARRI Alexa 65, 35mm T1.5, National Geographic production quality"
    ),
    (
        "Photorealistic 16:9 corporate wide shot, modern open-plan tech headquarters in Guayaquil Ecuador, "
        "two professionals as distant silhouettes near floor-to-ceiling windows (backs to camera), "
        "minimalist white desks, ultrawide monitors with blurred colorful bokeh only, "
        "through glass wall a pristine new datacenter aisle with Supermicro racks and green status LEDs, "
        "warm natural light, Canon EOS R5, authentic Fortune 500 photography"
    ),
    (
        "Cinematic photorealistic 16:9 establishing shot, futuristic Tier-4 datacenter cold aisle, "
        "technician silhouette walking away from camera between pristine server racks, "
        "AMD EPYC and GPU nodes with blue purple ambient LED, spotless raised floor, "
        "subtle lens flare, hyperrealistic infrastructure, BBC Planet Earth production values"
    ),
    (
        "Wide 16:9 premium tech lifestyle photo, boutique private cloud suite with designer furniture, "
        "open server rack with organized cabling and soft LED, ring light glow, "
        "laptop on desk showing abstract blurred screen colors, indoor plants, "
        "Architectural Digest meets Wired magazine editorial, natural authentic lighting"
    ),
    (
        "Cinematic 16:9 drone-style exterior, modern glass tech campus at blue hour, "
        "city lights bokeh, clean architecture, professional corporate film still, Sony Venice look"
    ),
    (
        "Photorealistic 16:9 close detail shot, premium workstation dual monitors, "
        "mechanical keyboard, shallow depth of field, warm desk lamp, productivity aesthetic, "
        "Apple commercial lighting quality"
    ),
]

BLUEPRINTS_9_16: list[str] = [
    (
        "Vertical 9:16 ultra photorealistic 2026 tech commercial, modern glass office at sunrise, "
        "Guayaquil skyline soft bokeh through window, minimalist desk with ultrawide monitor "
        "showing abstract blue UI glow only, premium lifestyle tech photography, Sony A7R V, f/2.8"
    ),
    (
        "Vertical 9:16 cinematic datacenter portrait, pristine server aisle, cyan and amber LED accents, "
        "worker silhouette tiny in background back turned, volumetric haze, ARRI Alexa look, "
        "hyperreal infrastructure, NOT old, NOT gritty"
    ),
    (
        "Vertical 9:16 dramatic low angle GPU compute rack, AMD Radeon servers, "
        "clean cable management, purple blue ambient light, premium B-roll for tech documentary"
    ),
    (
        "Vertical 9:16 modern coworking space, natural daylight, plants and white walls, "
        "laptop and coffee on marble table, shallow depth of field, Instagram Reels commercial quality"
    ),
    (
        "Vertical 9:16 night city exterior, contemporary building with subtle tech company lighting, "
        "wet pavement reflections, cinematic teal orange grade, NOT vintage film"
    ),
    (
        "Vertical 9:16 over-shoulder silhouette at standing desk, no face, "
        "multiple monitors with colorful abstract bokeh, ring light rim, content creator studio premium setup"
    ),
    (
        "Vertical 9:16 macro detail, fiber optic cables and network switch LEDs, "
        "extreme sharpness, product photography lighting, high-end IT infrastructure"
    ),
    (
        "Vertical 9:16 aerial-style interior wide, open plan innovation lab, "
        "robotics and server pods in background blur, bright optimistic 2026 futurism"
    ),
]

THEME_BOOST: list[tuple[str, str]] = [
    (r"correo|email|whatsapp", "communication technology mood via soft device glow"),
    (r"cotiz|factur|negocio", "enterprise business analytics atmosphere on blurred screens"),
    (r"redes|instagram|youtube|contenido", "content creator studio ring light setup"),
    (r"local|servidor|gpu|hardware", "cutting-edge on-premise AMD GPU infrastructure emphasis"),
    (r"ia|inteligencia|ralfia|automat", "subtle neural light trails and holographic UI accents in environment"),
    (r"ecuador|guayaquil|quito", "Latin American modern tech hub atmosphere, warm daylight"),
    (r"cliente|proyecto|visita", "professional field service and enterprise workflow mood"),
]


def _theme_boost(scene_text: str, title: str) -> str:
    blob = f"{title} {scene_text}".lower()
    hits = [extra for pat, extra in THEME_BOOST if re.search(pat, blob, re.I)]
    return ". ".join(hits[:2])


def visual_prompt_for_scene(
    scene_text: str,
    *,
    title: str = "",
    entity: str = "",
    scene_index: int = 0,
    aspect: str = "9:16",
    total_scenes: int = 1,
) -> str:
    blueprints = BLUEPRINTS_16_9 if aspect == "16:9" else BLUEPRINTS_9_16
    base = blueprints[scene_index % len(blueprints)]
    boost = _theme_boost(scene_text, title)
    aspect_hint = "Horizontal 16:9 widescreen cinematic." if aspect == "16:9" else "Vertical 9:16 mobile cinematic Reels."
    scene_mood = scene_text[:120].replace("\n", " ")
    return f"{base}. Scene mood: {scene_mood}. {boost}. {aspect_hint}{MODERN_QUALITY}{NO_FACE}{NO_TEXT}"
