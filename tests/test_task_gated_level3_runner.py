from scripts.run_task_gated_level3_validation import is_transport_failure


def test_schema_failure_cannot_authorize_transport_backup():
    assert not is_transport_failure("PROVIDER_SCHEMA_FAILURE")
    assert is_transport_failure("PROVIDER_PREDICTED_DEADLINE_REACHED")
