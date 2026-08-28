import subprocess
import unittest
from unittest.mock import patch

from raphiia_openai import whatsapp_commands, whatsapp_service_ops as ops


class TestWhatsappServiceOps(unittest.TestCase):
    def test_evolution_probe_uses_canonical_node_address(self):
        class Response:
            def raise_for_status(self): return None
            def json(self): return {"instance": {"state": "open"}}

        with patch.object(ops.notification_settings, "EVOLUTION_API_KEY", "fixture-key"), patch.object(
            ops.notification_settings, "EVOLUTION_INSTANCE", "fixture-primary"
        ), patch.object(ops.httpx, "get", return_value=Response()) as getter:
            self.assertEqual(ops._evolution_health("primary"), "up")
        self.assertEqual(
            getter.call_args.args[0],
            "http://192.168.1.4:8082/instance/connectionState/fixture-primary",
        )

    def test_evolution_without_credentials_reports_api_alive_not_connection_open(self):
        class Response:
            status_code = 200

        with patch.object(ops.notification_settings, "EVOLUTION_API_KEY", ""), patch.object(
            ops.notification_settings, "EVOLUTION_INSTANCE", "fixture-primary"
        ), patch.object(ops.httpx, "get", return_value=Response()) as getter:
            self.assertEqual(ops._evolution_health("primary"), "unauthorized_alive")
        self.assertEqual(getter.call_args.args[0], "http://192.168.1.4:8082/")

    def test_natural_parser_resolves_service_node_and_action(self):
        self.assertEqual(
            whatsapp_commands.parse_maintenance_request("recupera el MCP en .5"),
            {"action": "recover", "service": "mcp", "node": "amd"},
        )
        self.assertEqual(
            whatsapp_commands.parse_maintenance_request("reinicia el Panel de Control en .4"),
            {"action": "restart", "service": "portal", "node": "primary"},
        )
        self.assertEqual(
            whatsapp_commands.parse_maintenance_request("ejecuta rm -rf /"),
            None,
        )

    def test_unknown_service_never_becomes_unit_or_shell(self):
        result = whatsapp_commands.parse_maintenance_request("reinicia sshd en .4")
        self.assertEqual(result, {"error": "service_not_allowlisted"})
        self.assertNotIn("sshd", ops.SERVICE_BY_ID)

    def test_executor_uses_only_fixed_allowlisted_argv(self):
        before = {"ok": True, "healthy": False, "system_state": "active", "health": "down"}
        after = {"ok": True, "healthy": True, "system_state": "active", "health": "up"}
        proc = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(ops, "service_status", side_effect=[before, after]), patch.object(
            ops, "_run_node", return_value=proc
        ) as runner, patch.object(ops.time, "sleep"):
            result = ops.execute_service_action("mcp", "primary", "recover")
        self.assertTrue(result["ok"])
        self.assertEqual(
            runner.call_args.args,
            ("primary", ["systemctl", "--user", "restart", "ralfia-mcp.service"]),
        )

    def test_executor_rejects_stop_shell_and_unknown_services(self):
        self.assertEqual(ops.execute_service_action("mcp", "primary", "stop")["error"], "action_not_allowlisted")
        self.assertEqual(ops.execute_service_action("ssh", "primary", "restart")["error"], "service_not_allowlisted")

    def test_log_sanitizer_redacts_credentials(self):
        cleaned = ops.sanitize_log("token=abc123 password:secret normal line")
        self.assertNotIn("abc123", cleaned)
        self.assertNotIn("secret", cleaned)
        self.assertIn("normal line", cleaned)

    def test_remote_http_health_does_not_require_cross_node_ssh(self):
        failed_ssh = subprocess.CompletedProcess([], 255, "", "Permission denied")
        with patch.object(ops, "_local_node", return_value="amd"), patch.object(
            ops, "_run_node", return_value=failed_ssh
        ), patch.object(ops, "_tcp_open", return_value=True):
            result = ops.service_status("mcp", "primary")
        self.assertTrue(result["ok"])
        self.assertTrue(result["healthy"])
        self.assertEqual(result["system_state"], "unknown")
        self.assertEqual(result["telemetry"], "remote_unavailable")


if __name__ == "__main__": unittest.main()
