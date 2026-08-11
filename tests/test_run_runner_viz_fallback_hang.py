"""Regression tests for issue #784 — the ecoli_baseline Composites-tab run
hangs indefinitely (climbing memory) in the default-visualization fallback.

Three confirmed layers, one test group each:

- layer 1 (trigger): a dangling foreign entry in the lazy link registry made
  ``dict(core.link_registry)`` raise ``KeyError`` and crash canonical viz.
  ``_safe_link_registry_dict`` must skip the broken entry instead.
- layer 2 (fallthrough): a canonical-viz *failure* left ``viz_html`` empty,
  which routed a whole-cell composite into the expensive generic fallback.
  ``_render_viz`` must NOT fall to ``_render_default_viz`` when the composite
  declares canonical visualizations.
- layer 3 (the hang): the default fallback ``json.loads()``'d the full
  whole-cell state per history row over the entire (multi-run) history table.
  ``gather_emitter_outputs`` must scope to one run and skip oversized blobs.
"""
import json
import sqlite3
import tempfile
from pathlib import Path

from vivarium_workbench.lib import run_runner
from vivarium_workbench.lib.investigations import gather_emitter_outputs


# --------------------------------------------------------------------------
# layer 1 — a broken lazy-registry entry must not crash viz rendering
# --------------------------------------------------------------------------
class _BrokenLazyRegistry:
    """Mimics bigraph_schema's lazy_registry: one key raises on __getitem__,
    exactly like a foreign package left dangling after a discovery import fail."""
    def __init__(self):
        self._good = {"TimeSeriesPlot": object()}

    def keys(self):
        return list(self._good.keys()) + ["genecoli.processes.vecoli_process.VEcoliProcess"]

    def __getitem__(self, key):
        if key in self._good:
            return self._good[key]
        raise KeyError(key)


class _Core:
    def __init__(self, registry):
        self.link_registry = registry


def test_safe_link_registry_dict_skips_broken_entry():
    """A dangling registry key raises on lookup; the helper skips it rather
    than propagating the KeyError that crashed _render_canonical_viz (#784)."""
    core = _Core(_BrokenLazyRegistry())
    out = run_runner._safe_link_registry_dict(core)
    assert "TimeSeriesPlot" in out
    assert "genecoli.processes.vecoli_process.VEcoliProcess" not in out


def test_safe_link_registry_dict_plain_dict():
    """A normal dict registry materializes unchanged."""
    core = _Core({"A": 1, "B": 2})
    assert run_runner._safe_link_registry_dict(core) == {"A": 1, "B": 2}


# --------------------------------------------------------------------------
# layer 2 — declared canonical viz must NOT route into the default fallback
# --------------------------------------------------------------------------
def test_no_default_fallback_when_canonical_declared(monkeypatch):
    """When the composite declares canonical visualizations but canonical
    rendering yields nothing (e.g. it raised), _render_viz must NOT call the
    expensive _render_default_viz — that fallback is only for composites that
    declare no visualizations at all."""
    monkeypatch.setattr(run_runner, "_render_canonical_viz", lambda **kw: {})
    monkeypatch.setattr(run_runner, "_spec_declares_canonical_viz", lambda spec_id: True)

    called = {"default": False}

    def _boom(**kw):
        called["default"] = True
        return {"observables_over_time": "<div>FIG</div>"}

    monkeypatch.setattr(run_runner, "_render_default_viz", _boom)

    with tempfile.TemporaryDirectory() as d:
        run_runner._render_viz(
            composite=None, run_dir=Path(d),
            spec_id="ecoli_baseline", db_file="db", run_id="r", core=object(),
        )
        viz = json.loads((Path(d) / "viz.json").read_text())

    assert called["default"] is False, "default fallback ran despite declared canonical viz"
    assert viz == {}, f"expected empty viz.json, got {viz}"


