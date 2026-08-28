"""Búsqueda web ligera (DuckDuckGo HTML) — sin API key."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

import requests


def search_web(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Devuelve [{title, snippet, url}, ...]."""
    query = query.strip()
    if not query:
        return []
    try:
        r = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; RalphiIA/2.0)"},
            timeout=15,
        )
        r.raise_for_status()
        html = r.text
    except Exception as e:
        return [{"title": "Búsqueda no disponible", "snippet": str(e), "url": ""}]

    results: list[dict[str, Any]] = []
    blocks = re.split(r'<div class="result\s', html)
    for block in blocks[1:]:
        m_title = re.search(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            re.S,
        )
        m_snip = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
        if not m_title:
            continue
        title = _clean_html(m_title.group(2))
        url = m_title.group(1)
        snippet = _clean_html(m_snip.group(1)) if m_snip else ""
        results.append({"title": title, "snippet": snippet, "url": url})
        if len(results) >= max_results:
            break
    return results


def format_search_context(results: list[dict[str, Any]]) -> str:
    if not results:
        return "No encontré resultados en la web."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title', '')}\n   {r.get('snippet', '')}\n   {r.get('url', '')}")
    return "\n\n".join(lines)


def _clean_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    return unescape(text).strip()
