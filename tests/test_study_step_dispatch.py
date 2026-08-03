"""StudyStep.update() dispatches to the env worker's ``run_study`` capability
via the shared pool (same pattern as ``study_run_post.py`` /
``composite_flush.py``'s ``run_study_analyses`` dispatch), on the REAL
process-bigraph engine — with ``_RUN_ORDER`` left as ``None`` so the
production dispatch path (not the skeleton marker path) runs.

Requires `process_bigraph` (run under the v2ecoli venv; see the plan's Global
Constraints).
"""
from bigraph_schema import allocate_core
from process_bigraph import Composite

import vivarium_workbench.lib.investigation_steps as m
from vivarium_workbench.lib.investigation_steps import StudyStep


def _core():
    return allocate_core(top={"StudyStep": StudyStep})


def _doc(slug, prereqs, result_store, prereq_wires):
    return {
        "_type": "step",
        "address": "local:StudyStep",
        "config": {"workspace": "/ws", "study_slug": slug, "prereqs": prereqs},
        "inputs": prereq_wires,
        "outputs": {"result": [result_store]},
    }


class _FakePool:
    def __init__(self):
        self.calls = []

    def call(self, workspace, method, params):
        self.calls.append((workspace, method, params))
        return {"run_refs": ["r1"], "verdict": {"overall": "pass"}}


def test_study_step_dispatches_run_study_via_pool(monkeypatch):
    fake_pool = _FakePool()
    monkeypatch.setattr(
        "vivarium_workbench.lib.env_worker_pool.get_pool", lambda: fake_pool)

    # Ensure the skeleton path is off: real dispatch must run.
    assert m._RUN_ORDER is None

    state = {
        "A_result": {}, "B_result": {},
        "A": _doc("A", [], "A_result", {}),
        "B": _doc("B", ["A"], "B_result", {"prereq_A": ["A_result"]}),
    }
    composite = Composite(
        {"state": state, "run_steps_on_init": True}, core=_core())

    # Both StudySteps dispatched run_study, in dependency order (A before B).
    assert len(fake_pool.calls) == 2
    workspaces_and_methods = [(c[0], c[1]) for c in fake_pool.calls]
    assert workspaces_and_methods == [("/ws", "run_study"), ("/ws", "run_study")]

    slugs_in_order = [c[2]["study_slug"] for c in fake_pool.calls]
    assert slugs_in_order == ["A", "B"], slugs_in_order

    for c in fake_pool.calls:
        assert c[2] == {"workspace": "/ws", "study_slug": c[2]["study_slug"]}

    # Each step's result store holds the reply.
    reply = {"run_refs": ["r1"], "verdict": {"overall": "pass"}}
    assert composite.state["A_result"] == reply
    assert composite.state["B_result"] == reply
