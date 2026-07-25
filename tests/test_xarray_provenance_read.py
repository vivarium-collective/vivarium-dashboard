"""Disk-discovered zarr runs surface their self-describing provenance
(composite + config) from the store's root attrs; legacy attr-less stores
fall back to None (no composite/config)."""
import zarr
from vivarium_workbench.lib.simulations_index import (
    _read_zarr_provenance, _discover_xarray_runs,
)


def _make_store(path, provenance=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    g = zarr.open_group(str(path), mode="w")
    if provenance is not None:
        g.attrs["provenance"] = provenance
    return path


def test_read_provenance_roundtrip(tmp_path):
    z = _make_store(tmp_path / "store.zarr",
                    {"composite": "pkg.composites.x", "config": {"seed": 0}, "run_id": "r1"})
    prov = _read_zarr_provenance(z)
    assert prov["composite"] == "pkg.composites.x"
    assert prov["config"] == {"seed": 0}


def test_read_provenance_legacy_none(tmp_path):
    z = _make_store(tmp_path / "store.zarr", provenance=None)
    assert _read_zarr_provenance(z) is None


def test_discover_surfaces_provenance(tmp_path):
    runs = tmp_path / ".pbg" / "runs"
    _make_store(runs / "myrun" / "store.zarr",
                {"composite": "v2ecoli.composites.baseline.baseline",
                 "config": {"seed": 3, "condition": "with_aa"}, "run_id": "myrun"})
    rows = _discover_xarray_runs(tmp_path)
    assert len(rows) == 1
    assert rows[0]["spec_id"] == "v2ecoli.composites.baseline.baseline"
    assert rows[0]["config"] == {"seed": 3, "condition": "with_aa"}


def test_discover_legacy_store_no_provenance(tmp_path):
    runs = tmp_path / ".pbg" / "runs"
    _make_store(runs / "oldrun" / "store.zarr", provenance=None)
    rows = _discover_xarray_runs(tmp_path)
    assert len(rows) == 1
    assert rows[0]["spec_id"] is None
    assert rows[0].get("config") is None


def test_read_provenance_nested_partition_group(tmp_path):
    """The emitter writes provenance at its partition ROOT group
    (experiment_id=.../variant=.../lineage_seed=...), not the top store dir."""
    import zarr
    store = tmp_path / "store.zarr"
    root = zarr.open_group(str(store), mode="w")
    part = (root.create_group("experiment_id=e")
                .create_group("variant=0")
                .create_group("lineage_seed=0"))
    part.attrs["provenance"] = {"composite": "pkg.composites.deep",
                                "config": {"seed": 5}, "run_id": "r9"}
    prov = _read_zarr_provenance(store)
    assert prov["composite"] == "pkg.composites.deep"
    assert prov["config"] == {"seed": 5}


def test_discover_surfaces_nested_provenance(tmp_path):
    import zarr
    store = tmp_path / ".pbg" / "runs" / "run7" / "store.zarr"
    store.parent.mkdir(parents=True, exist_ok=True)
    part = (zarr.open_group(str(store), mode="w")
            .create_group("experiment_id=e").create_group("variant=0"))
    part.attrs["provenance"] = {"composite": "v2ecoli.composites.baseline.baseline",
                                "config": {"seed": 1}, "run_id": "run7"}
    rows = _discover_xarray_runs(tmp_path)
    assert rows[0]["spec_id"] == "v2ecoli.composites.baseline.baseline"
    assert rows[0]["config"] == {"seed": 1}
