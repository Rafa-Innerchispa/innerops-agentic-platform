# Seguridad antes de hacer público el backend

## Archivos que NUNCA se suben (`.gitignore`)

- `.env` — RUC, Evolution, MongoDB, etc.
- `*.pem`, `*.p12`, credenciales GCP

## Verificar antes de `gh repo edit --visibility public`

```bash
cd /home/rlopez/projects/innerspark-swarm-os-cursor-local
git ls-files | grep -E '^\.env$' && echo "STOP" || echo "OK: .env no tracked"
git grep -E 'BXQbDtMt|password.*@@' -- ':!docs/SEGURIDAD_GITHUB.md' && echo "STOP: secreto en código" || echo "OK"
```

## Secretos solo en `.env` del servidor

```
RUC_API_USER=
RUC_API_PASS=
EVOLUTION_API_KEY=
```

No copiar valores reales en README ni en `docs/*.md`.
