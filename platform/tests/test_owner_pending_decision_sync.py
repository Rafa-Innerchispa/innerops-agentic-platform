from inneros_core_runtime import ops_owner_decision_registry as odr


def test_close_pending_idempotent():
    out = odr.close_pending_after_owner_grant(
        "ops_nonexistent_test_task",
        channel="unit_test",
        owner_actor="TEST",
    )
    assert out.get("ok") is True