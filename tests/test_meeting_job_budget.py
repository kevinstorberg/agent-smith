import pytest

from services.jobs.service import validate_input_params


@pytest.mark.parametrize("timeout", [True, 0, 300, 599, "600", float("inf")])
def test_meeting_job_rejects_timeout_shorter_than_digestion_budget(timeout):
    with pytest.raises(ValueError, match="at least 600 seconds"):
        validate_input_params({"graph_type": "meeting_ingest", "graph_inputs": {}, "timeout": timeout})


def test_meeting_job_accepts_sufficient_budget_and_keeps_import_only_mode_available():
    validate_input_params({"graph_type": "meeting_ingest", "graph_inputs": {}, "timeout": 600})
    validate_input_params({"graph_type": "meeting_ingest", "graph_inputs": {"digest": False}, "timeout": 60})
