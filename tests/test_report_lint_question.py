from pathlib import Path
from vivarium_workbench.lib.report_views import _question_approach_findings

def test_flags_study_without_question(tmp_path):
    ws = tmp_path
    sdir = ws / "studies" / "no-q"; sdir.mkdir(parents=True)
    (sdir / "study.yaml").write_text("name: no-q\ntitle: No question here\n")
    checks = [f["check"] for f in _question_approach_findings(ws)]
    assert "missing_question" in checks

def test_no_flag_when_question_present(tmp_path):
    ws = tmp_path
    sdir = ws / "studies" / "has-q"; sdir.mkdir(parents=True)
    (sdir / "study.yaml").write_text("name: has-q\npurpose:\n  question: Does X match Y?\n")
    checks = [f["check"] for f in _question_approach_findings(ws)]
    assert "missing_question" not in checks
