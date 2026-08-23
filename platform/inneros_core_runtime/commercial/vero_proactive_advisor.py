"""Vero — asesora comercial proactiva (stock, historial, upsell)."""

from __future__ import annotations

import re
from typing import Any

from raphiia_openai import mongo_store
from raphiia_openai.operational.constants import COL_OPS_QUOTE_DRAFTS

# Señales de producto en lenguaje natural
PRODUCT_SIGNALS: dict[str, tuple[str, ...]] = {
    "camera": ("camara", "cámara", "camaras", "cámaras", "cctv", "videovigilancia", "ip cam", "bullet", "domo"),
    "nvr": ("nvr", "dvr", "grabador", "recorder", "videograbador"),
    "storage": ("disco", "hdd", "ssd", "almacenamiento", "storage", "tb"),
    "access_control": ("puerta", "zkteco", "control acceso", "biometric", "huella", "tarjeta"),
    "network": ("switch", "poe", "router", "cable utp", "fibra"),
    "alarm": ("alarma", "sensor", "detector", "sirena"),
}

# Si vendes X, Vero pregunta/sugiere Y
UPSELL_CHAIN: dict[str, list[dict[str, str]]] = {
    "camera": [
        {"key": "nvr", "question": "¿Necesitas grabador NVR/DVR? Tengo opciones en stock."},
        {"key": "storage", "question": "¿Disco duro para retención? (ej. 2TB, 4TB, 8TB)"},
        {"key": "network", "question": "¿Switch PoE o cableado UTP incluido?"},
    ],
    "access_control": [
        {"key": "network", "question": "¿Cableado, fuente o cerradura magnética incluidos?"},
        {"key": "storage", "question": "¿Licencias de software o servidor local?"},
    ],
    "nvr": [
        {"key": "storage", "question": "¿Discos instalados o cliente los compra aparte?"},
        {"key": "camera", "question": "¿Cuántas cámaras y qué resolución (2MP/4MP/8MP)?"},
    ],
}

SEARCH_ALIASES: dict[str, tuple[str, ...]] = {
    "camera": ("camara", "cámara", "camera", "cctv", "domo", "bullet", "hikvision", "dahua"),
    "nvr": ("nvr", "dvr", "grabador", "recorder"),
    "storage": ("disco", "hdd", "storage", "wd purple", "seagate"),
    "access_control": ("zkteco", "control", "puerta", "biometric", "proface"),
    "network": ("switch", "poe", "utp", "cat6"),
    "alarm": ("alarma", "sensor", "detector"),
}


def _norm(value: Any) -> str:
    return str(value or "").strip()


def detect_product_categories(message: str) -> list[str]:
    text = (message or "").lower()
    found: list[str] = []
    for category, signals in PRODUCT_SIGNALS.items():
        for sig in signals:
            if " " in sig:
                if sig in text:
                    found.append(category)
                    break
            elif re.search(rf"{re.escape(sig)}", text):
                found.append(category)
                break
    return list(dict.fromkeys(found))


def _search_terms(categories: list[str], message: str) -> list[str]:
    terms: list[str] = []
    for cat in categories:
        terms.extend(SEARCH_ALIASES.get(cat, (cat,)))
    # palabras significativas del mensaje
    for word in re.findall(r"[a-záéíóúñ0-9]{4,}", message.lower()):
        if word not in {"para", "cliente", "cotiz", "cotiza", "vero", "femar", "necesito"}:
            terms.append(word)
    return list(dict.fromkeys(terms))[:8]


def _find_client_quotes(client_id: str, limit: int = 10) -> list[dict[str, Any]]:
    db = mongo_store.get_db()
    cursor = db[COL_OPS_QUOTE_DRAFTS].find({"client_id": client_id}).sort("updated_at", -1).limit(limit)
    return [dict(doc) for doc in cursor]


