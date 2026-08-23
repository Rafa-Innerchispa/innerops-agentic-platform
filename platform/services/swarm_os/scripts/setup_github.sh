#!/usr/bin/env bash
# Conecta el repo local con GitHub y hace el primer push.
# Uso:
#   export GITHUB_TOKEN=ghp_xxxx   # token con repo scope
#   export GITHUB_USER=tu_usuario
#   ./scripts/setup_github.sh
set -euo pipefail
cd "$(dirname "$0")/.."

REPO_NAME="${GITHUB_REPO:-innerspark-swarm-os-cursor-local}"
GITHUB_USER="${GITHUB_USER:-}"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "ERROR: Define GITHUB_TOKEN (Personal Access Token con scope repo)"
  echo "Crear en: https://github.com/settings/tokens"
  exit 1
fi

if [[ -z "$GITHUB_USER" ]]; then
  GITHUB_USER=$(curl -s -H "Authorization: token ${GITHUB_TOKEN}" https://api.github.com/user | python3 -c "import sys,json; print(json.load(sys.stdin).get('login',''))" 2>/dev/null || true)
fi
if [[ -z "$GITHUB_USER" ]]; then
  echo "ERROR: Define GITHUB_USER (tu usuario GitHub)"
  exit 1
fi
echo "Usuario GitHub: $GITHUB_USER"

# Verificar que .env no está en staging
if git diff --cached --name-only | grep -qE '^\.env$'; then
  echo "ERROR: .env en staging — abortando"
  exit 1
fi

REMOTE="https://${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${REPO_NAME}.git"

if git remote get-url origin &>/dev/null; then
  git remote set-url origin "$REMOTE"
else
  git remote add origin "$REMOTE"
fi

# Crear repo si no existe
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  "https://api.github.com/repos/${GITHUB_USER}/${REPO_NAME}")

if [[ "$STATUS" == "404" ]]; then
  curl -s -H "Authorization: token ${GITHUB_TOKEN}" \
    -d "{\"name\":\"${REPO_NAME}\",\"private\":true}" \
    https://api.github.com/user/repos >/dev/null
  echo "Repo privado creado: ${GITHUB_USER}/${REPO_NAME}"
fi

git push -u origin master
# Quitar token de remote URL por seguridad
git remote set-url origin "git@github.com:${GITHUB_USER}/${REPO_NAME}.git" 2>/dev/null || \
  git remote set-url origin "https://github.com/${GITHUB_USER}/${REPO_NAME}.git"

echo "OK: https://github.com/${GITHUB_USER}/${REPO_NAME}"
