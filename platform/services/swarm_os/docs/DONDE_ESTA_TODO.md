# Dónde está todo — mapa de memoria (Rafael)

**Servidor:** `192.168.1.4` — accede desde Windows por **navegador**, sin escribir en terminal.

---

## 1. ¿El agente puede ejecutar en SSH?

**Sí.** Cursor ejecuta comandos **dentro del servidor** automáticamente.

Lo que **no** puede hacer sin ti:

| Acción | Por qué |
|--------|---------|
| Crear repo en **tu** GitHub | Necesita **tu** token personal (seguridad) |
| Aprobar algunos writes | A veces pide confirmación en Cursor |

Todo lo demás (import, reiniciar API, admin, scripts) **lo ejecuta el agente**.

---

## 2. Interfaces visuales (abrir en el navegador)

### Entrada principal (un solo bookmark)

| Qué | URL desde Windows | ¿Para qué? |
|-----|-------------------|------------|
| **RALF IA Portal v2.0** | http://192.168.1.4:8800 | **Panel único** — enlaces a todos los servicios |
| **Gestor de archivos** | http://192.168.1.4:8081 | Usuario `admin` — si no entra: `bash scripts/reset_filebrowser_password.sh` |
| **Centro de Datos (chat+voz)** | http://192.168.1.4:5173/datacenter | Crear/consultar por texto o micrófono |

### Servicios individuales

| Qué | URL desde Windows | ¿Para qué? |
|-----|-------------------|------------|
| **PC Doctor Admin** | http://192.168.1.4:5173 | Mini-ERP: clientes, inventario, cotizaciones |
| **Swarm-OS API docs** | http://192.168.1.4:8100/docs | Probar endpoints |
| **AnythingLLM (RAG)** | http://192.168.1.4:3001 | Preguntar sobre PDFs/manuales |
| **Open WebUI** | http://192.168.1.4:3000 | Chat general Ollama |
| **n8n** | http://192.168.1.4:5678 | Automatizaciones |
| **Portainer** | http://192.168.1.4:9000 | Docker visual |

**Arranque automático al reiniciar** (ejecutar una vez en el servidor con tu contraseña):

```bash
bash /home/rlopez/projects/innerspark-swarm-os-cursor-local/scripts/install_services.sh
```

Eso habilita: portal `:8800`, admin `:5173`, API `:8100`, gestor de archivos `:8081`.

**Nota sobre el puerto 9090:** es **Cockpit** (admin del Linux), no el mini-ERP. El ERP está en `:5173`. El panel único es `:8800`.

### Multiempresa y logos

| Empresa | Uso | Logo en servidor |
|---------|-----|------------------|
| **PC Doctor S.A.** | CCTV, soporte, urbanizaciones, cotizaciones hardware | `assets/branding/logo_pcdoctor.png` |
| **InnerChispa LLC** | IA local, RAG, agentes, servicios vendibles | `assets/branding/logo_innerchispa.png` |

Cambiar logo/colores: **Admin → Configuración** (`http://192.168.1.4:5173/settings`) o subir PNG por **FileBrowser** a `projects/innerspark-swarm-os-cursor-local/assets/branding/`.

Tus archivos en Windows (`J:\...\Logo_PC_Doctor.png`, `H:\...\InnerChispa_LLC.png`) puedes arrastrarlos por FileBrowser si quieres reemplazar los del backup Notion.

### GitHub — qué clave sirve

| Tipo | ¿Sirve para conectar el repo? |
|------|-------------------------------|
| **SSH keys** (Deploy keys) | Sí para `git push` por SSH, **no** para `setup_github.sh` tal cual |
| **GCP service account keys** | **No** — solo Google Cloud |
| **Personal Access Token (PAT)** | **Sí** — es lo que necesita `scripts/setup_github.sh` |

Crear PAT: https://github.com/settings/tokens → scope **repo** → pegar en chat o:

```bash
export GITHUB_USER=rafagye
export GITHUB_TOKEN=ghp_...
bash scripts/setup_github.sh
```

### Voz a texto (Whisper)

| URL | Estado |
|-----|--------|
| http://192.168.1.4:9001/docs | ✅ Activo — modelo local ligero |
| API inspección | `POST /inspection/{id}/upload-audio` ya usa Whisper |

---

## 3. Import Notion — ¿de dónde sale? ¿API?

**NO usa API de Notion hoy.** No hace falta que pegues token Notion.

### Fuente real (ya en el servidor)

```
/home/rlopez/backups/20260518_032357/ai-server-v2/n8n/notion_data/
└── Export-.../InnerChispa LLC/.../Bases Maestras OS Central/
    ├── DB04 — Instituciones y Clientes.csv
    ├── DB13 — Catálogo Maestro de Productos.csv
    ├── DB25 — Proveedores.csv
    └── DB26 — Inventario Hardware.csv
```

Es un **export CSV de Notion** guardado el **18-may-2026** cuando n8n/backup copió `notion_data`.

Script: `scripts/import_notion_csv.py` → lee esos CSV → escribe en **MongoDB** `pcdoctor_swarm`.

### Importado (última ejecución)

| Base | Registros en Mongo |
|------|-------------------|
| DB25 Proveedores | 13 |
| DB26 Inventario | 134 |
| DB13 Catálogo | 104 |
| DB04 Clientes | 29 |

**No tienes que hacer nada en Notion** para este import. Si actualizas Notion, luego: nuevo export CSV o API (fase futura).

---

## 4. Disco — ¿nos quedamos sin espacio?

| Ruta | Tamaño | Nota |
|------|--------|------|
| Disco total | **644 GB libres** de 877 GB (24% usado) | Bien por ahora |
| `/home/rlopez/backups` | **24 GB** | Exports Notion, backups viejos |
| `/home/rlopez/projects` | 1.3 GB | Código Swarm-OS |
| Segundo disco | Verificar con `lsblk` si hay mount aparte | Mover backups si crece |

El riesgo futuro es `backups/` (24G), no MongoDB.

---

## 5. GitHub — lo único que requiere tu mano

Solo el **token GitHub** (una vez):

```bash
export GITHUB_USER=rafagye
export GITHUB_TOKEN=ghp_...
./scripts/setup_github.sh
```

O pegar token al agente en chat para que ejecute el script.

---

## 6. Proyecto activo vs otros

| Ruta | Qué es |
|------|--------|
| `/home/rlopez/projects/innerspark-swarm-os-cursor-local/` | **PC Doctor OS — proyecto activo** |
| `/home/rlopez/inneros/` | Hackathon Google (otro) |
| `/home/rlopez/backups/.../notion_data/` | **Copia CSV de Notion** (solo lectura import) |
| MongoDB `pcdoctor_swarm` | Datos operativos vivos |

---

## 7. Si cambias a Gemini API

El código y MongoDB **siguen en el servidor**. Solo cambias el LLM en `.env` / `config.py`. Lee `docs/INSTRUCCIONES_AGENTE.md` — no depende del chat anterior.
