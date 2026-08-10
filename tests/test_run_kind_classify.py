"""``classify_run_kind`` — is a composite a timed simulation or a one-shot workflow?

The Composites-tab Run form shows a single "Steps" box for every composite, but
"Steps" means different things: for a TEMPORAL composite (Processes advancing in
time) it's the number of simulated timesteps; for a WORKFLOW (a Step-only DAG,
e.g. ParCa) it's a one-shot pipeline and a step count is meaningless. This
classifier lets the Run form say which one it is.

Rule: any ``_type == "process"`` node anywhere → temporal; else if there are
Step nodes → workflow; else unknown (no wiring to judge).
"""
from vivarium_workbench.lib.composite_resolve import classify_run_kind


def test_process_node_anywhere_is_temporal():
    state = {"agents": {"0": {"metabolism": {"_type": "process", "address": "local:X"}}}}
    assert classify_run_kind(state) == "temporal"


def test_steps_only_is_workflow():
    state = {
        "initialize": {"_type": "step", "address": "local:InitializeStep"},
        "basal_specs": {"_type": "step", "address": "local:BasalSpecsStep"},
    }
    assert classify_run_kind(state) == "workflow"


def test_process_wins_even_with_many_steps():
    # ecoli_baseline shape: mostly deriver Steps + at least one Process.
    state = {"cell": {"_type": "process"}, **{f"d{i}": {"_type": "step"} for i in range(45)}}
    assert classify_run_kind(state) == "temporal"


def test_empty_or_stateless_is_unknown():
    assert classify_run_kind(None) == "unknown"
    assert classify_run_kind({}) == "unknown"
    assert classify_run_kind({"some_store": {"value": 3}}) == "unknown"


def test_nested_lists_are_walked():
    state = {"nodes": [{"_type": "step"}, {"inner": [{"_type": "process"}]}]}
    assert classify_run_kind(state) == "temporal"
