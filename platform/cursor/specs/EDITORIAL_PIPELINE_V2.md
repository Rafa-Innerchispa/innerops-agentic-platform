# Editorial Pipeline v2 — Estudio IA (LinkedIn)

**Owner:** Cursor · **MCP OAuth/stream:** Codex (no tocar en paralelo)  
**Estado:** P0 fix aplicado · P1 spec · P2 preview studio

---

## Diagnóstico (prueba ChatGPT jul 2026)

| Síntoma | Causa real |
|---------|------------|
| `approve_pipeline_draft` → `published` | **Worker** `ralfia-editorial-worker` publicaba cola `queued` cada 90s |
| UI `:8101/editorial` publicaba al aprobar | `ApproveBody.publish_now=True` por defecto |
| Imagen con letras corruptas | Prompt pedía `clean typography` |
| ChatGPT no adjunta imagen | No existen tools `attach_media_*` aún |

**Fix P0 (Cursor, aplicado):**
- Worker: `EDITORIAL_AUTO_PUBLISH=0` por defecto — no auto-publica
- UI approve: `publish_now=False` por defecto
- `publish_pipeline_item(confirm=True)` obligatorio desde MCP
- Prompt Imagen: reglas `no text`, `no typography`, etc.

---

## Estados objetivo

```
draft → image_pending → ready_for_review → approved → queued → scheduled → publishing → published
                                                              ↘ failed / rejected
```

| Estado | Quién lo pone |
|--------|---------------|
| `draft` | `save_pipeline_draft` |
| `image_pending` / `generating_image` | `generate_draft_image` |
| `ready_for_review` | tras imagen adjunta |
| `approved` | `approve_pipeline_draft` (solo aprueba) |
| `queued` | `queue_pipeline_item` (P1) |
| `published` | **solo** `publish_pipeline_item(confirm=True)` o botón UI |

---

## Separación de responsabilidades

| Tool / acción | Hace | NO hace |
|---------------|------|---------|
| `save_pipeline_draft` | Guarda texto | Imagen, publicar |
| `generate_draft_image` | Imagen + Visual Director (P1) | Publicar |
| `approve_pipeline_draft` | Aprueba → post + cola | Publicar LinkedIn |
| `queue_pipeline_item` | P1 — encola explícito | Publicar |
| `publish_pipeline_item(confirm=True)` | LinkedIn | Aprobar contenido |

---

## Visual Director Agent (P1)

```
draft metadata → visual_director.py → direction JSON → prompt_builder.py → Google Imagen
```

Salida direction: concepto, metáfora, emoción, composición, obligatorios, prohibidos.

**Owner sugerido:** Antigravity (Google Imagen) + Cursor (integración).

---

## Colección `editorial_media` (P1)

Campos: `draft_id`, `provider`, `source`, `media_path`, `prompt`, `visual_direction`, `version`, `status`, `width`, `height`, `mime`, `created_at`.

Tools MCP nuevas:
- `attach_media_to_draft`
- `upload_draft_media`
- `regenerate_draft_image`
- `set_primary_media`
- `remove_media`
- `list_media`

---

## Preview Web (P1 — centro del flujo)

URL: `http://192.168.1.4:8101/editorial?draft={id}`

| Panel izquierdo | Panel derecho |
|-----------------|---------------|
| Post completo | Estado, prompt, provider |
| Simulación LinkedIn | Historial, metadata |
| Imagen | Botones acción |

Botones: Publicar ahora · Programar · Editar · Regenerar imagen · Subir imagen · Rechazar.

**Regla:** ningún botón publica sin confirmación explícita.

---

## MCP — límites Codex vs Cursor

| Tema | Owner |
|------|-------|
| OAuth, refresh token, Android re-auth | **Codex** |
| `mcp_version`, `system_debug`, stream gateway | **Codex** |
| `write_agent_message` bloqueado por OpenAI safety | ChatGPT cliente — renombrar/descripción tool (Codex propone) |
| Editorial pipeline, imagen, LinkedIn publish | **Cursor** |
| Visual Director Google | **Antigravity** |

---

## Flujo ideal ChatGPT

1. Redactar → `save_pipeline_draft(status=draft)`
2. `generate_draft_image(draft_id)` — revisar en `:8101/editorial`
3. Rafael preview → editar si hace falta
4. `approve_pipeline_draft(draft_id)` — **no publica**
5. Rafael confirma → `publish_pipeline_item(id, confirm=True)` **o** botón UI

**Prohibido en ChatGPT:** llamar `approve` y asumir que no publicó — verificar status antes de `publish`.
