# PC Doctor · Band of Agents — Stack para presentación (Gemini / jurado)

**Proyecto:** InnerSpark Swarm-OS — demo hackathon Band of Agents (BOA26)  
**Empresa:** PC Doctor S.A., Ecuador  
**Pitch:** *Most companies do not lack data. They lack memory.*  
**URL demo pública:** ver `data/hackathon_public_url.txt`  
**Rama:** `hackathon/band-fireless-2026`

---

## 1. Problema que resolvemos

Las empresas acumulan visitas técnicas, reportes, cotizaciones y documentos, pero esa información está **dispersa**. Un operador pregunta algo en campo y nadie “recuerda” qué pasó antes con ese cliente o ese sitio.

Nuestra demo muestra **cuatro agentes colaborando** para recuperar memoria real (MongoDB + documentos), analizarla y generar un reporte ejecutivo — con trazabilidad en Band y entrega por WhatsApp + email.

---

## 2. Arquitectura (una slide)

```
Operador (dashboard :5190)
    │
    ▼
FastAPI hackathon (:8200) — orquestador Python
    │
    ├── Band (app.band.ai) — identidad agentes + sala chat + audit trail LIVE
    │
    ├── Router Agent    → Featherless / Meta-Llama-3.1-8B-Instruct
    ├── Memory Agent    → Featherless + MongoDB + /home/rlopez/data/docs
    ├── Analyst Agent   → AIML / deepseek/deepseek-r1
    └── Documentation   → AIML / deepseek/deepseek-r1 → reporte MD + PDF
    │
    ├── Evolution API → WhatsApp (resumen + adjunto + enlace descarga)
    └── SMTP (cuenta InnerOS) → email con PDF adjunto
```

**Importante:** Band no es el LLM de inferencia; es la capa de **agentes identificables y auditables**. Los modelos corren vía Featherless y AIML desde nuestro servidor.

---

## 3. Agentes y modelos (tabla para slide)

| Agente | Rol | Plataforma identidad | LLM | Modelo |
|--------|-----|----------------------|-----|--------|
| Router (AG-001) | Enruta pregunta, define qué buscar | Band `@Router` | Featherless | Meta-Llama-3.1-8B-Instruct |
| Memory (AG-004) | Recupera memoria organizacional | Band `@Memory` | Featherless | Meta-Llama-3.1-8B-Instruct |
| Analyst (AG-003) | Riesgos y recomendaciones | Band `@analyst` | AIML | deepseek/deepseek-r1 |
| Documentation (AG-005) | Reporte ejecutivo Markdown/PDF | Band `@docmaker` | AIML | deepseek/deepseek-r1 |

---

## 4. Memoria organizacional (prueba de “no es fake”)

| Fuente | Tecnología | Qué contiene |
|--------|------------|--------------|
| MongoDB `pcdoctor_swarm` | pymongo | `sop_visits`, `technical_reports`, `reports`, `inspections`, `clients`, `documents` |
| Documentos servidor | filesystem | `/home/rlopez/data/docs/` (Markdown operativo) |

El dashboard incluye **Memory Proof**: conteos por colección + preview de documentos antes del Run.  
El reporte incluye sección **MongoDB Evidence (verified)** con hits crudos (colección, id, texto).

Ejemplos reales en BD: visitas PoE Torres de la Merced, reportes técnicos cámaras/switch, clientes UArtes, Thermocont, etc.

---

## 5. Stack tecnológico completo

| Capa | Tecnología |
|------|------------|
| Backend demo | Python 3, FastAPI :8200, SSE, WebSocket consola |
| Frontend demo | React, Vite :5190 |
| Orquestación agentes | Band REST API (4 agentes, API key por agente) |
| LLM routing | Featherless API + AIML API (OpenAI-compatible) |
| Base de datos | MongoDB Docker `pcdoctor_swarm` |
| WhatsApp | Evolution API v2 (instancia `ralphi-pcdoctor`) |
| Email | SMTP vía cuentas `email_accounts` (mismo módulo InnerOS) |
| PDF reporte | fpdf2 + DejaVu (UTF-8 español) |
| URL pública | ngrok → gateway :5188 (InnerOS + Hackathon misma base) |
| Servidor | Ubuntu, `192.168.1.4`, autostart cron + systemd |
| InnerOS (paralelo) | Swarm-OS :8100 / :5173 — flujo campo PC Doctor (no es la demo Band) |

---

## 6. Flujo demo para el jurado (2 minutos)

1. Abrir URL pública del dashboard hackathon.
2. (Opcional) **Preview memory** — ver datos Mongo reales.
3. Elegir pregunta sugerida (anclada a datos reales, ej. switch PoE Torres de la Merced).
4. Añadir teléfono/email extra del revisor si quieren recibir alertas.
5. **Run** — ver consola en vivo: Router → Memory → Analyst → Documentation (~3–5 min por AIML razonador).
6. Reporte en pantalla + **WhatsApp** (resumen + adjunto + link) + **email PDF** (destino en `HACKATHON_EMAIL_TO`).

---

## 7. Diferenciadores (mensajes clave)

- **Memoria real**, no RAG ficticio: MongoDB operativo de PC Doctor.
- **Multi-agente auditable**: Band LIVE con trail visible en UI.
- **Multi-modelo con propósito**: Featherless (rápido, routing/memoria) + DeepSeek R1 (análisis/documentación).
- **Entrega omnicanal**: dashboard + WhatsApp + email PDF + descarga pública.
- **Independencia**: servidor propio, MongoDB local, sin depender de un solo SaaS de chat.

---

## 8. Roadmap post-hackathon (1 slide opcional)

- Integrar entrega PDF/WhatsApp al flujo campo InnerOS (`master`).
- Switch `LLM_PROVIDER=ollama` para inferencia 100% local (Ollama ya en `:11434`).
- Email automático al cliente final tras reporte técnico aprobado.

---

## 9. Archivos del repo (referencia técnica)

| Archivo | Contenido |
|---------|-----------|
| `hackathon_band/pipeline.py` | Orquestación end-to-end |
| `hackathon_band/llm_client.py` | Routing Featherless / AIML |
| `hackathon_band/memory_source.py` | Búsqueda MongoDB + docs |
| `hackathon_band/delivery.py` | WhatsApp + email |
| `hackathon_band/band_adapter.py` | Integración Band REST |
| `docs/HACKATHON_BAND_OF_AGENTS.md` | Doc operativa hackathon |
| `docs/CONTINUIDAD_IA.md` | Mapa completo proyecto + backups |

---

## 10. Prompt sugerido para Gemini (copiar/pegar)

```
Eres mi asistente de pitch para el hackathon Band of Agents (BOA26).
Con el documento adjunto, crea:
1) Presentación de 8-10 slides (título, problema, arquitectura, agentes/modelos, demo live, diferenciadores, stack, cierre).
2) Guión de 3 minutos en español para presentación en video Devpost.
3) Bullets en inglés para descripción del proyecto.
Tono: profesional, claro, sin hype vacío. Enfatizar memoria organizacional REAL (MongoDB) y audit trail Band LIVE.
```
