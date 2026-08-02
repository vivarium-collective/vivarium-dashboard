"""Investigation-level analysis mechanism (investigation-as-composite design,
docs/superpowers/specs/2026-08-01-investigation-as-composite-design.md,
§Architecture 2-3):

  (a) ``env_worker._run_investigation_analysis`` — the worker capability that
      invokes an ``ANALYSIS_REGISTRY`` Analysis DIRECTLY
      (``cls(config, core=allocate_core()).update()``), bypassing the
      parquet-coupled ``run_study_analyses``/``build_cell_records`` path (the
      #712 blocker: that path globs a study's ``history/**/*.pq`` sweep output
      and returns ``{}`` for an investigation dir, so the Analysis is never
      invoked). Hermetic: injects a fake ``v2ecoli.workflow.analysis`` module
      via ``sys.modules`` (same technique as ``test_post_run_analyses.py``) so
      no real v2ecoli Analysis stack is needed.

  (b) ``InvestigationAnalysisStep`` — a process-bigraph ``Step`` wired to study result
      stores (one ``"node"`` port per ``study_slugs`` entry), on the REAL
      engine (mirrors ``test_study_step_dispatch.py``): runs after its wired
      ``StudyStep``s and assembles their results into ``config_verdicts``.

Both need ``bigraph_schema``/``process_bigraph`` (the v2ecoli venv; see the
plan's Global Constraints) — (a) additionally needs it for
``bigraph_schema.allocate_core`` inside ``_run_investigation_analysis``, so
unlike ``env_worker._run_study``'s hermetic test this one is not runnable on a
bare dev venv without process-bigraph installed.
"""
from __future__ import annotations

import sys
import types

from bigraph_schema import allocate_core
from process_bigraph import Composite

from vivarium_workbench import env_worker
import vivarium_workbench.lib.investigation_steps as m
from vivarium_workbench.lib.investigation_steps import (
    InvestigationAnalysisStep, StudyStep, _extract_study_verdict)


# ---------------------------------------------------------------------------
# (a) env_worker._run_investigation_analysis — hermetic
# ---------------------------------------------------------------------------

def _install_fake_registry(registry: dict) -> None:
    """Inject a fake ``v2ecoli.workflow.analysis`` module so
    ``from v2ecoli.workflow.analysis import ANALYSIS_REGISTRY`` resolves to
    ``registry`` without needing the real v2ecoli Analysis stack (mirrors
    ``tests/test_post_run_analyses.py``)."""
    fake_mod = types.ModuleType("v2ecoli.workflow.analysis")
    fake_mod.ANALYSIS_REGISTRY = registry  # type: ignore[attr-defined]
    sys.modules["v2ecoli.workflow.analysis"] = fake_mod


class _FakeMatrixAnalysis:
    """Mimics a config-only Analysis: ``cls(config, core=...).update()``."""

    def __init__(self, config, core=None):
        self.config = config
        self.core = core

    def update(self):
        return {"matrix_html": "<div/>"}


class _RaisingAnalysis:
    def __init__(self, config, core=None):
        pass

    def update(self):
        raise RuntimeError("analyze() blew up")


def test_writes_string_output_to_report_dir(tmp_path):
    _install_fake_registry({"comparison_matrix": _FakeMatrixAnalysis})
    report_dir = tmp_path / "reports"

    result = env_worker._run_investigation_analysis({
        "workspace": str(tmp_path),
        "name": "comparison_matrix",
        "config": {"config_verdicts": {"A": {"overall": "pass"}}},
        "report_dir": str(report_dir),
    })

    assert result["errors"] == []
    expected = report_dir / "comparison_matrix_matrix_html.html"
    assert result["written"] == [str(expected)]
    assert expected.read_text(encoding="utf-8") == "<div/>"


def test_non_string_outputs_are_skipped(tmp_path):
    class _MixedAnalysis:
        def __init__(self, config, core=None):
            pass

        def update(self):
            return {"matrix_html": "<div/>", "raw_scores": {"a": 1}, "count": 3}

    _install_fake_registry({"mixed": _MixedAnalysis})
    report_dir = tmp_path / "reports"

    result = env_worker._run_investigation_analysis({
        "workspace": str(tmp_path), "name": "mixed", "config": {},
        "report_dir": str(report_dir),
    })

    assert result["errors"] == []
    assert result["written"] == [str(report_dir / "mixed_matrix_html.html")]


def test_unknown_analysis_name_records_error_not_raise(tmp_path):
    _install_fake_registry({"comparison_matrix": _FakeMatrixAnalysis})

    result = env_worker._run_investigation_analysis({
        "workspace": str(tmp_path),
        "name": "does_not_exist",
        "config": {},
        "report_dir": str(tmp_path / "reports"),
    })

    assert result["written"] == []
    assert len(result["errors"]) == 1
    assert "does_not_exist" in result["errors"][0]["error"]
    assert "unknown analysis" in result["errors"][0]["error"]


