from raphiia_openai.a2a_agent_registry import merged_agent_cards, normalize_agent_key


def test_normalize_agent_key_preserves_canonical_ids():
    assert normalize_agent_key("ag25") == "AG-25"
    assert normalize_agent_key("AG_055") == "AG-55"
    assert normalize_agent_key("RalfIA") == "AG-25"


def test_merged_agent_cards_projects_catalog_and_base_cards():
    cards = merged_agent_cards({}, "1.0", "test")
    assert len(cards) >= 55
    assert "AG-25" in cards
    assert cards["AG-25"]["metadata"].get("root_orchestrator") is True


def test_base_card_overrides_catalog_metadata_without_losing_agent_id():
    cards = merged_agent_cards({"browser-qa": {"name": "Browser QA", "metadata": {"agent_id": "AG-55", "custom": True}}}, "1.0", "test")
    assert cards["AG-55"]["name"] == "Browser QA"
    assert cards["AG-55"]["metadata"]["agent_id"] == "AG-55"
    assert cards["AG-55"]["metadata"]["custom"] is True
