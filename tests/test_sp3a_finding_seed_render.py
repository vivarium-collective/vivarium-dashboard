"""SP3a structural tests for the finding-seed render layer (no JS harness).

The seed-from-finding loop was originally made visible in two places, both
rendered in plain JS:

  - ``study-detail.js`` — ``_seedFromFinding`` POSTed ``{parent, finding_id}``
    to ``/api/study-seed-followup``, delegating to the shared pbg seed
    mechanism. study-page-declutter Task 5 deleted its original UI trigger
    (the "Spine at a glance" panel's "Next" row, including the
    ``nextFindingId``-gated "seed study from this finding" label) along with
    the rest of that retired panel — the follow-up seeding capability itself
    survives via the Decide tab's ``.btn-seed-followup`` buttons
    (``_seedFollowupStudy`` / ``_seedFollowupProposal``). ``_seedFromFinding``
    itself had zero remaining callers (no template markup ever regained a
    trigger for it) and was deleted as dead code by Fable A #7
    (study-design-fable-pass §1.1-I / §6 #7) — see
    ``test_study_detail_js_has_no_seed_from_finding`` below.
  - ``walkthrough.js`` — a finding stamped with ``seeded_study`` renders a
    "→ seeded study X" link, closing the loop in the report. Unaffected by
    the ``_seedFromFinding`` deletion (a different, still-live code path).
"""
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent / "vivarium_workbench"


def test_study_detail_js_has_no_seed_from_finding():
    js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    # Deleted as dead code (Fable A #7): zero live callers anywhere in the
    # template/JS — its only prior UI trigger was already removed by
    # study-page-declutter Task 5 (see module docstring).
    assert "_seedFromFinding" not in js
    assert "_isFailingVerdict" not in js
    # The follow-up seeding capability itself survives via the sibling
    # handlers, which still POST to the same endpoint.
    assert "_seedFollowupStudy" in js
    assert "/api/study-seed-followup" in js


def test_report_template_renders_seeded_study_lineage():
    # The report (lib.investigation_report + template) renders a finding's
    # seeded_study back-link from the stamp.
    tpl = (_PKG / "templates" / "investigation-report.html").read_text(encoding="utf-8")
    assert "seeded_study" in tpl
    assert "finding-seeded" in tpl
    assert "seeded study" in tpl
