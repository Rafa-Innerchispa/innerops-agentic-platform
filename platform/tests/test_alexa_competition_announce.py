from __future__ import annotations

from unittest.mock import patch


def test_competition_entries_call_announce():
    for mod in ("cursor", "codex", "antigravity"):
        with patch("competition.announce_lib.announce_phrase", return_value={"ok": True}) as mock:
            entry = __import__(f"competition.entries.{mod}", fromlist=["run"])
            out = entry.run()
            assert out.get("ok") is True
            mock.assert_called_once()
