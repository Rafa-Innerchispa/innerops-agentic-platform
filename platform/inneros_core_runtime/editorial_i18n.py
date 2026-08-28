"""Idiomas panel editorial + publicación LinkedIn."""

from __future__ import annotations

# Idiomas publicación (traducción Ollama)
PUBLICATION_LANGUAGES: dict[str, str] = {
    "es": "Español",
    "en": "English",
    "hi": "हिन्दी (Hindi)",
    "pt": "Português",
    "fr": "Français",
    "de": "Deutsch",
    "zh": "中文 (Chinese)",
    "ja": "日本語 (Japanese)",
    "ar": "العربية (Arabic)",
    "it": "Italiano",
    "ko": "한국어 (Korean)",
    "ru": "Русский (Russian)",
    "nl": "Nederlands",
    "tr": "Türkçe",
    "pl": "Polski",
    "bn": "বাংলা (Bengali)",
    "ta": "தமிழ் (Tamil)",
    "te": "తెలుగు (Telugu)",
    "vi": "Tiếng Việt",
    "id": "Bahasa Indonesia",
    "th": "ไทย (Thai)",
    "he": "עברית (Hebrew)",
    "uk": "Українська",
    "sv": "Svenska",
    "da": "Dansk",
    "no": "Norsk",
    "fi": "Suomi",
    "ms": "Bahasa Melayu",
    "ca": "Català",
    "gl": "Galego",
}

# Idiomas UI del panel (strings completos)
PANEL_LANGUAGES: dict[str, str] = {
    "es": "Español",
    "en": "English",
    "hi": "हिन्दी",
    "pt": "Português",
    "fr": "Français",
    "de": "Deutsch",
    "zh": "中文",
    "ja": "日本語",
    "ar": "العربية",
}

_UI_ES = {
    "hub_title": "Estudio editorial LinkedIn",
    "hub_sub": "Editar · traducir · imagen · publicar con confirmación",
    "queue": "Cola de borradores",
    "refresh": "Actualizar",
    "show_archived": "Ver archivados/rechazados",
    "editor": "Editor + preview LinkedIn",
    "select_draft": "Selecciona un borrador",
    "pub_lang": "Idioma de publicación",
    "panel_lang": "Idioma del panel",
    "translate": "Traducir publicación",
    "save": "Guardar cambios",
    "regen_image": "Regenerar imagen",
    "copy": "Copiar texto",
    "reopen": "Reabrir para editar",
    "approve": "Aprobar (sin publicar)",
    "publish": "Publicar en LinkedIn",
    "archive": "Archivar / rechazar",
    "archived_hint": "Archivado ≠ borrado — activa «Ver archivados».",
    "chars": "caracteres",
    "title_overlay": "Insertar título en imagen (tipografía real, idioma de publicación)",
    "custom_overlay": "Texto personalizado en imagen (opcional)",
    "no_ai_text": "Sin texto inventado por IA (recomendado)",
    "allow_ai_text": "Permitir texto IA (no recomendado)",
    "visibility": "Visibilidad LinkedIn",
    "vis_public": "Público",
    "vis_connections": "Solo conexiones",
    "duplicate": "Duplicar borrador",
    "linkedin_posts": "Publicaciones recientes",
    "entity": "Entidad / marca",
    "entity_filter": "Filtrar entidad",
    "entity_all": "Todas las entidades",
    "entity_none": "Sin asignar",
    "linkedin_default": "LinkedIn: cuenta default (.env) si la entidad no tiene URN",
}

_UI_EN = {
    "hub_title": "LinkedIn Editorial Studio",
    "hub_sub": "Edit · translate · image · publish with confirmation",
    "queue": "Draft queue",
    "refresh": "Refresh",
    "show_archived": "Show archived/rejected",
    "editor": "Editor + LinkedIn preview",
    "select_draft": "Select a draft",
    "pub_lang": "Publication language",
    "panel_lang": "Panel language",
    "translate": "Translate publication",
    "save": "Save changes",
    "regen_image": "Regenerate image",
    "copy": "Copy text",
    "reopen": "Reopen for editing",
    "approve": "Approve (do not publish)",
    "publish": "Publish on LinkedIn",
    "archive": "Archive / reject",
    "archived_hint": "Archived ≠ deleted — enable «Show archived».",
    "chars": "characters",
    "title_overlay": "Insert title on image (real typography, publication language)",
    "custom_overlay": "Custom image text (optional)",
    "no_ai_text": "No AI-invented text (recommended)",
    "allow_ai_text": "Allow AI text (not recommended)",
    "visibility": "LinkedIn visibility",
    "vis_public": "Public",
    "vis_connections": "Connections only",
    "duplicate": "Duplicate draft",
    "linkedin_posts": "Recent publications",
    "entity": "Entity / brand",
    "entity_filter": "Filter entity",
    "entity_all": "All entities",
    "entity_none": "Unassigned",
    "linkedin_default": "LinkedIn: default account (.env) if entity has no URN",
}

