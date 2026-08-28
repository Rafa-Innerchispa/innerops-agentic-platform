# LinkedIn — entidad, cuenta y visibilidad

**Actualizado:** 2026-07-06 · Cursor

---

## Por qué InnerChispa publicaba en tu perfil personal

Hay **un solo token** LinkedIn en el panel (`LINKEDIN_ACCESS_TOKEN`), pero **dónde** publica lo define el **URN del autor**:

| Campo | Dónde |
|-------|--------|
| `LINKEDIN_AUTHOR_URN` (.env / panel) | **Fallback** — perfil personal Rafael |
| `entities.linkedin_author_urn` (Mongo) | **Por marca** — persona o página empresa |

**Regla en código** (`entity_linkedin.resolve_author_urn`):

1. Si la entidad del borrador tiene `linkedin_author_urn` → usa esa cuenta.
2. Si está **vacío** (InnerChispa, PC Doctor, InnerSpark hoy) → **cae al URN del .env** = tu perfil personal.

Por eso elegir «InnerChispa» en el selector **no cambiaba** el destino hasta que configures el URN de esa entidad.

---

## Tipos de cuenta LinkedIn

| Publicar como | URN ejemplo | Scope OAuth típico |
|---------------|-------------|-------------------|
| **Persona** (Rafael) | `urn:li:person:ABC123` | `w_member_social` |
| **Página empresa** (PC Doctor, InnerSpark…) | `urn:li:organization:987654` | `w_organization_social` |

**Visibilidad** (selector editorial): `PUBLIC` o `CONNECTIONS` — aplica al post, no elige la cuenta.

---

## ¿Una app LinkedIn o varias?

| Enfoque | Cuándo |
|---------|--------|
| **Una app** con `w_member_social` + `w_organization_social` | Recomendado si tú eres admin de todas las páginas |
| **Varias apps** | Solo si marcas separadas / tokens distintos por cliente |

Hoy el servidor usa **un token global**. Cada entidad diferencia **URN** (destino), no token distinto (P2 futuro si hace falta).

---

## Cómo configurar cada marca

### 1. Obtener URNs

```bash
# Persona (token actual)
curl -H "Authorization: Bearer TOKEN" https://api.linkedin.com/v2/me

# Organización — ID numérico de la página en LinkedIn → urn:li:organization:ID
```

### 2. Asignar en panel

**Panel :2002** → Proyectos y configuración → **Entidades LinkedIn**  
o **Admin :5173/entities**

Campos por entidad:

- `linkedin_author_urn` — obligatorio para publicar **como esa marca**
- `linkedin_publish_as` — `person` | `organization`

### 3. Seed actual (Mongo `entities`)

| entity_id | Nombre | URN hoy |
|-----------|--------|---------|
| `ent_rafael_personal` | Rafael personal | ✅ usa `.env` |
| `ent_innerchispa` | InnerChispa | ❌ vacío → fallback personal |
| `ent_pcdoctor` | PC Doctor | ❌ vacío → fallback personal |
| `ent_innerspark` | InnerSpark | ❌ vacío → fallback personal |

---

## Imagen que no llega (ChatGPT / editorial)

Causas frecuentes:

1. **`media_path` vacío o archivo no existe** → publica **solo texto** (sin error visible antes).
2. **Upload LinkedIn falla** → ahora hay **fallback a texto** + `image_error` en respuesta.
3. **Imagen placeholder** (`image_provider=placeholder`) → se ignora a propósito.

Flujo correcto con ChatGPT:

```
upload_draft_media(...)  o  generate_draft_image(draft_id)
→ approve_pipeline_draft
→ publish_pipeline_item  (o botón Publicar en :8101/editorial)
```

Tras publicar, revisa `get_publish_logs()` — campo `publish_mode`: `with_image` | `text_only` | `text_only_fallback`.

---

## Smart Quoter vs Antigravity (sin conflicto)

Cursor **no modificó** el código de Antigravity en `/home/rlopez/projects/innerspark-smart-quoter/` (`main.py`, UI).

Cursor solo añadió **ops**: systemd `ralfia-smart-quoter`, tarjeta panel :2002, registry, docs coordinación.

Antigravity sigue dueño del MVP frontend + flujo cotización.
