# Google API keys — AI Studio vs Cloud (para Rafael)

## Tu confusión resuelta

| Prefijo | Origen | ¿Válida para RalfIA editorial? |
|---------|--------|--------------------------------|
| **`AQ.`** | **Google AI Studio (nuevo 2026)** | **Sí** — es la clave correcta hoy |
| **`AIzaSy...`** | AI Studio antigua o Google Cloud Console | **Sí** — formato legacy |

**No te confundas:** las que empiezan por **`AQ.` también son de AI Studio**, no de otro sitio. Google cambió el formato en 2026.

**No necesitas** ir a Google Cloud Console para crear claves `AIzaSy...` si ya tienes `AQ.` en AI Studio — **usa la de AI Studio**.

Cloud Console solo si quieres Vertex AI, facturación GCP avanzada o service accounts.

---

## Si sigue el 401 con clave AQ.

1. En AI Studio → tu clave → **Restrict to Gemini API only** (no dejar Unrestricted).
2. Si aparece etiqueta **Blocked** → crear clave nueva.
3. Probar con SDK instalado: `pip install google-genai` (ya en requirements).
4. Si aún falla: bug conocido en algunas cuentas con claves AQ.; crear otra clave o pedir en el foro de Google AI.

El 401 con mensaje *Expected OAuth 2 access token* indica que **Google rechaza la clave**, no que el código esté mal (probado con header `x-goog-api-key` y SDK oficial).

---

## Pasos en AI Studio

1. https://aistudio.google.com/apikey
2. Copia clave `AQ....`
3. Si aparece **Unrestricted** → Add restrictions → **Generative Language API / Gemini API**
4. Pega en `.env`: `GOOGLE_API_KEY=AQ....` (sin comillas, sin espacios)
5. Reinicia:

```bash
pkill -f "raphiia-openai.*main.py" 2>/dev/null; cd /home/rlopez/projects/raphiia-openai && source venv/bin/activate && nohup python3 main.py >> /tmp/raphiia-8101.log 2>&1 &
systemctl --user restart ralfia-editorial-worker
```

---

## Skill `npx skills add google-gemini/gemini-skills`

Eso es para **Cursor IDE** (ayuda al agente en el chat), **no** para el servidor RalfIA.

```bash
npx skills add google-gemini/gemini-skills --skill gemini-interactions-api
```

Opcional — me da contexto Gemini en Cursor; **no** reemplaza `GOOGLE_API_KEY` en `.env` del servidor.

---

## Resumen

- **`AQ.` = AI Studio nuevo** ✓
- **`AIzaSy` = legacy** ✓  
- **Cloud Console = opcional**, no obligatorio para imágenes LinkedIn
- **LinkedIn** ya OK con tu token actual
