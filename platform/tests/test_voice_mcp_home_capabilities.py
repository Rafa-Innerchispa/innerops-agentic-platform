from raphiia_openai import voice_mcp_executor as voice


OWNER = {"username": "rlopez", "email": "pcdoctorgye@gmail.com", "is_admin": True}


def test_voice_owner_profile_includes_alarm_and_dmx_tools():
    tools = voice.allowed_tools(OWNER)
    assert "alarm_intelbras_status" in tools
    assert "dmx_set_scene" in tools
    assert "dmx_blackout" in tools
    assert "dmx_status" in tools


def test_voice_mcp_policy_summary_contract_for_health():
    summary = voice.mcp_policy_summary(OWNER, include_tools=False)
    assert summary["profile"]
    assert summary["visible_tool_count"] == len(voice.allowed_tools(OWNER))
    assert summary["full_catalog_access"] is True
    assert "visible_tools" not in summary


def test_voice_detects_alarm_without_generic_home_tool():
    calls = voice.detect_tool_calls(OWNER, "Ralphi, revisa la alarma Intelbras de la casa")
    assert calls[0][0] == "alarm_intelbras_status"
    assert not any(name == "ha_home_status" for name, _ in calls)


def test_voice_detects_dmx_scene_before_home_assistant_lights():
    calls = voice.detect_tool_calls(OWNER, "pon las luces DMX morado UV en los tachos")
    assert calls[0][0] == "dmx_set_scene"
    assert calls[0][1]["scene"] == "morado_uv"
    assert not any(name in {"ha_turn_on_light", "ha_turn_off_light"} for name, _ in calls)
