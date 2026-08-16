"""study_evaluator attaches a report_card_verdict/v2 `axis` (signed margin +
severity) to code outcomes; the outcome writer must carry it through into
runs[].outcomes so the margin survives to the report-card render."""
from vivarium_workbench.lib.auto_evaluate import _build_outcome_entry


def test_outcome_entry_preserves_axis():
    raw = {"result": "FAIL", "measured_value": 0.54, "evaluated_by": "code",
           "detail": "0.54 below band", "operator": "derived/in_range",
           "axis": {"verdict": "mismatch", "margin": -0.06, "severity": "hard"}}
    entry = _build_outcome_entry(raw, None)
    assert entry["result"] == "FAIL"
    assert entry["measured_value"] == 0.54          # existing fields unchanged
    assert entry["axis"] == {"verdict": "mismatch", "margin": -0.06, "severity": "hard"}


def test_outcome_entry_omits_axis_when_absent():
    # An agent/needs_rerun bucket (or an unmapped op) carries no axis.
    entry = _build_outcome_entry({"evaluated_by": "agent", "reason": "unknown kind"}, None)
    assert "axis" not in entry
    assert entry["result"] == "SKIP"                # agent bucket → SKIP
