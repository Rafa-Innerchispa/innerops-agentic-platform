# Servicios del servidor — qué es cada uno (Ralphi IA v2.0)

## Accesos y contraseñas

| Servicio | URL | Usuario / clave |
|----------|-----|-----------------|
| **Portal** | http://192.168.1.4:8800 | Sin login |
| **PC Doctor Admin** | http://192.168.1.4:5173 | Sin login (demo) — Centro Datos: `demo`/`RalphiDemo2026` o `admin`/`RalphiAdmin2026` |
| **FileBrowser** | http://192.168.1.4:8081 | `admin` / `RalphiIA2026` |
| **Open WebUI** | http://192.168.1.4:3000 | Sin login hoy (red local) — conviene activar usuario después |
| **AnythingLLM** | http://192.168.1.4:3001 | Primera vez: crear admin en el asistente de setup |

---

## Capas del sistema (no mezclar)

```
┌─────────────────────────────────────────────────────────┐
│  PC Doctor Admin (:5173) + MongoDB pcdoctor_swarm       │
│  → Negocio: clientes, inventario, cotizaciones, SOP     │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  AnythingLLM (:3001) + Qdrant inneros_kb                │
│  → RAG: manuales PDF, racks, documentos técnicos        │
│  → Preguntas sobre archivos indexados                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Open WebUI (:3000) + Ollama (:11434)                   │
│  → Chat libre con modelos locales                       │
└─────────────────────────────────────────────────────────┘
```

**MongoDB (Notion CSV)** ≠ **Qdrant (vectores)**. El import de Notion a MongoDB alimenta el ERP. Qdrant `inneros_kb` es memoria RAG del proyecto inneros/Notion páginas.

---

## AnythingLLM — configuración recomendada

1. Abre http://192.168.1.4:3001 → asistente inicial
2. **LLM:** Ollama → URL `http://192.168.1.4:11434` (o `http://ollama:11434` si está en la misma red Docker)
3. **Modelo chat:** `qwen2.5:7b` o `llama3.1:8b` (documentos técnicos)
4. **Embeddings:** `nomic-embed-text:latest` (ya instalado en Ollama)
5. Crea **Workspace** por tema: `PC-Doctor-Manuales`, `Racks-CCTV`, etc.
6. Sube PDFs/manuales → AnythingLLM indexa → preguntas en lenguaje natural

No reemplaza el catálogo MongoDB — complementa para leer PDFs largos.

---

## LiteLLM Gateway (:4000)

Puente que unifica varias APIs de modelos (OpenAI, Ollama, etc.) en **una sola URL**. Lo usa inneros/hackathon. PC Doctor Admin hoy habla **directo con Ollama** (`:11434`), no pasa por LiteLLM.

---

## Qdrant (:6333) — colección `inneros_kb`

Base de **vectores** para búsqueda semántica del stack inneros/Ralphi Gateway. **No** es el inventario PC Doctor. Dashboard: http://192.168.1.4:6333/dashboard

---

## Evolution API (:8082)

API de **WhatsApp** (enviar/recibir mensajes). Pantalla "Welcome" = API viva. Instancias WhatsApp se configuran en su panel/manager. Estado: contenedor Up; instancia WhatsApp puede necesitar QR de nuevo.

---

## Ralphi Gateway (:8091)

API legacy de **ai-server-v2** (inneros): memoria Notion, Qdrant, agentes de búsqueda. `/docs` = Swagger. Es **otro cerebro** aparte de Swarm-OS PC Doctor (`:8100`). Proyecto futuro: unificar; hoy conviven.

---

## Open WebUI sin contraseña

Normal en red local de confianza. Para producción: Settings → Authentication → activar login.
