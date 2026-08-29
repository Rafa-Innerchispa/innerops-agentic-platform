"""Tests for KPI telemetry hooks."""
from __future__ import annotations

import unittest

from inneros_core_runtime import kpi_telemetry


class KpiTelemetryTests(unittest.TestCase):
    def test_human_hours_returned(self) -> None:
        hh = kpi_telemetry.human_hours_returned(
            estimated_manual_minutes=60,
            human_minutes_spent=15,
            confidence="estimated",
        )
        self.assertAlmostEqual(hh["human_hours_returned"], 0.75)
        self.assertFalse(hh["measured"])

    def test_record_task_kpi_not_measured_by_default(self) -> None:
        row = kpi_telemetry.record_task_kpi(
            task_id="ops_test",
            agent="cursor",
            outcome="PASS",
            correlation_id="corr-kpi",
            estimated_manual_minutes=30,
            human_minutes_spent=0,
        )
        self.assertEqual(row["schema_version"], kpi_telemetry.KPI_SCHEMA_VERSION)
        self.assertFalse(row["human_hours_returned"]["measured"])


if __name__ == "__main__":
    unittest.main()
