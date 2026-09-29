# AG-60 Universal Device Fabric

Universal Physical Device Fabric is the read-only connectivity and inventory agent for physical infrastructure.

Scope:

- Cameras, NVR/DVR/XVR, video intercoms and access control.
- Network equipment, PBX/voice, smart home and DMX lighting.
- Bellini I-II and Casa / PC Doctor Lab acceptance inventories.

Safety contract:

- Discovery uses TCP connect, HTTP GET metadata and RTSP OPTIONS only.
- No DHCP, VLAN, firewall, firmware, reboot, credential, camera, PBX, alarm or access-control mutation.
- Credentials are represented only as `credential_ref` presence and are never returned as plaintext.
- Live binding is fail-closed; `device_fabric_bind` is dry-run unless future owner approval adds a write plane.

MCP profile:

- `device_fabric`

MCP tools:

- `device_fabric_providers`
- `device_fabric_discover`
- `device_fabric_probe`
- `device_fabric_bind`
- `device_fabric_inventory`
- `device_fabric_capabilities`
- `device_fabric_health`
- `device_fabric_get`
