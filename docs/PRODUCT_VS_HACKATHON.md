# Producto vs Hackathon — reglas InnerOS

## Regla de oro

**InnerOS (plataforma empresa) NO depende de carpetas hackathon.**  
Los hackathons siguen en `~/projects/<hackathon>/`, activos e independientes.

```
InnerOS ──HTTP/MCP──► Productos vendibles (quoteops, workforce-ai)
InnerOS ──X──► NO imports ni paths hardcoded a hackathons
Hackathon ──opcional──► consume producto InnerOS vía API
```

---

## Tres tipos de repo

| Tipo | `kind` | Ejemplo | ¿InnerOS depende? | ¿Hackathon? |
|------|--------|---------|-------------------|-------------|
| **Plataforma** | `platform` | `~/inneros/inneros_core/` | — (es el kernel) | No |
| **Producto vendible** | `product` | `innerspark-workforce-ai`, `ralphiia-quoteops` | Solo vía **HTTP/MCP/symlink modules/** | Puede **demostrarse** en hackathon |
| **Hackathon puro** | `hackathon` | `hackathon-autopilot`, `ralphiia-liveops-intelligence` | **Nunca** | Sí, solo imagen/demo |

---

## Producto usado en hackathon (Workforce AI)

Un mismo repo puede ser **producto** y **demo de hackathon**:

```yaml
# config/products/workforce-ai.yaml
product_id: workforce-ai
repo: ~/projects/innerspark-workforce-ai
kind: product
sellable: true
entity_id: ent_innerchispa
hackathon_profiles:
  - event: "Nombre convocatoria 2026"
    branch: hackathon/xxx          # solo en el repo producto
    uses_platform_mcp: true        # el hackathon llama MCP, no al revés
platform_integration:
  mode: http                       # mcp | http | none
  port: null                       # definir cuando se integre
```

**Diferencia clave:**

| Aspecto | Producto | Hackathon |
|---------|----------|-----------|
| Repo | Propio, versionado, vendible | Propio, deadline, demo |
| Datos | Mongo tenant / product DB | Datos demo o snapshot |
| Deploy | systemd / módulo InnerOS | Puerto temporal + ngrok |
| InnerOS | Expone API; **no lee** su carpeta | No es dependencia de ops |
| Tras hackathon | Sigue en catálogo productos | Archivo en portfolio; repo intacto |

---

## Qué puede referenciar InnerOS

| Permitido | Ruta / mecanismo |
|-----------|------------------|
| Infra ops | `ralfiia-amd-standby/` (sync, ollama) |
| Módulos producto | `inneros_core/modules/quoteops` → symlink |
| Agent pool | `inneros_core/agents_pool/` |
| Datos tenant | `~/data/tenants/pcdoctor`, `innerchispa` |
| Portal UI | `innerspark-swarm-os-cursor-local` (fase separación) |

| **Prohibido en código platform** | Alternativa |
|-----------------------------------|-------------|
| Paths a `hackathon-autopilot/` | Env `INNEROS_WEB_STAGING_DIR` (opcional, editorial) |
| Imports Python desde hackathon | API HTTP o MCP |
| Mongo `hackathon_autopilot` en ops críticos | Solo tools editoriales opt-in |

Registro machine-readable: `config/REPO_REGISTRY.yaml`

---

## Hackathons activos (imagen — no tocar ops)

Repos en `~/projects/` — **sin mover**, cada uno con su systemd/puerto:

- `hackathon-autopilot` (:8090)
- `hackathon-funding-hub` (:8099)
- `ralphiia-liveops-intelligence` (:8788)
- `amd-ralfiia-hybrid-ops-copilot` (:8220)
- `uipath-copilot`, `gitlab-transcend`, etc.

InnerOS puede **listar** en portfolio web (editorial) — no **depender** para MCP/contabilidad/WhatsApp.

---

## Futuro

1. Nuevos hackathons → solo en `~/projects/`, nunca dentro `inneros_core/`
2. Nuevos productos → `config/products/` + symlink en `modules/`
3. Workforce AI → producto en catálogo; hackathon usa branch + MCP
