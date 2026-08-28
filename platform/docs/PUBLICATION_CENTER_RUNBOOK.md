# RalfIA Publication Center

Fecha: 2026-08-04

## Objetivo

Unificar las aprobaciones de contenido de InnerChispa sin crear portales duplicados.

El centro operativo es:

- Portal principal: `http://192.168.1.4:2002`
- Centro de publicaciones: `http://192.168.1.4:8101/editorial`
- Astro staging: `http://192.168.1.4:5185/staging-web/`

## Flujo recomendado

1. Crear o detectar proyecto/hackathon.
2. Sincronizar inventario canónico desde el Centro de publicaciones.
3. Revisar contenido en Web / Astro interno.
4. Aprobar o publicar en Astro staging.
5. Preparar LinkedIn desde el mismo Centro de publicaciones.
6. Publicar LinkedIn sólo con aprobación humana explícita.

## Botones clave

- `Sincronizar inventario canónico`: importa `hackathons_portfolio.json` a la cola Web/Astro.
- `Crear Web/Astro`: convierte un draft editorial en contenido web interno.
- `Aprobar`: marca contenido como aprobado.
- `Publicar Astro`: publica contenido interno y dispara export/rebuild.
- `Exportar JSON Astro`: regenera `published_content.json` y fichas Markdown para Astro.

## Endpoints principales

- `GET /api/editorial/drafts`
- `GET /api/editorial/web-content`
- `POST /api/editorial/web-content/sync-canonical`
- `POST /api/editorial/web-content/from-draft/{draft_id}`
- `POST /api/editorial/web-content/{content_id}/status`
- `POST /api/editorial/web-content/export-astro`

## MCP

Tools útiles para ChatGPT/RalfIA:

- `create_web_content`
- `update_web_content`
- `change_web_content_status`
- `list_web_content`
- `export_web_content_for_astro`
- `sync_hackathon_portfolio_to_web_content`

## Seguridad

- `www.innerchispa.us`, DNS y hosting compartido no se tocan desde este flujo.
- Astro es interno/staging y puede actualizarse con aprobación ligera.
- LinkedIn es externo y debe requerir aprobación humana antes de publicar.
- Los repositorios alternativos no se cuentan como proyectos distintos.
- No publicar premios/resultados sin evidencia oficial.
