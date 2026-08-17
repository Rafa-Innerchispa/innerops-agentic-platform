"""Editorial Hub — UI aprobación + API LinkedIn pipeline."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from raphiia_openai import editorial_store, image_gen, linkedin_client
from raphiia_openai.editorial_i18n import PANEL_LANGUAGES, PUBLICATION_LANGUAGES, normalize_lang, ui_strings
from raphiia_openai.editorial_translate import translate_content
from raphiia_openai.editorial_publish import publish_destination
from raphiia_openai import config_store
from raphiia_openai.operational import web_content_manager
from raphiia_openai.settings import GOOGLE_API_KEY

router = APIRouter(tags=["editorial"])


class RejectBody(BaseModel):
    reason: str = ""


class ApproveBody(BaseModel):
    approved_by: str = "rafael"
    publish_now: bool = False
    allow_personal_fallback: bool = False


class SocialAccountPatchBody(BaseModel):
    linkedin_author_urn: str | None = None
    linkedin_publish_as: str | None = None
    label: str | None = None


class DraftPatchBody(BaseModel):
    title: str | None = None
    markdown: str | None = None
    hashtags: list[str] | None = None
    publication_lang: str | None = None
    linkedin_visibility: str | None = None
    entity_id: str | None = None


class TranslateBody(BaseModel):
    target_lang: str = "en"
    source_lang: str | None = None


class GenerateImageBody(BaseModel):
    include_ai_text: bool = False
    overlay_text: str = ""
    overlay_lang: str = "es"
    use_title_overlay: bool = True


class WebContentStatusBody(BaseModel):
    new_status: str
    approved_by: str | None = "rafael"


class WebContentFromDraftBody(BaseModel):
    content_type: str = "hackathon"
    slug: str | None = None
    visibility: str = "internal"
    theme: str = "living-lab"
    status: str = "review"


class WebContentSyncBody(BaseModel):
    source_path: str | None = None
    default_status: str = "review"
    publish_safe_items: bool = True


def _slugify(value: str) -> str:
    raw = (value or "innerchispa-update").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    return raw or "innerchispa-update"


@router.get("/api/editorial/languages")
def api_languages():
    return {
        "publication": PUBLICATION_LANGUAGES,
        "panel": PANEL_LANGUAGES,
        "visibility": linkedin_client.list_visibility_options(),
    }


@router.get("/api/editorial/i18n")
def api_i18n(lang: str = "es"):
    code = normalize_lang(lang, allowed=PANEL_LANGUAGES)
    return {"lang": code, "strings": ui_strings(code)}


@router.get("/api/editorial/linkedin/profile")
def api_linkedin_profile():
    return linkedin_client.get_member_profile()


@router.get("/api/editorial/published")
def api_published(limit: int = 15):
    from raphiia_openai.mongo_store import get_db
    from raphiia_openai.settings import COL_SOCIAL_DESTINATIONS

    db = get_db()
    rows = list(
        db[COL_SOCIAL_DESTINATIONS]
        .find({"status": "published"}, {"_id": 1, "linkedin_post_urn": 1, "post_id": 1, "updated_at": 1})
        .sort("updated_at", -1)
        .limit(min(limit, 50))
    )
    out = []
    for row in rows:
        post = editorial_store.get_post(row.get("post_id", ""))
        urn = row.get("linkedin_post_urn", "")
        stats = linkedin_client.try_post_statistics(urn)
        out.append(
            {
                "destination_id": str(row["_id"]),
                "linkedin_post_urn": urn,
                "published_at": row.get("updated_at"),
                "title": (post or {}).get("title", ""),
                "publication_lang": (post or {}).get("publication_lang", "es"),
                "statistics": stats,
            }
        )
    return {"ok": True, "items": out}


@router.get("/editorial", response_class=HTMLResponse)
def editorial_ui():
    return HTMLResponse(_EDITORIAL_HTML)


@router.get("/api/editorial/config")
def editorial_config():
    return {
        "google_api": bool(config_store.get_google_api_key() or GOOGLE_API_KEY),
        "linkedin": linkedin_client.config_status(),
        "linkedin_capabilities": linkedin_client.api_capabilities(),
    }


@router.get("/api/editorial/entities")
def api_list_entities():
    from raphiia_openai.entity_linkedin import list_entities_for_editorial

    items = list_entities_for_editorial()
    return {"ok": True, "count": len(items), "items": items}


@router.get("/api/editorial/social/accounts")
def api_social_accounts():
    from raphiia_openai import editorial_social

    items = editorial_social.list_linkedin_accounts()
    return {"ok": True, "items": items}


@router.get("/api/editorial/social/preview")
def api_social_preview(entity_id: str = ""):
    from raphiia_openai import editorial_social

    return editorial_social.publish_preview(entity_id or None)


@router.patch("/api/editorial/social/accounts/{entity_id}")
def api_patch_social_account(entity_id: str, body: SocialAccountPatchBody):
    from raphiia_openai import editorial_social

    return editorial_social.patch_entity_linkedin(
        entity_id,
        linkedin_author_urn=body.linkedin_author_urn,
        linkedin_publish_as=body.linkedin_publish_as,
        label=body.label,
    )


@router.get("/api/editorial/drafts")
def api_list_drafts(
    channel: str | None = None,
    entity_id: str | None = None,
    status: str | None = None,
    include_archived: bool = False,
):
    items = editorial_store.list_drafts(
        channel=channel, entity_id=entity_id, status=status, include_archived=include_archived
    )
    return {"ok": True, "count": len(items), "items": items}


@router.get("/api/editorial/drafts/{draft_id}")
def api_get_draft(draft_id: str):
    r = editorial_store.get_draft(draft_id)
    if not r.get("ok"):
        raise HTTPException(404, r.get("error", "not found"))
    return r


@router.patch("/api/editorial/drafts/{draft_id}")
def api_patch_draft(draft_id: str, body: DraftPatchBody):
    st = editorial_store.get_draft(draft_id)
    if not st.get("ok"):
        raise HTTPException(404, st.get("error", "not found"))
    if st["draft"].get("status") == editorial_store.STATUS_PUBLISHED:
        raise HTTPException(400, "published — duplicate draft to edit")

    draft = st["draft"]
    lang = draft.get("publication_lang", "es")

    if body.publication_lang:
        lang = normalize_lang(body.publication_lang)
        switched = editorial_store.switch_publication_lang(draft_id, lang)
        if not switched.get("ok"):
            raise HTTPException(400, switched.get("error", "switch failed"))
        draft = switched["draft"]
        lang = draft.get("publication_lang", lang)

    patch: dict = {}
    if body.title is not None:
        patch["title"] = body.title
    if body.markdown is not None:
        patch["markdown"] = body.markdown
        patch["body"] = body.markdown
    if body.hashtags is not None:
        patch["hashtags"] = body.hashtags
    if body.linkedin_visibility is not None:
        patch["linkedin_visibility"] = body.linkedin_visibility.upper()
    if body.entity_id is not None:
        patch["entity_id"] = body.entity_id.strip() or None

    if body.title is None and body.markdown is None and body.publication_lang and not patch:
        return {"ok": True, "draft": draft}

    if not patch and body.publication_lang is None and body.entity_id is None:
        raise HTTPException(400, "nothing to update")

    cur_status = draft.get("status", editorial_store.STATUS_DRAFT)
    if cur_status == editorial_store.STATUS_REJECTED:
        patch["status"] = editorial_store.STATUS_DRAFT

    result = editorial_store.update_draft(draft_id, patch) if patch else {"ok": True, "draft": draft}
    if result.get("ok") and (body.title is not None or body.markdown is not None):
        d = result["draft"]
        editorial_store.save_localization(
            draft_id,
            d.get("publication_lang", lang),
            title=d.get("title", ""),
            markdown=d.get("markdown", d.get("body", "")),
        )
    return result


@router.post("/api/editorial/drafts/{draft_id}/translate")
def api_translate_draft(draft_id: str, body: TranslateBody):
    st = editorial_store.get_draft(draft_id)
    if not st.get("ok"):
        raise HTTPException(404, st.get("error", "not found"))
    d = st["draft"]
    tgt = normalize_lang(body.target_lang)
    src_lang = d.get("publication_lang", "es")
    locs = d.get("localizations") or {}
    if src_lang not in locs:
        editorial_store.save_localization(
            draft_id, src_lang, title=d.get("title", ""), markdown=d.get("markdown", d.get("body", ""))
        )
    tr = translate_content(
        title=d.get("title", ""),
        markdown=d.get("markdown", d.get("body", "")),
        target_lang=tgt,
        source_lang=body.source_lang or src_lang,
    )
    if not tr.get("ok") and not tr.get("fallback"):
        raise HTTPException(502, tr.get("error", "translate failed"))
    fb = tr.get("fallback") or tr
    title = tr.get("title") or fb.get("title", d.get("title", ""))
    markdown = tr.get("markdown") or fb.get("markdown", d.get("markdown", ""))
    editorial_store.save_localization(draft_id, tgt, title=title, markdown=markdown)
    out = editorial_store.switch_publication_lang(draft_id, tgt, title=title, markdown=markdown)
    return {**out, "translation": tr}


@router.post("/api/editorial/drafts/{draft_id}/duplicate")
def api_duplicate_draft(draft_id: str):
    r = editorial_store.duplicate_draft(draft_id)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "duplicate failed"))
    return r


@router.post("/api/editorial/drafts/{draft_id}/reopen")
def api_reopen_draft(draft_id: str):
    r = editorial_store.reopen_draft(draft_id)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "reopen failed"))
    return r


@router.post("/api/editorial/drafts/{draft_id}/generate-image")
def api_generate_image(draft_id: str, body: GenerateImageBody | None = None):
    body = body or GenerateImageBody()
    r = editorial_store.get_draft(draft_id)
    if not r.get("ok"):
        raise HTTPException(404, r.get("error"))
    d = r["draft"]
    editorial_store.update_draft(draft_id, {"status": editorial_store.STATUS_GENERATING})
    overlay = body.overlay_text.strip()
    if body.use_title_overlay and not overlay:
        overlay = (d.get("title") or "").strip()[:120]
    pub_lang = d.get("publication_lang", "es")
    gen = image_gen.generate_for_draft(
        draft_id,
        d.get("title", ""),
        d.get("markdown", d.get("body", "")),
        include_ai_text=body.include_ai_text,
        overlay_text=overlay or None,
        overlay_lang=body.overlay_lang or pub_lang,
    )
    if not gen.get("ok"):
        editorial_store.update_draft(draft_id, {"status": editorial_store.STATUS_DRAFT})
        raise HTTPException(500, "generación falló")
    out = editorial_store.attach_media(
        draft_id,
        media_path=gen["media_path"],
        media_prompt=gen["media_prompt"],
        provider=gen["provider"],
    )
    return {**out, "warnings": gen.get("warnings", [])}


@router.post("/api/editorial/drafts/{draft_id}/approve")
def api_approve(draft_id: str, body: ApproveBody):
    r = editorial_store.approve_draft(draft_id, approved_by=body.approved_by)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "approve failed"))
    publish_result = None
    if body.publish_now:
        publish_result = publish_destination(
            r["destination_id"],
            allow_personal_fallback=body.allow_personal_fallback,
        )
    return {**r, "publish": publish_result}


@router.post("/api/editorial/drafts/{draft_id}/reject")
def api_reject(draft_id: str, body: RejectBody):
    return editorial_store.reject_draft(draft_id, body.reason)


@router.post("/api/editorial/publish/{destination_id}")
def api_publish(destination_id: str, allow_personal_fallback: bool = False):
    result = publish_destination(
        destination_id,
        allow_personal_fallback=allow_personal_fallback,
    )
    if not result.get("ok") and not result.get("queued"):
        raise HTTPException(502, result.get("error", "publish failed"))
    return result


@router.get("/api/editorial/web-content")
def api_web_content(content_type: str | None = None, status: str | None = None, limit: int = 50):
    return web_content_manager.list_web_content(content_type=content_type, status=status, limit=limit)


@router.post("/api/editorial/web-content/from-draft/{draft_id}")
def api_web_content_from_draft(draft_id: str, body: WebContentFromDraftBody):
    st = editorial_store.get_draft(draft_id)
    if not st.get("ok"):
        raise HTTPException(404, st.get("error", "draft not found"))
    draft = st["draft"]
    title = draft.get("title") or "InnerChispa update"
    slug = _slugify(body.slug or title)
    result = web_content_manager.create_web_content(
        content_id=f"editorial-{draft_id}",
        content_type=body.content_type,
        title=title,
        slug=slug,
        description=draft.get("markdown") or draft.get("body") or "",
        technologies=(draft.get("metadata") or {}).get("technologies") or [],
        images=[{"path": draft.get("media_path"), "provider": draft.get("image_provider", "")}] if draft.get("media_path") else [],
        demo_url=(draft.get("metadata") or {}).get("demo_url") or "",
        github_url=(draft.get("metadata") or {}).get("github_url") or "",
        visibility=body.visibility,
        theme=body.theme,
        status=body.status,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "web content create failed"))
    return result


@router.post("/api/editorial/web-content/{content_id}/status")
def api_web_content_status(content_id: str, body: WebContentStatusBody):
    result = web_content_manager.change_web_content_status(
        content_id=content_id,
        new_status=body.new_status,
        approved_by=body.approved_by,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "web content status failed"))
    return result


@router.post("/api/editorial/web-content/export-astro")
def api_web_content_export_astro(output_dir: str = "/home/rlopez/projects/hackathon-autopilot/staging/innerchispa-web/src/data"):
    result = web_content_manager.export_web_content_for_astro(output_dir)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "astro export failed"))
    return result


@router.post("/api/editorial/web-content/sync-canonical")
def api_web_content_sync_canonical(body: WebContentSyncBody | None = None):
    payload = body or WebContentSyncBody()
    result = web_content_manager.sync_hackathon_portfolio(
        payload.source_path or web_content_manager.CANONICAL_HACKATHON_PORTFOLIO,
        default_status=payload.default_status,
        publish_safe_items=payload.publish_safe_items,
    )
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "canonical sync failed"))
    return result


_EDITORIAL_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Ralphi IA — Editorial Hub</title>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;800&display=swap" rel="stylesheet"/>
  <style>
    :root { --bg:#0f172a; --card:#1e293b; --accent:#38bdf8; --text:#f1f5f9; --muted:#94a3b8; }
    * { box-sizing: border-box; }
    body { font-family: "Outfit", system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 1.5rem; }
    .ralphi-banner {
      margin: -1.5rem -1.5rem 1.25rem; padding: 1.25rem 1.5rem;
      background: linear-gradient(125deg, #0c1424, #121a2e 50%, #0f1f38);
      border-bottom: 1px solid #334155;
    }
    .ralphi-banner h1 {
      margin: 0; font-size: 1.75rem; font-weight: 800;
      background: linear-gradient(92deg, #5bd8ff, #78a8ff, #c4a5ff);
      -webkit-background-clip: text; background-clip: text; color: transparent;
    }
    .ralphi-banner p { margin: 0.35rem 0 0; color: var(--muted); font-size: 0.95rem; }
    .ralphi-banner em { font-style: normal; color: #5bd8ff; font-weight: 600; }
    .ralphi-ver { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.1em; color: #5bd8ff;
      border: 1px solid rgba(91,216,255,.3); padding: 3px 8px; border-radius: 999px; margin-left: 8px; vertical-align: middle; }
    h1.page-title { font-size: 1.15rem; margin: 0 0 .5rem; color: var(--accent); }
    .sub { color: var(--muted); margin-bottom: 1.5rem; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
    .card { background: var(--card); border-radius: 12px; padding: 1rem; border: 1px solid #334155; }
    .card h2 { margin: 0 0 .75rem; font-size: 1rem; color: var(--accent); }
    .status { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: .75rem; background: #334155; }
    .status.review { background: #854d0e; }
    .status.approved { background: #166534; }
    pre { white-space: pre-wrap; font-size: .85rem; background: #0f172a; padding: .75rem; border-radius: 8px; max-height: 240px; overflow: auto; }
    img.preview { max-width: 100%; border-radius: 8px; margin-top: .5rem; }
    button { cursor: pointer; border: none; border-radius: 8px; padding: .5rem 1rem; font-weight: 600; margin-right: .5rem; margin-top: .5rem; }
    .btn-primary { background: var(--accent); color: #0f172a; }
    .btn-ok { background: #22c55e; color: #052e16; }
    .btn-danger { background: #ef4444; color: #fff; }
    .btn-muted { background: #475569; color: #fff; }
    #config { font-size: .85rem; color: var(--muted); margin-bottom: 1rem; }
    .item { border-bottom: 1px solid #334155; padding: .75rem 0; cursor: pointer; }
    .item:hover { background: #33415533; }
    .li-preview { background:#fff; color:#000; border-radius:8px; padding:12px; margin:.75rem 0; font-size:.9rem; }
    .li-preview .li-head { display:flex; gap:8px; align-items:center; margin-bottom:8px; }
    .li-preview .li-avatar { width:40px; height:40px; border-radius:50%; background:#0a66c2; color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; }
    .field { width:100%; margin:.5rem 0; padding:.5rem; border-radius:8px; border:1px solid #334155; background:#0f172a; color:var(--text); font-family:inherit; }
    textarea.field { min-height:160px; resize:vertical; }
    .meta { font-size:.8rem; color:var(--muted); }
    .img-opts { background:#0f172a; padding:.75rem; border-radius:8px; margin:.5rem 0; font-size:.85rem; }
    .img-opts label { display:block; margin:.35rem 0; cursor:pointer; }
    .item.active { background: #33415566; }
    .dest-row { display:grid; grid-template-columns:1fr auto; gap:.5rem; align-items:start; padding:.5rem 0; border-bottom:1px solid #334155; font-size:.85rem; }
    .dest-ok { color:#4ade80; }
    .dest-warn { color:#fbbf24; }
    .dest-bad { color:#f87171; }
    .dest-box { background:#0f172a; border:1px solid #334155; border-radius:8px; padding:.75rem; margin:.5rem 0; font-size:.85rem; }
    .mini-actions { display:flex; gap:.35rem; flex-wrap:wrap; justify-content:flex-end; }
    .web-status-published { color:#4ade80; }
    .web-status-approved { color:#38bdf8; }
    .web-status-review { color:#fbbf24; }
    .web-status-draft { color:#94a3b8; }
  </style>
</head>
<body>
  <header class="ralphi-banner">
    <h1>Ralphi IA <span class="ralphi-ver">v2.0</span></h1>
    <p><em>your second brain</em> · Editorial Hub · LinkedIn y multicanal</p>
  </header>
  <h1 class="page-title" id="t_hub_title">Editorial Hub</h1>
  <p class="sub" id="t_hub_sub">…</p>
  <div class="meta" style="margin-bottom:1rem;display:flex;flex-wrap:wrap;gap:1rem;align-items:center">
    <span>
      <label id="t_panel_lang">Panel</label>
      <select id="panelLang" class="field" style="max-width:220px;display:inline-block;width:auto" onchange="setPanelLang(this.value)"></select>
    </span>
    <span>
      <label id="t_entity_filter">Entidad</label>
      <select id="entityFilter" class="field" style="max-width:260px;display:inline-block;width:auto" onchange="loadDrafts()"></select>
    </span>
  </div>
  <div id="config">…</div>
  <div class="card" id="socialDestPanel" style="margin-bottom:1rem">
    <h2 style="margin:0 0 .5rem;font-size:1rem;color:var(--accent)">Destinos LinkedIn</h2>
    <p class="meta">Entidad editorial ≠ cuenta real. Configura URN de página aquí — sin editar .env.</p>
    <div id="socialAccounts"></div>
  </div>
  <div class="card" id="webAstroPanel" style="margin-bottom:1rem">
    <h2 style="margin:0 0 .5rem;font-size:1rem;color:var(--accent)">Web / Astro interno</h2>
    <p class="meta">Mismo flujo de aprobación, otro canal. Al publicar aquí se exporta para Astro staging interno; LinkedIn sigue separado.</p>
    <button class="btn-muted" onclick="loadWebContent()">Actualizar web</button>
    <button class="btn-ok" onclick="syncCanonicalNow()">Sincronizar inventario canónico</button>
    <button class="btn-primary" onclick="exportAstroNow()">Exportar JSON Astro</button>
    <div id="webContentList"></div>
  </div>
  <div class="grid">
    <div class="card">
      <h2 id="t_queue">Cola</h2>
      <button class="btn-muted" id="t_refresh" onclick="loadDrafts()">Actualizar</button>
      <label class="meta"><input type="checkbox" id="showArchived" onchange="loadDrafts()"/> <span id="t_archived">Archivados</span></label>
      <div id="list"></div>
      <h2 id="t_published" style="margin-top:1rem">Publicados</h2>
      <div id="published"></div>
    </div>
    <div class="card">
      <h2 id="t_editor">Editor</h2>
      <div id="detail"><p class="sub" id="t_select">Selecciona un borrador</p></div>
    </div>
  </div>
<script>
let drafts = [], selected = null, capNotes = [], pubLangs = {}, panelLangs = {}, visOpts = [], UI = {}, entities = [], entityMap = {}, socialAccounts = [], panelLang = localStorage.getItem('ralfia_panel_lang')||'es';

function destStatusClass(s) {
  if (s === 'connected') return 'dest-ok';
  if (s === 'connected_fallback') return 'dest-warn';
  return 'dest-bad';
}

async function loadSocialAccounts() {
  const r = await fetch('/api/editorial/social/accounts');
  const j = await r.json();
  socialAccounts = j.items || [];
  const el = document.getElementById('socialAccounts');
  if (!el) return;
  el.innerHTML = socialAccounts.map(a => `
    <div class="dest-row">
      <div>
        <strong>${esc(a.entity_name||a.label)}</strong>
        <span class="${destStatusClass(a.status)}"> · ${esc(a.status)}</span>
        <div class="meta">${esc(a.destination_summary || a.label || '')}</div>
        <input class="field" style="margin-top:.35rem;font-size:.8rem" id="urn_${esc(a.entity_id)}"
          placeholder="urn:li:organization:… o urn:li:person:…"
          value="${esc(a.author_urn && !a.uses_fallback ? a.author_urn : '')}"/>
      </div>
      <button class="btn-muted" style="margin:0" onclick="saveSocialUrn('${esc(a.entity_id)}')">Guardar URN</button>
    </div>`).join('');
}

async function saveSocialUrn(entityId) {
  const inp = document.getElementById('urn_'+entityId);
  const urn = (inp?.value || '').trim();
  const r = await fetch('/api/editorial/social/accounts/'+encodeURIComponent(entityId), {
    method:'PATCH', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({linkedin_author_urn: urn, linkedin_publish_as: urn.includes('organization') ? 'organization' : 'personal'})
  });
  const j = await r.json();
  if (!j.ok) alert('Error: '+(j.error||'?'));
  else { alert('Guardado — '+ (j.preview?.destination_summary||'')); await loadEntities(); await loadSocialAccounts(); if (selected) selectDraft(selected); }
}

async function refreshDestHint(entityId) {
  const r = await fetch('/api/editorial/social/preview?entity_id='+encodeURIComponent(entityId||''));
  const p = await r.json();
  const hint = document.getElementById('linkedinDestHint');
  const box = document.getElementById('publishDestBox');
  const html = `<span class="${destStatusClass(p.status)}">${esc(p.destination_summary||'—')}</span>` +
    (p.warnings?.length ? '<br/><span class="dest-warn">⚠ '+esc(p.warnings.join(' · '))+'</span>' : '');
  if (hint) hint.innerHTML = html;
  if (box) box.innerHTML = '<strong>Al publicar:</strong><br/>'+html +
    (p.can_publish ? '' : '<br/><span class="dest-bad">Publicación bloqueada hasta configurar URN o confirmar fallback personal.</span>');
  return p;
}

function entityLabel(id){ return entityMap[id]?.name || id || '—'; }

async function loadEntities() {
  const r = await fetch('/api/editorial/entities');
  const j = await r.json();
  entities = j.items || [];
  entityMap = Object.fromEntries(entities.map(e => [e.entity_id, e]));
  const opts = `<option value="">${esc(t('entity_all'))}</option>` +
    entities.map(e => `<option value="${esc(e.entity_id)}">${esc(e.name)}</option>`).join('');
  document.getElementById('entityFilter').innerHTML = opts;
}

function entitySelectOptions(selectedId) {
  const none = `<option value="">${esc(t('entity_none'))}</option>`;
  return none + entities.map(e =>
    `<option value="${esc(e.entity_id)}" ${e.entity_id===selectedId?'selected':''}>${esc(e.name)}</option>`
  ).join('');
}

function t(k){ return UI[k] || k; }

async function loadLangCatalog() {
  const r = await fetch('/api/editorial/languages');
  const j = await r.json();
  pubLangs = j.publication || {};
  panelLangs = j.panel || {};
  visOpts = j.visibility || [];
  const ps = document.getElementById('panelLang');
  ps.innerHTML = Object.entries(panelLangs).map(([c,n])=>`<option value="${c}">${esc(n)}</option>`).join('');
  ps.value = panelLang in panelLangs ? panelLang : 'es';
}

async function setPanelLang(code) {
  panelLang = code; localStorage.setItem('ralfia_panel_lang', code);
  const r = await fetch('/api/editorial/i18n?lang='+encodeURIComponent(code));
  const j = await r.json(); UI = j.strings || {};
  document.getElementById('t_hub_title').textContent = t('hub_title');
  document.getElementById('t_hub_sub').textContent = t('hub_sub');
  document.getElementById('t_queue').textContent = t('queue');
  document.getElementById('t_refresh').textContent = t('refresh');
  document.getElementById('t_archived').textContent = t('show_archived');
  document.getElementById('t_editor').textContent = t('editor');
  document.getElementById('t_select').textContent = t('select_draft');
  document.getElementById('t_published').textContent = t('linkedin_posts');
  document.getElementById('t_panel_lang').textContent = t('panel_lang');
  document.getElementById('t_entity_filter').textContent = t('entity_filter');
  if (selected) selectDraft(selected);
}

async function loadConfig() {
  const r = await fetch('/api/editorial/config');
  const c = await r.json();
  capNotes = (c.linkedin_capabilities && c.linkedin_capabilities.available_now) || [];
  document.getElementById('config').innerHTML =
    `Google API: ${c.google_api ? '✓' : '✗'} · LinkedIn: ${c.linkedin.ready ? '✓' : '✗'} · ` +
    capNotes.slice(0,3).join(' · ');
  loadPublished();
  loadSocialAccounts();
}

async function loadPublished() {
  const r = await fetch('/api/editorial/published?limit=8');
  const j = await r.json();
  const el = document.getElementById('published');
  if (!j.items || !j.items.length) { el.innerHTML = '<p class="meta">—</p>'; return; }
  el.innerHTML = j.items.map(p=>`<div class="meta" style="padding:.35rem 0;border-bottom:1px solid #334155">${esc(p.title||'Post')} · ${esc(p.publication_lang||'')} · <code>${esc((p.linkedin_post_urn||'').slice(-20))}</code></div>`).join('');
}

async function loadWebContent() {
  const r = await fetch('/api/editorial/web-content?limit=30');
  const j = await r.json();
  const el = document.getElementById('webContentList');
  if (!el) return;
  const items = j.items || [];
  if (!items.length) {
    el.innerHTML = '<p class="meta">Sin publicaciones web todavía. Abre un borrador y usa “Crear Web/Astro”.</p>';
    return;
  }
  el.innerHTML = items.map(item => `
    <div class="dest-row">
      <div>
        <strong>${esc(item.title||item.content_id)}</strong>
        <span class="web-status-${esc(item.status||'draft')}"> · ${esc(item.status||'draft')}</span>
        <div class="meta">${esc(item.type||'content')} · /${esc(item.slug||'')} · ${esc((item.updated_at||'').slice(0,19))}</div>
      </div>
      <div class="mini-actions">
        <button class="btn-muted" style="margin:0" onclick="webStatus('${esc(item.content_id)}','review')">Review</button>
        <button class="btn-ok" style="margin:0" onclick="webStatus('${esc(item.content_id)}','approved')">Aprobar</button>
        <button class="btn-primary" style="margin:0" onclick="webStatus('${esc(item.content_id)}','published')">Publicar Astro</button>
      </div>
    </div>`).join('');
}

async function webStatus(contentId, status) {
  const msg = status === 'published'
    ? '¿Publicar en Astro interno ahora? Esto dispara export/rebuild staging.'
    : `¿Cambiar estado web a ${status}?`;
  if (!confirm(msg)) return;
  const r = await fetch('/api/editorial/web-content/'+encodeURIComponent(contentId)+'/status', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({new_status: status, approved_by:'rafael'})
  });
  const j = await r.json();
  if (!j.ok) alert('Error: '+(j.detail||j.error||JSON.stringify(j)));
  else alert(status === 'published' ? 'Publicado/exportándose a Astro interno.' : 'Estado actualizado.');
  loadWebContent();
}

async function exportAstroNow() {
  if (!confirm('¿Exportar contenido publicado a Astro staging ahora?')) return;
  const r = await fetch('/api/editorial/web-content/export-astro', {method:'POST'});
  const j = await r.json();
  if (!j.ok) alert('Error: '+(j.detail||j.error||JSON.stringify(j)));
  else alert(`Exportado para Astro: ${j.exported_count||0} items`);
  loadWebContent();
}

async function syncCanonicalNow() {
  const msg = 'Esto importa/actualiza el inventario canónico de hackathons/proyectos hacia Web/Astro. No publica LinkedIn. ¿Continuar?';
  if (!confirm(msg)) return;
  const r = await fetch('/api/editorial/web-content/sync-canonical', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({default_status:'review', publish_safe_items:true})
  });
  const j = await r.json();
  if (!j.ok) alert('Error: '+(j.detail||j.error||JSON.stringify(j)));
  else alert(`Sincronizado: ${j.created||0} nuevos · ${j.updated||0} actualizados · ${j.skipped||0} omitidos`);
  loadWebContent();
}

async function loadDrafts() {
  const arch = document.getElementById('showArchived')?.checked;
  const ent = document.getElementById('entityFilter')?.value || '';
  let url = '/api/editorial/drafts?include_archived=' + (arch ? 'true' : 'false');
  if (ent) url += '&entity_id=' + encodeURIComponent(ent);
  const r = await fetch(url);
  const j = await r.json();
  drafts = j.items || [];
  const el = document.getElementById('list');
  if (!drafts.length) { el.innerHTML = '<p class="sub">Sin borradores — usa ChatGPT MCP save_pipeline_draft(channel=linkedin)</p>'; return; }
  el.innerHTML = drafts.map(d => `
    <div class="item ${selected===d._id?'active':''}" onclick="selectDraft('${d._id}')">
      <strong>${esc(d.title||d.channel||'Sin título')}</strong>
      <span class="status ${d.status==='ready_for_review'?'review':''}">${esc(d.status)}</span>
      <div class="sub">${esc(d.channel)} · ${esc(entityLabel(d.entity_id))} · ${esc((d.updated_at||'').slice(0,19))}</div>
    </div>`).join('');
}

function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;'); }

function charCount(t){ return (t||'').length; }

function linkedinPreview(title, body, entityId) {
  const ent = entityMap[entityId] || {};
  const avatar = (ent.name || 'RP').slice(0, 2).toUpperCase();
  const head = ent.name ? `${esc(ent.name)}` : 'Rafael · PC Doctor';
  const snip = (body||'').slice(0, 300);
  return `<div class="li-preview"><div class="li-head"><div class="li-avatar">${avatar}</div><div><strong>${head}</strong><br/><span class="meta">Vista previa feed</span></div></div>${esc(snip)}${(body||'').length>300?'…':''}</div>`;
}

async function selectDraft(id) {
  selected = id;
  loadDrafts();
  const r = await fetch('/api/editorial/drafts/'+id);
  const j = await r.json();
  const d = j.draft;
  const pl = d.publication_lang || 'es';
  const vis = d.linkedin_visibility || 'PUBLIC';
  const entId = d.entity_id || '';
  const pubOpts = Object.entries(pubLangs).map(([c,n])=>`<option value="${c}" ${c===pl?'selected':''}>${esc(n)}</option>`).join('');
  const visSel = visOpts.map(v=>`<option value="${v.id}" ${v.id===vis?'selected':''}>${esc(v.label_es||v.id)}</option>`).join('');
  const entSel = entitySelectOptions(entId);
  const locs = d.localizations || {};
  const locBadges = Object.keys(locs).map(l=>`<span class="status">${esc(l)}</span>`).join(' ');
  const img = d.media_path ? `<img class="preview" src="/api/editorial/media?path=${encodeURIComponent(d.media_path)}" alt="preview"/>` : '<p class="sub">Sin imagen</p>';
  const prov = d.image_provider || '';
  const provLabel = prov.startsWith('chatgpt') ? '🟢 ChatGPT (tu imagen)' : (prov.startsWith('google') ? '🟡 Google/Gemini (servidor)' : (prov === 'placeholder' ? '⚪ Placeholder (sin foto LinkedIn)' : (prov ? esc(prov) : 'Sin imagen adjunta')));
  const rejected = d.status === 'rejected';
  document.getElementById('detail').innerHTML = `
    <span class="status ${d.status==='ready_for_review'?'review':''}">${esc(d.status)}</span>
    ${locBadges ? '<p class="meta">Versiones: '+locBadges+'</p>' : ''}
    <p class="meta">${charCount(d.markdown||d.body||'')} / 3000 ${t('chars')}</p>
    <label class="meta">${t('entity')}</label>
    <select id="editEntity" class="field" onchange="saveEntity('${d._id}')">${entSel}</select>
    <p class="meta" id="linkedinDestHint">${esc(entityMap[entId]?.linkedin_label || t('linkedin_default'))}</p>
    <div class="dest-box" id="publishDestBox">Cargando destino…</div>
    <label class="meta">${t('pub_lang')}</label>
    <select id="pubLang" class="field" onchange="changePubLang('${d._id}')">${pubOpts}</select>
    <label class="meta">${t('visibility')}</label>
    <select id="visLang" class="field" onchange="saveVisibility('${d._id}')">${visSel}</select>
    <input class="field" id="editTitle" value="${esc(d.title||'')}"/>
    <textarea class="field" id="editBody">${esc(d.markdown||d.body||'')}</textarea>
    ${linkedinPreview(d.title, d.markdown||d.body||'', entId)}
    <p class="meta"><strong>Imagen:</strong> ${provLabel}</p>
    ${img}
    <div class="img-opts">
      <label><input type="checkbox" id="optTitleOverlay" checked/> ${t('title_overlay')}</label>
      <input class="field" id="optOverlay" placeholder="${t('custom_overlay')}"/>
      <label class="meta"><input type="checkbox" id="optAiText"/> ${t('allow_ai_text')}</label>
    </div>
    <button class="btn-primary" onclick="saveDraft('${d._id}')">${t('save')}</button>
    <button class="btn-primary" onclick="translateDraft('${d._id}')">${t('translate')}</button>
    <button class="btn-primary" onclick="genImage('${d._id}')">${t('regen_image')}</button>
    <button class="btn-primary" onclick="createWebFromDraft('${d._id}')">Crear Web/Astro</button>
    <button class="btn-muted" onclick="copyPost()">${t('copy')}</button>
    <button class="btn-muted" onclick="duplicateDraft('${d._id}')">${t('duplicate')}</button>
    ${rejected ? `<button class="btn-muted" onclick="reopenDraft('${d._id}')">${t('reopen')}</button>` : ''}
    <button class="btn-ok" onclick="approveOnly('${d._id}')">${t('approve')}</button>
    <button class="btn-ok" onclick="publishNow('${d._id}')">${t('publish')}</button>
    <button class="btn-danger" onclick="reject('${d._id}')">${t('archive')}</button>
    <p class="meta">${t('archived_hint')}</p>`;
  refreshDestHint(entId);
}

async function saveEntity(id) {
  const entity_id = document.getElementById('editEntity')?.value || '';
  await fetch('/api/editorial/drafts/'+id, {
    method:'PATCH', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({entity_id})
  });
  await loadEntities();
  await refreshDestHint(entity_id);
  loadDrafts();
}

async function changePubLang(id) {
  const lang = document.getElementById('pubLang').value;
  const r = await fetch('/api/editorial/drafts/'+id, {
    method:'PATCH', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({publication_lang: lang})
  });
  const j = await r.json();
  if (j.draft && j.draft.localizations && j.draft.localizations[lang]) selectDraft(id);
  else if (confirm('¿Traducir a '+lang+'?')) translateDraft(id, lang);
  else selectDraft(id);
}

async function translateDraft(id, forcedLang) {
  const lang = forcedLang || document.getElementById('pubLang')?.value || 'en';
  const r = await fetch('/api/editorial/drafts/'+id+'/translate', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({target_lang: lang})
  });
  const j = await r.json();
  if (!j.ok) alert('Error traducción');
  else { alert('OK → '+lang); selectDraft(id); }
}

async function saveVisibility(id) {
  const v = document.getElementById('visLang').value;
  await fetch('/api/editorial/drafts/'+id, {
    method:'PATCH', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({linkedin_visibility: v})
  });
}

async function duplicateDraft(id) {
  const r = await fetch('/api/editorial/drafts/'+id+'/duplicate', {method:'POST'});
  const j = await r.json();
  if (j.draft) { selectDraft(j.draft._id); loadDrafts(); }
}

async function saveDraft(id) {
  const title = document.getElementById('editTitle').value;
  const markdown = document.getElementById('editBody').value;
  const r = await fetch('/api/editorial/drafts/'+id, {
    method:'PATCH', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({title, markdown})
  });
  const j = await r.json();
  if (!j.ok) alert('Error guardando');
  else { alert('Guardado'); selectDraft(id); loadDrafts(); }
}

async function createWebFromDraft(id) {
  const type = prompt('Tipo para web: hackathon o project', 'hackathon') || 'hackathon';
  const slug = prompt('Slug URL interno (opcional, sin espacios). Si lo dejas vacío se genera desde el título.', '') || '';
  const status = confirm('¿Mandar directo a revisión web? Aceptar = review, Cancelar = draft') ? 'review' : 'draft';
  const r = await fetch('/api/editorial/web-content/from-draft/'+encodeURIComponent(id), {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({content_type:type, slug:slug||null, visibility:'internal', theme:'living-lab', status})
  });
  const j = await r.json();
  if (!j.ok) alert('Error: '+(j.detail||j.error||JSON.stringify(j)));
  else alert('Creado para Web/Astro: '+j.content.content_id);
  loadWebContent();
}

function copyPost() {
  const t = document.getElementById('editBody')?.value || '';
  navigator.clipboard.writeText(t).then(()=>alert('Copiado'));
}

async function reopenDraft(id) {
  await fetch('/api/editorial/drafts/'+id+'/reopen', {method:'POST'});
  alert('Reabierto — ya puedes editar');
  loadDrafts(); selectDraft(id);
}

async function genImage(id) {
  const useTitle = document.getElementById('optTitleOverlay')?.checked;
  const overlay = document.getElementById('optOverlay')?.value || '';
  const includeAiText = document.getElementById('optAiText')?.checked || false;
  const r0 = await fetch('/api/editorial/drafts/'+id);
  const cur = (await r0.json()).draft;
  if (cur?.image_provider?.startsWith('chatgpt') && !confirm('Ya hay imagen de ChatGPT. ¿Sustituir por Google/Gemini?')) return;
  const r = await fetch('/api/editorial/drafts/'+id+'/generate-image', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({include_ai_text: includeAiText, overlay_text: overlay, use_title_overlay: useTitle, overlay_lang: document.getElementById('pubLang')?.value || 'es'})
  });
  const j = await r.json();
  if (!j.ok) alert('Error: '+(j.detail||JSON.stringify(j)));
  else {
    const p = j.draft?.image_provider || '';
    const msg = p.startsWith('chatgpt')
      ? 'Imagen ChatGPT guardada ('+p+') — LinkedIn usará esta foto.'
      : (p === 'placeholder'
      ? 'Placeholder (Google falló) — preview OK; LinkedIn irá solo texto si publicas.'
      : 'Imagen Google/Gemini ('+p+')');
    alert(msg);
    selectDraft(id);
  }
}

async function approveOnly(id) {
  if (!confirm('¿Aprobar borrador sin publicar en LinkedIn?')) return;
  const r = await fetch('/api/editorial/drafts/'+id+'/approve', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({publish_now:false})
  });
  const j = await r.json();
  if (!j.ok) alert('Error: '+(j.error||JSON.stringify(j)));
  else alert('Aprobado — en cola. Usa Publicar cuando estés listo.');
  loadDrafts(); selectDraft(id);
}

async function publishNow(id) {
  const entity_id = document.getElementById('editEntity')?.value || '';
  const preview = await refreshDestHint(entity_id);
  let allowFallback = false;
  let msg = 'DESTINO LINKEDIN\\n\\n' + (preview.destination_summary||'?');
  if (preview.warnings?.length) msg += '\\n\\n⚠ ' + preview.warnings.join('\\n⚠ ');
  if (!preview.can_publish) {
    if (preview.allow_fallback_option) {
      if (!confirm(msg + '\\n\\n¿Publicar en PERFIL PERSONAL como fallback? (solo si lo confirmas)')) return;
      allowFallback = true;
    } else {
      alert(msg + '\\n\\nPublicación bloqueada. Configura URN en Destinos LinkedIn arriba.');
      return;
    }
  } else {
    if (!confirm(msg + '\\n\\n¿Publicar AHORA en LinkedIn? Acción irreversible.')) return;
  }
  const r = await fetch('/api/editorial/drafts/'+id+'/approve', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({publish_now:true, allow_personal_fallback: allowFallback})
  });
  const j = await r.json();
  if (j.publish && !j.publish.ok) {
    const err = j.publish.error || JSON.stringify(j.publish);
    alert(j.publish.blocked ? ('Bloqueado:\\n'+err+'\\n\\n'+(j.publish.hint||'')) : ('Aprobado pero LinkedIn: '+err));
  }
  else if (j.publish?.ok) {
    let msg = 'Publicado: '+j.publish.linkedin_urn;
    if (j.publish.publish_mode==='text_only') msg += ' (solo texto, sin imagen)';
    if (j.publish.publish_mode==='text_only_fallback') msg += ' (solo texto — falló imagen: '+(j.publish.image_error||'?')+')';
    if (j.publish.author?.warning) msg += '\\n\\n⚠ '+j.publish.author.warning;
    alert(msg);
  }
  else alert('En cola — revisa estado.');
  loadDrafts(); selectDraft(id);
}

async function approve(id) { return approveOnly(id); }

async function reject(id) {
  const reason = prompt('Motivo archivar (opcional):')||'';
  await fetch('/api/editorial/drafts/'+id+'/reject', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({reason})
  });
  alert('Archivado — no se borra. Marca «Ver archivados» para reabrir.');
  selected=null; loadDrafts();
  document.getElementById('detail').innerHTML='<p class="sub">Archivado — recuperable en la lista</p>';
}

loadLangCatalog().then(()=>loadEntities()).then(()=>setPanelLang(panelLang)).then(()=>{ loadConfig(); loadDrafts(); loadWebContent(); });
setInterval(loadDrafts, 30000);
setInterval(loadWebContent, 45000);
</script>
</body>
</html>"""


@router.get("/api/editorial/media")
def serve_media(path: str):
    from pathlib import Path

    p = Path(path)
    allowed = Path("/home/rlopez/data/media")
    try:
        p.resolve().relative_to(allowed.resolve())
    except ValueError:
        raise HTTPException(403, "path not allowed")
    if not p.is_file():
        raise HTTPException(404)
    from fastapi.responses import FileResponse

    return FileResponse(p)
