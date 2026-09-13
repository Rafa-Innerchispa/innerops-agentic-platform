from raphiia_openai import voice_mcp_executor as voice
from raphiia_openai import homeassistant_client as ha


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


def test_alarm_status_phrase_is_not_misclassified_as_arm_write():
    assert ha._is_alarm_request("revisa la alarma Intelbras")
    assert not ha._requested_alarm_write("revisa la alarma Intelbras")
    assert ha._requested_alarm_action("arma la alarma Intelbras") == "alarm_arm_away"


def test_alarm_action_requires_explicit_owner_approval():
    result = ha._maybe_apply_alarm_action("arma la alarma Intelbras", "alarm_control_panel.intelbras")
    assert result["requested_write"] is True
    assert result["executed"] is False
    assert result["reason"] == "explicit_alarm_approval_required"


def test_alarm_action_routes_through_home_assistant_when_approved(monkeypatch):
    calls = []

    def fake_call_service(domain, service, *, entity_id=None, data=None):
        calls.append((domain, service, entity_id, data))
        return {"ok": True}

    monkeypatch.setattr(ha, "call_service", fake_call_service)
    result = ha._maybe_apply_alarm_action("sí autorizo armar la alarma Intelbras", "alarm_control_panel.intelbras")
    assert result["executed"] is True
    assert calls == [("alarm_control_panel", "alarm_arm_away", "alarm_control_panel.intelbras", None)]
