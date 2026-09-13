from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
UNIT = PLATFORM_ROOT / "deploy" / "systemd" / "ralfia-mcp-profile@.service"
INSTALLER = PLATFORM_ROOT / "scripts" / "install_mcp_profile_service.sh"


class McpProfileFailClosedTests(unittest.TestCase):
    def test_instance_environment_is_required(self) -> None:
        text = UNIT.read_text(encoding="utf-8")
        required = "EnvironmentFile=/home/rlopez/.config/ralphiia/mcp-profiles/%i.env"
        optional = "EnvironmentFile=-/home/rlopez/.config/ralphiia/mcp-profiles/%i.env"
        self.assertIn(required, text)
        self.assertNotIn(optional, text)

    def test_canonical_port_guard_runs_before_free_port(self) -> None:
        text = UNIT.read_text(encoding="utf-8")
        guard = 'Refusing bounded MCP profile on canonical port 8102'
        free_port = 'free_port.sh ${MCP_PORT}'
        self.assertIn(guard, text)
        self.assertIn(free_port, text)
        self.assertLess(text.index(guard), text.index(free_port))

    def test_profile_uses_current_inneros_mcp_runtime(self) -> None:
        text = UNIT.read_text(encoding="utf-8")
        self.assertIn("-m inneros_core_runtime.mcp_server", text)
        self.assertNotIn("-m raphiia_openai.mcp_server", text)

    def test_installer_rejects_canonical_port_before_any_apply(self) -> None:
        result = subprocess.run(
            ["bash", str(INSTALLER), "quoteops", "8102", "--plan"],
            cwd=PLATFORM_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Refusing bounded MCP profile on canonical port 8102", result.stderr)

    def test_installer_preserves_safe_quoteops_default(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('PORT="${2:-8110}"', text)
        self.assertIn("CANONICAL_MCP_PORT=8102", text)
        self.assertLess(text.index("PORT == CANONICAL_MCP_PORT"), text.index('if [[ ! -f "$UNIT_SOURCE" ]]'))


if __name__ == "__main__":
    unittest.main()
