# Conectar GitHub — un paso que solo tú puedes autorizar

El agente **no puede** crear el repo en tu cuenta sin un **Personal Access Token** tuyo.

## Pasos (5 minutos)

### 1. Crear token en GitHub

1. Ir a https://github.com/settings/tokens
2. **Generate new token (classic)**
3. Scope: `repo` (privado)
4. Copiar el token `ghp_...`

### 2. En el servidor (SSH)

```bash
cd /home/rlopez/projects/innerspark-swarm-os-cursor-local
export GITHUB_USER=rafagye          # tu usuario GitHub
export GITHUB_TOKEN=ghp_XXXXXXXXX   # el token
chmod +x scripts/setup_github.sh
./scripts/setup_github.sh
```

El script:
- Crea repo privado `innerspark-swarm-os-cursor-local` si no existe
- Hace `git push` sin subir `.env`

### 3. Alternativa SSH (sin token en script)

```bash
ssh-keygen -t ed25519 -C "ralphi-ia-ver-10" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
# Pegar en GitHub → Settings → SSH keys
git remote add origin git@github.com:rafagye/innerspark-swarm-os-cursor-local.git
git push -u origin master
```

## Estado actual

- Git local con commits ✅
- Remote GitHub ❌ hasta ejecutar arriba
