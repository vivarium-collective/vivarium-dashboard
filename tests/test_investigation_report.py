"""Tests for the deterministic investigation-report generator.

The generator must render one investigation to a single self-contained HTML
document from EXISTING files only (investigation.yaml, study.yaml, loop-trajectory
JSON) — no model call, no invented content. These tests build a tiny fixture
workspace on the fly and assert the assembled data shapes + self-containment.
"""
import json

import yaml

from vivarium_workbench.lib.investigation_report import (
    build_report_data,
    render_html,
    render_investigation_report,
)


def _write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(obj, sort_keys=False), encoding="utf-8")


def _ws(tmp_path):
    """A minimal flat-layout workspace with a sourcing investigation (incl. an
    adversarial-control trap) and an agentic-build investigation with a trajectory."""
    _write(tmp_path / "workspace.yaml", {"schema_version": 2, "name": "tw", "package_path": "pkg"})

    # --- sourcing investigation ---
    _write(tmp_path / "investigations" / "src" / "investigation.yaml", {
        "name": "src", "title": "Sourcing", "status": "complete",
        "question": "Can an agent source the model well?",
        "executive": {"what_is_this": "audit", "verdict": "graded correctly", "verdict_status": "passed"},
        "catalog": {"mod-a": ["physics_2d", "collision"]},
        "studies": ["reuse-ok", "trap"],
    })
    _write(tmp_path / "studies" / "reuse-ok" / "study.yaml", {
        "name": "reuse-ok", "title": "Reuse OK", "confidence": "Accepted", "gate_status": "passed",
        "requires": ["physics_2d", "collision"], "claim": "reuse mod-a",
        "sourcing": {"decision": "reuse", "modules": ["mod-a"], "rationale": "fits",
                     "audit": {"gate": "pass", "axes": {"source_fit": "within_tol", "reinvention": "within_tol"},
                               "catches_if_wrong": "build-new would trip reinvention"}},
        "baseline": [{"name": "mod-a", "composite": "pkg.composites.reuse_ok", "module": "mod-a", "domain": "2D physics"}],
        "behavior_tests": [{"name": "sourcing-fit", "classification": "primary",
                            "measure": {"kind": "audit-axis", "path": "sourcing.source_fit"},
                            "pass_if": {"op": "==", "value": "within_tol"}}],
        "runs": [{"name": "reuse-ok", "status": "completed",
                  "outcomes": {"SOURCING-GATE": {"result": "PASS", "detail": "gate=pass"}}}],
        "conclusion": "The audit graded this PASS.",
    })
    _write(tmp_path / "studies" / "trap" / "study.yaml", {
        "name": "trap", "title": "Trap", "confidence": "Refuted", "gate_status": "failed",
        "requires": ["physics_2d", "spatial"], "claim": "no clean fit",
        "sourcing": {"decision": "reuse", "modules": ["mod-a"], "rationale": "tempting but wrong",
                     "audit": {"gate": "fail", "axes": {"source_fit": "mismatch", "reinvention": "within_tol"},
                               "catches_if_wrong": "needs spatial, mod-a lacks it"}},
        "baseline": [{"name": "mod-a", "composite": "pkg.composites.trap", "module": "mod-a"}],
        "behavior_tests": [{"name": "sourcing-fit", "measure": {"kind": "audit-axis", "path": "sourcing.source_fit"},
                            "pass_if": {"op": "==", "value": "within_tol"}}],
        "runs": [{"name": "trap", "status": "audit-only",
                  "outcomes": {"SOURCING-GATE": {"result": "FAIL", "detail": "gate=fail"}}}],
        "conclusion": "The audit refused this bad reuse.",
    })

    # --- agentic-build investigation with a trajectory ---
    _write(tmp_path / "investigations" / "build" / "investigation.yaml", {
        "name": "build", "title": "Build challenges", "status": "in_progress",
        "question": "Which tasks require an agent?", "studies": ["tsk"],
    })
    _write(tmp_path / "studies" / "tsk" / "study.yaml", {
        "name": "tsk", "title": "Task", "confidence": "Accepted", "gate_status": "passed",
        "question": "Build a model that passes the tests.",
        "biological_summary": "A Composite: FooProc + BarProc over a/b.",
        "baseline": [{"name": "final", "composite": "pkg.composites.tsk"}],
        "behavior_tests": [{"name": "growth", "description": "grows", "pass_if": {"op": ">=", "value": 0}}],
        "runs": [{"name": "tsk-agent", "status": "completed",
                  "outcomes": {"LOOP-OUTCOME": {"result": "PASS", "detail": "DONE in 1 edit"}}}],
        "conclusion": "## Final model\nFooProc + BarProc.\n\n## Result\nDONE 1/1.",
        "loop_provenance": "tsk-agent",
    })
    traj = {"schema": "agent_build_trajectory/v1", "study": "tsk", "driver": "LLM agent",
            "tests": [{"id": "growth", "label": "grows", "expected": ">= 0", "provenance": "max biomass"}],
            "iterations": [
                {"iteration": 0, "n_pass": 0, "n_hard": 1, "newly_fixed": [],
                 "agent_decision": {"action": "install", "mechanism": "FooProc", "reasoning": "start"},
                 "tests": [{"id": "growth", "verdict": "mismatch", "observed": 0.0, "expected": ">= 0", "margin": -1.0}]},
                {"iteration": 1, "n_pass": 1, "n_hard": 1, "newly_fixed": ["growth"],
                 "agent_decision": {"action": "done", "reasoning": "passes"},
                 "tests": [{"id": "growth", "verdict": "within_tol", "observed": 5.0, "expected": ">= 0", "margin": 5.0}]},
            ],
            "result": {"state": "DONE", "edits": 1, "violations": []}}
    (tmp_path / "investigations" / "build" / "tsk_agent_trajectory.json").write_text(json.dumps(traj))
    return tmp_path


