"""Walking-skeleton: characterize how the process-bigraph engine schedules
StudySteps, against the REAL engine. Establishes the two load-bearing facts the
InvestigationComposite generator relies on:

  1. Prerequisite wiring (a step's input wired to the store an upstream step
     writes) orders the two steps: upstream before downstream. Transitive.
  2. Independent steps (no wiring between them) run in a NONDETERMINISTIC order
     (engine hash/set order, NOT declared order) — so declared-order
     determinism requires the generator to add synthetic serial edges.

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


def _run(state):
    order = []
    m._RUN_ORDER = order
    try:
        Composite({"state": state, "run_steps_on_init": True}, core=_core())
    finally:
        m._RUN_ORDER = None
    return order


def test_prereq_wiring_orders_two_steps():
    # B depends on A: B's prereq input wired to the store A writes.
    order = _run({
        "A_result": {}, "B_result": {},
        "A": _doc("A", [], "A_result", {}),
        "B": _doc("B", ["A"], "B_result", {"prereq_A": ["A_result"]}),
    })
    assert order == ["A", "B"], order


def test_chain_of_three_orders_transitively():
    # C <- B <- A
    order = _run({
        "A_result": {}, "B_result": {}, "C_result": {},
        "A": _doc("A", [], "A_result", {}),
        "B": _doc("B", ["A"], "B_result", {"prereq_A": ["A_result"]}),
        "C": _doc("C", ["B"], "C_result", {"prereq_B": ["B_result"]}),
    })
    assert order == ["A", "B", "C"], order


def test_independent_steps_run_all_without_ordering_guarantee():
    # No wiring between them: all three run, but the order is engine hash order,
    # NOT declared order. We assert only completeness, and document that the
    # generator must NOT rely on declared order emerging naturally.
    order = _run({
        "x_result": {}, "y_result": {}, "z_result": {},
        "x": _doc("x", [], "x_result", {}),
        "y": _doc("y", [], "y_result", {}),
        "z": _doc("z", [], "z_result", {}),
    })
    assert set(order) == {"x", "y", "z"}, order


def test_serial_wiring_enforces_declared_order():
    # THE MECHANISM the generator uses for deterministic declared order:
    # synthetic serial edges y<-x, z<-y turn independent studies into a chain.
    order = _run({
        "x_result": {}, "y_result": {}, "z_result": {},
        "x": _doc("x", [], "x_result", {}),
        "y": _doc("y", ["x"], "y_result", {"prereq_x": ["x_result"]}),
        "z": _doc("z", ["y"], "z_result", {"prereq_y": ["y_result"]}),
    })
    assert order == ["x", "y", "z"], order
