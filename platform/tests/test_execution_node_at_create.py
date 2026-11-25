from inneros_core_runtime.ops_execution_node_routing import apply_execution_node_at_create


def test_default_antigravity_intel():
    doc = apply_execution_node_at_create({"assignee": "antigravity", "title": "t"}, None)
    assert doc["target_execution_node"] == "intel"
    assert doc["payload"]["target_node"] == "intel"


def test_explicit_amd():
    doc = apply_execution_node_at_create(
        {"assignee": "antigravity", "title": "t"},
        "amd",
    )
    assert doc["target_execution_node"] == "amd"
    assert doc["payload"]["fail_closed_on_node_mismatch"] is True