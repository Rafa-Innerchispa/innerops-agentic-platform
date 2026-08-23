# Plantillas y formatos — cotización, factura, informe

**Importante:** hay **dos cosas distintas** que a veces se mezclan.

| Concepto | Qué es | Dónde vive |
|----------|--------|------------|
| **Formularios admin** | Pantallas para **meter datos** (cliente, líneas, precios) | Refine `:5173` + MongoDB |
| **Plantillas PDF-first** | **Diseño** del documento que entregas al cliente | `templates/` + logo en `assets/branding/` |

Los formularios de Notion **no se suben tal cual** al admin. Se **extrae el diseño** una vez y el sistema **rellena** con datos de MongoDB (DB38).

---

## 1. Qué tienes hoy en el servidor

### A) Exportaciones actuales (MVP — muy básicas)

`tools/pdf_generator.py` genera **Markdown simple**, sin logo ni formato PC Doctor:

- Título texto "Cotización — PC Doctor S.A."
- Lista de ítems
- Subtotal / IVA / Total

**No usa** las plantillas oficiales de Notion todavía.

### B) Plantillas oficiales Notion (diseño real)

En el backup del servidor (export mayo 2026):

```
.../Playbook V2 — OS Central/📁 Plantillas (OFICIALES)/
  📄 Plantilla — Cotización PC Doctor (ES).md
  📊 Plantilla — Informe Técnico PC Doctor.md
  📄 Plantilla — Carta Oficial PC Doctor (ES).md
  📁 Plantilla — Proyecto Maestro PC Doctor.md

.../📚 Plantillas/
  🧾 Plantilla — Factura PC Doctor (DB32).md
```

Esas plantillas incluyen:

- Logo (referencia a `PCDoctor_ICON_web_ready.png` / `Logo_PC_Doctor.png`)
- RUC PC Doctor: 0992418575001
- Secciones: presentación, alcance, ítems, totales, condiciones, garantía
- Reglas PDF-first (no placeholders, fecha fija, líneas desde DB38)

**Los PNG del logo NO vinieron en el export CSV/MD** — solo enlaces rotos. Hay que **subir el logo una vez** al proyecto.

---

## 2. ¿Cómo sacar el formato de Notion?

**No importar la plantilla Notion a MongoDB** como registro.

Flujo correcto:

```
Plantilla Notion (diseño)
        ↓ copiar estructura UNA vez
templates/html/cotizacion_pcd.html  (Jinja2)
assets/branding/logo_pcdoctor.png   (archivo real)
        ↓ al cotizar
MongoDB DB27 + DB38 (datos)
        ↓ render
PDF PCD-COT-26-0001.pdf
        ↓
colección documents (PDF-first)
```

### Pasos concretos

1. **Logo:** subir `logo_pcdoctor.png` a  
   `/home/rlopez/projects/innerspark-swarm-os-cursor-local/assets/branding/`

2. **Plantillas HTML:** convertir las secciones de la plantilla Notion a HTML+Jinja2 (mejoradas, no copia pixel-perfect de Notion).

3. **Motor PDF:** WeasyPrint o similar (HTML → PDF con logo embebido).

4. **Código:** reemplazar `pdf_generator.py` para usar plantillas por tipo:
   - `cotizacion` → plantilla cotización
   - `informe` → plantilla informe
   - `factura` → plantilla factura (DB32)

---

## 3. ¿Subir directamente o importar?

| Opción | ¿Recomendado? | Por qué |
|--------|---------------|---------|
| Pegar plantillas Notion en Mongo | ❌ | Notion es para humanos; PDF se genera mejor con HTML |
| Subir logo + HTML al servidor | ✅ | Una vez; control total |
| Import CSV datos (DB26, clientes) | ✅ | Ya hecho — son **datos**, no diseño |
| Sync Notion API plantillas | ⏳ Fase futura | Solo si cambias diseño seguido en Notion |

**Datos** (precios, clientes) → import CSV / Mongo.  
**Diseño** (cotización bonita) → carpeta `templates/` en el proyecto.

---

## 4. Campos que la plantilla debe rellenar (desde Mongo)

### Cotización (DB27 + DB38)

| Campo plantilla | Fuente Mongo |
|-----------------|--------------|
| PCD-COT-26-XXXX | `quotes.code` |
| Cliente, RUC, dirección | `clients` |
| Fecha | `quotes.created_at` |
| Líneas tabla | `quote_lines` (DB38) |
| Subtotal, IVA, Total | calculado DB38 |
| Alcance, garantía, pago | `quotes` + reglas Playbook |

### Informe (DB45)

| Campo | Fuente |
|-------|--------|
| Código | `technical_reports.code` |
| Técnico, hallazgos | `technical_reports` |
| Cliente | `clients` |

### Factura (DB32) — pendiente implementar

Misma lógica con plantilla `factura_pcd.html`.

---

## 5. Logo — dónde va

```
assets/branding/
  logo_pcdoctor.png      ← principal (web + PDF)
  logo_innerchispa.png   ← si aplica documento dual
```

En HTML:

```html
<img src="file:///.../assets/branding/logo_pcdoctor.png" class="header-logo" />
```

Rafael: si tienes el PNG en Drive/Windows, súbelo al servidor en esa carpeta (o dime y lo copiamos en la siguiente sesión).

---

## 6. Mejoras respecto a Notion (sin ser idéntico)

Puedes **mejorar** el formato al migrar:

- Tabla de líneas siempre desde DB38 (automática)
- Logo y colores corporativos fijos
- QR o código de seguimiento opcional
- Pie de página legal Ecuador
- Versión EN bilingüe si quieres

Notion sigue siendo **referencia de contenido**; el PDF final lo genera el servidor.

---

## 7. Próximo paso técnico

1. Crear `assets/branding/` + `templates/html/`
2. Portar plantilla Cotización PC Doctor (ES) a Jinja2
3. WeasyPrint en `pdf_generator.py`
4. Endpoint `GET /api/v1/quotes/{id}/pdf`

¿Tienes el archivo `Logo_PC_Doctor.png` o `PCDoctor_ICON_web_ready.png` en Drive o Windows?
