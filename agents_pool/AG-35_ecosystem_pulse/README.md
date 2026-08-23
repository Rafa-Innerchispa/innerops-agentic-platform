# AG-35 Ecosystem Pulse

**Agente único de reporte ecosistema** (Intel + AMD):

- Disco ambos nodos
- Progreso ingesta KB (AG-34)
- Servicios `ralfia-*` failed
- Qdrant puntos
- WhatsApp digest 2x/día + alerta inmediata si servicios caídos

Timer: `ralfia-ecosystem-pulse.timer` (08:00 y 20:00 UTC)

Instalar: `bash ralfiia-amd-standby/scripts/install_ecosystem_monitoring.sh`

## Política WhatsApp alertas operativas

| Variable | Valor recomendado |
|----------|-------------------|
| `NOTIFY_WHATSAPP_TO` | Tu móvil personal `593999059000` |
| `RALFIA_ALERTS_TO` | Igual (override explícito) |
| `RALFIA_ALERTS_VIA_NODE` | `primary` → envía vía Evolution **Intel PC Doctor** |

Los chips Evolution son **remitentes** (PC Doctor vs InnerChispa).  
Tú recibes **destino** siempre en tu número personal.

Agentes que notifican:
- **AG-31** recovery post-boot
- **AG-33** sync stale
- **AG-34** ingesta KB %
- **AG-35** pulso ecosistema
- **dual-node-monitor** servicios caídos
- **disk_guard** disco lleno

## Almacenamiento AMD

Ver `ralfiia-amd-standby/docs/DISK_STRATEGY.md` — HDD 2 TB en `/home/rlopez/data`, variable `DISK_HDD_ROOT`.
