import json
from vivarium_workbench.lib import simulations_index as si


def test_completed_run_backfills_and_caches(tmp_path, monkeypatch):
    # a completed run with no cached capabilities gets derived + written back
    monkeypatch.setattr(si.run_capabilities, "derive_capabilities",
                        lambda *a, **k: ["observables", "fluxes"])
    row = {"run_id": "r1", "status": "completed", "capabilities_json": None,
           "db_path": "x.db", "store_path": None}
    out = si._capabilities_for_row(row, conn=_FakeConn())
    assert out == ["observables", "fluxes"]

def test_inprogress_run_derives_without_caching(monkeypatch):
    monkeypatch.setattr(si.run_capabilities, "derive_capabilities",
                        lambda *a, **k: ["observables"])
    conn = _FakeConn()
    row = {"run_id": "r2", "status": "running", "capabilities_json": None,
           "db_path": "x.db", "store_path": None}
    out = si._capabilities_for_row(row, conn=conn)
    assert out == ["observables"]
    assert conn.writes == []  # not cached while running

def test_cached_value_is_used(monkeypatch):
    called = {"n": 0}
    def spy(*a, **k):
        called["n"] += 1; return ["x"]
    monkeypatch.setattr(si.run_capabilities, "derive_capabilities", spy)
    row = {"run_id": "r3", "status": "completed",
           "capabilities_json": json.dumps(["observables", "mass"])}
    out = si._capabilities_for_row(row, conn=_FakeConn())
    assert out == ["observables", "mass"]
    assert called["n"] == 0  # no recompute when cached

class _FakeConn:
    def __init__(self): self.writes = []
