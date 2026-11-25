from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

import importlib.util

_budget_path = PLATFORM_DIR / "inneros_core_runtime" / "notifications" / "ops_ha_push_budget.py"
_spec = importlib.util.spec_from_file_location("ops_ha_push_budget_test", _budget_path)
assert _spec and _spec.loader
budget = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(budget)  # type: ignore[attr-defined]


class OpsHaPushBudgetTests(unittest.TestCase):
    def test_owner_auth_exempt_even_at_cap(self):
        col = MagicMock()
        col.find_one.return_value = {"day": "2099-01-01", "total": 9999, "counts": {}}
        with (
            patch.object(budget, "_collection", return_value=col),
            patch.dict(os.environ, {"OPS_HA_PUSH_DAILY_CAP": "10", "OPS_HA_PUSH_OWNER_AUTH_EXEMPT": "1"}, clear=False),
            patch.object(budget, "_today_key", return_value="2099-01-01"),
        ):
            out = budget.should_send(budget.CLASS_OWNER_AUTH)
        self.assertTrue(out.get("allowed"))
        self.assertEqual(out.get("reason"), "owner_auth_exempt")

    def test_scout_blocked_when_disabled(self):
        self.assertFalse(budget.ha_scout_enabled())
        with patch.dict(os.environ, {"NOTIFY_OPS_HA_SCOUT": "0"}, clear=False):
            self.assertFalse(budget.ha_scout_enabled())

    def test_primary_ha_disables_telegram_secondary_by_default(self):
        with patch.dict(
            os.environ,
            {"NOTIFY_OPS_PRIMARY": "ha_companion", "NOTIFY_OPS_TELEGRAM_SECONDARY": "0"},
            clear=False,
        ):
            self.assertFalse(budget.telegram_secondary_enabled())


if __name__ == "__main__":
    unittest.main()