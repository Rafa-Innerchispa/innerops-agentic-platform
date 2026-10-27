"""Vantage QLink field adapter: no hardware required, zero TX is mandatory."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from inneros_core_runtime import device_fabric, vantage_qlink_field as field


def test_provider_is_clearly_not_validated_and_read_only():
    found = {p["provider_id"]: p for p in device_fabric.device_fabric_providers()["providers"]}
    qlink = found["vantage_qlink"]
    assert qlink["support_state"] == "not_validated"
    assert qlink["protocols"] == ["rs232_qlink"]
    assert "passive_serial_observe" in qlink["capabilities"]
    assert "control" not in qlink["capabilities"]


@pytest.mark.parametrize("raw,kind", [
    ("SW 1 9 23 1", "button_event"),
    ("RGS# 1 9 23 0", "button_state"),
    ("VGS# 1 9 23 1", "button_state"),
    ("LO 1 2 3 4 50", "enclosure_load_report"),
    ("LS 1 2 3 4", "station_load_unverified"),
    ("garbled!\n", "unknown"),
    ("", "empty"),
])
def test_parse_never_claims_station_bus_load_status(raw, kind):
    assert field.parse_line(raw)["kind"] == kind
    if kind == "button_event":
        assert field.parse_line(raw)["load_state_verified"] is False


def test_active_serial_commands_are_never_transmitted(monkeypatch):
    class FakeSerial:
        writes = 0
        def __init__(self, **kwargs):
            self.timeout = kwargs["timeout"]
            self.lines = [b"SW 1 9 23 1\r\n", b"LS 1 5 3 2\r\n", b""]
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def readline(self, limit):
            return self.lines.pop(0) if self.lines else b""
        def write(self, data):
            type(self).writes += 1
            raise AssertionError("Read-only adapter tried to transmit a command")

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=FakeSerial))
    timestamps = iter([0.0, 0.0, 0.005, 0.010, 0.020, 1.0])
    monkeypatch.setattr(field.time, "monotonic", lambda: next(timestamps, 1.1))
    result = field.observe_serial("COM5", seconds=0.1, site_id="puerto_azul_ashley")
    assert result["ok"] is True
    assert result["count"] == 2
    assert result["frames"][0]["kind"] == "button_event"
    assert result["frames"][1]["kind"] == "station_load_unverified"
    assert result["transmitted_commands"] == 0
    assert FakeSerial.writes == 0
    assert result["relay_control_implemented"] is False


def test_observer_rejects_unscoped_site_and_long_capture():
    with pytest.raises(ValueError):
        field.observe_serial("COM1", seconds=10, site_id="../other_client")
    with pytest.raises(ValueError):
        field.observe_serial("COM1", seconds=61, site_id="ashley")


def test_backup_manifest_never_modifies_files(tmp_path):
    file = tmp_path / "ASHLEY_FLASH.qlk"
    file.write_bytes(b"example backup bytes")
    before = file.stat().st_mtime_ns
    result = field.backup_manifest([str(file)], site_id="puerto_azul_ashley")
    assert result["backups"][0]["sha256"] == hashlib.sha256(b"example backup bytes").hexdigest()
    assert result["source_files_modified"] is False
    assert result["source_files_uploaded"] is False
    assert before == file.stat().st_mtime_ns


def test_manifest_rejects_unexpected_extension(tmp_path):
    file = tmp_path / "secrets.env"
    file.write_text("DO_NOT_READ")
    with pytest.raises(ValueError):
        field.backup_manifest([str(file)], site_id="puerto_azul_ashley")
