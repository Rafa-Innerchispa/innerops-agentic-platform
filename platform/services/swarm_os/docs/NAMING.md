# Nomenclatura — InnerOS, SwarmOS, Ralphi-IA

**Última actualización:** 2026-06-12

## Nombres oficiales

| Nombre | Qué es | Dónde vive |
|--------|--------|------------|
| **Ralphi-IA** | Marca del servidor / appliance IA soberano | Host `ralphi-ia-ver-10` (192.168.1.4) |
| **InnerOS** | Plataforma paraguas (negocio, salud, casa, proyectos) | UI `/inneros`, marca producto |
| **SwarmOS** | Motor de agentes (8 droides, CrewAI, API tools) | Repo `innerspark-swarm-os-cursor-local` |
| **PC Doctor Admin** | ERP operativo (clientes, cotizaciones, correo) | `:5173` + MongoDB `pcdoctor_swarm` |

## Carpetas que NO confundir

| Ruta | Realidad |
|------|----------|
| `/home/rlopez/projects/innerspark-swarm-os-cursor-local` | **Proyecto activo** SwarmOS + InnerOS UI |
| `/home/rlopez/inneros/` | Legacy RAG (LiteLLM, Qdrant) — consolidar después, no borrar aún |
| `/home/rlopez/agentes/` | Experimento viejo Flask+Ollama — **no es SwarmOS** |
| `/home/rlopez/data/` | **Datos compartidos** — Notion, GDrive, media, informes |
| URL `/inneros` | Pantalla hackathon/demo — no es la carpeta `~/inneros` |

## Reglas

1. **Código** → `~/projects/<repo>/` (Git)
2. **Datos** → `~/data/` (sin Git, compartido entre proyectos)
3. **MongoDB** = fuente de verdad de negocio
4. **Open WebUI** = laboratorio chat, no memoria ERP

## Cursor

Abrir workspace en:

```
/home/rlopez/projects/innerspark-swarm-os-cursor-local
```

Los datos están fuera del repo en `/home/rlopez/data`.