def test_raising_analysis_records_error_not_raise(tmp_path):
    _install_fake_registry({"boom": _RaisingAnalysis})

    result = env_worker._run_investigation_analysis({
        "workspace": str(tmp_path),
        "name": "boom",
        "config": {},
        "report_dir": str(tmp_path / "reports"),
    })

    assert result["written"] == []
    assert len(result["errors"]) == 1
    assert result["errors"][0]["analysis"] == "boom"
    assert "blew up" in result["errors"][0]["error"]


def test_write_failure_records_error_not_raise(tmp_path, monkeypatch):
    # A report_dir that cannot be written (mkdir raises) must be recorded as an
    # error, never propagated — the third exception path in the capability.
    _install_fake_registry({"comparison_matrix": _FakeMatrixAnalysis})

    import pathlib

    orig_mkdir = pathlib.Path.mkdir

    def boom_mkdir(self, *a, **k):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(pathlib.Path, "mkdir", boom_mkdir)

    result = env_worker._run_investigation_analysis({
        "workspace": str(tmp_path),
        "name": "comparison_matrix",
        "config": {"config_verdicts": {}},
        "report_dir": str(tmp_path / "reports"),
    })

    monkeypatch.setattr(pathlib.Path, "mkdir", orig_mkdir)
    assert result["written"] == []
    assert len(result["errors"]) == 1
    assert "read-only filesystem" in result["errors"][0]["error"]


def test_missing_name_records_error_not_raise(tmp_path):
    result = env_worker._run_investigation_analysis({
        "workspace": str(tmp_path), "report_dir": str(tmp_path / "reports")})
    assert result["written"] == []
    assert "name" in result["errors"][0]["error"]


def test_missing_report_dir_records_error_not_raise(tmp_path):
    _install_fake_registry({"comparison_matrix": _FakeMatrixAnalysis})
    result = env_worker._run_investigation_analysis({
        "workspace": str(tmp_path), "name": "comparison_matrix"})
    assert result["written"] == []
    assert "report_dir" in result["errors"][0]["error"]


# ---------------------------------------------------------------------------
# (b) InvestigationAnalysisStep — real engine, stubbed pool
# ---------------------------------------------------------------------------

# The class is named ``InvestigationAnalysisStep`` (NOT ``AnalysisStep``)
# specifically to avoid a short-name link-registry collision with
# v2ecoli.workflow.analysis.AnalysisStep — the base class every real v2ecoli
# Analysis subclasses, which claims the ``"AnalysisStep"`` short alias first in
# a v2ecoli venv. With the unique name, the plain short address resolves to our
# class; no fully-qualified address is needed.
_ANALYSIS_ADDRESS = "local:InvestigationAnalysisStep"


def _core():
    return allocate_core(top={"StudyStep": StudyStep, "InvestigationAnalysisStep": InvestigationAnalysisStep})


def _study_doc(slug, result_store):
    return {
        "_type": "step",
        "address": "local:StudyStep",
        "config": {"workspace": "/ws", "study_slug": slug, "prereqs": []},
        "inputs": {},
        "outputs": {"result": [result_store]},
    }


def _analysis_doc(name, study_slugs, study_ports, report_dir="/ws/reports", params=None):
    return {
        "_type": "step",
        "address": _ANALYSIS_ADDRESS,
        "config": {
            "workspace": "/ws", "name": name, "params": params or {},
            "study_slugs": study_slugs, "report_dir": report_dir,
        },
        "inputs": study_ports,
        "outputs": {"written": ["written"]},
    }


class _FakePool:
    def __init__(self):
        self.calls = []

    def call(self, workspace, method, params):
        self.calls.append((workspace, method, params))
        if method == "run_study":
            return {"run_refs": ["r1"],
                    "verdict": {"study": params["study_slug"], "overall": "pass"}}
        return {"written": [f"/ws/reports/{params['name']}_matrix_html.html"],
                "errors": []}


