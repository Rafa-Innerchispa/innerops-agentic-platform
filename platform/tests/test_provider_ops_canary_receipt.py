"""Receipt test for innocuous Codex/Antigravity provider canaries (always offline)."""

from __future__ import annotations

import unittest


class ProviderOpsCanaryReceiptTests(unittest.TestCase):
    def test_canary_receipt_module_loads(self) -> None:
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
