"""Tests for lib.zarr_default_viz — the zarr-native Viz/Report fallback for
runs whose data lives only in a zarr/XArray emitter store (every GovCloud/Ray-
dispatched run), where the framework's SQLite-only render pipeline
(run_runner._render_default_viz, viva_superpowers.TimeSeriesFromObservables)
has no path at all.
"""
from __future__ import annotations

import pytest

from vivarium_workbench.lib import zarr_default_viz


def make_fake_zarr(store_path, n_steps=4):
    """Same fixture shape as tests/test_explorer_data.py's make_fake_zarr —
    a real zarr datatree with one scalar (Mass) and one vector (Fluxes) leaf,
    exercising the actual xarray read path rather than mocking it away."""
    pytest.importorskip("xarray")
    import numpy as np
    import xarray as xr

    emit = list(range(n_steps))
    part = xr.Dataset({"time_gen=1": ("emitstep_gen=1", [float(s) for s in emit])})
    mass = xr.Dataset({"generation=1": ("emitstep_gen=1", [100.0 + s for s in emit])})
    flux = xr.Dataset(
        {"generation=1": (("emitstep_gen=1", "id_base_reaction_fluxes"),
                          np.array([[1.0 + s, 2.0 + s, 3.0 + s] for s in emit]))},
        coords={"id_base_reaction_fluxes": ["RXN-A", "RXN-B", "RXN-C"]})
    dt = xr.DataTree.from_dict({
        "experiment_id=e/variant=0/lineage_seed=0": part,
        "experiment_id=e/variant=0/lineage_seed=0/cell_mass": mass,
        "experiment_id=e/variant=0/lineage_seed=0/base_reaction_fluxes": flux,
    })
    dt.to_zarr(str(store_path), mode="w")


# ---------------------------------------------------------------------------
# pick_default_observables — pure, no zarr I/O
# ---------------------------------------------------------------------------


def test_pick_skips_vector_leaves():
    categories = {
        "Mass": [{"path": "cell_mass", "kind": "scalar"}],
        "Fluxes": [{"path": "base_reaction_fluxes", "kind": "vector"}],
    }
    assert zarr_default_viz.pick_default_observables(categories) == ["cell_mass"]


def test_pick_caps_per_category_and_total():
    categories = {
        "Mass": [{"path": f"m{i}", "kind": "scalar"} for i in range(10)],
        "Growth & division": [{"path": f"g{i}", "kind": "scalar"} for i in range(10)],
        "Bulk molecules": [{"path": f"b{i}", "kind": "scalar"} for i in range(10)],
    }
    chosen = zarr_default_viz.pick_default_observables(categories)
    assert len(chosen) <= zarr_default_viz._TOTAL_CAP
    # per-category cap respected for the first category
    assert chosen[:zarr_default_viz._PER_CATEGORY_CAP] == ["m0", "m1", "m2"]


def test_pick_returns_empty_when_no_scalar_leaves():
    categories = {"Mass": [{"path": "x", "kind": "vector"}]}
    assert zarr_default_viz.pick_default_observables(categories) == []


# ---------------------------------------------------------------------------
# render_default_viz — real zarr store, real xarray read
# ---------------------------------------------------------------------------


def test_render_default_viz_produces_real_chart_from_zarr(tmp_path):
    store = tmp_path / "store.zarr"
    make_fake_zarr(store, n_steps=4)
    html = zarr_default_viz.render_default_viz(store, "run-1")
    assert "cell_mass" in html
    assert "Plotly.newPlot" in html
    # actual data values made it into the rendered trace, not just the name
    assert "100.0" in html or "100" in html


def test_render_default_viz_no_numeric_leaves_placeholder(tmp_path):
    """A store with only vector leaves (no scalar Mass/Growth/Bulk) yields the
    explanatory placeholder, not an empty or broken chart."""
    pytest.importorskip("xarray")
    import numpy as np
    import xarray as xr

    store = tmp_path / "store.zarr"
    flux = xr.Dataset(
        {"generation=1": (("emitstep_gen=1", "id_base_reaction_fluxes"),
                          np.array([[1.0, 2.0, 3.0]]))},
        coords={"id_base_reaction_fluxes": ["RXN-A", "RXN-B", "RXN-C"]})
    dt = xr.DataTree.from_dict({
        "experiment_id=e/variant=0/lineage_seed=0/base_reaction_fluxes": flux,
    })
    dt.to_zarr(str(store), mode="w")
    html = zarr_default_viz.render_default_viz(store, "run-2")
    assert "No numeric scalar observables" in html
    assert "Plotly.newPlot" not in html


def test_render_default_viz_missing_store_never_raises(tmp_path):
    html = zarr_default_viz.render_default_viz(tmp_path / "does-not-exist.zarr", "run-3")
    assert isinstance(html, str)
    assert "Plotly.newPlot" not in html
