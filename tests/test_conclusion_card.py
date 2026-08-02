"""The Decide tab's three-track verdict as a DEFAULT "conclusion" report card.

Mirrors ``test_gate_verdict_surface.py``'s coverage of the
``write_gate_evaluator`` precedent: (a) compute + persist writes the artifact
and is idempotent; (b) the study-detail render prefers the persisted verdict
over its own live recompute, falling back when nothing is persisted; (c) the
`conclusion` card is excluded from ``derive_findings_from_report_cards`` so it
can never feed its own ``explanatory_gain`` input on the next compute.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
import pytest

from vivarium_workbench.lib import conclusion_card
from vivarium_workbench.lib.study_spec import (
    derive_findings_from_report_cards,
    load_study_detail_spec,
)

_V3_BASE = {
    "schema_version": 3,
    "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
    "variants": [],
}


def _write_study(ws: Path, slug: str, **fields) -> Path:
    sd = ws / "studies" / slug
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: ws\n")
    spec = dict(_V3_BASE, name=slug, objective="test", status="in_progress", **fields)
    (sd / "study.yaml").write_text(yaml.safe_dump(spec))
    return sd


@pytest.fixture
def study_dir(tmp_path):
    """Completed runs, a passing gate, and an interpretation-tier finding —
    the three tracks should compute PASS / PASS / PASS."""
    ws = tmp_path / "ws"
    return _write_study(
        ws, "demo-study",
        pipeline_gate={"gate_evaluator": {"result": "passed"}},
        runs=[{"name": "r1", "status": "completed"}],
        findings=[{"tier": "interpretation", "statement": "X dominates"}],
    )


# --- (a) compute + persist, idempotent --------------------------------------

def test_write_conclusion_card_writes_both_files_with_expected_schema(study_dir):
    changed = conclusion_card.write_conclusion_card(study_dir)
    assert changed is True

    html_path = study_dir / "viz" / "report_card" / "conclusion.html"
    verdict_path = study_dir / "viz" / "report_card" / "conclusion.verdict.json"
    assert html_path.is_file()
    assert verdict_path.is_file()

    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict["schema"] == "conclusion_card/v1"
    assert verdict["overall"] == "within_tol"  # worst-of-3, all PASS -> within_tol
    tracks = verdict["tracks"]
    assert tracks["biological_validation"]["result"] == "PASS"
    assert tracks["regression_compatibility"]["result"] == "PASS"
    assert tracks["explanatory_gain"]["result"] == "PASS"

    html = html_path.read_text(encoding="utf-8")
    assert '<meta name="viv-artifact" content="report-card">' in html
    assert "Empirical validation" in html
    assert "PASS" in html


def test_write_conclusion_card_idempotent_second_call_is_noop(study_dir):
    assert conclusion_card.write_conclusion_card(study_dir) is True
    assert conclusion_card.write_conclusion_card(study_dir) is False


def test_write_conclusion_card_never_raises_on_missing_study(tmp_path):
    missing = tmp_path / "nope"
    assert conclusion_card.write_conclusion_card(missing) is False


def test_write_conclusion_card_rewrites_when_inputs_change(study_dir):
    assert conclusion_card.write_conclusion_card(study_dir) is True
    assert conclusion_card.write_conclusion_card(study_dir) is False

    # Flip the gate result -> biological_validation FAIL; must be detected as
    # a real change (not a false idempotent no-op).
    spec = yaml.safe_load((study_dir / "study.yaml").read_text(encoding="utf-8"))
    spec["pipeline_gate"]["gate_evaluator"]["result"] = "failed"
    (study_dir / "study.yaml").write_text(yaml.safe_dump(spec))

    assert conclusion_card.write_conclusion_card(study_dir) is True
    verdict = json.loads(
        (study_dir / "viz" / "report_card" / "conclusion.verdict.json")
        .read_text(encoding="utf-8")
    )
    assert verdict["tracks"]["biological_validation"]["result"] == "FAIL"


# --- (b) prefer-persisted at render -----------------------------------------

def test_load_study_detail_spec_prefers_persisted_verdict(study_dir):
    ws = study_dir.parent.parent
    conclusion_card.write_conclusion_card(study_dir)

    # Now mutate study.yaml so a LIVE recompute would say FAIL, but the
    # persisted card (frozen from before the mutation) still says PASS.
    spec = yaml.safe_load((study_dir / "study.yaml").read_text(encoding="utf-8"))
    spec["pipeline_gate"]["gate_evaluator"]["result"] = "failed"
    (study_dir / "study.yaml").write_text(yaml.safe_dump(spec))

    detail = load_study_detail_spec(ws, "demo-study")
    cv = detail["derived"]["conclusion_verdicts"]
    assert cv["biological_validation"]["result"] == "PASS"  # persisted, not the live FAIL


def test_load_study_detail_spec_falls_back_to_recompute_when_no_card(study_dir):
    ws = study_dir.parent.parent
    # No conclusion.verdict.json written at all.
    detail = load_study_detail_spec(ws, "demo-study")
    cv = detail["derived"]["conclusion_verdicts"]
    assert cv["biological_validation"]["result"] == "PASS"
    assert cv["regression_compatibility"]["result"] == "PASS"
    assert cv["explanatory_gain"]["result"] == "PASS"


def test_load_study_detail_spec_merges_live_authored_basis_over_persisted(study_dir):
    ws = study_dir.parent.parent
    conclusion_card.write_conclusion_card(study_dir)

    # Author edits the free-text basis after the card was persisted — the
    # render must show the fresh basis even though `result` stays persisted.
    spec = yaml.safe_load((study_dir / "study.yaml").read_text(encoding="utf-8"))
    spec["conclusion_verdicts"] = {
        "biological_validation": {"basis": "fresh authored rationale"},
    }
    (study_dir / "study.yaml").write_text(yaml.safe_dump(spec))

    detail = load_study_detail_spec(ws, "demo-study")
    cv = detail["derived"]["conclusion_verdicts"]
    assert cv["biological_validation"]["result"] == "PASS"  # still persisted
    assert cv["biological_validation"]["basis"] == "fresh authored rationale"  # live


# --- (c) feedback-loop guard -------------------------------------------------

def test_derive_findings_from_report_cards_excludes_conclusion_card(tmp_path):
    ws = tmp_path / "ws"
    sd = _write_study(ws, "guarded-study", runs=[{"name": "r1", "status": "completed"}])
    rc_dir = sd / "viz" / "report_card"
    rc_dir.mkdir(parents=True)
    (rc_dir / "conclusion.html").write_text("<html><head><title>c</title></head></html>")
    (rc_dir / "conclusion.verdict.json").write_text(
        json.dumps({"schema": "conclusion_card/v1", "overall": "within_tol"}))

    report_card_urls = {"conclusion": {"url": "/studies/guarded-study/viz/report_card/conclusion.html",
                                        "verdict": "within_tol"}}
    findings = derive_findings_from_report_cards(ws, "guarded-study", report_card_urls, None)
    assert findings == []  # the ONLY card is `conclusion` -> no derived finding at all


def test_conclusion_card_explanatory_gain_not_fed_by_its_own_prior_output(tmp_path):
    """A study whose ONLY report card is `conclusion` must not gain an
    interpretation finding from that card — explanatory_gain's findings input
    stays exactly what it was (empty -> GAP), proving no feedback loop."""
    ws = tmp_path / "ws"
    sd = _write_study(ws, "loop-study",
                       pipeline_gate={"gate_evaluator": {"result": "passed"}},
                       runs=[{"name": "r1", "status": "completed"}])

    # First sync: no findings, no prior card -> GAP, card persists overall=ungraded.
    assert conclusion_card.write_conclusion_card(sd) is True
    verdict1 = json.loads((sd / "viz" / "report_card" / "conclusion.verdict.json")
                          .read_text(encoding="utf-8"))
    assert verdict1["tracks"]["explanatory_gain"]["result"] == "GAP"

    # Second sync: the conclusion card now exists on disk. If it fed back into
    # findings (bug), explanatory_gain would flip to PARTIAL/PASS here even
    # though no real evidence was added. It must NOT change.
    assert conclusion_card.write_conclusion_card(sd) is False  # unchanged -> idempotent no-op
    verdict2 = json.loads((sd / "viz" / "report_card" / "conclusion.verdict.json")
                          .read_text(encoding="utf-8"))
    assert verdict2["tracks"]["explanatory_gain"]["result"] == "GAP"
