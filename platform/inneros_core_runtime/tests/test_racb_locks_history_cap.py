"""El historial de locks no puede crecer sin tope (rompió Mongo en 16 MB)."""
import unittest

from inneros_core_runtime import racb_locks as locks


class LockHistoryCapTests(unittest.TestCase):
    def test_push_keeps_only_last_entries(self):
        push = locks.history_push_update(
            action="renew", agent="AG-25", task_id="ops_x", revision=41
        )
        entry = push["history"]
        self.assertEqual(entry["$slice"], -locks.LOCK_HISTORY_CAP)
        self.assertEqual(len(entry["$each"]), 1)
        self.assertEqual(entry["$each"][0]["action"], "renew")
        self.assertEqual(entry["$each"][0]["agent"], "ag-25")
        self.assertEqual(entry["$each"][0]["revision"], 41)

    def test_cap_is_small(self):
        self.assertLessEqual(locks.LOCK_HISTORY_CAP, 100)


if __name__ == "__main__":
    unittest.main()
