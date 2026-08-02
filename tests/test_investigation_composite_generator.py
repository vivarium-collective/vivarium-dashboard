"""``build_investigation_composite`` — compiles an ``investigation.yaml`` into
a process-bigraph composite STATE DICT (design:
docs/superpowers/specs/2026-08-01-investigation-as-composite-design.md
§Architecture 3).

(a)-(c) are pure dict-shape assertions — HERMETIC, no engine needed, dev venv
is fine. (d) runs the produced state on the REAL process-bigraph engine (v2ecoli
venv) with the worker pool stubbed, mirroring
``tests/test_investigation_analysis_step.py``'s
``test_analysis_step_runs_after_studies_and_receives_verdicts``.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from vivarium_workbench.lib.investigation_composite import build_investigation_composite


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _mk_investigation(ws: Path, inv_slug: str, members: list[str],
                       study_specs: dict[str, dict] | None = None,
                       analyses: list[dict] | None = None) -> None:
    """Minimal fixture: investigations/<inv>/investigation.yaml (members: ...)
    + studies/<slug>/study.yaml for each member (default empty spec)."""
    inv_doc: dict = {"members": members}
    if analyses is not None:
        inv_doc["analyses"] = analyses
    _write_yaml(ws / "investigations" / inv_slug / "investigation.yaml", inv_doc)
    study_specs = study_specs or {}
    for slug in members:
        _write_yaml(ws / "studies" / slug / "study.yaml",
                    study_specs.get(slug, {}))


# ---------------------------------------------------------------------------
# (a) no-prereq fixture: synthetic serial chain in declared order
# ---------------------------------------------------------------------------

def test_no_prereq_investigation_wires_synthetic_serial_chain(tmp_path):
    _mk_investigation(tmp_path, "inv", ["m0", "m1", "m2"])

    state = build_investigation_composite(tmp_path, "inv")

    # 3 StudyStep docs + 3 result stores.
    for slug in ("m0", "m1", "m2"):
        assert state[slug]["_type"] == "step"
        assert state[slug]["address"] == "local:StudyStep"
        assert state[f"study_{slug}_result"] == {}
        assert state[slug]["outputs"] == {"result": [f"study_{slug}_result"]}
        assert state[slug]["config"]["workspace"] == str(tmp_path)
        assert state[slug]["config"]["study_slug"] == slug

    # m0: first declared member, no prereq wire.
    assert state["m0"]["inputs"] == {}
    assert state["m0"]["config"]["prereqs"] == []

    # m1: synthetic serial edge to m0.
    assert state["m1"]["inputs"] == {"prereq_m0": ["study_m0_result"]}
    assert state["m1"]["config"]["prereqs"] == ["m0"]

    # m2: synthetic serial edge to m1 (not m0).
    assert state["m2"]["inputs"] == {"prereq_m1": ["study_m1_result"]}
    assert state["m2"]["config"]["prereqs"] == ["m1"]

    # No analyses declared -> no analysis docs/stores.
    assert not any(k.startswith("analysis_") for k in state)


# ---------------------------------------------------------------------------
# (b) real-prereq fixture: no synthetic edge added on top
# ---------------------------------------------------------------------------

def test_real_prereq_wired_and_no_synthetic_edge_added(tmp_path):
    _mk_investigation(tmp_path, "inv", ["A", "B"], study_specs={
        "B": {"pipeline_gate": {"prerequisites": [{"study": "A"}]}},
    })

    state = build_investigation_composite(tmp_path, "inv")

    assert state["A"]["inputs"] == {}
    assert state["A"]["config"]["prereqs"] == []

    assert state["B"]["inputs"] == {"prereq_A": ["study_A_result"]}
    assert state["B"]["config"]["prereqs"] == ["A"]


def test_bare_string_prerequisite_entry_is_honored(tmp_path):
    _mk_investigation(tmp_path, "inv", ["A", "B"], study_specs={
        "B": {"pipeline_gate": {"prerequisites": ["A"]}},
    })

    state = build_investigation_composite(tmp_path, "inv")

    assert state["B"]["inputs"] == {"prereq_A": ["study_A_result"]}
    assert state["B"]["config"]["prereqs"] == ["A"]


def test_legacy_parent_studies_does_not_wire_a_prereq(tmp_path):
    # pipeline_gate.prerequisites is read STRICTLY — the legacy
    # `parent_studies` key must not be consulted (mirrors #712's
    # `_study_prereqs`). B falls back to the synthetic serial edge to A
    # (the immediately-preceding declared member) instead.
    _mk_investigation(tmp_path, "inv", ["A", "B"], study_specs={
        "B": {"parent_studies": ["A"]},
    })

    state = build_investigation_composite(tmp_path, "inv")

    assert state["B"]["inputs"] == {"prereq_A": ["study_A_result"]}
    assert state["B"]["config"]["prereqs"] == ["A"]


def test_prerequisite_outside_investigation_is_dropped(tmp_path):
    # A prerequisite naming a study that is not a member of THIS
    # investigation is not a member -> dropped; falls back to no real
    # prereq, so the (first-member) study gets no synthetic edge either.
    _mk_investigation(tmp_path, "inv", ["B"], study_specs={
        "B": {"pipeline_gate": {"prerequisites": [{"study": "outsider"}]}},
    })

    state = build_investigation_composite(tmp_path, "inv")

    assert state["B"]["inputs"] == {}
    assert state["B"]["config"]["prereqs"] == []


# ---------------------------------------------------------------------------
# (c) analyses: wired to every study result store
# ---------------------------------------------------------------------------

def test_analysis_entry_wired_to_every_study_result_store(tmp_path):
    _mk_investigation(
        tmp_path, "inv", ["m0", "m1"],
        analyses=[{"name": "comparison_matrix", "params": {"opt": True}}])

    state = build_investigation_composite(tmp_path, "inv")

    doc = state["analysis_comparison_matrix"]
    assert doc["_type"] == "step"
    assert doc["address"] == "local:InvestigationAnalysisStep"
    assert doc["config"]["workspace"] == str(tmp_path)
    assert doc["config"]["name"] == "comparison_matrix"
    assert doc["config"]["params"] == {"opt": True}
    assert doc["config"]["study_slugs"] == ["m0", "m1"]
    assert doc["config"]["report_dir"] == str(
        tmp_path / "investigations" / "inv" / "reports")
    assert doc["inputs"] == {
        "study_m0": ["study_m0_result"], "study_m1": ["study_m1_result"]}
    assert doc["outputs"] == {"written": ["analysis_comparison_matrix_written"]}
    assert state["analysis_comparison_matrix_written"] == {}


def test_analysis_params_defaults_to_empty_dict(tmp_path):
    _mk_investigation(
        tmp_path, "inv", ["m0"], analyses=[{"name": "comparison_matrix"}])

    state = build_investigation_composite(tmp_path, "inv")

    assert state["analysis_comparison_matrix"]["config"]["params"] == {}


# ---------------------------------------------------------------------------
# (d) ENGINE test: run the produced state on the real process-bigraph engine
# with the worker pool stubbed. Requires process_bigraph (v2ecoli venv).
# ---------------------------------------------------------------------------

def test_engine_runs_studies_in_prereq_order_then_analysis_last(tmp_path, monkeypatch):
    from bigraph_schema import allocate_core
    from process_bigraph import Composite

    from vivarium_workbench.lib.investigation_steps import (
        StudyStep, InvestigationAnalysisStep)
    import vivarium_workbench.lib.investigation_steps as m

    # Real-prereq fixture: B depends on A.
    _mk_investigation(tmp_path, "inv", ["A", "B"], study_specs={
        "B": {"pipeline_gate": {"prerequisites": [{"study": "A"}]}},
    }, analyses=[{"name": "comparison_matrix"}])

    state = build_investigation_composite(tmp_path, "inv")

    class _FakePool:
        def __init__(self):
            self.calls = []

        def call(self, workspace, method, params):
            self.calls.append((workspace, method, params))
            if method == "run_study":
                return {"run_refs": ["r1"],
                        "verdict": {"study": params["study_slug"], "overall": "pass"}}
            return {"written": [f"{params['report_dir']}/{params['name']}_matrix_html.html"],
                    "errors": []}

    fake_pool = _FakePool()
    monkeypatch.setattr(
        "vivarium_workbench.lib.env_worker_pool.get_pool", lambda: fake_pool)

    # Ensure the skeleton marker paths are off: real dispatch must run.
    assert m._RUN_ORDER is None
    assert m._ANALYSIS_RUN_ORDER is None

    core = allocate_core(top={
        "StudyStep": StudyStep, "InvestigationAnalysisStep": InvestigationAnalysisStep})
    Composite({"state": state, "run_steps_on_init": True}, core)

    methods_and_slugs = [
        (c[1], c[2].get("study_slug") or c[2].get("name")) for c in fake_pool.calls]

    # A before B (prereq order), analysis dispatched last.
    assert methods_and_slugs == [
        ("run_study", "A"),
        ("run_study", "B"),
        ("run_investigation_analysis", "comparison_matrix"),
    ], methods_and_slugs

    analysis_call = fake_pool.calls[-1]
    assert analysis_call[2]["config"]["config_verdicts"] == {
        "A": {"run_refs": ["r1"], "verdict": {"study": "A", "overall": "pass"}},
        "B": {"run_refs": ["r1"], "verdict": {"study": "B", "overall": "pass"}},
    }
