# Nomenclatura Ralfi IA — vigente 2026-08-05

## Marca

| Escribir | No usar |
|----------|---------|
| **Ralfi IA** | Ralphi IA, RalfiIA, RalphIA, RaphiIA (solo en código legacy Python `raphiia_openai`) |
| **Ralfi IA Platform** | raphiia-openai (nombre carpeta legacy → symlink) |

## Árbol raíz `/home/rlopez/projects/`

```
ralfi-ia-platform/      ← Operación multi-empresa (kernel + módulos)
ralfi-ia-personal/      ← Salud, memoria, espiritualidad, libros (Rafael López)
iskcon/                 ← ISKCON (vertical espiritual, NO dentro de plataforma)
ralfi-ia-infra/         ← Dual-nodo .4/.5, sync, Docker ops
hackathons/             ← Symlinks a pilotos aislados (reutilizan MCP)
```

**Symlinks legacy (compatibilidad servicios):** `raphiia-openai`, `ralfiia-amd-standby`, `iskcon-panihati-2026`

## Ralfi IA Platform — interior

```
ralfi-ia-platform/
├── companies/              ← Multi-empresa (cada una factura)
│   ├── innerchispa/        InnerChispa LLC
│   ├── pcdoctor/           PC Doctor S.A.
│   ├── rafael-lopez/       Rafael López (personal)
│   ├── ralfi-ia/           Kernel plataforma (ent_ralfia)
│   ├── iskcon/             Referencia ISKCON (repo separado)
│   └── template/           Clon para nuevo cliente
├── modules/
│   ├── accounting/         MOD-ACCOUNTING + Contifico archive
│   ├── quoting/            QuoteOps + Smart Quoter
│   ├── inventory/          Stock, productos, ofertas
│   ├── pcdoctor-ops/       Clientes, sitios, visitas, informes
│   ├── home-assistant/     Domótica (puente HA)
│   ├── coordination/       Agentes, INBOX
│   └── portal-mcp/         Panel :2002 + MCP :8102
├── connectors/             APIs externas (contifico, notion, gdrive, email, whatsapp)
├── raphiia_openai/         ← Paquete Python (renombrar en fase 2)
└── infra/systemd/          Units systemd
```

## Reglas

1. **Empresa ≠ carpeta repo** — una empresa = `companies/<slug>/config/entity.yaml` + `entity_id` en Mongo.
2. **ISKCON nunca dentro de platform ops** — repo `iskcon/` aparte; solo referencia en `companies/iskcon/`.
3. **Personal nunca mezclado con `ops_clients`** — repo `ralfi-ia-personal/` + entity `ent_rafael_personal`.
4. **Hackathon = repo aislado** — enlace en `hackathons/`; no duplicar kernel.
5. **Replicar cliente** = copiar `companies/template/` + desplegar stack Ralfi IA Platform.

## entity_id canónicos (Mongo `entities`)

| entity_id | Nombre | Tipo |
|-----------|--------|------|
| `ent_ralfia` | Ralfi IA | platform |
| `ent_pcdoctor` | PC Doctor S.A. | organization |
| `ent_innerchispa` | InnerChispa LLC | organization |
| `ent_innerspark` | InnerSpark | organization |
| `ent_domotika` | Domotika | organization |
| `ent_rafael_personal` | Rafael López | personal |
| `ent_iskcon` | ISKCON | organization |
| `ent_creatoros` | CreatorOS | platform |
| `ent_TEMPLATE` | Plantilla nuevo cliente | template |

**Fuente de verdad:** `companies/ENTITIES_CANONICAL.yaml`
