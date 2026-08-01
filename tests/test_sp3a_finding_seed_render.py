"""SP3a structural tests for the finding-seed render layer (no JS harness).

The seed-from-finding loop is made visible in two places, both rendered in
plain JS (so these are string-presence structural checks, paired with manual
verification):

  - ``study-detail.js`` — ``_seedFromFinding`` POSTs ``{parent, finding_id}``
    to ``/api/study-seed-followup``, delegating to the shared pbg seed
    mechanism. study-page-declutter Task 5 deleted its original UI trigger
    (the "Spine at a glance" panel's "Next" row, including the
    ``nextFindingId``-gated "seed study from this finding" label) along with
    the rest of that retired panel — the follow-up seeding capability itself
    survives via the Decide tab's ``.btn-seed-followup`` buttons
    (``_seedFollowupStudy`` / ``_seedFollowupProposal``), so
    ``_seedFromFinding``/``finding_id``/the endpoint are still asserted here.
  - ``walkthrough.js`` — a finding stamped with ``seeded_study`` renders a
    "→ seeded study X" link, closing the loop in the report.
"""
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent / "vivarium_workbench"


def test_study_detail_js_has_seed_from_finding_button():
    js = (_PKG / "static" / "study-detail.js").read_text(encoding="utf-8")
    # The dedicated handler POSTs {parent, finding_id} (delegates to pbg).
    assert "_seedFromFinding" in js
    assert "finding_id" in js
    assert "/api/study-seed-followup" in js


def test_walkthrough_js_renders_seeded_study_lineage():
    js = (_PKG / "static" / "walkthrough.js").read_text(encoding="utf-8")
    # The finding card renders the seeded_study back-link from the stamp.
    assert "seeded_study" in js
    assert "finding-seeded" in js
    assert "seeded study" in js
