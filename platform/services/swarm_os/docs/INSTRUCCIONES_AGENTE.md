# Instrucciones para retomar el proyecto (cualquier modelo IA)

**Para Rafael:** cuando cambies de modelo o se acaben los créditos, abre Cursor en este proyecto y pega el **prompt de arranque** al final de este documento. No necesitas el chat anterior.

**Última actualización:** 2026-06-18

---

## 1. Qué es este proyecto

Sistema multi-agente **local** para **PC Doctor S.A.** (Ecuador):

- Técnico en campo → audio/fotos → RUC/cédula SRI → cliente MongoDB → reporte técnico → cotización → revisión → correo/WhatsApp
- Servidor: `192.168.1.4` (`ralphi-ia-ver-10`)
- Ruta en servidor: `/home/rlopez/projects/innerspark-swarm-os-cursor-local/`
- IP servidor: **`192.168.1.4`** (`ralphi-ia-ver-10`)
- Tu PC Windows **no tiene MongoDB** — todo vive en el servidor

**NO es** el hackathon Google AI Studio (`/home/rlopez/inneros/`).

---

## 2. Dónde está TODO (mapa de documentos)

| Archivo | Para qué leerlo |
|---------|-----------------|
| **`AGENTS.md`** (raíz) | Entrada rápida para Cursor |
| **`docs/CONTINUIDAD_IA.md`** | **Guía maestra** — backups, rutas, hackathon, prompt arranque |
| **`docs/INSTRUCCIONES_AGENTE.md`** | Este archivo — onboarding |
| **`docs/MAPA_PROYECTO.md`** | Constitución: visión, agentes, endpoints, decisiones, fases |
| **`docs/HACKATHON_BAND_OF_AGENTS.md`** | Demo Band :5190 / :8200 |
| **`ARRANQUE_AUTOMATICO.md`** | systemd, ngrok, autostart |
| **`docs/ESQUEMA_MONGODB_DBxx.md`** | Esquema completo DB01–DB52 + colecciones Mongo |
| **`docs/CANON_CORRECCIONES_DBxx.md`** | Correcciones vs Notion (DB41, DB12, etc.) |
| **`docs/RECUPERACION_DESASTRE.md`** | Backups y restauración |
| **`docs/GITHUB_SEGURO.md`** | Subir a GitHub sin filtrar secretos |
| **`docs/SOPS_LOGICA_OPERATIVA.md`** | SOPs Master + invariantes Playbook |
| **`docs/RELACIONES_Y_FLUJOS.md`** | Relaciones DB → Mongo + secuencia API |
| **`docs/ACCESO_RED.md`** | Windows → 192.168.1.4 |
| **`README.md`** | Comandos curl y arranque |

### Datos que persisten aunque cambies de modelo

| Qué | Dónde |
|-----|-------|
| Clientes, cotizaciones, etc. | MongoDB `pcdoctor_swarm` en `:27017` |
| Código | Este repo en disco (+ git) |
| Credenciales | `.env` (no en git; incluido en disaster recovery cifrado en tar) |
| Media subida | `data/media/` |
| Exportables | `data/exports/` |
| Estado operativo JSON | `/home/rlopez/data/manifests/swarm-os-estado.json` |
| Backups nube | `Ralphi-IA-Gdrive:RalphiIA_Backups/disaster_recovery/` |
| Docs memoria organizacional | `/home/rlopez/data/docs/` |

---

## 3. Servicios (todos en 192.168.1.4)

| Servicio | Puerto | Desde tu Windows | En el servidor (SSH) |
|----------|--------|------------------|----------------------|
| Swarm-OS API | 8100 | `curl http://192.168.1.4:8100/status` | `curl http://127.0.0.1:8100/status` |
| MongoDB | 27017 | Compass → `192.168.1.4:27017` | `127.0.0.1:27017` en `.env` |
| Ollama | 11434 | (interno) | `127.0.0.1:11434` |
| Whisper | 9001 | (interno) | Docker en `/home/rlopez/whisper-service` |

Detalle red: **`docs/ACCESO_RED.md`**

---

## 4. Modelo de datos — versión actual

### Legacy (v1) — sigue funcionando, no borrar aún

