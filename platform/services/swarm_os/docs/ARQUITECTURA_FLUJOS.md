# Arquitectura — ¿Por qué no las 52 bases en cada flujo?

## Respuesta corta

**Las 52 DBxx son todo el OS Central** (empresa completa: finanzas, editorial, grants, research, domótica, ISKCON, InnerSpark…).

**Cada operación del día usa solo el subconjunto que necesita.**  
No cotizas CCTV pasando por DB15 editorial ni DB35 grants.

Es como un hospital: tiene 40 departamentos, pero una consulta de urgencias solo activa 5.

---

## Tres capas

| Capa | Qué es | Cuántas DB |
|------|--------|------------|
| **A. Infraestructura de datos** | Todas las colecciones Mongo creadas y listas | 52 + hub + documents + … |
| **B. Flujos operativos** | Cadenas SOP para tareas concretas | 5 registrados en `_flow_registry` |
| **C. Flujo código activo hoy** | Lo que `crew.py` ejecuta end-to-end | 1 flujo: **Campo PC Doctor** |

---

## Flujo activo en código (Fase A)

**Tarea:** técnico en urbanización → inspección → informe → cotización.

| Paso | DB | Colección | ¿Por qué entra? |
|------|-----|-----------|-----------------|
| 1 | DB04 | `clients` | Identificar cliente (RUC/SRI) |
| 2 | Hub | `client_hubs` | Gate Hub-first |
| 3 | DB05 | `contacts` | (opcional) contacto principal |
| 4 | DB42 | `sop_visits` | Registro formal de visita |
| 5 | MED | `media_assets` | Fotos/audio (si subes archivos) |
| 6 | DB45 | `technical_reports` | Reporte técnico exportable |
| 7 | DB27 | `quotes` | Cabecera cotización |
| 8 | DB38 | `quote_lines` | Matemática (líneas) |
| 9 | DB26/DB13 | `inventory_items` / `catalog_products` | Ítems al cotizar |
| 10 | DB40 | `serials` | PCD-SOP / PCD-RPT / PCD-COT |
| 11 | DB41 | `verification_rules` | Gates calidad |
| 12 | DOC | `documents` | PDF-first |
| 13 | DB52 | `ai_provenance` | Trazabilidad IA |

**~13 piezas de ~55.** El resto se activa en otros flujos.

---

## Flujos que existen pero NO corre crew.py aún

| Flujo | DB involucradas | Cuándo |
|-------|-----------------|--------|
| Onboarding | DB04, DB05, Hub | Alta cliente nueva |
| Cobro real | DB29, DB32, DB31, DB30 | Al facturar/cobrar |
| Taller recepción | DB43, DB29, DB45 | Equipo en taller |
| Editorial | DB47→48→49, DB15… | Publicar caso real |
| Finanzas mensual | DB30–36, DB33 | Contabilidad |
| Ideas | DB11 | Captura idea suelta |
| KPIs | DB37 | Quick log productividad |
| Proyecto grande | DB08, DB06, DB46 | Implementación formal |

---

## Analogía

```
OS Central = ciudad con 52 edificios (DB01–DB52)
Flujo campo = ruta del técnico: casa cliente → taller → oficina
  Solo visita: cliente, visita, reporte, cotización, PDF
  No pasa por: banco (DB31), redacción (DB15), universidad (DB10)
```

---

## ¿Están creadas las 52 en Mongo?

**Sí** — todas las colecciones existen en `pcdoctor_swarm` (servidor 192.168.1.4).

Vacías hasta que un flujo las use. Ver:

```bash
curl http://192.168.1.4:8100/schema/registry
```

---

## Roadmap flujos en código

1. ✅ **Campo PC Doctor** (DB04→42→45→27/38) — `crew.py` + `workflow_v2.py`
2. ⏳ Cobro (DB29→31)
3. ⏳ Taller DB43
4. ⏳ Editorial DB47→48→49
5. ⏳ Finanzas DB31 diario

Cada flujo nuevo = nuevo orquestador o endpoints, **mismas colecciones**.
