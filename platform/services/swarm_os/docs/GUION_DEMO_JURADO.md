# Guión demo jurado — Band of Agents (2–3 min)

**URL pública:** https://sworn-profusely-alongside.ngrok-free.dev  
**Idioma UI:** Español (selector arriba a la derecha si aplica)

---

## Antes de grabar (30 s)

1. Abre la URL en Chrome (acepta pantalla ngrok si aparece).
2. Comprueba que el header muestra contadores Mongo (`sop_visits`, `technical_reports`, etc.).
3. Deja el teléfono visible (WhatsApp) y un email de prueba configurado en `.env` (`HACKATHON_EMAIL_TO`).

---

## Minuto 0:00 — Contexto (20 s)

> «Somos PC Doctor S.A. Este dashboard no es un chatbot genérico: consulta **memoria operativa real** en MongoDB — visitas SOP, reportes técnicos, clientes — y cuatro agentes especializados la analizan, documentan y entregan el resultado por web, WhatsApp y email. **Band** registra cada paso con identidad y trazabilidad en vivo.»

**En pantalla:** scroll lento por el dashboard — Agent Map + Memory Proof.

---

## Minuto 0:20 — Evidencia antes de preguntar (25 s)

> «Antes de ejecutar, **Memory Proof** muestra qué hay en la base para esta pregunta. No inventamos datos: las fuentes son colecciones Mongo y documentos del servidor.»

**Acción:** clic en una **pregunta sugerida** (PoE / cámaras / Torres de la Merced).

**En pantalla:** Memory Proof con hits y contadores.

---

## Minuto 0:45 — Run en vivo (60–90 s)

> «Pulso Run. Router y Memory usan Featherless; Analyst y Documentation usan AIML con deepseek-r1 — puede tardar uno o dos minutos. Lo importante no es el proveedor LLM, sino la **orquestación por rol** y la **evidencia verificable**.»

**Acción:** Run. Mientras corre:
- Señala **Agent Map** (pasos iluminándose).
- **Live Console** (logs del pipeline).
- **Band Audit Trail** (mensajes LIVE con handles `rafagye/*`).

**No digas:** «mira la web de Featherless/AIML» — no aporta.

---

## Minuto 2:15 — Reporte + entrega (35 s)

> «El reporte incluye la sección **MongoDB Evidence (verified)**: IDs, colecciones y extractos reales. Eso es lo que el jurado puede auditar.»

**Acción:** scroll al **Report Panel** → sección de evidencia.

> «Al terminar, el mismo reporte llega por **WhatsApp** con enlace de descarga y adjunto, y por **email** con PDF desde nuestra cuenta corporativa InnerOS.»

**Acción:** muestra móvil (mensaje + `.md`) y Gmail (PDF `PC Doctor · Reporte Band`).

---

## Minuto 2:50 — Cierre (10 s)

> «En resumen: memoria organizacional real de PC Doctor, multi-agente con Band, entrega omnicanal. InnerSpark Swarm-OS — campo operativo en MongoDB, no slides.»

**En pantalla:** header con stats Mongo + URL en barra de direcciones.

---

## Si algo falla en vivo

| Problema | Qué decir |
|----------|-----------|
| AIML lento | «El analista usa razonamiento profundo; la demo ya generó un reporte completo.» |
| ngrok caído | Usa captura de pantalla + enlace Devpost con URL alternativa del `data/hackathon_public_url.txt`. |
| Email no llega | Muestra WhatsApp + reporte en pantalla; email depende de SMTP corporativo. |

---

## Qué NO mostrar

- Webs de Featherless o AIML API.
- Código de `llm_client.py`.
- InnerOS admin completo (`:5173`) salvo 10 s de contraste «campo vs memoria Band».

---

## Comandos útiles (operador, no en video)

```bash
cat data/hackathon_public_url.txt
bash scripts/restart_hackathon_stack.sh
curl -sf http://127.0.0.1:8200/api/status | python3 -m json.tool
```
