# GitHub sin filtrar secretos

## Regla de oro

| Sube a GitHub | NO subas nunca |
|---------------|----------------|
| Código `.py`, `requirements.txt` | `.env` (tiene RUC pass, etc.) |
| `.env.example` (plantilla vacía) | `gcp-key.json`, `*.pem`, tokens |
| `docs/`, `README.md` | Respaldos `.tar.gz` |
| `.gitignore` | `data/media/` con fotos/audio reales |

## Cómo comprobar antes de cada push

```bash
cd /home/rlopez/projects/innerspark-swarm-os-cursor-local
git status
git diff --cached --name-only | grep -iE '\.env$|key|secret|credential|password' && echo "¡ALTO! Hay secretos" || echo "OK para push"
```

## Si un secreto se subió por error

1. Rotar la clave/contraseña (cambiarla en el servicio)
2. Borrar del historial Git (o crear repo nuevo limpio)
3. Nunca solo `git rm` — queda en el historial

## Repo recomendado

- **Privado** en GitHub
- Nombre sugerido: `innerspark-swarm-os-cursor-local`
- Solo rama `master` o `main`

## Primer push (cuando tengas cuenta GitHub)

```bash
# En el servidor, con SSH key o token configurado:
git remote add origin git@github.com:TU_USUARIO/innerspark-swarm-os-cursor-local.git
git push -u origin master
```

El archivo `.env` está en `.gitignore` — Git lo ignora automáticamente.
