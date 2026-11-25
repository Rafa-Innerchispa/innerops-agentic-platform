from inneros_core_runtime import ops_execution_node_routing as oenr


def test_antigravity_defaults_intel():
    task = {"assignee": "antigravity", "payload": {}}
    node, reason = oenr.resolve_target_node(task, "antigravity")
    assert node == "intel"
    assert "provider_default" in reason


def test_owner_picks_amd():
    task = {"payload": {"owner_execution_node": "amd"}}
    node, _ = oenr.resolve_target_node(task, "antigravity")
    assert node == "amd"


def test_normalize_aliases():
    assert oenr.normalize_node("ralfiia-amd") == "amd"
    assert oenr.normalize_node("primary") == "intel"