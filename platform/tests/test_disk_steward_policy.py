from pathlib import Path
from types import SimpleNamespace

import pytest

from inneros_core_runtime import disk_steward
from inneros_core_runtime.notifications import evolution_client


def test_detect_archive_base_skips_root_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = {Path("/home/rlopez/data"), Path("/mnt/datos_agentes")}

    monkeypatch.setattr(Path, "exists", lambda self: self in existing or str(self) == "/")
    monkeypatch.setattr(
        disk_steward,
        "_filesystem_for",
        lambda path: "/dev/root" if str(path) in {"/", "/home/rlopez/data"} else "/dev/sdb1",
    )
    monkeypatch.setattr(
        disk_steward.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=880 * 1024**3, used=100, free=800),
    )

    assert disk_steward._detect_archive_base() == Path("/mnt/datos_agentes")


def test_detect_archive_base_prefers_largest_non_root_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = {Path("/home/rlopez/data"), Path("/mnt/datos_agentes")}

    monkeypatch.setattr(Path, "exists", lambda self: self in existing or str(self) == "/")
    monkeypatch.setattr(
        disk_steward,
        "_filesystem_for",
        lambda path: {
            "/": "/dev/root",
            "/home/rlopez/data": "/dev/sdb1",
            "/mnt/datos_agentes": "/dev/sdc1",
        }.get(str(path), ""),
    )
    monkeypatch.setattr(
        disk_steward.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=(1800 if str(path) == "/home/rlopez/data" else 880) * 1024**3, used=100, free=800),
    )

    assert disk_steward._detect_archive_base() == Path("/home/rlopez/data")


def test_different_filesystem_blocks_same_source_and_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(disk_steward, "_mount_source", lambda path: "/dev/root")

    assert disk_steward._different_filesystem(Path("/home/rlopez/backups/a.tar.gz"), Path("/home/rlopez/data/backups")) is False


def test_build_status_warns_on_any_pressured_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        disk_steward,
        "scan_mounts",
        lambda: [
            {"mount": "/", "use_pct": 50, "free_pct": 50, "level": "ok", "is_primary": True},
            {"mount": "/mnt/datos_agentes", "use_pct": 85, "free_pct": 15, "level": "critical", "is_primary": False},
        ],
    )
    monkeypatch.setattr(disk_steward, "scan_backups", lambda: [])
    monkeypatch.setattr(disk_steward, "_safe_move_candidates", lambda: [])

    status = disk_steward.build_status(include_candidates=True)

    assert status["overall"] == "critical"
    assert status["pressured_mounts"][0]["mount"] == "/mnt/datos_agentes"


def test_notification_local_node_prefers_known_hostname_over_stale_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RALFIA_NODE", "amd")
    monkeypatch.setattr(evolution_client.socket, "gethostname", lambda: "ralphi-ia-ver-10")

    assert evolution_client.local_node() == "primary"
