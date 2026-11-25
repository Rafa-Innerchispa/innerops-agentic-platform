#!/usr/bin/env bash
# Instala ntfy + habilita servicios InnerOS Owner Push en Intel (usuario systemd).
set -euo pipefail

PLATFORM="${INNEROS_PLATFORM_ROOT:-/home/rlopez/inneros/inneros_core/platform}"
NTFY_BIN="${NTFY_BIN:-${HOME}/.local/bin/ntfy}"
NTFY_VERSION="${NTFY_VERSION:-v2.38.2}"

if [[ ! -x "$NTFY_BIN" ]]; then
  echo "Descargando ntfy ${NTFY_VERSION}…"
  tmp="$(mktemp -d)"
  arch="$(uname -m)"
  ver="${NTFY_VERSION#v}"
  case "$arch" in
    x86_64) asset="ntfy_${ver}_linux_amd64.tar.gz" ;;
    aarch64) asset="ntfy_${ver}_linux_arm64.tar.gz" ;;
    *) echo "Arquitectura no soportada: $arch"; exit 1 ;;
  esac
  curl -fsSL "https://github.com/binwiederhier/ntfy/releases/download/${NTFY_VERSION}/${asset}" -o "${tmp}/ntfy.tgz"
  tar -xzf "${tmp}/ntfy.tgz" -C "${tmp}"
  bin="$(find "${tmp}" -maxdepth 2 -type f -name ntfy | head -1)"
  mkdir -p "$(dirname "$NTFY_BIN")"
  install -m 0755 "${bin}" "$NTFY_BIN"
  rm -rf "$tmp"
fi

mkdir -p "${PLATFORM}/var/ntfy" "${PLATFORM}/var/ntfy-attachments" "${PLATFORM}/config/ntfy"
if [[ ! -f "${PLATFORM}/config/ntfy/server.yml" ]]; then
  echo "Falta ${PLATFORM}/config/ntfy/server.yml (sincroniza desde git)."
  exit 1
fi

systemctl --user daemon-reload
systemctl --user enable --now inneros-ntfy.service inneros-owner-push.service
systemctl --user is-active inneros-ntfy.service inneros-owner-push.service

echo ""
echo "En el móvil:"
echo "  1) Instala 'ntfy' (Play Store / F-Droid)."
echo "  2) Añade suscripción: http://192.168.1.4:2586/ralfia-owner-ops"
echo "  3) Abre PWA: http://192.168.1.4:8244/owner-ops/ → Añadir a inicio."
echo "  (Tailscale/HTTPS opcional para fuera de casa.)"