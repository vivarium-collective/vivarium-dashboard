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


def test_running_to_completed_transition_refreshes_jsonl_capabilities(tmp_path, monkeypatch):
    """A run's capabilities must NOT get stuck on a stale mid-run snapshot.

    A running run's tag set is a live, uncached preview (see
    test_inprogress_run_derives_without_caching); it only becomes the
    authoritative, finalized value once the run completes (cached into
    runs_meta.capabilities_json). Once a partial mid-run snapshot is folded
    into the JSONL via a `backfill` event, a presence-only self-heal check
    lets it permanently shadow the FINAL tag set after completion. This test
    fails against that bug (surfaced capabilities stay `["observables"]`
    forever) and passes once the running->completed transition forces a
    resync.
    """
    from vivarium_workbench.lib import composite_runs

    ws = tmp_path
    db = ws / ".pbg" / "composite-runs.db"
    conn = composite_runs.connect(db)
    rid = "spec__1__abc"

    composite_runs.save_metadata(
        conn, spec_id="spec", run_id=rid, params={}, label="baseline",
        started_at=1.0, n_steps=10, workspace=ws, emitter="sqlite",
        study_slug="baseline", investigation_slug=None, origin="local")

    # While running: a partial snapshot gets derived (never cached) and
    # folded into the JSONL log.
    monkeypatch.setattr(si.run_capabilities, "derive_capabilities",
                        lambda *a, **k: ["observables"])
    mid_run = si.build_simulations_data(ws)
    mid_row = next(s for s in mid_run["simulations"] if s["run_id"] == rid)
    assert mid_row["capabilities"] == ["observables"]

    # Run completes; its FINAL tag set (in runs_meta.capabilities_json once
    # lazily backfilled) is a superset of the mid-run preview.
    composite_runs.complete_metadata(
        conn, run_id=rid, n_steps=10, status="completed", workspace=ws)
    monkeypatch.setattr(si.run_capabilities, "derive_capabilities",
                        lambda *a, **k: ["fluxes", "observables"])
    final = si.build_simulations_data(ws)
    final_row = next(s for s in final["simulations"] if s["run_id"] == rid)
    assert final_row["capabilities"] == ["fluxes", "observables"]

    # Cached now (runs_meta.capabilities_json written on the completed pass
    # above); a further call must not shadow it back to the mid-run preview
    # or recompute it.
    called = {"n": 0}
    def spy(*a, **k):
        called["n"] += 1
        return ["should", "not", "be", "used"]
    monkeypatch.setattr(si.run_capabilities, "derive_capabilities", spy)
    again = si.build_simulations_data(ws)
    again_row = next(s for s in again["simulations"] if s["run_id"] == rid)
    assert again_row["capabilities"] == ["fluxes", "observables"]
    assert called["n"] == 0
