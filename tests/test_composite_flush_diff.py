"""Slice 3 Task 1: cross-iteration test_diff.json in the engine flush.

`run_flush` writes `run_dir/test_diff.json = viva_superpowers.diff_reports
(prev_cards, curr_cards)` against the PRIOR run's `run_dir` (there is no
`history/` in the workbench — study-level `viz/report_card/*.verdict.json`
files are overwritten each run). Best-effort: a first run / missing prev
run_dir yields an all-"new" diff rather than raising.
"""
import json
import sqlite3
import types
from pathlib import Path

from vivarium_workbench.lib.composite_flush import _write_test_diff


def _card(overall, group, axis_id, verdict, margin):
    return {
        "overall": overall,
        "groups": {group: {"axes": [
            {"id": axis_id, "verdict": verdict, "margin": margin},
        ]}},
    }


def _wc(p: Path, doc: dict):
    p.write_text(json.dumps(doc), encoding="utf-8")


# --- Task 1 Step 1: the pure, testable helper -------------------------------

def test_write_test_diff_fixed_axis(tmp_path):
    prev_run = tmp_path / "run0"
    curr_run = tmp_path / "run1"
    prev_run.mkdir()
    curr_run.mkdir()
    _wc(prev_run / "standard.verdict.json",
        _card("mismatch", "grp1", "ax1", "mismatch", -0.5))
    _wc(curr_run / "standard.verdict.json",
        _card("within_tol", "grp1", "ax1", "within_tol", 0.5))

    ok = _write_test_diff(curr_run, prev_run)
    assert ok is True

    diff = json.loads((curr_run / "test_diff.json").read_text(encoding="utf-8"))
    assert diff["schema"] == "test_diff/v1"
    per = {(r["card"], r["group"], r["id"]): r for r in diff["per"]}
    entry = per[("standard", "grp1", "ax1")]
    assert entry["change"] == "fixed"
    assert entry["prev"] == "mismatch"
    assert entry["curr"] == "within_tol"


def test_write_test_diff_no_prev_run_is_all_new(tmp_path):
    curr_run = tmp_path / "run1"
    curr_run.mkdir()
    _wc(curr_run / "standard.verdict.json",
        _card("within_tol", "grp1", "ax1", "within_tol", 0.5))

    ok = _write_test_diff(curr_run, None)
    assert ok is True
    diff = json.loads((curr_run / "test_diff.json").read_text(encoding="utf-8"))
    assert diff["per"][0]["change"] == "new"


def test_write_test_diff_missing_prev_dir_is_all_new(tmp_path):
    curr_run = tmp_path / "run1"
    curr_run.mkdir()
    _wc(curr_run / "standard.verdict.json",
        _card("within_tol", "grp1", "ax1", "within_tol", 0.5))

    ok = _write_test_diff(curr_run, tmp_path / "no-such-run")
    assert ok is True
    diff = json.loads((curr_run / "test_diff.json").read_text(encoding="utf-8"))
    assert diff["per"][0]["change"] == "new"


def test_write_test_diff_best_effort_never_raises(tmp_path, monkeypatch):
    curr_run = tmp_path / "run1"
    curr_run.mkdir()

    def _boom(prev, curr):
        raise RuntimeError("boom")

    ok = _write_test_diff(curr_run, None, diff_fn=_boom)
    assert ok is False
    assert not (curr_run / "test_diff.json").exists()


def test_write_test_diff_rejects_nan(tmp_path):
    """F2 hardening: allow_nan=False on the diff write, matching the repo
    convention (_write_json / verdict writes). A diff_fn that (incorrectly)
    produces a NaN margin_delta must raise a ValueError from json.dumps
    rather than silently writing invalid JSON a browser's JSON.parse would
    reject."""
    curr_run = tmp_path / "run1"
    curr_run.mkdir()

    def _nan_diff(prev, curr):
        return {"schema": "test_diff/v1",
                "per": [{"card": "c", "group": "g", "id": "a",
                         "change": "regressed", "margin_delta": float("nan")}],
                "rollup": {}}

    ok = _write_test_diff(curr_run, None, diff_fn=_nan_diff)
    assert ok is False                                # caught, best-effort
    assert not (curr_run / "test_diff.json").exists()  # no partial write


# --- Task 1 Step 4: run_flush integration -----------------------------------

