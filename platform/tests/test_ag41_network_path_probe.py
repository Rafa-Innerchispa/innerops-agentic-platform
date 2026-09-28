from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "inneros_core_runtime" / "agents" / "ag41_peer_ops_executor.py"
SPEC = importlib.util.spec_from_file_location("ag41_network_probe_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
ag41 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ag41)


def _proc(argv: list[str], returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def _project(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "site.json").write_text(
        json.dumps(
            {
                "project_id": "fixture-building",
                "site_id": "fixture-site",
                "authorized_subnets": ["10.44.0.0/24"],
                "diagnostic_sentinels": {
                    "gateway": ["10.44.0.1"],
                    "core": ["10.44.0.10", "10.44.0.11"],
                },
            }
        ),
        encoding="utf-8",
    )


def _resolver(tmp_path: Path):
    return {
        "project_path": str(tmp_path),
        "project": {"project_id": "fixture-building"},
    }


def test_scope_loads_from_private_project_config(tmp_path: Path) -> None:
    _project(tmp_path)
    with patch(
        "raphiia_openai.project_runtime_registry.resolve_project",
        return_value=_resolver(tmp_path),
    ):
        networks, sentinels, meta = ag41._network_probe_scope("fixture-building", "primary")

    assert [str(item) for item in networks] == ["10.44.0.0/24"]
    assert sentinels == ("10.44.0.1", "10.44.0.10", "10.44.0.11")
    assert meta["site_id"] == "fixture-site"


def test_probe_rejects_target_outside_project_scope(tmp_path: Path) -> None:
    _project(tmp_path)
    with patch(
        "raphiia_openai.project_runtime_registry.resolve_project",
        return_value=_resolver(tmp_path),
    ), pytest.raises(PermissionError, match="network_probe_target_out_of_scope"):
        ag41.peer_network_path_probe(
            project_id="fixture-building",
            targets=["8.8.8.8"],
            count=1,
        )


def test_probe_rejects_hostname(tmp_path: Path) -> None:
    _project(tmp_path)
    with patch(
        "raphiia_openai.project_runtime_registry.resolve_project",
        return_value=_resolver(tmp_path),
    ), pytest.raises(ValueError, match="network_probe_requires_ip_literal"):
        ag41.peer_network_path_probe(
            project_id="fixture-building",
            targets=["example.com"],
            count=1,
        )


def test_parse_ping_output() -> None:
    parsed = ag41._parse_ping_output(
        "3 packets transmitted, 3 received, 0% packet loss, time 2002ms\n"
        "rtt min/avg/max/mdev = 1.100/2.200/3.300/0.400 ms\n"
    )
    assert parsed["transmitted"] == 3
    assert parsed["received"] == 3
    assert parsed["packet_loss_percent"] == 0.0
    assert parsed["rtt_ms"]["avg"] == 2.2


def test_probe_is_read_only_and_scoped(tmp_path: Path) -> None:
    _project(tmp_path)

    def fake_run(node: str, argv: list[str], **kwargs):
        if argv[:3] == ["ip", "route", "get"]:
            return _proc(argv, 0, "10.44.0.1 dev tailscale0\n")
        if argv and argv[0] == "ping":
            return _proc(
                argv,
                0,
                "3 packets transmitted, 3 received, 0% packet loss, time 2002ms\n"
                "rtt min/avg/max/mdev = 2.000/2.500/3.000/0.300 ms\n",
            )
        raise AssertionError(argv)

    with patch(
        "raphiia_openai.project_runtime_registry.resolve_project",
        return_value=_resolver(tmp_path),
    ), patch.object(ag41, "_run_node", side_effect=fake_run) as runner:
        result = ag41.peer_network_path_probe(
            project_id="fixture-building",
            targets=["10.44.0.1", "10.44.0.10"],
            count=3,
            timeout_seconds=1,
        )

    assert result["ok"] is True
    assert result["summary"]["reachable"] == 2
    assert result["security"]["read_only"] is True
    assert result["security"]["project_runtime_scope_enforced"] is True
    assert runner.call_count == 4
    assert all(call.args[1][0] in {"ip", "ping"} for call in runner.call_args_list)


def test_probe_defaults_to_project_sentinels(tmp_path: Path) -> None:
    _project(tmp_path)
    seen = []

    def fake_run(node: str, argv: list[str], **kwargs):
        seen.append(argv)
        if argv[:3] == ["ip", "route", "get"]:
            return _proc(argv, 0, f"{argv[-1]} dev tailscale0\n")
        return _proc(
            argv,
            0,
            "1 packets transmitted, 1 received, 0% packet loss, time 0ms\n"
            "rtt min/avg/max/mdev = 1.000/1.000/1.000/0.000 ms\n",
        )

    with patch(
        "raphiia_openai.project_runtime_registry.resolve_project",
        return_value=_resolver(tmp_path),
    ), patch.object(ag41, "_run_node", side_effect=fake_run):
        result = ag41.peer_network_path_probe(project_id="fixture-building", count=1)

    assert result["summary"]["targets"] == 3
    assert [row["target"] for row in result["results"]] == [
        "10.44.0.1",
        "10.44.0.10",
        "10.44.0.11",
    ]
    assert all(cmd[0] in {"ip", "ping"} for cmd in seen)
