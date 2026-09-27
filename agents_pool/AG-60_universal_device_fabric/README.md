# AG-60 Universal Device Fabric

AG-60 is the read-only physical device connectivity agent for InnerOS and PC
Doctor field work. It coordinates the Universal Physical Device Fabric MCP
surface:

- `device_fabric_providers`
- `device_fabric_discover`
- `device_fabric_probe`
- `device_fabric_bind`
- `device_fabric_inventory`
- `device_fabric_capabilities`
- `device_fabric_health`
- `device_fabric_get`

## Scope

The agent inventories and identifies physical infrastructure without changing
live systems. It supports:

- Hikvision cameras, NVR/DVR, video intercoms and access control
- Dahua IP cameras and analog channels through DVR/NVR/XVR
- TP-Link/Tapo, Imou and EZVIZ
- ZKTeco through Workforce ADMS/iClock
- Grandstream UCM and GWN/GCC as separate providers
- Intelbras through Home Assistant/Guardian
- UniFi/Ubiquiti through Home Assistant/AG-32
- DMX through AG-59
- Broadlink, Tuya and Alexa through Home Assistant/VoiceOps
- ONVIF, RTSP and generic network discovery

## Safety

AG-60 never changes DHCP, VLANs, firewall, firmware, cameras, NVRs, PBX,
alarms or access control. Live operations are restricted to read-only TCP,
HTTP, RTSP and registry/status reads. Authenticated write paths must remain in
their provider-specific audited agents.
