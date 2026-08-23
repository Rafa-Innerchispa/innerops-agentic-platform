# RALF IA v2.0 — Memoria del desarrollo (importar a Notion)

> **Fecha:** Junio 2026 · **Servidor:** ralphi-ia-ver-10 · **IP:** 192.168.1.4  
> **Proyecto activo:** `/home/rlopez/projects/innerspark-swarm-os-cursor-local/`  
> **GitHub:** `rafagye/innerspark-swarm-os-cursor-local` (privado)

---

## Qué es

Mini-ERP / OS Central para **PC Doctor S.A.** (Ecuador) + marca **InnerChispa LLC** (IA, RAG, agentes). Multiempresa: misma plataforma, logos y catálogos distintos.

---

## Entrada única (bookmark)

| URL | Rol |
|-----|-----|
| http://192.168.1.4:8800 | **Portal RALF IA v2.0** — todos los servicios |
| http://192.168.1.4:5173 | PC Doctor Admin (Refine) — trabajo diario |
| http://192.168.1.4:8081 | FileBrowser — archivos sin SSH |
| http://192.168.1.4:8100/docs | API Swarm-OS |

---

## Multiempresa

| Empresa | Negocio | Logo |
|---------|---------|------|
| PC Doctor S.A. | CCTV, soporte, urbanizaciones | `assets/branding/logo_pcdoctor.png` |
| InnerChispa LLC | IA local, RAG, agentes, consultoría | `assets/branding/logo_innerchispa.png` |

Configuración: Admin → **Configuración** (`/settings`). Logos editables ahí o por FileBrowser.

Servicios InnerChispa en catálogo (DB13): botón seed en Configuración — RAG, agentes CrewAI, Whisper, mantenimiento, etc.

---

## Stack técnico

- **MongoDB** `pcdoctor_swarm` — verdad operativa (DB04–DB52 mapeadas)
- **FastAPI** `:8100` — inspecciones, gates, CRUD admin, voz
- **Refine + Ant Design** `:5173` — clientes, inventario, catálogo, cotizaciones
- **CrewAI** — flujo campo → informe → cotización (~8 agentes hoy)
- **Whisper** `:9001` — voz a texto español (ligero, local)
- **AnythingLLM** `:3001` — RAG documentos
- **Open WebUI** `:3000` — chat Ollama
- **n8n** `:5678`, **Portainer** `:9000`, **Cockpit** `:9090`

---

## Datos importados (Notion CSV mayo 2026)

| Base | Registros |
|------|-----------|
| DB04 Clientes | 29 |
| DB13 Catálogo | 104 |
| DB25 Proveedores | 13 |
| DB26 Inventario | 134 |

Fuente: `/home/rlopez/backups/.../notion_data/.../Bases Maestras OS Central/`

---

## Preservación (no perder el trabajo)

1. **GitHub** — código y documentación
2. **Backup diario 1:30 AM** → Google Drive `RalphiIA_Backups/disaster_recovery/`
3. **Comando restaurar:** `restaura-a-ralphia`

Ver `docs/RALPHI_IA_PRESERVACION.md` en el repo.

---

## Documentación en el repo (orden de lectura)

1. `AGENTS.md`
2. `docs/INSTRUCCIONES_AGENTE.md`
3. `docs/DONDE_ESTA_TODO.md`
4. `docs/MAPA_PROYECTO.md`
5. `docs/ESQUEMA_MONGODB_DBxx.md`

---

## Pendiente

- PDF con plantilla Notion + logo embebido
- GitHub conectado (token PAT)
- Logo InnerSpark “full” definitivo (provisional InnerChispa LLC)
- Integrar voz en UI admin (hoy vía API inspección)

---

## Decisiones

- **Configuración visual** para logos/colores (no solo chat IA) — fuente de verdad en MongoDB
- **Chat IA** para operación y preguntas, no para reemplazar config de marca
- **127.0.0.1** en `.env` del servidor; desde Windows usar **192.168.1.4**
