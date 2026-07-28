"""Unit tests for batch_progress_fields — the compose BatchProgress (#183) → Runs-tab
row mapper. Pure function; no I/O."""

from vivarium_workbench.lib.remote_simulations import batch_progress_fields


def test_running_batch_maps_progress_and_status():
    out = batch_progress_fields(
        {"lineages": "925:1000", "generations": "10:10", "overall": 60.7, "status": "RUNNING"}
    )
    assert out["status"] == "running"
    assert out["progress_step"] == 925
    assert out["n_steps"] == 1000
    assert out["overall"] == 60.7


def test_completed_when_overall_hits_100():
    out = batch_progress_fields({"lineages": "1000:1000", "overall": 100.0, "status": None})
    assert out["status"] == "completed"


def test_completed_when_status_terminal_even_if_overall_short():
    out = batch_progress_fields({"lineages": "1000:1000", "overall": 99.5, "status": "SUCCEEDED"})
    assert out["status"] == "completed"


def test_failed_status_maps_to_failed():
    out = batch_progress_fields({"lineages": "40:1000", "overall": 4.0, "status": "FAILED"})
    assert out["status"] == "failed"


def test_none_input_is_safe():
    out = batch_progress_fields(None)
    assert out["status"] == "pending"
    assert "progress_step" not in out


def test_empty_dict_is_pending_with_no_progress_fields():
    out = batch_progress_fields({})
    assert out["status"] == "pending"
    assert "progress_step" not in out and "n_steps" not in out


def test_malformed_lineages_ignored_but_status_preserved():
    out = batch_progress_fields({"lineages": "garbage", "status": "running"})
    assert out["status"] == "running"
    assert "progress_step" not in out


def test_partial_lineages_started_only():
    out = batch_progress_fields({"lineages": "300:", "status": "running"})
    assert out["progress_step"] == 300
    assert "n_steps" not in out