def test_sourcing_data_shape_and_provenance(tmp_path):
    ws = _ws(tmp_path)
    d = build_report_data(ws, "src")
    assert d["title"] == "Sourcing"
    assert [s["slug"] for s in d["studies"]] == ["reuse-ok", "trap"]
    # sourcing block passes through verbatim (the report's actual subject)
    reuse = d["studies"][0]
    assert reuse["sourcing"]["decision"] == "reuse"
    assert reuse["sourcing"]["audit"]["axes"]["source_fit"] == "within_tol"
    # the trap is a real fail (its adversarial-control treatment is derived from this)
    trap = d["studies"][1]
    assert trap["gate_status"] == "failed" and trap["confidence"] == "Refuted"
    assert trap["sourcing"]["audit"]["gate"] == "fail"
    # only known top-level keys — nothing invented
    assert set(d) <= {"slug", "title", "status", "question", "hypothesis", "lead",
                      "executive", "at_a_glance", "catalog", "workspace", "provenance", "studies"}


def test_agentic_trajectory_attached(tmp_path):
    ws = _ws(tmp_path)
    d = build_report_data(ws, "build")
    assert len(d["studies"]) == 1
    s = d["studies"][0]
    assert "agent_trajectory" in s
    assert s["agent_trajectory"]["result"]["state"] == "DONE"
    assert len(s["agent_trajectory"]["iterations"]) == 2
    assert s["behavior_tests"][0]["name"] == "growth"


def test_render_is_self_contained(tmp_path):
    ws = _ws(tmp_path)
    html = render_html(build_report_data(ws, "src"))
    # no unrendered placeholders
    assert "__DATA__" not in html and "__TITLE__" not in html
    # self-contained: no live calls, no external assets
    assert "fetch(" not in html
    assert 'src="http' not in html and 'href="http' not in html
    assert "/api/" not in html
    # real field values are present (rendered from data, not invented)
    assert "Sourcing" in html
    assert "reuse" in html and "mod-a" in html


def test_render_writes_file(tmp_path):
    ws = _ws(tmp_path)
    out = render_investigation_report(ws, "build")
    assert out.name == "investigation-build.html"
    assert out.is_file()
    assert "Build challenges" in out.read_text(encoding="utf-8")


def test_missing_investigation_raises(tmp_path):
    ws = _ws(tmp_path)
    try:
        build_report_data(ws, "nope")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError for a missing investigation")
