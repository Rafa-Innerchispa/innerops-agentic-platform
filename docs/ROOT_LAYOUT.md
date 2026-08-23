# InnerOS Core — Layout raíz (canónico)

**ROOT:** `/home/rlopez/inneros/`  
**CORE:** `/home/rlopez/inneros/inneros_core/`  
**Marca producto:** InnerOS (InnerChispa Operating System) · operado con Ralfi IA

---

## Por qué esta raíz

| Decisión | Razón |
|----------|-------|
| `~/inneros/` en home de Rafael | Producto InnerChispa — replicable a clientes |
| `inneros_core/` dentro | Lo que se clona (código + config), no datos sensibles |
| `agents_pool/` dentro del core | AG-xx usados por MCP, scripts, hackathons |
| `platform/` = MCP + conectores + MOD-* | Un solo paquete Python (`raphiia_openai` → futuro `inneros_platform`) |
| `tenants/` separado de `companies/` | **companies/** = config legal/branding · **tenants/** = runtime + data paths |
| Datos en `~/data/tenants/<slug>/` | Clonar core **sin** arrastrar Mongo/Contifico PC Doctor |

---

## Árbol completo

```
/home/rlopez/inneros/
├── README.md
├── INNEROS_ENV.sh                 # export INNEROS_* (source en shell/systemd)
└── inneros_core/
    ├── agents_pool/               # AG-01…AG-36
    │   └── AG-07_notion_cosmos_orchestrator/
    │       ├── config/agent.yaml
    │       └── src/logic.py
    │
    ├── platform/                  # ← TODO EL CÓDIGO MCP (migrado desde raphiia-openai)
    │   ├── raphiia_openai/
    │   │   ├── mcp_server.py      # MCP :8102
    │   │   ├── mcp_catalog/
    │   │   ├── contifico_*.py     # → futuro connectors/contifico/
    │   │   ├── notion_*.py
    │   │   ├── operational/       # → futuro modules/
    │   │   └── agents/registry.py
    │   ├── systemd/user/          # units (migrar a infra/systemd)
    │   ├── venv/
    │   ├── .env
    │   └── scripts/
    │
    ├── companies/                 # Config multi-empresa (git)
    │   ├── ENTITIES_CANONICAL.yaml
    │   ├── pcdoctor/config/entity.yaml
    │   ├── innerchispa/config/entity.yaml
    │   └── template/config/entity.yaml
    │
    ├── tenants/                   # Runtime por tenant (pcdoctor excluido en clone)
    │   ├── pcdoctor/tenant.yaml    # PC Doctor — producción EC
    │   ├── innerchispa/tenant.yaml # InnerChispa — US
    │   └── template/tenant.yaml
    │
    ├── modules/                   # Apps con puerto propio
    │   ├── quoteops → projects/ralphiia-quoteops
    │   └── smart-quoter → projects/innerspark-smart-quoter
    │
    ├── services/                  # Entrypoints delgados (fase siguiente)
    ├── infra/systemd/
    ├── docs/
    └── scripts/
        ├── migrate_to_inneros_root.sh
        └── clone_deployment.sh    # Clonar SIN pcdoctor
```

---

## Multi-tenant: PC Doctor + InnerChispa

| | PC Doctor | InnerChispa |
|---|-----------|-------------|
| **tenant_id** | `pcdoctor` | `innerchispa` |
| **entity_id** | `ent_pcdoctor` | `ent_innerchispa` |
| **País/moneda** | EC / USD | US / USD |
| **WhatsApp** | chip primary · `RalphiIA-pcdoctor` | chip AMD · `Innerchispa` |
| **Datos** | `~/data/tenants/pcdoctor/` | `~/data/tenants/innerchispa/` |
| **Mongo** | `ops_*`, `contifico_*`, `accounting_*` | `innerchispa_*`, quotes |

Ambos comparten **mismo core** (MCP, agents_pool, módulos). El filtro es `entity_id` + namespace Mongo.

---

## Replicar para cliente nuevo (sin PC Doctor)

```bash
bash /home/rlopez/inneros/inneros_core/scripts/clone_deployment.sh \
  acme-corp ent_acme /opt/inneros-acme
```

Excluye automáticamente:
- `tenants/pcdoctor/`
- `.env` y `venv/` (reconfigurar en destino)

Incluye:
- `agents_pool/` completo
- `platform/` código
- `innerchispa/` como referencia de tenant US
- `template/` para nuevo slug

---

## Acceso usuarios vs admins

```
Admin (SSH)  ──►  ~/inneros/  (filesystem completo)
Usuario      ──►  Portal :2002 + OAuth  (sin shell)
Revisor      ──►  SSH restringido + grupo inneros-review (solo lectura)
```

---

## Fuera de InnerOS (no clonar)

| Ruta | Contenido |
|------|-----------|
| `~/data/` | Mongo dumps, ai_coordination, notion_export |
| `~/inneros/projects/inneros/` | RAG legacy Cognee (fase absorción) |
| `~/projects/iskcon/` | Vertical espiritual |
| `~/projects/hackathons/` | Pilotos aislados |
| `~/ralfi-ia-personal/` | Memoria privada Rafael |

---

## Compatibilidad legacy

Symlinks activos:
- `~/inneros_core` → `inneros/inneros_core/agents_pool`
- `~/projects/raphiia-openai` → `inneros/inneros_core/platform`
- `~/projects/ralfi-ia-platform` → `inneros/inneros_core`

Systemd existente sigue funcionando vía symlinks hasta actualizar units.

---

*Actualizado: 2026-08-05*
