"""The Simulations-DB surfaces each run's exact reproduction config (generator
params). Study.yaml runs merge study-declared params with the run entry's own;
runs_meta rows expose params_json minus transport-provenance keys.
"""
from vivarium_workbench.lib.simulations_index import (
    _study_declared_params, _run_entry_config, _RUN_PROVENANCE_KEYS,
)


def test_declared_params_from_conditions():
    data = {"conditions": {"baseline": {"params": {"condition": "with_aa", "seed": 0}}}}
    assert _study_declared_params(data) == {"condition": "with_aa", "seed": 0}


def test_declared_params_from_baseline_list():
    data = {"baseline": [{"composite": "x", "params": {"seed": 3, "n_cells": 2}}]}
    assert _study_declared_params(data) == {"seed": 3, "n_cells": 2}


def test_declared_params_empty():
    assert _study_declared_params({"runs": []}) == {}


def test_entry_config_overlays_declared():
    declared = {"condition": "with_aa", "seed": 0}
    entry = {"name": "r", "seed": 7, "params": {"cache_dir": "out/cache"}, "n_steps": 100}
    cfg = _run_entry_config(entry, declared)
    # entry seed overrides declared; params merged; n_steps folded in
    assert cfg == {"condition": "with_aa", "seed": 7, "cache_dir": "out/cache", "n_steps": 100}


def test_entry_config_none_when_empty():
    assert _run_entry_config({"name": "r"}, {}) is None


def test_provenance_keys_stripped_set():
    assert {"source", "simulation_id", "store_path"} <= _RUN_PROVENANCE_KEYS
    assert "seed" not in _RUN_PROVENANCE_KEYS
    assert "config_overrides" not in _RUN_PROVENANCE_KEYS