def _find_similar_quotes(keywords: list[str], *, exclude_client_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    if not keywords:
        return []
    db = mongo_store.get_db()
    or_clauses = []
    for kw in keywords[:5]:
        q = re.escape(kw)
        or_clauses.extend([
            {"title": {"$regex": q, "$options": "i"}},
            {"notes": {"$regex": q, "$options": "i"}},
            {"display_number": {"$regex": q, "$options": "i"}},
        ])
    filt: dict[str, Any] = {"$or": or_clauses}
    if exclude_client_id:
        filt["client_id"] = {"$ne": exclude_client_id}
    cursor = db[COL_OPS_QUOTE_DRAFTS].find(filt).sort("updated_at", -1).limit(limit)
    results = []
    for doc in cursor:
        row = dict(doc)
        row.pop("_id", None)
        line_items = row.get("line_items") or []
        if line_items and float(row.get("total") or 0) > 0:
            results.append(row)
    return results


def _search_stock(terms: list[str], limit: int = 12) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from raphiia_openai import product_intelligence
    from raphiia_openai.contifico_bridge import search_contifico_products
    from raphiia_openai.operational import inventory_store

    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    contifico_items: list[dict[str, Any]] = []

    for term in terms:
        res = inventory_store.search_inventory_catalog(term, limit=limit)
        for item in res.get("items") or []:
            iid = _norm(item.get("item_id"))
            if iid and iid not in seen:
                seen.add(iid)
                items.append(item)

        cf_res = search_contifico_products(term, limit=limit)
        for cf in cf_res.get("items") or []:
            cid = _norm(cf.get("contifico_product_id"))
            if cid and cid not in seen:
                seen.add(cid)
                contifico_items.append(cf)

    if len(items) < 3 and terms:
        for term in terms[:4]:
            pi_res = product_intelligence.search({"query": term, "limit": limit})
            for item in pi_res.get("items") or []:
                iid = _norm(item.get("item_id"))
                if iid and iid not in seen:
                    seen.add(iid)
                    items.append(item)
            if len(items) >= limit:
                break

    return items[:limit], contifico_items[:limit]


def _try_quoteops_sourcing(quoteops_mission_id: str | None) -> dict[str, Any] | None:
    if not quoteops_mission_id:
        return None
    try:
        from raphiia_openai import quoteops_mcp_bridge

        result = quoteops_mcp_bridge.call(
            "quoteops_get_sourcing_recommendations",
            {"mission_id": quoteops_mission_id, "language": "es"},
        )
        if result.get("ok") is False and result.get("error") in {
            "quoteops_mcp_not_configured",
            "quoteops_unavailable",
            "quoteops_http_error",
        }:
            return None
        return result
    except Exception:
        return None


def _stock_line_suggestions(stock_items: list[dict[str, Any]], max_lines: int = 6) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for item in stock_items[:max_lines]:
        qty = float(item.get("qty_on_hand") or 0)
        offer = item.get("best_offer") or {}
        price = float(offer.get("price") or item.get("unit_cost") or 0)
        if price <= 0:
            continue
        lines.append({
            "description": _norm(item.get("name") or item.get("sku")),
            "quantity": 1,
            "unit_price": round(price, 2),
            "sku": _norm(item.get("sku")),
            "item_id": _norm(item.get("item_id")),
            "qty_on_hand": qty,
            "from_stock": True,
        })
    return lines


def _proactive_questions(
    categories: list[str],
    *,
    has_stock: bool,
    has_prior_quote: bool,
    catalog_total: int = 0,
) -> list[str]:
    questions: list[str] = []
    if "camera" in categories:
        questions.append("¿Cuántas cámaras y qué tipo (domo, bullet, PTZ, interior/exterior)?")
        questions.append("¿Resolución objetivo (2MP, 4MP, 8MP) y marca preferida?")
    if "access_control" in categories:
        questions.append("¿Cuántos puntos de acceso y qué tecnología (huella, tarjeta, facial)?")
    for cat in categories:
        for upsell in UPSELL_CHAIN.get(cat, []):
            questions.append(upsell["question"])
    if has_stock:
        questions.append("Puedo armar la cotización con lo que ya tenemos en stock — ¿confirmo cantidades?")
    if has_prior_quote:
        questions.append("Este cliente ya tiene cotizaciones similares — ¿duplico y ajusto la más reciente?")
    if not categories:
        inv_hint = f" ({catalog_total} ítems)" if catalog_total else ""
        questions.extend([
            "¿Qué productos o servicio incluye? (cámaras, puertas, cableado, mano de obra…)",
            f"¿Tienes cantidades y precios objetivo, o reviso nuestro catálogo local{inv_hint}?",
        ])
    return list(dict.fromkeys(questions))[:8]


def _contifico_line_suggestions(contifico_items: list[dict[str, Any]], max_lines: int = 6) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for item in contifico_items[:max_lines]:
        price = float(item.get("unit_price") or 0)
        if price <= 0:
            continue
        lines.append({
            "description": _norm(item.get("name")),
            "quantity": 1,
            "unit_price": round(price, 2),
            "sku": _norm(item.get("sku") or item.get("contifico_product_id")),
            "from_local_catalog": True,
            "source": item.get("source"),
        })
    return lines


def build_proactive_briefing(
    *,
    message: str,
    client_id: str | None = None,
    client_name: str | None = None,
    quoteops_mission_id: str | None = None,
) -> dict[str, Any]:
    """Genera briefing proactivo antes de crear cotización vacía."""
    from raphiia_openai.contifico_bridge import contifico_product_stats
    from raphiia_openai.operational import inventory_store

    catalog_stats = inventory_store.inventory_catalog_stats()
    local_stats = contifico_product_stats()
    inventory_total = int(catalog_stats.get("total_items") or 0)
    local_products_total = int(local_stats.get("local_products") or local_stats.get("referenced_product_ids") or 0)
    categories = detect_product_categories(message)
    terms = _search_terms(categories, message)
    stock_items, contifico_items = (
        _search_stock(terms) if terms else _search_stock(["camara", "cctv", "switch"], limit=8)
    )
    client_quotes: list[dict[str, Any]] = []
    if client_id:
        client_quotes = _find_client_quotes(client_id)
    similar = _find_similar_quotes(terms, exclude_client_id=client_id)
    sourcing = _try_quoteops_sourcing(quoteops_mission_id)

    # Cotizaciones del cliente con líneas útiles
    client_with_lines = [
        q for q in client_quotes
        if (q.get("line_items") or []) and float(q.get("total") or 0) > 0
    ]
    best_prior = client_with_lines[0] if client_with_lines else None
    best_similar = similar[0] if similar else None

    stock_lines = _stock_line_suggestions(stock_items)
    contifico_lines = _contifico_line_suggestions(contifico_items)
    questions = _proactive_questions(
        categories,
        has_stock=bool(stock_items or contifico_items),
        has_prior_quote=bool(client_with_lines),
        catalog_total=inventory_total + local_products_total,
    )

    stock_summary = []
    for item in stock_items[:4]:
        qty = item.get("qty_on_hand", 0)
        offer = item.get("best_offer") or {}
        price = offer.get("price")
        stock_summary.append({
            "name": item.get("name"),
            "sku": item.get("sku"),
            "qty_on_hand": qty,
            "price": price,
            "currency": offer.get("currency", "USD"),
            "supplier": offer.get("party_name") or offer.get("party_id"),
            "offer_count": len(item.get("offers") or []),
            "source": "inventory_items",
        })
    for item in contifico_items[:4]:
        stock_summary.append({
            "name": item.get("name"),
            "sku": item.get("sku") or item.get("contifico_product_id"),
            "price": item.get("unit_price"),
            "currency": "USD",
            "source": item.get("source") or "local_product_catalog",
            "usage_count": item.get("usage_count"),
        })

    duplicate_candidate = None
    if best_prior:
        duplicate_candidate = {
            "source": "client_prior",
            "quote_id": best_prior.get("quote_id"),
            "display_number": best_prior.get("display_number"),
            "total": best_prior.get("total"),
            "line_count": len(best_prior.get("line_items") or []),
        }
    elif best_similar:
        duplicate_candidate = {
            "source": "similar_quote",
            "quote_id": best_similar.get("quote_id"),
            "display_number": best_similar.get("display_number"),
            "total": best_similar.get("total"),
            "client_id": best_similar.get("client_id"),
            "line_count": len(best_similar.get("line_items") or []),
        }

    suggested_line_items = stock_lines or contifico_lines
    if not suggested_line_items and duplicate_candidate:
        src_id = duplicate_candidate.get("quote_id")
        src = next((q for q in client_quotes + similar if q.get("quote_id") == src_id), None)
        if src:
            suggested_line_items = [
                {
                    "description": ln.get("description", "Item"),
                    "quantity": ln.get("quantity", 1),
                    "unit_price": ln.get("unit_price", ln.get("price", 0)),
                    "from_duplicate": True,
                }
                for ln in (src.get("line_items") or [])[:12]
            ]

    narrative_parts = []
    if client_name:
        narrative_parts.append(f"Cliente: **{client_name}**.")
    if categories:
        narrative_parts.append(f"Detecto: {', '.join(categories)}.")
    if stock_summary:
        narrative_parts.append(
            f"En catálogo local encontré {len(stock_summary)} ítem(s) "
            f"(inventario {inventory_total} + histórico {local_products_total})."
        )
    elif inventory_total or local_products_total:
        narrative_parts.append(
            f"Revisé catálogo local ({inventory_total} inventario + {local_products_total} productos históricos)."
        )
    if duplicate_candidate:
        narrative_parts.append(
            f"Hay cotización previa `{duplicate_candidate.get('display_number')}` "
            f"(${duplicate_candidate.get('total')}) — puedo duplicarla y ajustar."
        )
    if questions:
        narrative_parts.append("Antes de cerrar, necesito confirmar algunos puntos.")

    return {
        "ok": True,
        "catalog_source": "local_merged",
        "inventory_total_items": inventory_total,
        "local_products_total": local_products_total,
        "catalog_total_items": inventory_total + local_products_total,
        "catalog_total_offers": int(catalog_stats.get("total_offers") or 0),
        "local_only": True,
        "categories": categories,
        "search_terms": terms,
        "stock": stock_summary,
        "stock_items": stock_items,
        "local_catalog_items": contifico_items,
        "quoteops_sourcing": sourcing,
        "client_prior_quotes": [
            {
                "quote_id": q.get("quote_id"),
                "display_number": q.get("display_number"),
                "total": q.get("total"),
                "status": q.get("status"),
                "updated_at": q.get("updated_at"),
            }
            for q in client_quotes[:5]
        ],
        "similar_quotes": [
            {
                "quote_id": q.get("quote_id"),
                "display_number": q.get("display_number"),
                "total": q.get("total"),
                "title": q.get("title"),
            }
            for q in similar[:3]
        ],
        "duplicate_candidate": duplicate_candidate,
        "suggested_line_items": suggested_line_items,
        "proactive_questions": questions,
        "narrative": " ".join(narrative_parts),
        "ready_to_quote": bool(suggested_line_items) and len(suggested_line_items) >= 1,
    }


def duplicate_quote_for_client(
    source_quote_id: str,
    *,
    client_id: str,
    client_name: str,
    message: str = "",
    entity_id: str = "ent_pcdoctor",
) -> dict[str, Any]:
    """Duplica cotización existente para el mismo u otro cliente."""
    from raphiia_openai import pcdoctor_store

    db = mongo_store.get_db()
    src = db[COL_OPS_QUOTE_DRAFTS].find_one({"quote_id": source_quote_id})
    if not src:
        return {"ok": False, "error": "source_quote_not_found", "source_quote_id": source_quote_id}
    payload: dict[str, Any] = {
        "client_id": client_id,
        "title": f"Cotización {client_name} (basada en {src.get('display_number') or source_quote_id})",
        "notes": message[:2000] or f"Duplicada desde {source_quote_id}",
        "entity_id": entity_id,
        "numbering_namespace": "ralfia",
        "status": "draft",
        "line_items": src.get("line_items") or [],
        "tax_rate": src.get("tax_rate", 0.15),
        "commercial_terms": src.get("commercial_terms"),
        "source": "vero_duplicate",
        "duplicated_from": source_quote_id,
    }
    return pcdoctor_store.create_quote_draft(payload)


def format_proactive_reply(briefing: dict[str, Any], *, agent: str = "Vero") -> str:
    lines = [f"*{agent} · asesora comercial*"]
    if briefing.get("narrative"):
        lines.append(str(briefing["narrative"]))
    stock = briefing.get("stock") or []
    if stock:
        lines.append("\n*Inventario de cotización:*")
        for s in stock[:5]:
            price = s.get("price")
            supplier = s.get("supplier")
            ptxt = f" — ${price}" if price else ""
            stxt = f" ({supplier})" if supplier else ""
            lines.append(f"• {s.get('name')} (x{s.get('qty_on_hand', '?')}){ptxt}{stxt}")
    dup = briefing.get("duplicate_candidate")
    if dup:
        lines.append(
            f"\n*Cotización similar:* `{dup.get('display_number')}` ${dup.get('total')} "
            f"({dup.get('line_count')} líneas) — dime *duplica* para copiarla."
        )
    qs = briefing.get("proactive_questions") or []
    if qs:
        lines.append("\n*Te pregunto:*")
        for q in qs[:5]:
            lines.append(f"• {q}")
    if briefing.get("ready_to_quote"):
        lines.append("\n✅ Tengo líneas sugeridas listas — confirma cantidades o dime *arma la cotización*.")
    return "\n".join(lines)
