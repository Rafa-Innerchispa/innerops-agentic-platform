"""Local MCP server for a technician's Vantage QLink field laptop.

Start via: python -m inneros_core_runtime.vantage_qlink_mcp
This process MUST run on the computer physically attached by RS-232.
The remote AMD/Intel MCP runtime has no direct access to the laptop's USB.

Only read-only tools are exported. Firmware/configuration writes, V-commands
and station load switching are intentionally absent.
"""
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from inneros_core_runtime import vantage_qlink_field as field

mcp = FastMCP(
    "InnerOS Vantage QLink — Onsite Field Adapter",
    instructions=(
        "RS-232 QLink field tools are read-only and local to this laptop. "
        "Never infer relay state from a keypad button event. "
        "No programming or control tools are available. "
        "Do not treat this as connected to the remote InnerOS instance until "
        "a scoped authenticated field relay is explicitly configured."
    ),
)


@mcp.tool()
def vantage_serial_ports() -> dict[str, Any]:
    """List physical serial ports visible to THIS local field laptop only."""
    return field.list_serial_ports()


@mcp.tool()
def vantage_qlink_capabilities() -> dict[str, Any]:
    """Report supported and unsupported QLink features (without touching hardware)."""
    return {
        "ok": True,
        "provider_id": field.PROVIDER_ID,
        "mode": "local_read_only",
        "controller_model_reference": "CLMNES050",
        "serial_port_listing": True,
        "passive_capture": True,
        "one_known_button_query_VGS": True,
        "backup_hash_manifest": True,
        "button_event_observation": "available_only_if_QLink_emits_serial_frames",
        "QLink_VGS_query": "one_known_address; read-only request transmits RS232 bytes",
        "station_bus_relay_state": "NOT_VERIFIED",
        "relay_or_scene_control": "NOT_IMPLEMENTED",
        "QLink_programming": "NOT_IMPLEMENTED",
        "Home_Assistant_entity_exposure": "NOT_IMPLEMENTED",
        "remote_InnerOS_communication": "NOT_IMPLEMENTED",
        "requires_onsite_connection": True,
        "no_automatic_writes": True,
    }


@mcp.tool()
def vantage_qlink_observe(port: str, site_id: str, seconds: float = 5.0) -> dict[str, Any]:
    """Read unsolicited QLink RS232 messages for up to 60s; NEVER send commands."""
    return field.observe_serial(
        port, site_id=site_id, seconds=seconds, max_events=100
    )


@mcp.tool()
def vantage_qlink_read_switch_state(
    port: str, site_id: str, master: int, station: int, button: int
) -> dict[str, Any]:
    """Query ONE known QLink keypad switch address with non-mutating VGS#.

    Returns button state (not relay/load state). Serial sends a read command.
    Never probes a guessed range, toggles devices, or programs the Master.
    """
    return field.query_switch_state(
        port, site_id=site_id, master=master,
        station=station, button=button
    )


@mcp.tool()
def vantage_qlink_backup_manifest(site_id: str, paths: list[str]) -> dict[str, Any]:
    """SHA-256 inventory of existing .qlk/.bak/.bin files within approved local folder."""
    return field.backup_manifest(paths, site_id=site_id)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
