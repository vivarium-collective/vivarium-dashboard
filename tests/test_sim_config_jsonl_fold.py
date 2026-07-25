"""Config must survive the JSONL fold: _rec_to_simrow surfaces it from an
explicit `config` record or derives it from the saved `params`.
"""
from vivarium_workbench.lib.simulations_index import _rec_to_simrow


def test_explicit_config_on_record():
    row = _rec_to_simrow("r1", {"spec_id": "x", "status": "completed",
                                "config": {"seed": 7, "condition": "with_aa"}})
    assert row["config"] == {"seed": 7, "condition": "with_aa"}


def test_config_derived_from_params_strips_provenance():
    row = _rec_to_simrow("r2", {"spec_id": "x", "status": "completed",
                                "params": {"seed": 3, "config_overrides": {"a": 1},
                                           "source": "smsvpctest", "simulation_id": 9}})
    assert row["config"] == {"seed": 3, "config_overrides": {"a": 1}}


def test_no_config_when_neither():
    row = _rec_to_simrow("r3", {"spec_id": "x", "status": "completed"})
    assert row.get("config") is None
