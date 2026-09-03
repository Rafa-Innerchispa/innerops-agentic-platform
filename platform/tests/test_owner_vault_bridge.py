from __future__ import annotations

import ast
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from raphiia_openai import owner_vault_bridge as bridge
from raphiia_openai.mcp_catalog import tool_catalog


OWNER_VAULT_TOOLS = {
    "owner_vault_store_secret",
    "owner_vault_secret_status",
    "owner_vault_materialize_project_env",
}


class OwnerVaultBridgeTests(unittest.TestCase):
    def test_imports_resolve_to_isolated_worktree(self) -> None:
        self.assertTrue(str(Path(bridge.__file__).resolve()).startswith(str(PLATFORM_ROOT)))
        self.assertTrue(str(Path(tool_catalog.__file__).resolve()).startswith(str(PLATFORM_ROOT)))

    def test_store_secret_is_owner_only_and_never_returns_plaintext(self) -> None:
        denied = bridge.store_secret(category="alpaca", key="api_secret", secret="TOP-SECRET", actor="CHATGPT")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"], "owner_only")
        self.assertFalse(denied["secret_returned"])

        with mock.patch.object(
            bridge.owner_vault,
            "save_owner_credential",
            return_value={"ok": True, "vault_id": "cred_alpaca_api_secret"},
        ) as save:
            result = bridge.store_secret(
                category="alpaca",
                key="api_secret",
                secret="TOP-SECRET",
                label="Alpaca paper secret",
                project_id="inneros-alpha-alpaca",
                actor="RAFAEL",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["secret_ref"], "owner_vault:alpaca/api_secret")
        self.assertFalse(result["secret_returned"])
        self.assertNotIn("TOP-SECRET", repr(result))
        save.assert_called_once()
        self.assertEqual(save.call_args.kwargs["secret"], "TOP-SECRET")
        self.assertEqual(save.call_args.kwargs["metadata"]["project_id"], "inneros-alpha-alpaca")

    def test_secret_status_uses_reveal_false(self) -> None:
        with mock.patch.object(
            bridge.owner_vault,
            "get_owner_credential",
            return_value={
                "ok": True,
                "vault_id": "cred_alpaca_api_secret",
                "label": "Alpaca paper secret",
                "metadata": {"project_id": "inneros-alpha-alpaca"},
                "updated_at": "2026-09-03T00:00:00+00:00",
            },
        ) as get:
            result = bridge.secret_status(category="alpaca", key="api_secret", actor="RAFAEL")

        self.assertTrue(result["ok"])
        self.assertTrue(result["present"])
        self.assertFalse(result["secret_returned"])
        self.assertNotIn("secret", {key.lower() for key in result if key != "secret_returned"})
        get.assert_called_once_with("api_secret", category="alpaca", reveal=False, actor="RAFAEL")

    def test_materialize_project_env_is_0600_and_does_not_echo_values(self) -> None:
        secret_value = "alpaca-paper-secret-value"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with (
                mock.patch.object(bridge.Path, "home", return_value=tmp_path),
                mock.patch.object(
                    bridge.owner_vault,
                    "get_owner_credential",
                    return_value={"ok": True, "secret": secret_value},
                ) as get,
            ):
                result = bridge.materialize_project_env(
                    namespace="inneros-alpha-alpaca",
                    bindings={"ALPACA_API_SECRET": "owner_vault:alpaca/api_secret"},
                    static_values={"ALPACA_TRADING_MODE": "paper"},
                    actor="RAFAEL",
                )

            target = tmp_path / ".config" / "inneros-alpha-alpaca" / "runtime.env"
            self.assertTrue(result["ok"])
            self.assertEqual(result["mode"], "0600")
            self.assertFalse(result["secret_returned"])
            self.assertNotIn(secret_value, repr(result))
            self.assertTrue(target.is_file())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            content = target.read_text(encoding="utf-8")
            self.assertIn("ALPACA_API_SECRET=" + secret_value, content)
            self.assertIn("ALPACA_TRADING_MODE=paper", content)
            get.assert_called_once_with("api_secret", category="alpaca", reveal=True, actor="RAFAEL")

    def test_materialize_rejects_invalid_ref_and_multiline_values(self) -> None:
        invalid = bridge.materialize_project_env(
            namespace="inneros-alpha-alpaca",
            bindings={"ALPACA_API_SECRET": "not-a-vault-ref"},
            actor="RAFAEL",
        )
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["error"], "invalid_secret_ref")

        with mock.patch.object(
            bridge.owner_vault,
            "get_owner_credential",
            return_value={"ok": True, "secret": "line1\nline2"},
        ):
            multiline = bridge.materialize_project_env(
                namespace="inneros-alpha-alpaca",
                bindings={"ALPACA_API_SECRET": "owner_vault:alpaca/api_secret"},
                actor="RAFAEL",
            )
        self.assertFalse(multiline["ok"])
        self.assertEqual(multiline["error"], "multiline_secret_not_supported")
        self.assertFalse(multiline["secret_returned"])

    def test_mcp_server_declares_owner_vault_tools(self) -> None:
        source = (PLATFORM_ROOT / "inneros_core_runtime" / "mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertTrue(OWNER_VAULT_TOOLS.issubset(functions), sorted(OWNER_VAULT_TOOLS - functions))

    def test_catalog_contains_strict_owner_vault_contracts(self) -> None:
        self.assertTrue(OWNER_VAULT_TOOLS.issubset(set(tool_catalog.ALL_MCP_TOOL_NAMES)))
        store = tool_catalog.describe_tool("owner_vault_store_secret")
        status_meta = tool_catalog.describe_tool("owner_vault_secret_status")
        materialize = tool_catalog.describe_tool("owner_vault_materialize_project_env")
        self.assertEqual(store["required_scopes"], ["ralfia:admin", "ralfia:private_memory"])
        self.assertEqual(store["risk_level"], "high")
        self.assertEqual(status_meta["required_scopes"], ["ralfia:read", "ralfia:private_memory"])
        self.assertEqual(status_meta["risk_level"], "medium")
        self.assertEqual(materialize["required_scopes"], ["ralfia:admin", "ralfia:private_memory"])
        self.assertEqual(materialize["risk_level"], "high")
        self.assertEqual(materialize["output_schema"]["mode"], "0600")
        self.assertEqual(store["output_schema"]["secret_returned"], "false")


if __name__ == "__main__":
    unittest.main()
