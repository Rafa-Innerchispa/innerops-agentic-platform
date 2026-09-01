# LinkedIn — entidad, cuenta y visibilidad

**Actualizado:** 2026-09-01 · Codex

---

## Modelo correcto: una conexión, cuatro entidades

El sistema editorial maneja cuatro entidades:

| entity_id | Entidad | Tipo LinkedIn | Estado esperado |
|-----------|---------|---------------|-----------------|
| `ent_rafael_personal` | Rafael López | Perfil personal | Token + `urn:li:person:...` |
| `ent_innerchispa` | InnerChispa | Página empresa | `urn:li:organization:...` |
| `ent_pcdoctor` | PC Doctor | Página empresa | `urn:li:organization:...` |
| `ent_innerspark` | InnerSpark | Página empresa | Crear página primero, luego URN |

LinkedIn no ofrece una API general para “controlar toda la cuenta” sin OAuth.
El camino correcto es **una app LinkedIn** autorizada por tu usuario, con scopes
de perfil y organización. Si tu usuario es administrador de InnerChispa, PC
Doctor e InnerSpark, el mismo token puede publicar en esas páginas usando URNs
distintos.

## Por qué una marca puede caer al perfil personal

Hay **un solo token** LinkedIn (`LINKEDIN_ACCESS_TOKEN`), pero **dónde** publica lo define el **URN del autor**:

| Campo | Dónde |
|-------|--------|
| `LINKEDIN_AUTHOR_URN` (.env / panel) | **Fallback** — perfil personal Rafael |
| `entities.linkedin_author_urn` (Mongo) | **Por marca** — persona o página empresa |

**Regla en código** (`editorial_social.resolve_for_publish`):

1. Rafael personal puede usar fallback `.env`.
2. Páginas empresa requieren `entities.linkedin_author_urn`.
3. Sin URN de página → queda bloqueado hasta configurar la página, salvo que Rafael confirme fallback personal explícito.

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

Hoy el servidor usa **un token global**. Cada entidad diferencia **URN** (destino), no token distinto.

Scopes mínimos para el flujo:

- `w_member_social` — publicar como Rafael.
- `w_organization_social` — publicar como páginas empresa.
- `r_organization_admin` o acceso equivalente de Marketing Developer Platform — descubrir páginas administradas con `organizationAcls`.
- `openid`/`profile` o `r_liteprofile` equivalente — validar identidad del token.

---

## Cómo configurar cada marca

### 1. Obtener URNs

```bash
# Persona (token actual)
curl -H "Authorization: Bearer TOKEN" https://api.linkedin.com/v2/me

# Organización — el sistema puede intentar listar páginas administradas:
curl http://SERVER:8101/api/editorial/linkedin/organizations
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
| `ent_innerspark` | InnerSpark | página pendiente de crear/configurar |

## Diagnóstico sin publicar

```bash
curl http://SERVER:8101/api/editorial/linkedin/diagnostics
curl http://SERVER:8101/api/editorial/linkedin/organizations
curl http://SERVER:8101/api/editorial/social/accounts
```

Si `organizations` devuelve 403, no es fallo del código: falta producto/scope
LinkedIn o el usuario no es admin de la página.

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
