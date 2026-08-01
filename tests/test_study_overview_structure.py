from pathlib import Path

TPL = Path("vivarium_workbench/templates/study-detail.html").read_text(encoding="utf-8")


def test_group_headers_present():
    # Redesign: narrative order Question & approach -> Findings -> Debts ->
    # Conclusion. The old "Summary" card was removed (verdict is shown once, in
    # the header pill + spine-at-a-glance), and a Conclusion block closes it out.
    assert "Question &amp; approach" in TPL or "Question & approach" in TPL
    assert "Findings" in TPL
    assert ">Conclusion</h2>" in TPL
    assert "Plan &amp; provenance" in TPL or "Plan & provenance" in TPL


def test_study_card_cut():
    assert 'data-narrative-path="study_card.' not in TPL


def test_status_select_retired():
    # The legacy single-axis status <select> was retired; the header status pill
    # (derived from the multi-axis fields) is canonical.
    assert TPL.count('id="status-select"') == 0


def test_question_text_exactly_once():
    assert TPL.count('id="question-text"') == 1


def test_hypothesis_text_exactly_once():
    assert TPL.count('id="hypothesis-text"') == 1


def test_objective_text_exactly_once():
    assert TPL.count('id="objective-text"') == 1


def test_epistemic_debts_panel_present():
    assert 'id="epistemic-debts-panel"' in TPL


def test_feedback_tracked_panel_present():
    assert 'id="feedback-tracked-panel"' in TPL


def test_report_conclusion_present():
    # The conclusion field is wired through the progressive-disclosure edit_field
    # macro (data-narrative-path="{{ path }}"), so assert the path is referenced.
    assert "report.conclusion" in TPL


def test_biological_summary_present():
    # The editable data-narrative-path="biological_summary" field was replaced
    # by a read-only "Summary." purpose-callout card (editability intentionally
    # dropped per spec); pin that study.biological_summary still renders there.
    assert '<strong>Summary.</strong> {{ study.biological_summary }}' in TPL


def test_set_study_tab_tests_present():
    assert "_setStudyTab('tests')" in TPL


def test_set_study_tab_conclusions_present():
    assert "_setStudyTab('conclusions')" in TPL
