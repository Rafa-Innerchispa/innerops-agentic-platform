# Registro de servicios Ralfi IA — 2026-08-05

> Plataforma: `ralfi-ia-platform` · Puertos canónicos: `ai_coordination/PORTS_CANONICAL.md`

## Núcleo plataforma (siempre activo en Intel .4)

| Servicio systemd | Módulo | Puerto | Función |
|------------------|--------|--------|---------|
| `ralfia-portal.service` | portal-mcp | **2002** | Hub Control Center, `/accounting/ui` |
| `ralfia-mcp.service` | portal-mcp | **8102** | MCP tools (117+) |
| `ralfia-app.service` | portal-mcp | **8101** | Health + editorial hub |
| `ralfia-auth.service` | portal-mcp | **8103** | OAuth |
| `ralfia-voice-gateway.service` | portal-mcp | **8200** | voz.pcdoctor.ai PWA |
| `ralfia-coordination-daemon.service` | coordination | — | AG-25 orquestador |
| `ralfia-quoteops.service` | quoting/quoteops | **8765** | Cotizaciones conversacionales |
| `ralfia-smart-quoter.service` | quoting/smart-quoter | **2026** | Cotizador audio/Ollama |
| `ralfia-mcp-profile@quoteops.service` | quoting | **8102** | Perfil MCP acotado quoteops |

## Infra / monitoreo

| Servicio | Módulo | Función |
|----------|--------|---------|
| `ralfia-dual-node-monitor.service` | infra | Salud .4/.5 |
| `ralfia-ollama-router.service` | infra | Router Ollama :11435 (AMD) |
| `ralfia-kb-ingest-sentinel.timer` | connectors/gdrive | Ingesta KB |
| `ralfia-ecosystem-pulse.timer` | coordination | Alertas WhatsApp |
| `ralfia-boot-verify.service` | infra | Post-boot check |

## Editorial / media

| Servicio | Módulo | Función |
|----------|--------|---------|
| `ralfia-editorial-worker.service` | coordination | Cola LinkedIn/imágenes |
| `ralfia-gpu-handoff.service` | infra | Ollama ↔ ComfyUI |

## Home Assistant

| Componente | Módulo | Notas |
|------------|--------|-------|
| Docker Home Assistant | **home-assistant** | Domótica · puerto estándar HA |
| `ralfia-ha-watch.service` | home-assistant | Watchdog (si configurado) |
| `homeassistant_client.py` | home-assistant | Puente en plataforma MCP |

## Hackathons (aislados — carpeta `hackathons/`)

| Proyecto | Puerto | Servicio |
|----------|--------|----------|
| liveops-intelligence | 8788 | `ralfia-liveops-bridge` |
| funding-hub | 8099 | `ralfia-funding-hub` |
| hackathon-autopilot | 8096 | `ralf-hackathon-autopilot` |
| amd-hybrid-ops | 8220 | docker |

## ISKCON (repo separado `iskcon/`)

| Componente | Puerto |
|------------|--------|
| Sponsor Desk preview | **2027** |
| iskcon-panihati-2026 | (evento) |

## Docker compartido

| Servicio | Puerto |
|----------|--------|
| MongoDB | 27017 |
| Qdrant | 6333 |
| Ollama | 11434 |
| Evolution API | 8082 |
| n8n | 5678 |
| Open WebUI | 3000 |
| AnythingLLM | 3001 |

## Reinicio plataforma (después de reestructura)

```bash
systemctl --user restart ralfia-portal ralfia-mcp ralfia-app ralfia-quoteops ralfia-smart-quoter
```
