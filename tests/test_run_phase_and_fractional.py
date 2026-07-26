"""Fractional run durations + run-phase sub-status.

Covers the temporal-composite duration going float (broker `_drive` advances a
final partial tick) and the run "phase" the detached executor writes so the UI
can announce simulate → rendering visualizations → analysis flush.
"""

from vivarium_workbench.lib import composite_runs as cr
from vivarium_workbench.lib.composite_runs import connect, save_metadata, set_phase, query_run_meta
from vivarium_workbench.lib.emitters import _drive


class _RecordingComposite:
    """Minimal composite stub that records each run() interval."""

    def __init__(self):
        self.calls = []
        self.state = {}

    def run(self, n):
        self.calls.append(n)


def test_drive_whole_duration_runs_unit_ticks():
    c = _RecordingComposite()
    _drive(c, 3, None)
    assert c.calls == [1, 1, 1]


def test_drive_fractional_duration_adds_partial_final_tick():
    c = _RecordingComposite()
    _drive(c, 3.5, None)
    assert c.calls == [1, 1, 1, 0.5]


def test_drive_sub_unit_duration_runs_only_the_fraction():
    c = _RecordingComposite()
    _drive(c, 0.25, None)
    assert c.calls == [0.25]


def test_drive_reports_progress_only_for_whole_ticks():
    c = _RecordingComposite()
    seen = []
    _drive(c, 2.5, lambda step: seen.append(step))
    assert seen == [1, 2]  # the fractional remainder does not emit a progress tick


def _mkdb(tmp_path):
    db = tmp_path / "composite-runs.db"
    conn = connect(str(db))
    save_metadata(conn, spec_id="pkg.composites.demo", run_id="r1", params={},
                  label="", started_at=0.0, n_steps=2.5)
    return conn


def test_set_phase_roundtrips_through_query(tmp_path):
    conn = _mkdb(tmp_path)
    assert query_run_meta(conn, run_id="r1")["phase"] is None
    set_phase(conn, run_id="r1", phase="analysis flush")
    assert query_run_meta(conn, run_id="r1")["phase"] == "analysis flush"


def test_fractional_n_steps_persists(tmp_path):
    conn = _mkdb(tmp_path)
    assert query_run_meta(conn, run_id="r1")["n_steps"] == 2.5


def test_status_view_exposes_phase_only_while_running(tmp_path):
    # phase surfaces while running; a terminal run reports phase=None.
    conn = _mkdb(tmp_path)
    set_phase(conn, run_id="r1", phase="analysis flush")
    meta = query_run_meta(conn, run_id="r1")
    # Mirror build_composite_run_status's phase gate without a full workspace:
    running_phase = meta.get("phase") if meta["status"] == "running" else None
    assert running_phase == "analysis flush"
    cr.complete_metadata(conn, run_id="r1", n_steps=2.5, status="completed")
    meta2 = query_run_meta(conn, run_id="r1")
    terminal_phase = meta2.get("phase") if meta2["status"] == "running" else None
    assert terminal_phase is None
