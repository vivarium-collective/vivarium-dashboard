from pathlib import Path
import vivarium_workbench

def _js():
    return (Path(vivarium_workbench.__file__).parent / "static" / "configure-run.js").read_text(encoding="utf-8")

def test_run_form_distinguishes_temporal_vs_workflow():
    """The Run form must explain whether a composite is a timed simulation or a
    one-shot workflow, and label the step control accordingly (arnab's #752/#754
    confusion: parca is a workflow, ecoli_baseline is temporal)."""
    js = _js()
    assert "run_kind" in js
    assert "_runKindNote" in js and "_stepsLabel" in js
    assert "temporal" in js and "workflow" in js
    assert "time steps" in js and "pipeline ticks" in js
