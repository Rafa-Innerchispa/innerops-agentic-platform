#!/usr/bin/env bash
set -euo pipefail
cd /home/rlopez/inneros/inneros_core/platform
export PYTHONPATH=.
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Falta TELEGRAM_BOT_TOKEN" >&2
  exit 1
fi
export TELEGRAM_BOT_TOKEN
./venv/bin/python3 << PY
import os
from inneros_core_runtime import owner_vault
tok = os.environ["TELEGRAM_BOT_TOKEN"].strip()
r = owner_vault.save_owner_credential(
    key="telegram_bot_token",
    secret=tok,
    category="telegram",
    label="RalfIA OPS Telegram Bot",
    metadata={"source": "telegram_store_bot_token.sh"},
    actor="RAFAEL",
)
print(r)
PY
systemctl --user restart inneros-telegram-ops-poll.service 2>/dev/null || true
echo "Envía /start al bot en Telegram para registrar chat_id."
