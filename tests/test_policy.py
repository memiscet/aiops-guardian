from aiops.policy import decide

def test_block_unsafe():
    assert decide("delete_namespace", "stage4-lab") == "blocked"

def test_block_unrecognized():
    assert decide("something_new", "stage4-lab") == "blocked"

def test_block_wrong_namespace():
    assert decide("collect_logs", "production") == "blocked"

def test_require_approval():
    assert decide("rollback_deployment", "stage4-lab") == "approval_required"

def test_allow_read_only():
    assert decide("collect_logs", "stage4-lab") == "allowed"
