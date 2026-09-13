# Intelbras Guardian / ANM 24 NET Integration

Status: middleware and HA component installed; AG-32/voice guard prepared; waiting for owner OAuth + device password.
Date: 2026-09-13
Owner: AG-32 Home Assistant Bridge / Codex

## Runtime

- Middleware source: `/home/rlopez/inneros/inneros_core/integrations/intelbras-guardian`
- Middleware compose: `/home/rlopez/inneros/inneros_core/integrations/intelbras-guardian/docker-compose.inneros.yml`
- Middleware URL from HA/LAN: `http://192.168.1.4:8015`
- Container: `intelbras-guardian-api`
- Port binding: `192.168.1.4:8015 -> 8000`, LAN-only host binding, not Cloudflare/public.
- Persistent data: `/home/rlopez/inneros/inneros_core/integrations/intelbras-guardian/data`
- HA config path: `/mnt/datos_agentes/home-assistant/config`
- HA custom component: `/config/custom_components/intelbras_guardian`
- HA container network: host.

## Installed Component

Source repository: `https://github.com/bobaoapae/guardian-api-intelbras`
The upstream README lists `ANM 24 NET / G2` as supported via ISECNet V1 Cloud / IP Receiver.
The integration creates Home Assistant entities for `alarm_control_panel`, zones, events, sensors, switches and buttons after OAuth and device password configuration.

## Verification Already Done

- `docker compose -f docker-compose.inneros.yml up -d --build` succeeded.
- `curl http://192.168.1.4:8015/api/v1/health` returns `healthy`.
- Home Assistant restarted and loaded custom integration; log only shows normal warning for custom integration.
- Local alarm device is visible on LAN as `device_tracker.alarma_interbras`, IP `192.168.1.202`, MAC `d8:36:5f:2b:15:ae`, TCP `9009` open.
- AG-32/voice smoke reports read-only alarm presence, `requested_write=false` for "revisa la alarma", and `tcp_9009=open`.
- Focused regression suite: `PYTHONPATH=platform /home/rlopez/inneros/inneros_core/platform/venv/bin/python -m pytest platform/tests/test_voice_mcp_home_capabilities.py -q` -> `7 passed`.

## Owner Action Required

Complete the Home Assistant config flow:

1. Open Home Assistant: `http://192.168.1.4:8123`
2. Go to Settings -> Devices & Services -> Add Integration.
3. Search for `Intelbras Guardian`.
4. Use:
   - Host: `192.168.1.4`
   - Port: `8015`
5. Open the Intelbras OAuth URL shown by HA.
6. Log in with the Intelbras account that owns the alarm.
7. Paste the final callback URL back into the HA form.
8. In integration options, configure device password/PIN for the alarm panel.

## Guardrails

- Do not expose the middleware through Cloudflare/public routes.
- Do not commit or print Intelbras credentials or alarm PIN.
- Keep arm/disarm/panic/siren commands behind Home Assistant auth and owner approval phrases in voice/MCP.
- If OAuth fails, check `docker logs intelbras-guardian-api` and HA logs for `intelbras_guardian`.

## Next Automation Work

AG-32/voice is already prepared to detect `alarm_control_panel.*` entities when HA creates them:

- Read status automatically switches from UniFi/TCP presence to the HA alarm panel state when the entity appears.
- Arm/disarm are routed only through Home Assistant and only when the request includes an explicit owner approval phrase.
- Panic, siren and PGM remain blocked until a physical runbook is validated.
- Still pending after OAuth: verify zones, last event, battery/tamper/power sensors.
- Add WhatsApp alerts for alarm triggered, grid/power related alarm trouble if exposed, tamper and battery low.
