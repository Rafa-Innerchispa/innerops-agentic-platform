# Destinos sociales editorial — spec

**Actualizado:** 2026-07-06 · Cursor (handoff ChatGPT P0 editorial)

---

## Dos conceptos separados

| Concepto | Colección | Qué es |
|----------|-----------|--------|
| **Entidad editorial** | `entities` | Marca, tono, metadata (InnerChispa, PC Doctor…) |
| **Cuenta LinkedIn** | `editorial_linkedin_accounts` | Dónde publica de verdad (URN + tipo) |

Cola de publicación: `social_destinations` (post en cola → LinkedIn API).

---

## Reglas de publicación

1. **Rafael personal** (`ent_rafael_personal`) — conectado vía token + URN `.env`.
2. **Páginas empresa** — requieren `linkedin_author_urn` = `urn:li:organization:ID`.
3. **Sin URN de página** → publicación **bloqueada** (no silenciosa).
4. **Fallback personal** — solo si Rafael confirma explícitamente en el diálogo de publicar.

---

## UI

Panel **http://192.168.1.4:8101/editorial** → sección **Destinos LinkedIn**:

- Estado por entidad (connected / missing_config / connected_fallback)
- Campo URN editable sin SSH
- Preview destino antes de publicar

---

## APIs

| Método | Ruta |
|--------|------|
| GET | `/api/editorial/social/accounts` |
| GET | `/api/editorial/social/preview?entity_id=` |
| PATCH | `/api/editorial/social/accounts/{entity_id}` |

---

## LinkedIn — persona vs página

- Páginas dependen del perfil personal como admin en LinkedIn.
- **Un token** puede servir si la app tiene `w_member_social` + `w_organization_social`.
- Cada entidad usa **URN distinto** — no hace falta app distinta por marca (fase 1).

Ver también `docs/ENTITY_LINKEDIN.md`.
