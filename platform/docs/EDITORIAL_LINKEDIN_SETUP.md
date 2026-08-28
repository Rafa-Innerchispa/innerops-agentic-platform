# Editorial LinkedIn — arranque rápido

## 1. Dependencias

```bash
cd /home/rlopez/projects/raphiia-openai
source venv/bin/activate
pip install Pillow
```

## 2. Variables `.env`

```env
GOOGLE_API_KEY=tu_clave_ai_studio  # AQ.... (2026) o AIzaSy... — ver docs/GOOGLE_API_KEYS.md
LINKEDIN_ACCESS_TOKEN=...
LINKEDIN_AUTHOR_URN=urn:li:person:XXXX
```

**LinkedIn:** [Developer Portal](https://www.linkedin.com/developers/) → app → OAuth → scopes `w_member_social`, `r_liteprofile`.  
**Author URN:** `GET https://api.linkedin.com/v2/me` con el token.

**Google Imagen:** API key desde [Google AI Studio](https://aistudio.google.com/apikey) o GCP Vertex.  
Si falla Imagen, prueba `GEMINI_IMAGE_MODEL=gemini-2.0-flash-preview-image-generation`.

## 3. Servicios

```bash
# Health + Editorial UI (:8101)
./run.sh

# Worker imágenes + cola LinkedIn (sin sudo)
bash /home/rlopez/data/ai_coordination/scripts/install_editorial_worker.sh
```

## 4. UI

**http://192.168.1.4:8101/editorial**

- Ver borradores
- Generar imagen
- Aprobar y publicar

## 5. ChatGPT MCP

```
save_pipeline_draft(channel="linkedin", title="...", markdown="...")
generate_draft_image(draft_id="...")
```

Luego aprueba en `/editorial`.

## 6. Flujo Mongo

`editorial_pipeline` → `media_library` → `editorial_posts` → `social_destinations` → LinkedIn

Ver `ai_coordination/MONGO_SCHEMA.md`