def test_analysis_step_runs_after_studies_and_receives_verdicts(monkeypatch):
    fake_pool = _FakePool()
    monkeypatch.setattr(
        "vivarium_workbench.lib.env_worker_pool.get_pool", lambda: fake_pool)

    assert m._RUN_ORDER is None
    assert m._ANALYSIS_RUN_ORDER is None

    state = {
        "A_result": {}, "B_result": {}, "written": {},
        "A": _study_doc("A", "A_result"),
        "B": _study_doc("B", "B_result"),
        "analysis": _analysis_doc(
            "comparison_matrix", ["A", "B"],
            {"study_A": ["A_result"], "study_B": ["B_result"]},
            params={"static_opt": True}),
    }
    Composite({"state": state, "run_steps_on_init": True}, core=_core())

    methods = [c[1] for c in fake_pool.calls]
    # Both studies ran (order between independent A/B is not asserted here —
    # test_investigation_steps_skeleton.py covers that non-determinism), and
    # the analysis dispatch is the LAST call: the engine only makes it
    # eligible once both wired study results are available.
    assert methods.count("run_study") == 2
    assert methods[-1] == "run_investigation_analysis"

    analysis_call = fake_pool.calls[-1]
    assert analysis_call[0] == "/ws"
    dispatched_config = analysis_call[2]["config"]
    assert dispatched_config["static_opt"] is True
    # config_verdicts now holds the EXTRACTED verdict, not the raw run_study
    # reply — the _FakePool reply here has no ``analyses`` key, so extraction
    # falls back to the reply's top-level ``verdict`` (store data-flow
    # refactor, design §2; behavior intentionally changed from the raw-reply
    # shape this test previously asserted).
    assert dispatched_config["config_verdicts"] == {
        "A": {"study": "A", "overall": "pass"},
        "B": {"study": "B", "overall": "pass"},
    }
    assert analysis_call[2]["name"] == "comparison_matrix"
    assert analysis_call[2]["report_dir"] == "/ws/reports"
    # workspace is threaded into the analysis config so an investigation-level
    # analysis can locate per-study verdict files on disk.
    assert dispatched_config["workspace"] == "/ws"


class _FakePoolWithAnalyses:
    """``run_study`` replies carry the store data-flow refactor's ``analyses``
    key (design §2) — the per-study ``comparison_cards`` verdict lives at
    ``analyses.comparison_cards.verdict``, alongside an unrelated top-level
    ``verdict`` (the conclusion card) that must NOT be picked up instead."""

    def __init__(self):
        self.calls = []

    def call(self, workspace, method, params):
        self.calls.append((workspace, method, params))
        if method == "run_study":
            slug = params["study_slug"]
            return {
                "run_refs": ["r"],
                "verdict": {"overall": "cnc"},
                "analyses": {
                    "comparison_cards": {
                        "verdict": {"overall": "within_tol", "cfg": slug},
                    },
                },
                "errors": [],
            }
        return {"written": [f"/ws/reports/{params['name']}_matrix_html.html"],
                "errors": []}


def test_analysis_step_extracts_verdict_from_analyses_store(monkeypatch):
    """config_verdicts is assembled from state[f"study_{slug}"]["analyses"]
    ["comparison_cards"]["verdict"] — the store data-flow refactor's
    canonical source — NOT the raw run_study reply and NOT the reply's
    unrelated top-level ``verdict`` (the conclusion card)."""
    fake_pool = _FakePoolWithAnalyses()
    monkeypatch.setattr(
        "vivarium_workbench.lib.env_worker_pool.get_pool", lambda: fake_pool)

    state = {
        "A_result": {}, "B_result": {}, "written": {},
        "A": _study_doc("A", "A_result"),
        "B": _study_doc("B", "B_result"),
        "analysis": _analysis_doc(
            "comparison_matrix", ["A", "B"],
            {"study_A": ["A_result"], "study_B": ["B_result"]},
        ),
    }
    Composite({"state": state, "run_steps_on_init": True}, core=_core())

    analysis_call = fake_pool.calls[-1]
    assert analysis_call[1] == "run_investigation_analysis"
    dispatched_config = analysis_call[2]["config"]
    assert dispatched_config["config_verdicts"] == {
        "A": {"overall": "within_tol", "cfg": "A"},
        "B": {"overall": "within_tol", "cfg": "B"},
    }


# ---------------------------------------------------------------------------
# _extract_study_verdict — unit-level precedence
# ---------------------------------------------------------------------------

def test_extract_study_verdict_prefers_named_analysis_verdict():
    res = {
        "verdict": {"overall": "cnc"},
        "analyses": {"comparison_cards": {"verdict": {"overall": "within_tol"}}},
    }
    assert _extract_study_verdict(res, "comparison_cards") == {"overall": "within_tol"}


def test_extract_study_verdict_falls_back_to_top_level_verdict():
    res = {"run_refs": ["r"], "verdict": {"overall": "cnc"}, "analyses": {}}
    assert _extract_study_verdict(res, "comparison_cards") == {"overall": "cnc"}


def test_extract_study_verdict_falls_back_to_raw_result_unchanged():
    res = {"run_refs": ["r"]}
    assert _extract_study_verdict(res, "comparison_cards") == {"run_refs": ["r"]}


def test_analysis_step_result_store_holds_written_reply(monkeypatch):
    fake_pool = _FakePool()
    monkeypatch.setattr(
        "vivarium_workbench.lib.env_worker_pool.get_pool", lambda: fake_pool)

    state = {
        "A_result": {}, "written": {},
        "A": _study_doc("A", "A_result"),
        "analysis": _analysis_doc(
            "comparison_matrix", ["A"], {"study_A": ["A_result"]}),
    }
    composite = Composite({"state": state, "run_steps_on_init": True}, core=_core())

    assert composite.state["written"] == [
        "/ws/reports/comparison_matrix_matrix_html.html"]
