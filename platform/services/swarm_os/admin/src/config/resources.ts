export type FieldDef = {
  name: string;
  label: string;
  required?: boolean;
  type?: "text" | "number" | "textarea" | "select";
  options?: string[];
  default?: string | number;
};

export const RESOURCE_CONFIG: Record<
  string,
  { title: string; idField: string; columns: string[]; fields: FieldDef[] }
> = {
  entities: {
    title: "Entidades / marcas (DB01)",
    idField: "entity_id",
    columns: ["entity_id", "name", "slug", "kind", "status"],
    fields: [
      { name: "name", label: "Nombre", required: true },
      { name: "slug", label: "Slug (URL)", required: true },
      {
        name: "kind",
        label: "Tipo",
        type: "select",
        options: ["organization", "personal", "platform"],
        default: "organization",
      },
      { name: "status", label: "Estado", default: "active" },
      { name: "notes", label: "Notas", type: "textarea" },
    ],
  },
  "inventory-items": {
    title: "Inventario hardware (DB26)",
    idField: "item_code",
    columns: ["sku", "nombre", "marca", "categoria", "stock", "precio_contado", "precio_tarjeta", "precio_proveedor"],
    fields: [
      { name: "nombre", label: "Nombre producto", required: true },
      { name: "marca", label: "Marca" },
      { name: "categoria", label: "Categoría" },
      { name: "supplier_id", label: "ID proveedor (sup_…)" },
      { name: "precio_proveedor", label: "Precio compra proveedor", type: "number", default: 0 },
      { name: "precio_contado", label: "Precio venta contado", type: "number", default: 0 },
      { name: "precio_tarjeta", label: "Precio venta tarjeta", type: "number", default: 0 },
      { name: "stock", label: "Stock", type: "number", default: 0 },
    ],
  },
  "catalog-products": {
    title: "Catálogo productos y servicios (DB13)",
    idField: "code",
    columns: ["code", "nombre", "tipo", "empresa", "linea_negocio", "precio_sugerido", "estado"],
    fields: [
      { name: "code", label: "Código" },
      { name: "nombre", label: "Nombre", required: true },
      { name: "tipo", label: "Tipo", type: "select", options: ["producto", "servicio", "bundle"], default: "servicio" },
      { name: "empresa", label: "Empresa", type: "select", options: ["pcdoctor", "innerchispa"], default: "pcdoctor" },
      { name: "linea_negocio", label: "Línea de negocio" },
      { name: "precio_sugerido", label: "Precio sugerido USD", type: "number", default: 0 },
      { name: "descripcion_comercial", label: "Descripción", type: "textarea" },
      { name: "estado", label: "Estado", default: "Activo" },
    ],
  },
  suppliers: {
    title: "Proveedores (DB25)",
    idField: "supplier_id",
    columns: ["ruc", "nombre", "ciudad", "email", "phone", "estado"],
    fields: [
      { name: "nombre", label: "Nombre", required: true },
      { name: "ruc", label: "RUC", required: true },
      { name: "ciudad", label: "Ciudad" },
      { name: "email", label: "Email" },
      { name: "phone", label: "Teléfono (+593…)" },
      { name: "estado", label: "Estado", default: "Activo" },
    ],
  },
  quotes: {
    title: "Cotizaciones (DB27)",
    idField: "quote_id",
    columns: ["serial", "ruc", "client_name", "company_id", "estado", "total"],
    fields: [
      { name: "client_id", label: "ID cliente (usar buscador en visitas)", required: true },
      { name: "company_id", label: "Empresa", type: "select", options: ["pcdoctor", "innerchispa"], default: "pcdoctor" },
      { name: "titulo", label: "Título" },
      { name: "notas", label: "Notas", type: "textarea" },
    ],
  },
  "sop-visits": {
    title: "Visitas SOP (DB42)",
    idField: "visit_id",
    columns: ["visit_id", "client_ruc", "client_name", "tipo", "estado", "fecha"],
    fields: [
      { name: "client_id", label: "ID interno (auto)" },
      { name: "tipo", label: "Tipo visita", default: "soporte" },
      { name: "notas", label: "Notas de campo", type: "textarea" },
    ],
  },
  "technical-reports": {
    title: "Technical reports (DB45)",
    idField: "report_id",
    columns: ["serial", "titulo", "client_name", "client_ruc", "visit_id", "estado"],
    fields: [
      { name: "titulo", label: "Título", required: true },
      { name: "visit_id", label: "ID visita (opcional)" },
      { name: "content_md", label: "Contenido", type: "textarea" },
    ],
  },
};
