#!/usr/bin/env bash
# Restablece usuario admin de FileBrowser (cuando admin/admin no entra).
set -euo pipefail
NEW_PASS="${1:-RalphiIA2026}"
echo "Deteniendo FileBrowser..."
docker stop filebrowser 2>/dev/null || true
echo "Nueva contraseña para usuario admin: $NEW_PASS"
docker run --rm -v docker_filebrowser_config:/config filebrowser/filebrowser:latest \
  --database /config/filebrowser.db users update admin --password "$NEW_PASS"
docker start filebrowser
echo "OK — entra en http://192.168.1.4:8081 con admin / $NEW_PASS"