| Colección | Uso |
|-----------|-----|
| `inspections` | Visita mezclada (campo + hallazgos + media) |
| `reports` | Informe ligado a `inspection_id` |
| `quote_headers` / `quote_lines` | Cotización ligada a `inspection_id` |
| `clients` | Cliente por RUC |
| `inventory` | Inventario demo |
| `audit_log` | Log básico de agentes |

### Canónico (v2) — implementar y migrar hacia aquí

Ver `docs/ESQUEMA_MONGODB_DBxx.md`. Fase A usa:

- `client_hubs`, `contacts`, `sop_visits`, `technical_reports`, `media_assets`
- `quotes`, `quote_lines` (con `quote_id`, no solo `inspection_id`)
- `catalog_products`, `inventory_items`, `suppliers`, `purchase_prices`
- `serials`, `verification_rules`, `validation_results`, `documents`
- `ai_provenance`, `works`

**Inicializar estructura (OBLIGATORIO una vez):** `python scripts/init_mongodb_schema.py`  
Crea las 60+ colecciones, índices, secuenciales DB40 y registro `_schema_registry`.

**Migración (OPCIONAL):** `python scripts/migrate_v1_to_v2.py`  
Solo si ya tenías datos en `inspections` (formato viejo) y quieres copiarlos al formato nuevo.  
Si empiezas de cero o no te importan pruebas viejas, **no la necesitas**.

---

## 5. Errores ya corregidos EN ESTE PROYECTO (no replicar)

| Tema | Canónico aquí | Notion puede estar desactualizado |
|------|---------------|-----------------------------------|
| DB41 | Reglas de verificación cotización | Notion a veces dice "Informes Técnicos" |
| Informes formales | Plantilla/tipo dentro de **DB45** Reportes | No crear DB41-informes |
| DB12 | Grants & Funding (falta volcar en Notion) | Hueco en índice Notion |
| Visitas | **DB42** `sop_visits` separado de **DB45** `technical_reports` | No usar solo `inspections` |
| Cotización | DB27 cabecera + **DB38 líneas** (matemática en líneas) | — |

Detalle: `docs/CANON_CORRECCIONES_DBxx.md`

---

## 6. Qué NO hacer (evita dañar el proyecto)

1. No mover ni fusionar con `inneros/` o `agentes/`
2. No commitear `.env`
3. No cambiar puertos sin actualizar MAPA y README
4. No eliminar colecciones legacy sin migrar
5. No inventar códigos PCD-COT — usar `next_serial()` en `tools/schema.py`
6. No reescribir todo el crew si solo piden un fix puntual

---

## 7. Fase de trabajo actual

**Fase A** (prioridad):

- [ ] Esquema v2 con índices (`tools/schema.py`) — hecho
- [ ] Documentación canónica — hecho
- [ ] Migración v1→v2 — script listo
- [ ] Conectar `crew.py` al modelo v2 (sop_visits, quotes con serial)
- [ ] Gates DB41 en agente Revisor
- [ ] PDF real (hoy solo Markdown en `data/exports/`)

---

## 8. Prompt de arranque (copiar y pegar a un modelo nuevo)

```
Estoy en el proyecto InnerSpark Swarm-OS Cursor Local para PC Doctor S.A.

Ruta: /home/rlopez/projects/innerspark-swarm-os-cursor-local/

ANTES de cambiar código, lee en este orden:
1. AGENTS.md
2. docs/INSTRUCCIONES_AGENTE.md
3. docs/MAPA_PROYECTO.md
4. docs/ESQUEMA_MONGODB_DBxx.md
5. docs/CANON_CORRECCIONES_DBxx.md

Reglas: MongoDB pcdoctor_swarm es verdad operativa; no mezclar con inneros/;
DB27+DB38 para cotizaciones; DB45 reportes; DB42 visitas SOP; DB41 reglas verificación;
usar next_serial() para códigos; .env fuera de git; cambios mínimos; español.

Dime qué fase A falta según MAPA_PROYECTO.md y continúa sin romper legacy inspections.
```

---

## 9. Si algo falla al cambiar de modelo

1. `curl http://192.168.1.4:8100/status` — ¿API viva? (desde Windows)
2. `mongosh pcdoctor_swarm --eval "db.getCollectionNames()"` — ¿datos intactos?
3. Leer `docs/RECUPERACION_DESASTRE.md` para restaurar desde backup
4. Git local: `git log --oneline -5` en el proyecto

**Los datos en MongoDB no dependen del modelo IA.** Solo el código y docs en disco importan para retomar.
