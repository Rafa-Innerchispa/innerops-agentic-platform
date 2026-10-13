"""Regression checks for bounded recovery of vanished Cursor headless workers."""
from scripts.cursor_ops_headless_autopilot import _headless_max_reaps


def test_headless_retry_budget_defaults_to_three(monkeypatch):
    monkeypatch.delenv("INNEROS_CURSOR_HEADLESS_MAX_REAPS", raising=False)
    assert _headless_max_reaps() == 3


def test_headless_retry_budget_accepts_valid_configuration(monkeypatch):
    monkeypatch.setenv("INNEROS_CURSOR_HEADLESS_MAX_REAPS", "5")
    assert _headless_max_reaps() == 5


def test_headless_retry_budget_clamps_nonpositive_values(monkeypatch):
    for value in ("0", "-2"):
        monkeypatch.setenv("INNEROS_CURSOR_HEADLESS_MAX_REAPS", value)
        assert _headless_max_reaps() == 1


def test_headless_retry_budget_fails_safe_on_invalid_input(monkeypatch):
    for value in ("invalid", ""):
        monkeypatch.setenv("INNEROS_CURSOR_HEADLESS_MAX_REAPS", value)
        assert _headless_max_reaps() == 3
