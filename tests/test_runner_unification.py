"""Runner unification (investigation-as-composite design, §Architecture 4,
Task 6): ``run_investigation_composite`` is the execution entry point
``prepare_investigation`` delegates to for a full run, replacing the flat
per-study POST loop with the dependency-ordered composite.

Fixture style mirrors ``tests/test_investigation_composite_generator.py``.
Uses the ``run_study_fn`` injection hook (not the ``env_worker_pool``
monkeypatch other substrate tests use) to keep this hermetic while also
exercising ``run_investigation_composite``'s own summary-building — see its
docstring for why that hook exists.

Requires ``process_bigraph``/``bigraph_schema`` (v2ecoli venv; see the plan's
Global Constraints).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from vivarium_workbench.lib.investigation_execution import run_investigation_composite


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


def _fake_run_study(calls: list):
    def _fn(workspace, study_slug):
        calls.append((workspace, study_slug))
        return {"run_refs": [{"run_id": f"run-{study_slug}", "sim_name": study_slug}],
                "verdict": {"study": study_slug, "overall": "pass"}, "errors": []}
    return _fn


# ---------------------------------------------------------------------------
# (a) GOLDEN no-prereq: 3 members, no prereqs, no analyses -> declared order.
# ---------------------------------------------------------------------------

def test_golden_no_prereq_runs_in_declared_order(tmp_path):
    _mk_investigation(tmp_path, "inv", ["m0", "m1", "m2"])

    calls: list = []
    summary = run_investigation_composite(
        tmp_path, "inv", run_study_fn=_fake_run_study(calls))

    assert summary["investigation"] == "inv"
    assert summary["studies_ran"] == ["m0", "m1", "m2"]
    assert summary["analyses"] == []
    assert summary["errors"] == []

    # The worker was called once per study, in declared order, with the
    # right workspace + slug.
    assert calls == [
        (str(tmp_path), "m0"), (str(tmp_path), "m1"), (str(tmp_path), "m2")]

    # study_results carries each study's full reply (additive convenience
    # for callers like prepare_investigation).
    assert set(summary["study_results"]) == {"m0", "m1", "m2"}
    assert summary["study_results"]["m0"]["verdict"]["overall"] == "pass"


# ---------------------------------------------------------------------------
# (b) prereq order: C declares pipeline_gate.prerequisites: [{study: A}] ->
#     A runs before C. B (no real prereq) chains off the preceding declared
#     member per the synthetic-serial rule.
# ---------------------------------------------------------------------------

def test_prereq_order_runs_dependency_before_dependent(tmp_path):
    _mk_investigation(tmp_path, "inv", ["A", "B", "C"], study_specs={
        "C": {"pipeline_gate": {"prerequisites": [{"study": "A"}]}},
    })

    calls: list = []
    summary = run_investigation_composite(
        tmp_path, "inv", run_study_fn=_fake_run_study(calls))

    order = summary["studies_ran"]
    assert order.index("A") < order.index("C"), order
    assert set(order) == {"A", "B", "C"}
    assert summary["errors"] == []


# ---------------------------------------------------------------------------
# (c) analysis: runs after all studies; dispatch recorded via the analysis
#     hook (module-level ``_ANALYSIS_RUN_ORDER`` skeleton is left off, so the
#     real ``_run_analysis_hook`` -> env worker pool path is exercised;
#     stub the pool so this stays hermetic).
# ---------------------------------------------------------------------------

def test_analysis_runs_after_studies_and_is_recorded(tmp_path, monkeypatch):
    _mk_investigation(
        tmp_path, "inv", ["m0", "m1"],
        analyses=[{"name": "comparison_matrix"}])

    class _FakePool:
        def __init__(self):
            self.calls = []

        def call(self, workspace, method, params):
            self.calls.append((workspace, method, params))
            return {"written": ["matrix.html"], "errors": []}

    fake_pool = _FakePool()
    monkeypatch.setattr(
        "vivarium_workbench.lib.env_worker_pool.get_pool", lambda: fake_pool)

    calls: list = []
    summary = run_investigation_composite(
        tmp_path, "inv", run_study_fn=_fake_run_study(calls))

    assert summary["studies_ran"] == ["m0", "m1"]
    assert summary["analyses"] == ["comparison_matrix"]
    assert summary["errors"] == []

    # The analysis dispatch went through the (stubbed) env worker pool, after
    # both studies ran.
    assert len(fake_pool.calls) == 1
    workspace, method, params = fake_pool.calls[0]
    assert method == "run_investigation_analysis"
    assert params["name"] == "comparison_matrix"


def test_analysis_errors_are_captured_in_summary(tmp_path, monkeypatch):
    _mk_investigation(
        tmp_path, "inv", ["m0"],
        analyses=[{"name": "comparison_matrix"}])

    class _FailingPool:
        def call(self, workspace, method, params):
            return {"written": [], "errors": [{"stage": "render", "error": "boom"}]}

    monkeypatch.setattr(
        "vivarium_workbench.lib.env_worker_pool.get_pool", lambda: _FailingPool())

    calls: list = []
    summary = run_investigation_composite(
        tmp_path, "inv", run_study_fn=_fake_run_study(calls))

    assert summary["errors"] == [
        {"analysis": "comparison_matrix", "error": {"stage": "render", "error": "boom"}}]


def test_study_errors_in_reply_are_captured_without_aborting(tmp_path):
    _mk_investigation(tmp_path, "inv", ["m0", "m1"])

    def _fn(workspace, study_slug):
        errs = [{"stage": "baseline", "error": "boom"}] if study_slug == "m0" else []
        return {"run_refs": [], "verdict": None, "errors": errs}

    summary = run_investigation_composite(tmp_path, "inv", run_study_fn=_fn)

    assert summary["studies_ran"] == ["m0", "m1"]  # both ran; no abort
    assert summary["errors"] == [
        {"study": "m0", "error": {"stage": "baseline", "error": "boom"}}]


def test_raised_exception_propagates_fail_loud(tmp_path):
    _mk_investigation(tmp_path, "inv", ["m0", "m1"])

    def _fn(workspace, study_slug):
        if study_slug == "m0":
            raise RuntimeError("worker crashed")
        return {"run_refs": [], "verdict": None, "errors": []}

    try:
        run_investigation_composite(tmp_path, "inv", run_study_fn=_fn)
        assert False, "expected RuntimeError to propagate"
    except RuntimeError as e:
        assert "worker crashed" in str(e)


# ---------------------------------------------------------------------------
# prepare_investigation delegation: a FULL run (not render_only, no single
# `study=`) routes through run_investigation_composite; render_only and the
# single-study path keep the original POST-driven prepare_study route
# (backward-compat — see prepare_investigation.py's docstring/comments).
# ---------------------------------------------------------------------------

def test_prepare_investigation_full_run_delegates_to_composite(tmp_path, monkeypatch):
    import vivarium_workbench.lib.investigation_execution as ie
    from vivarium_workbench.lib import prepare_investigation as pi

    _mk_investigation(tmp_path, "inv", ["m0", "m1"])

    calls = []

    def _fake_run_investigation_composite(ws, inv, **kw):
        calls.append((str(ws), inv))
        return {
            "investigation": inv, "studies_ran": ["m0", "m1"], "analyses": [],
            "errors": [],
            "study_results": {
                "m0": {"run_refs": [{"sim_name": "m0", "run_id": "r0"}]},
                "m1": {"run_refs": [{"sim_name": "m1", "run_id": "r1"}]},
            },
        }

    monkeypatch.setattr(ie, "run_investigation_composite", _fake_run_investigation_composite)

    out = pi.prepare_investigation(tmp_path, investigation="inv")

    # The composite ran, not the old per-study POST loop.
    assert calls == [(str(tmp_path), "inv")]
    assert out["investigation"] == "inv"
    assert out["generation_id"]
    slugs = [s["study"] for s in out["studies"]]
    assert slugs == ["m0", "m1"]
    # No comparative_visualizations declared -> rendering is skipped, but the
    # composite-driven run is still reflected.
    for s in out["studies"]:
        assert s["skipped"] == "no comparative_visualizations"
        assert s["runs"][0]["run_id"] in ("r0", "r1")


def test_prepare_investigation_single_study_and_render_only_bypass_composite(
        tmp_path, monkeypatch):
    import vivarium_workbench.lib.investigation_execution as ie
    from vivarium_workbench.lib import prepare_investigation as pi

    _mk_investigation(tmp_path, "inv", ["m0", "m1"])

    def _boom(ws, inv, **kw):
        raise AssertionError("run_investigation_composite must not be called here")

    monkeypatch.setattr(ie, "run_investigation_composite", _boom)

    # Single-study path.
    out1 = pi.prepare_investigation(tmp_path, investigation="inv", study="m0")
    assert [s["study"] for s in out1["studies"]] == ["m0"]

    # render_only path.
    out2 = pi.prepare_investigation(tmp_path, investigation="inv", render_only=True)
    assert [s["study"] for s in out2["studies"]] == ["m0", "m1"]
