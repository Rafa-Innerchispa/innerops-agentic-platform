# Entrega comprobada — 27 octubre 2026

Orden de continuidad: msg_52c204fb4101503c. Se continúa codex/nebius-nvidia-validation-20261024; no se reasigna ni reabre ops_5541a2712440 (dev_swarm, pending_human_review).

Repositorio público creado y verificado por GitHub: https://github.com/Rafa-Innerchispa/inneros-nebius-nvidia-physical-ai-2026
Main público inicial: 02337da34b288e03e7940fdc14301b222039e417.
CI público PASS: https://github.com/Rafa-Innerchispa/inneros-nebius-nvidia-physical-ai-2026/actions/runs/40458630789
Solo diez archivos explícitamente auditados de la exportación; ninguna historia Git o configuración privada copiada.

57 pruebas del proyecto PASS; cinco rutas reales HTTP 200 en ASGI aislado ligado a loopback, detenido al terminar. No representa despliegue productivo. Respuestas JSON saneadas: API_HTTP_EVIDENCE_20261027.json.

Comando reproducible en la raíz del worktree:
`PYTHONPATH=platform /home/rlopez/inneros/inneros_core/platform/venv/bin/python -m pytest platform/tests/test_capability_gateway.py platform/tests/test_nebius_nvidia_gateway.py tests/test_nebius_nvidia_runtime.py platform/tests/test_guardian_api_contract.py public-export/inneros-nebius-nvidia-physical-ai-2026/tests/test_public_runtime.py -q`

Inferencia Nebius REAL: pendiente. Rafael autorizó explícitamente una sola prueba con créditos existentes, datos sintéticos y hasta 2048 tokens de salida, sin compras ni recargas. El cliente actual limita la salida a 512. No habilitar inferencia de pago permanente en el API.

Credenciales: refs owner_vault:nebius_token_factory/api_key y owner_vault:nebius/api_key ausentes; búsqueda de metadatos Nebius vacía y variables oficiales ausentes en Intel/AMD. No se imprimieron secretos. Se preparó entrada oculta directamente al Vault para el owner. Mientras falte la clave: BLOCKED_MISSING_VAULT_CREDENTIAL; cero inferencias de pago realizadas.

No se modificó el frontend de ChatGPT, ni servicios físicos, alta disponibilidad, Cursor, Alexa o llamadas; no se envió Devpost.


## Update: owner credential enrolled and live inference verified

The owner supplied a credential, stored only in owner_vault. The first approved attempt failed with TypeError while parsing the provider response; its complete response/usage were not retained. A second attempt was separately approved with a 2048 output-token bound and returned REAL inference with NVIDIA Nemotron 3 Nano: 308 prompt + 692 completion = 1000 tokens, finish_reason stop. See NEBIUS_SECOND_LIVE_RECEIPT_20261027.json. The first failed receipt remains preserved separately. No card, top-up, production deployment, physical mutation or recurring paid job was added. Parser receipt retention and bounded output configuration pass 50 offline tests.