_UI_HI = {
    "hub_title": "LinkedIn संपादकीय स्टूडियो",
    "hub_sub": "संपादित करें · अनुवाद · छवि · पुष्टि के साथ प्रकाशित करें",
    "queue": "ड्राफ्ट कतार",
    "refresh": "रीफ़्रेश",
    "show_archived": "संग्रहीत/अस्वीकृत दिखाएं",
    "editor": "संपादक + LinkedIn पूर्वावलोकन",
    "select_draft": "एक ड्राफ्ट चुनें",
    "pub_lang": "प्रकाशन भाषा",
    "panel_lang": "पैनल भाषा",
    "translate": "प्रकाशन का अनुवाद",
    "save": "परिवर्तन सहेजें",
    "regen_image": "छवि पुनः बनाएं",
    "copy": "टेक्स्ट कॉपी करें",
    "reopen": "संपादन के लिए पुनः खोलें",
    "approve": "अनुमोदित (प्रकाशित न करें)",
    "publish": "LinkedIn पर प्रकाशित करें",
    "archive": "संग्रह / अस्वीकार",
    "archived_hint": "संग्रहीत ≠ हटाया — «संग्रहीत दिखाएं» चालू करें।",
    "chars": "अक्षर",
    "title_overlay": "छवि पर शीर्षक (वास्तविक टाइपोग्राफी)",
    "custom_overlay": "कस्टम छवि पाठ (वैकल्पिक)",
    "no_ai_text": "AI पाठ नहीं (अनुशंसित)",
    "allow_ai_text": "AI पाठ (अनुशंसित नहीं)",
    "visibility": "LinkedIn दृश्यता",
    "vis_public": "सार्वजनिक",
    "vis_connections": "केवल कनेक्शन",
    "duplicate": "ड्राफ्ट डुप्लिकेट",
    "linkedin_posts": "हाल की प्रकाशनाएं",
}

UI_STRINGS: dict[str, dict[str, str]] = {
    "es": _UI_ES,
    "en": _UI_EN,
    "hi": _UI_HI,
    "pt": {**_UI_EN, "hub_title": "Estúdio editorial LinkedIn", "pub_lang": "Idioma da publicação"},
    "fr": {**_UI_EN, "hub_title": "Studio éditorial LinkedIn", "pub_lang": "Langue de publication"},
    "de": {**_UI_EN, "hub_title": "LinkedIn Redaktionsstudio", "pub_lang": "Veröffentlichungssprache"},
    "zh": {**_UI_EN, "hub_title": "LinkedIn 编辑工作室", "pub_lang": "发布语言"},
    "ja": {**_UI_EN, "hub_title": "LinkedIn 編集スタジオ", "pub_lang": "公開言語"},
    "ar": {**_UI_EN, "hub_title": "استوديو LinkedIn", "pub_lang": "لغة المنشور"},
}


def normalize_lang(code: str | None, *, allowed: dict[str, str] | None = None) -> str:
    base = (code or "es").strip().lower().replace("_", "-").split("-")[0]
    catalog = allowed or PUBLICATION_LANGUAGES
    return base if base in catalog else "es"


def ui_strings(lang: str) -> dict[str, str]:
    code = normalize_lang(lang, allowed=PANEL_LANGUAGES)
    return UI_STRINGS.get(code) or UI_STRINGS["en"]


def overlay_brand(lang: str) -> str:
    labels = {
        "es": "PC Doctor · RalfIA",
        "en": "PC Doctor · RalfIA",
        "hi": "पीसी डॉक्टर · RalfIA",
        "pt": "PC Doctor · RalfIA",
        "fr": "PC Doctor · RalfIA",
        "de": "PC Doctor · RalfIA",
        "zh": "PC Doctor · RalfIA",
        "ja": "PC Doctor · RalfIA",
        "ar": "PC Doctor · RalfIA",
    }
    return labels.get(normalize_lang(lang), "PC Doctor · RalfIA")