def test_run_flush_writes_test_diff_vs_prev_run(tmp_path, monkeypatch):
    from vivarium_workbench.lib import composite_flush

    ws = tmp_path
    runs_root = ws / ".pbg" / "runs"
    run0 = runs_root / "r0"
    run1 = runs_root / "r1"
    run0.mkdir(parents=True)
    run1.mkdir(parents=True)
    _wc(run0 / "standard.verdict.json",
        _card("mismatch", "grp1", "ax1", "mismatch", -0.5))
    _wc(run1 / "standard.verdict.json",
        _card("within_tol", "grp1", "ax1", "within_tol", 0.5))
    (run1 / "viz.json").write_text(json.dumps({"fig1": {}}), encoding="utf-8")

    db_file = ws / "runs.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        "CREATE TABLE runs_meta (run_id TEXT PRIMARY KEY, started_at REAL, "
        "completed_at REAL)")
    conn.execute("INSERT INTO runs_meta VALUES ('r0', 1.0, 2.0)")
    conn.execute("INSERT INTO runs_meta VALUES ('r1', 3.0, NULL)")
    conn.commit()
    conn.close()

    def _fake_dispatch(**kwargs):
        return [{"name": "cards", "written": [
            str(run1 / "standard.verdict.json"),
        ], "errors": []}]

    monkeypatch.setattr(composite_flush, "_dispatch_analyses", _fake_dispatch)
    req = types.SimpleNamespace(steps=1, spec_id="pkg.mod.name")
    result = composite_flush.run_flush(
        run1, req=req, spec_id="pkg.mod.name",
        db_file=str(db_file), run_id="r1", core=None)

    assert result["has_diff"] is True
    diff = json.loads((run1 / "test_diff.json").read_text(encoding="utf-8"))
    per = {(r["card"], r["group"], r["id"]): r for r in diff["per"]}
    assert per[("standard", "grp1", "ax1")]["change"] == "fixed"


def test_run_flush_finds_prev_run_under_nonstandard_runs_root(tmp_path, monkeypatch):
    """F1 hardening: prev-run resolution must be layout-agnostic — derived from
    run_dir.parent (the CURRENT run's own runs-root), not a hardcoded
    <ws>/.pbg/runs/... reconstruction via parents[2]. A workspace with a
    layout:-remapped runs root (here a made-up "custom_runs_root" two levels
    up from ws_root, so a parents[2]-based ".pbg"/"runs" guess would land on a
    directory that doesn't exist) must still find the prev run and produce a
    real change, not silently fall back to an all-"new" diff.
    """
    from vivarium_workbench.lib import composite_flush

    ws = tmp_path
    runs_root = ws / "some" / "custom_runs_root"   # NOT .pbg/runs
    run0 = runs_root / "r0"
    run1 = runs_root / "r1"
    run0.mkdir(parents=True)
    run1.mkdir(parents=True)
    _wc(run0 / "standard.verdict.json",
        _card("mismatch", "grp1", "ax1", "mismatch", -0.5))
    _wc(run1 / "standard.verdict.json",
        _card("within_tol", "grp1", "ax1", "within_tol", 0.9))
    (run1 / "viz.json").write_text(json.dumps({"fig1": {}}), encoding="utf-8")

    db_file = ws / "runs.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        "CREATE TABLE runs_meta (run_id TEXT PRIMARY KEY, started_at REAL, "
        "completed_at REAL)")
    conn.execute("INSERT INTO runs_meta VALUES ('r0', 1.0, 2.0)")
    conn.execute("INSERT INTO runs_meta VALUES ('r1', 3.0, NULL)")
    conn.commit()
    conn.close()

    def _fake_dispatch(**kwargs):
        return [{"name": "cards", "written": [
            str(run1 / "standard.verdict.json"),
        ], "errors": []}]

    monkeypatch.setattr(composite_flush, "_dispatch_analyses", _fake_dispatch)
    req = types.SimpleNamespace(steps=1, spec_id="pkg.mod.name")
    result = composite_flush.run_flush(
        run1, req=req, spec_id="pkg.mod.name",
        db_file=str(db_file), run_id="r1", core=None)

    assert result["has_diff"] is True
    diff = json.loads((run1 / "test_diff.json").read_text(encoding="utf-8"))
    per = {(r["card"], r["group"], r["id"]): r for r in diff["per"]}
    # The point: a real "fixed" (mismatch -> within_tol) change was found —
    # if prev-run resolution had silently missed (the old parents[2]/".pbg"/
    # "runs" bug under this non-standard layout), every axis would diff as
    # "new" instead.
    assert per[("standard", "grp1", "ax1")]["change"] == "fixed"


def test_run_flush_first_run_no_db_skips_diff_cleanly(tmp_path, monkeypatch):
    from vivarium_workbench.lib import composite_flush

    run0 = tmp_path
    _wc(run0 / "standard.verdict.json",
        _card("within_tol", "grp1", "ax1", "within_tol", 0.5))
    (run0 / "viz.json").write_text(json.dumps({"fig1": {}}), encoding="utf-8")

    def _fake_dispatch(**kwargs):
        return [{"name": "cards", "written": [
            str(run0 / "standard.verdict.json"),
        ], "errors": []}]

    monkeypatch.setattr(composite_flush, "_dispatch_analyses", _fake_dispatch)
    req = types.SimpleNamespace(steps=1, spec_id="pkg.mod.name")
    result = composite_flush.run_flush(
        run0, req=req, spec_id="pkg.mod.name",
        db_file=str(tmp_path / "no-such-runs.db"), run_id="r0", core=None)

    assert result["has_diff"] is True   # no prev -> all-new diff, still written
    diff = json.loads((run0 / "test_diff.json").read_text(encoding="utf-8"))
    assert diff["per"][0]["change"] == "new"
