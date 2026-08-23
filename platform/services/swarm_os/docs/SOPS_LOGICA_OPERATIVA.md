# SOPs + Lógica Operativa — OS Central (Master)

**Copia local canónica** (2026-06-09). Fuente Notion: índice maestro SOPs.  
**Para programar:** ver `RELACIONES_Y_FLUJOS.md` y `tools/gates.py`.

Constitución: Playbook V2.0 — OS Central (Notion).

---

## 1) Cómo usar este documento

- **Operar el OS:** Playbook V2 → SOP específico.
- **Automatizar / código:** este índice + `RELACIONES_Y_FLUJOS.md` + `ESQUEMA_MONGODB_DBxx.md`.

---

## 2) Constitución

- **Playbook V2.0** = única constitución operativa. Si algo contradice, es legacy.

---

## 3) SOPs oficiales (índice)

### 3.1 PC Doctor — Cliente / Comercial / Técnico

1. **SOP Flujo Cliente / Hub / Trabajo / Informe / Cotización / PDF-first**
   - Gates: Hub-first, anti-duplicación, PDF-first, DB38 manda.
   - Salida: Hub → PDFs / Exportables.

2. **Gate "Listo para enviar"** — no exportar si PDF-first no existe o ≠ DB38.

3. **SOP Revisión, Negociación y Control de Margen (Cotizaciones)**

4. **SOP Cálculo de Margen y Descuento Seguro**

### 3.2 Separación de bases (anti-caos)

| DB | Rol |
|----|-----|
| DB11 | Ideas / triage |
| DB37 | Evidencia / KPIs |
| DB45 | Entregables técnicos / reportes exportables |
| DB13 | Producto vendible formal |
| DB06 | Oferta comercial |
| DB08 | Proyecto real |
| DB14 | Automatización |

### 3.3 Editorial

- DB29/DB45 → DB47 → DB48 → DB49 + DB21/16/22/23

### 3.4 Finanzas

- **DB31 = transacción real** (fuente de verdad movimiento de dinero)

### 3.5 Plantillas PDF-first

- Entregables siempre desde plantilla oficial → Hub → PDFs / Exportables

---

## A) Reglas no negociables (invariantes)

1. Playbook V2 es constitución.
2. **Anti-duplicación** antes de crear: DB04, DB05, DB25, DB26, DB27, DB08.
3. **Hub-first:** sin Hub no hay documentos sueltos.
4. **PDF-first:** lo enviado al cliente vive en Hub → PDFs / Exportables.
5. **DB38 manda** en matemáticas. PDF ≠ DB38 → no enviar.
6. **Dinero real:** cobro/pago → debe existir DB31 enlazada.
7. **Separación anti-caos** (tabla 3.2).

---

## B) Flujo canónico

1. Validar/crear **DB04** Cliente
2. Validar/crear **DB05** Contacto
3. Validar/crear **Hub** (subpáginas mínimas)
4. Registrar ejecución: **DB29** trabajo, **DB42** visita SOP, **DB43** ticket
5. **DB45** reporte técnico + link PDF-first
6. **DB27** cabecera + **DB38** líneas
7. PDF-first en Hub → Exportables
8. Todo reflejado en Hub

---

## C) Gate "Listo para enviar"

- [ ] PDF-first final en Hub / `documents`
- [ ] Sin placeholders (@today, pendiente, por definir)
- [ ] PDF-first coincide con DB38
- [ ] Responsable/técnico cuando aplica
- [ ] Cliente exacto, sin duplicado dudoso

---

## D) QA cotización (resumen)

- Integridad CCTV/redes/cableado (ítems obligatorios o nota explícita)
- Costos reales: transporte, consumibles, MO externa, etc.
- Orden negociación: alcance → reutilizar infra → forma pago → descuento
- Matemática: subtotal = Σ líneas; IVA; total

---

## E) Flujos internos (programación)

| Flujo | Pasos DB |
|-------|----------|
| Onboarding | DB04 → DB05 → Hub |
| Cotización | DB27 → DB38 → PDF-first → Hub |
| Trabajo/Soporte | DB29/DB42/DB43 → DB45 → PDF-first |
| Pagos | DB32 → DB31 → DB30 + contexto |
| Editorial | DB29/DB45 → DB47 → DB48 → DB49 |

---

## F) Gates a nivel código

Implementados en `tools/gates.py`:

- Duplicado (nombre/RUC/tel/email)
- Hub inexistente
- Placeholders
- Consistencia DB38 ↔ cabecera/PDF
- Trazabilidad financiera (DB31 si hay cobro)
