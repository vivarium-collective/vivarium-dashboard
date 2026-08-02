"""Task 3 / Fable Increment A #5: pure partition of the observable surface into
saved (emitted) vs excluded (available-but-not-emitted) rows, plus the R2
three-state ``excluded_state`` marker (``computed`` / ``empty`` /
``unavailable``). See
``.superpowers/sdd/2026-07-31-study-page-declutter/task-3-brief.md`` and
``docs/superpowers/specs/2026-08-01-study-design-fable-pass.md`` §5.1-5.2.
"""
from __future__ import annotations

from vivarium_workbench.lib.readouts_views import _compute_excluded, _split_saved_excluded


def test_excluded_is_available_minus_emitted():
    emitted = ["a.b.x", "a.b.y"]
    available = ["a.b.x", "a.b.y", "a.b.z", "a.c.w"]
    saved, excluded = _split_saved_excluded(emitted, available)
    assert {r["store_path"] for r in saved} == {"a.b.x", "a.b.y"}
    assert {r["store_path"] for r in excluded} == {"a.b.z", "a.c.w"}


def test_excluded_empty_when_emit_is_total():
    leaves = ["a.b.x", "a.b.y"]
    saved, excluded = _split_saved_excluded(leaves, leaves)
    assert excluded == []
    assert len(saved) == 2


# ---------------------------------------------------------------------------
# _compute_excluded: the real saved/excluded split + R2 three-state marker.
# ---------------------------------------------------------------------------

_AVAILABLE = {"leaves": [
    "agents.0.listeners.mass.cell_mass",
    "agents.0.listeners.mass.other_thing",
    "agents.0.config.cache_dir",
]}


def test_compute_excluded_subset_spec_yields_real_nonempty_excluded():
    """A spec whose readouts/tests declare a strict subset of the available
    surface -> excluded is the genuine difference, not an echo of the input."""
    spec = {"readouts": [{"name": "cm", "store_path": "listeners.mass.cell_mass"}]}
    result = _compute_excluded(spec, _AVAILABLE)
    assert result["excluded_state"] == "computed"
    assert result["emit_selection"] == "subset"
    excluded_paths = {r["store_path"] for r in result["excluded"]}
    assert excluded_paths == {
        "agents.0.listeners.mass.other_thing",
        "agents.0.config.cache_dir",
    }
    assert "agents.0.listeners.mass.cell_mass" not in excluded_paths


def test_compute_excluded_no_declarations_is_total_emit_not_computed():
    """A spec that declares nothing (no readouts/tests/visualizations) falls
    back to run_runner's 'save everything' behavior — genuinely nothing is
    excluded, distinct from 'we could not tell'."""
    spec = {"readouts": [], "tests": [], "visualizations": []}
    result = _compute_excluded(spec, _AVAILABLE)
    assert result["excluded"] == []
    assert result["excluded_state"] == "empty"
    assert result["emit_selection"] == "total"


def test_compute_excluded_propagates_failure_for_caller_to_degrade(monkeypatch):
    """_compute_excluded itself raises on failure (e.g. collect_emit_paths_from_spec
    blowing up) rather than silently returning []; build_study_readouts is the
    layer responsible for catching this and marking 'unavailable'."""
    from vivarium_workbench.lib import composite_runs as cr

    def _boom(spec):
        raise RuntimeError("readout_resolver import exploded")

    monkeypatch.setattr(cr, "collect_emit_paths_from_spec", _boom)
    import pytest
    with pytest.raises(RuntimeError):
        _compute_excluded({"readouts": []}, _AVAILABLE)


def test_build_study_readouts_marks_unavailable_on_uncomputable_composite(tmp_path, monkeypatch):
    """End-to-end: when the composite cannot build, build_study_readouts must
    never fabricate an empty excluded set — it reports excluded_state
    'unavailable' with a reason, and never raises (no 500)."""
    import yaml as _yaml
    from vivarium_workbench.lib import readouts_views as rv

    sd = tmp_path / "studies" / "udemo"
    sd.mkdir(parents=True)
    (sd / "study.yaml").write_text(_yaml.safe_dump({
        "name": "udemo",
        "baseline": [{"composite": "nonexistent.composite"}],
        "readouts": [{"name": "panel-z", "store_path": "listeners.foo.qux"}],
    }))
    monkeypatch.setattr(
        rv, "_available_observables_for_ref",
        lambda ws, ref: (_ for _ in ()).throw(FileNotFoundError("out/cache/initial_state.json")),
    )
    body, status = rv.build_study_readouts(tmp_path, "udemo")
    assert status == 422, body
    assert body["excluded"] == []
    assert body["excluded_state"] == "unavailable"
    assert body.get("reason"), body
