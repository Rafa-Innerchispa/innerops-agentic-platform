#!/usr/bin/env bash
# Auto-activación AMD tras haber registrado el email una vez en Intel (Evolution Foundation).
set -euo pipefail

EMAIL="${EVOLUTION_OPERATOR_EMAIL:-}"
AMD="${RALFIA_AMD_HOST:-192.168.1.5}"
PORT=8082
LICENSE_BASE="${LICENSE_BASE_URL:-https://license.evolutionfoundation.com.br}"

if [[ -z "$EMAIL" ]]; then
  echo "Define EVOLUTION_OPERATOR_EMAIL=tu@correo.com"
  exit 2
fi

status=$(curl -sf -m 10 "http://${AMD}:${PORT}/license/status")
inst=$(echo "$status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('instance_id',''))")
st=$(echo "$status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")

if [[ "$st" == "active" ]]; then
  echo "AMD ya active instance_id=$inst"
  exit 0
fi

if [[ -z "$inst" ]]; then
  echo "No instance_id en /license/status"
  exit 1
fi

echo "Registrando auto tier=community instance_id=$inst email=$EMAIL"
resp=$(curl -sf -m 30 -X POST "${LICENSE_BASE}/v1/register/auto" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${EMAIL}\",\"tier\":\"community\",\"version\":\"2.4.0\",\"instance_id\":\"${inst}\"}") || {
  echo "Falló /v1/register/auto — usa manager manual en http://${AMD}:${PORT}/manager/login"
  exit 1
}

echo "$resp" | python3 -m json.tool
echo "Reinicia evolution-api-amd y comprueba: curl http://${AMD}:${PORT}/license/status"
