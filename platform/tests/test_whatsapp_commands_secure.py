import unittest
from unittest.mock import patch

from raphiia_openai import whatsapp_commands as commands


class TestSecureWhatsappCommands(unittest.TestCase):
    @staticmethod
    def operational_identity():
        return {
            "authenticated": True,
            "principal_id": "principal_pcdoctor_operations",
            "preferred_name": "PC Doctor",
            "roles": ["operational_line"],
            "scopes": list(commands.whatsapp_identity.OPS_SCOPES),
            "sender_hash": "fixture-operations",
        }

    def test_bare_status_queries_both_nodes(self):
        snapshot = {"checked_at": "fixture", "source": "fixture", "evidence_ref": "health:fixture", "tool_call_id": "health_fixture"}
        with patch.object(commands.whatsapp_service_ops, "status_snapshot", return_value=snapshot) as collector, patch.object(
            commands.whatsapp_service_ops, "format_status_text", return_value="fixture"
        ) as formatter:
            result = commands.execute_command("estado")
        self.assertEqual(result["node"], "all")
        collector.assert_called_once_with(None)
        formatter.assert_called_once_with(None, snapshot=snapshot)
        self.assertEqual(result["evidence_ref"], "health:fixture")

    def test_explicit_status_selects_requested_node(self):
        snapshot = {"checked_at": "fixture", "source": "fixture", "evidence_ref": "health:fixture", "tool_call_id": "health_fixture"}
        with patch.object(commands.whatsapp_service_ops, "status_snapshot", return_value=snapshot) as collector, patch.object(
            commands.whatsapp_service_ops, "format_status_text", return_value="fixture"
        ) as formatter:
            result = commands.execute_command("estado del servidor .5")
        self.assertEqual(result["node"], "amd")
        collector.assert_called_once_with("amd")
        formatter.assert_called_once_with("amd", snapshot=snapshot)

    def test_diagnostic_uses_allowlisted_service_and_sanitized_log_api(self):
        status = {"ok": True, "healthy": False, "system_state": "inactive", "health": "down"}
        logs = {"ok": True, "logs": "fixture saneado"}
        with patch.object(commands.whatsapp_service_ops, "service_status", return_value=status), patch.object(
            commands.whatsapp_service_ops, "recent_logs", return_value=logs
        ) as reader:
            result = commands.execute_command("diagnostica MCP en .5")
        self.assertEqual(result["service"], "mcp")
        self.assertEqual(result["node"], "amd")
        reader.assert_called_once_with("mcp", "amd", lines=20)

    def test_unknown_diagnostic_service_is_rejected(self):
        result = commands.execute_command("logs de ssh en .5")
        self.assertEqual(result["error"], "service_not_allowlisted")

    def test_voice_like_natural_requests_route_to_typed_tools(self):
        self.assertEqual(
            commands.parse_command("Quiero que me digas el estado de los dos servidores")[0],
            "status",
        )
        self.assertEqual(
            commands.parse_command("Puedes revisar qué es lo que pasa con el panel de control del servidor 4")[0],
            "diagnostic",
        )
        self.assertEqual(
            commands.parse_command("¿Qué comandos puedes ejecutar en ese video?")[0],
            "help",
        )

    def test_email_detail_and_reply_commands_do_not_overlap_generic_email(self):
        self.assertEqual(commands.parse_command("correo mail_fixture")[0], "email_detail")
        cmd, arg = commands.parse_command("responder mail_fixture: Respuesta ficticia")
        self.assertEqual(cmd, "email_reply")
        self.assertIn("Respuesta ficticia", arg)

    def test_menu_exposes_typed_options_and_custom_prompt(self):
        menu = commands.execute_command("menu")
        self.assertEqual(menu["interactive"]["kind"], "buttons")
        self.assertEqual(
            [button["id"] for button in menu["interactive"]["buttons"]],
            ["menu.status", "menu.email", "menu.more"],
        )
        more = commands.execute_command("más opciones")
        self.assertEqual(more["command"], "menu_more")
        custom = commands.execute_command("solicitud personalizada")
        self.assertIn("texto o audio", custom["text"])

    def test_operational_line_can_read_status_but_not_business_data(self):
        with patch.object(
            commands.whatsapp_identity, "resolve_identity", return_value=self.operational_identity()
        ), patch.object(
            commands, "execute_command", return_value={"ok": True, "text": "fixture status"}
        ) as execute:
            allowed = commands.handle_inbound_command(
                "estado .5", "593000000222", reply=False, conversation_id="chat-operations"
            )
            denied = commands.handle_inbound_command(
                "saldo", "593000000222", reply=False, conversation_id="chat-operations"
            )
        self.assertTrue(allowed["ok"])
        self.assertEqual(denied["error"], "unauthorized_sender")
        execute.assert_called_once_with("estado .5")


if __name__ == "__main__":
    unittest.main()