def test_default_fallback_still_runs_when_no_canonical(monkeypatch):
    """The default fallback is preserved for composites that declare no viz."""
    monkeypatch.setattr(run_runner, "_render_canonical_viz", lambda **kw: {})
    monkeypatch.setattr(run_runner, "_spec_declares_canonical_viz", lambda spec_id: False)
    monkeypatch.setattr(
        run_runner, "_render_default_viz",
        lambda **kw: {"observables_over_time": "<div>FIG</div>"},
    )
    with tempfile.TemporaryDirectory() as d:
        run_runner._render_viz(
            composite=None, run_dir=Path(d),
            spec_id="simple", db_file="db", run_id="r", core=object(),
        )
        viz = json.loads((Path(d) / "viz.json").read_text())
    assert "observables_over_time" in viz


# --------------------------------------------------------------------------
# layer 3 — gather_emitter_outputs must scope to one run and bound blob size
# --------------------------------------------------------------------------
def _make_db(tmp: Path, *, big_run: bool = True) -> Path:
    db = tmp / "runs.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE runs_meta (run_id TEXT PRIMARY KEY, spec_id TEXT, "
        "sim_name TEXT, label TEXT, params_json TEXT, started_at REAL, "
        "completed_at REAL, n_steps INTEGER, status TEXT)")
    conn.execute("CREATE TABLE history (simulation_id TEXT, step INTEGER, "
                 "global_time REAL, state TEXT)")
    # run r1 — small blobs
    conn.execute("INSERT INTO runs_meta VALUES (?,?,?,?,?,?,?,?,?)",
                 ("r1", "spec", "one", "one", "{}", 0.0, 1.0, 3, "completed"))
    for i in range(3):
        conn.execute("INSERT INTO history VALUES (?,?,?,?)",
                     ("r1", i, float(i), json.dumps({"level": float(i + 1)})))
    # run r2 — a whole-cell-scale blob (large bulk array) per row
    conn.execute("INSERT INTO runs_meta VALUES (?,?,?,?,?,?,?,?,?)",
                 ("r2", "spec", "two", "two", "{}", 0.0, 1.0, 3, "completed"))
    big = {"bulk": list(range(20000))} if big_run else {"level": 1.0}
    for i in range(3):
        conn.execute("INSERT INTO history VALUES (?,?,?,?)",
                     ("r2", i, float(i), json.dumps(big)))
    conn.commit()
    conn.close()
    return db


def test_gather_scoped_to_run_id(tmp_path):
    """Passing run_id parses ONLY that run's history — not every run in the db
    (the workspace composite-runs.db accumulates many CE runs; #784)."""
    db = _make_db(tmp_path)
    out = gather_emitter_outputs(db, run_id="r1")
    sims = out["by_sim"]
    assert set(sims) == {"one"}, f"expected only run r1's sim, got {list(sims)}"
    assert sims["one"][0]["run_id"] == "r1"


def test_gather_unscoped_still_returns_all_runs(tmp_path):
    """Backward-compat: no run_id → every run present (canonical behavior)."""
    db = _make_db(tmp_path, big_run=False)
    out = gather_emitter_outputs(db)
    assert set(out["by_sim"]) == {"one", "two"}


def test_gather_skips_oversized_blobs(tmp_path):
    """max_state_bytes skips whole-cell-scale rows instead of json.loads()'ing
    them into an unbounded observable set — the actual #784 hang."""
    db = _make_db(tmp_path)
    out = gather_emitter_outputs(db, run_id="r2", max_state_bytes=1024)
    run = out["by_sim"]["two"][0]
    # the giant "bulk" blob was skipped, so no bulk observable was gathered
    assert "bulk" not in run["observables"], "oversized blob was not skipped"


def test_gather_keeps_small_blobs_under_cap(tmp_path):
    """A run whose blobs are under the cap is gathered normally even with the
    cap set (only oversized rows are dropped)."""
    db = _make_db(tmp_path)
    out = gather_emitter_outputs(db, run_id="r1", max_state_bytes=1024)
    run = out["by_sim"]["one"][0]
    assert run["observables"]["level"] == [1.0, 2.0, 3.0]
