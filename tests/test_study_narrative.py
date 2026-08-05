"""Tests for vivarium_workbench/lib/study_narrative.py — the YAML-direct writers
for the v4 narrative-spine fields (set-verdicts, add-literature-anchor,
add-pivot, add-requirement).

Covers:
- happy path for each subcommand (writes a valid v4 spec field)
- dry-run path (no file change)
- merge semantics for set-verdicts (existing values preserved when not
  passed; new values overwrite when passed)
- duplicate-id rejection for add-pivot, add-requirement
- enum guards (invalid result, invalid effort)
- workspace + study-yaml resolution errors
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vivarium_workbench.lib.study_narrative import (
    DesignPivot,
    ImplementationRequirement,
    LiteratureAnchor,
    VerdictUpdate,
    add_literature_anchor,
    add_pivot,
    add_requirement,
    set_verdicts,
)


# ---------------------------------------------------------------------------
# Fixture: minimal workspace with one v4 study.
# ---------------------------------------------------------------------------


@pytest.fixture
def ws_with_study(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_text("name: test\n")
    sd = ws / "studies" / "s1"
    sd.mkdir(parents=True)
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 4,
        "name": "s1",
        "status": "draft",
        "baseline": [{"name": "b", "composite": "pkg.composites.foo"}],
    }))
    return ws


def _load(ws: Path) -> dict:
    return yaml.safe_load((ws / "studies" / "s1" / "study.yaml").read_text())


# ---------------------------------------------------------------------------
# set_verdicts
# ---------------------------------------------------------------------------


class TestSetVerdicts:
    def test_writes_all_three_tracks(self, ws_with_study):
        set_verdicts(
            ws_with_study, "s1",
            regression=VerdictUpdate("PASS", "Builds cleanly."),
            biological=VerdictUpdate("MIXED", "atp_fraction outside band."),
            explanatory=VerdictUpdate("POSITIVE", "Three findings worth keeping."),
        )
        spec = _load(ws_with_study)
        cv = spec["conclusion_verdicts"]
        assert cv["regression_compatibility"] == {"result": "PASS", "basis": "Builds cleanly."}
        assert cv["biological_validation"] == {"result": "MIXED", "basis": "atp_fraction outside band."}
        assert cv["explanatory_gain"] == {"result": "POSITIVE", "basis": "Three findings worth keeping."}

    def test_writes_only_one_track(self, ws_with_study):
        set_verdicts(
            ws_with_study, "s1",
            biological=VerdictUpdate("FAIL", "Off by 10x."),
        )
        cv = _load(ws_with_study)["conclusion_verdicts"]
        assert cv == {"biological_validation": {"result": "FAIL", "basis": "Off by 10x."}}

    def test_merges_with_existing(self, ws_with_study):
        # First call sets all three.
        set_verdicts(
            ws_with_study, "s1",
            regression=VerdictUpdate("PASS", "old basis"),
            biological=VerdictUpdate("PENDING", "old basis"),
        )
        # Second call updates only biological.result — regression untouched.
        set_verdicts(
            ws_with_study, "s1",
            biological=VerdictUpdate("PASS", None),
        )
        cv = _load(ws_with_study)["conclusion_verdicts"]
        assert cv["regression_compatibility"] == {"result": "PASS", "basis": "old basis"}
        # biological.basis preserved from the first call; result updated.
        assert cv["biological_validation"] == {"result": "PASS", "basis": "old basis"}

    def test_dry_run_does_not_write(self, ws_with_study):
        before = _load(ws_with_study)
        set_verdicts(
            ws_with_study, "s1",
            regression=VerdictUpdate("PASS"),
            dry_run=True,
        )
        assert _load(ws_with_study) == before

    @pytest.mark.parametrize("track,bad", [
        ("regression", "OK"),
        ("biological", "TRUE"),
        ("explanatory", "PASS"),  # PASS is regression-track, not explanatory
    ])
    def test_invalid_result_rejected(self, ws_with_study, track, bad):
        kwargs = {track: VerdictUpdate(bad, None)}
        with pytest.raises(ValueError, match="must be one of"):
            set_verdicts(ws_with_study, "s1", **kwargs)


# ---------------------------------------------------------------------------
# add_literature_anchor
# ---------------------------------------------------------------------------


class TestLiteratureAnchor:
    def test_appends(self, ws_with_study):
        add_literature_anchor(
            ws_with_study, "s1",
            LiteratureAnchor(
                expectation="DnaA-ATP / total ~ 20-50%",
                model_observable="bulk[DnaA_ATP] / bulk[DnaA_total]",
                source="Boesen 2024",
                status_in_workspace="Not yet measurable",
                cites=["Boesen2024"],
            ),
        )
        anchors = _load(ws_with_study)["literature_anchors"]
        assert len(anchors) == 1
        assert anchors[0]["expectation"] == "DnaA-ATP / total ~ 20-50%"
        assert anchors[0]["cites"] == ["Boesen2024"]

    def test_multiple_appends_preserve_order(self, ws_with_study):
        for i in range(3):
            add_literature_anchor(
                ws_with_study, "s1",
                LiteratureAnchor(
                    expectation=f"anchor {i}",
                    model_observable=f"obs {i}",
                ),
            )
        anchors = _load(ws_with_study)["literature_anchors"]
        assert [a["expectation"] for a in anchors] == ["anchor 0", "anchor 1", "anchor 2"]

    def test_empty_optionals_omitted(self, ws_with_study):
        add_literature_anchor(
            ws_with_study, "s1",
            LiteratureAnchor(expectation="x", model_observable="y"),
        )
        entry = _load(ws_with_study)["literature_anchors"][0]
        assert set(entry.keys()) == {"expectation", "model_observable"}

    def test_empty_expectation_rejected(self, ws_with_study):
        with pytest.raises(ValueError, match="expectation"):
            add_literature_anchor(
                ws_with_study, "s1",
                LiteratureAnchor(expectation="   ", model_observable="y"),
            )

    def test_dry_run_does_not_write(self, ws_with_study):
        before = _load(ws_with_study)
        add_literature_anchor(
            ws_with_study, "s1",
            LiteratureAnchor(expectation="x", model_observable="y"),
            dry_run=True,
        )
        assert _load(ws_with_study) == before


# ---------------------------------------------------------------------------
# add_pivot
# ---------------------------------------------------------------------------


class TestAddPivot:
    def test_appends(self, ws_with_study):
        add_pivot(
            ws_with_study, "s1",
            DesignPivot(
                id="dnaa-02-EQ-04",
                question="A or B?",
                alternatives=["A. Add locked species", "B. Patch stoichMatrix"],
                requested_response="Expert opinion on (A) vs (B)",
            ),
        )
        pivots = _load(ws_with_study)["design_pivot_required"]
        assert pivots[0]["id"] == "dnaa-02-EQ-04"
        assert pivots[0]["status"] == "open"
        assert len(pivots[0]["alternatives"]) == 2

    def test_duplicate_id_rejected(self, ws_with_study):
        add_pivot(ws_with_study, "s1", DesignPivot(id="P-1", question="x"))
        with pytest.raises(ValueError, match="already exists"):
            add_pivot(ws_with_study, "s1", DesignPivot(id="P-1", question="y"))

    def test_bad_id_rejected(self, ws_with_study):
        with pytest.raises(ValueError, match="^[A-Za-z0-9]"):
            add_pivot(ws_with_study, "s1", DesignPivot(id="has space", question="x"))

    def test_empty_question_rejected(self, ws_with_study):
        with pytest.raises(ValueError, match="question"):
            add_pivot(ws_with_study, "s1", DesignPivot(id="P-1", question="   "))


# ---------------------------------------------------------------------------
# add_requirement
# ---------------------------------------------------------------------------


class TestAddRequirement:
    def test_appends(self, ws_with_study):
        add_requirement(
            ws_with_study, "s1",
            ImplementationRequirement(
                id="req-1",
                title="Split DnaA bulk into ATP/ADP/apo species",
                kind="state_variables",
                effort="XS",
                description="Add three new bulk species.",
                steps=["Step 1", "Step 2"],
                unblocks=["dnaa-02 behavior_tests", "dnaa-03 box binding"],
            ),
        )
        reqs = _load(ws_with_study)["implementation_requirements"]
        assert reqs[0]["id"] == "req-1"
        assert reqs[0]["kind"] == "state_variables"
        assert reqs[0]["effort"] == "XS"
        assert reqs[0]["unblocks"] == ["dnaa-02 behavior_tests", "dnaa-03 box binding"]

    def test_duplicate_id_rejected(self, ws_with_study):
        add_requirement(ws_with_study, "s1",
                        ImplementationRequirement(id="r", title="t"))
        with pytest.raises(ValueError, match="already exists"):
            add_requirement(ws_with_study, "s1",
                            ImplementationRequirement(id="r", title="t2"))

    def test_invalid_effort_rejected(self, ws_with_study):
        with pytest.raises(ValueError, match="effort"):
            add_requirement(
                ws_with_study, "s1",
                ImplementationRequirement(id="r", title="t", effort="MEDIUM"),
            )

    def test_empty_optionals_omitted(self, ws_with_study):
        add_requirement(
            ws_with_study, "s1",
            ImplementationRequirement(id="r", title="t"),
        )
        entry = _load(ws_with_study)["implementation_requirements"][0]
        # Only id, title, status (defaults to "planned").
        assert set(entry.keys()) == {"id", "title", "status"}

    def test_object_shape_rejected(self, ws_with_study):
        """The schema allows implementation_requirements to be an object too;
        the helper refuses to extend that shape (user must convert manually)."""
        sf = ws_with_study / "studies" / "s1" / "study.yaml"
        spec = yaml.safe_load(sf.read_text())
        spec["implementation_requirements"] = {"some-key": "some-value"}
        sf.write_text(yaml.safe_dump(spec))
        with pytest.raises(ValueError, match="object shape"):
            add_requirement(ws_with_study, "s1",
                            ImplementationRequirement(id="r", title="t"))


# ---------------------------------------------------------------------------
# Workspace + study resolution
# ---------------------------------------------------------------------------


class TestResolution:
    def test_missing_study_yaml(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "workspace.yaml").write_text("name: test\n")
        with pytest.raises(FileNotFoundError, match="Study 'missing' not found"):
            add_literature_anchor(
                ws, "missing",
                LiteratureAnchor(expectation="x", model_observable="y"),
            )
