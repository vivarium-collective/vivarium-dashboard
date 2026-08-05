"""baseline.step — run a bare process-bigraph Step as a study baseline.

Builds a throwaway workspace package (its own ``core.build_core`` + a trivial
Step) on sys.path, then exercises the real ``step_baseline`` synthesis and
``resolve_study_baseline_state`` routing end-to-end: the synthesized state is a
runnable composite whose emitter captures the Step's output.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from vivarium_workbench.lib.step_baseline import (
    STEP_PREFIX, is_step_spec, step_address, build_step_state,
)


@pytest.fixture()
def step_pkg(tmp_path, monkeypatch):
    """A minimal workspace package with build_core() + a Step that outputs 42."""
    pkg = tmp_path / "stepwspkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "steps.py").write_text(textwrap.dedent('''
        from process_bigraph import Step

        class AnswerStep(Step):
            config_schema = {"offset": "integer"}
            def inputs(self):
                return {}
            def outputs(self):
                return {"answer": "integer"}
            def update(self, inputs):
                return {"answer": 42 + int(self.config.get("offset") or 0)}
    '''), encoding="utf-8")
    (pkg / "core.py").write_text(textwrap.dedent('''
        from process_bigraph import allocate_core
        from stepwspkg.steps import AnswerStep

        def build_core():
            core = allocate_core()
            core.register_link("stepwspkg.steps.AnswerStep", AnswerStep)
            core.register_link("AnswerStep", AnswerStep)
            return core
    '''), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    # ensure a clean import of the freshly written package
    for m in list(sys.modules):
        if m == "stepwspkg" or m.startswith("stepwspkg."):
            del sys.modules[m]
    return "stepwspkg"


ADDR = "local:stepwspkg.steps.AnswerStep"


def test_is_step_spec_and_address():
    assert is_step_spec("step:" + ADDR)
    assert not is_step_spec("viva.composites.x.name")
    assert not is_step_spec(None)
    assert step_address("step:" + ADDR) == ADDR
    assert step_address(ADDR) == ADDR  # identity when not prefixed


def test_build_step_state_shape(step_pkg):
    state, err = build_step_state(STEP_PREFIX + ADDR, step_pkg, {"offset": 0})
    assert err is None
    # a top-level store per output, the step node wired to it, and a RAMEmitter
    assert "answer" in state
    assert state["step"]["address"] == ADDR
    assert state["step"]["outputs"] == {"answer": ["answer"]}
    assert state["step"]["inputs"] == {}
    assert state["emitter"]["address"] == "local:RAMEmitter"
    assert state["emitter"]["config"]["emit"] == {"answer": "node"}


def test_build_step_state_runs_and_emits(step_pkg):
    from process_bigraph import Composite, gather_emitter_results
    import importlib
    core = importlib.import_module(f"{step_pkg}.core").build_core()
    state, err = build_step_state(STEP_PREFIX + ADDR, step_pkg, {"offset": 8})
    assert err is None
    comp = Composite({"state": state}, core=core)
    comp.run(1)
    frames = list(gather_emitter_results(comp).values())[0]
    assert frames[-1]["answer"] == 50  # 42 + offset 8


def test_resolve_study_baseline_state_routes_step(step_pkg):
    from vivarium_workbench.lib.study_run_state import resolve_study_baseline_state
    state, err = resolve_study_baseline_state(Path("."), step_pkg, STEP_PREFIX + ADDR, {"offset": 0})
    assert err is None and state is not None
    assert state["step"]["address"] == ADDR


def test_build_step_state_bad_address_errors(step_pkg):
    state, err = build_step_state(STEP_PREFIX + "local:stepwspkg.steps.NoSuchStep", step_pkg, {})
    assert state is None and err and "introspect" in err["error"].lower()


def test_build_step_state_bad_pkg_errors():
    state, err = build_step_state(STEP_PREFIX + ADDR, "nonexistent_pkg_xyz", {})
    assert state is None and err and "core" in err["error"].lower()
