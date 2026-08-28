# Checklist seguridad — repo público hackathon

Antes de push a GitHub / lablab.ai:

## Nunca commitear

- [ ] `.env` (keys Band, Featherless, AIML, Gemini)
- [ ] `hackathon_band/.band_local/*.json` (audit trail puede tener contenido operativo)
- [ ] `hackathon_band/outputs/*.md` (reportes con datos clientes)
- [ ] Credenciales MongoDB, tokens ngrok, etc.

## Sí commitear

- [ ] `hackathon_band/` código fuente
- [ ] `.env.example` con placeholders vacíos
- [ ] `docs/HACKATHON_BAND_OF_AGENTS.md`
- [ ] `hackathon_band/ui/` (sin `node_modules/`)

## Verificar antes de demo pública

```bash
git status
grep -r "sk-\|Bearer\|AIza\|AQ\." hackathon_band/ docs/ || echo "OK sin keys en código"
python hackathon_band/hackathon_demo.py --check
```

## Datos en demo

- Memoria = MongoDB operativo + docs reales del servidor
- No usar datos ficticios de clientes en commits
- Reportes generados quedan en `outputs/` (gitignored)

## Rama

Solo `hackathon/band-fireless-2026` — **no merge a master** hasta revisión post-hackathon.
