"""Study-origin runs get a result_fingerprint too (reproducible-rerun-spine
Task 3 / G4, fix round 1).

``composite_subprocess.run_composite_subprocess`` (invoked by
``study_runs._launch_run_and_flush`` for study baseline/variant/rerun
launches) is a SEPARATE completion path from ``run_runner.execute``
(composite-origin runs only) — the two don't share code. Task 3 originally
only wired ``result_fingerprint`` computation into ``run_runner.execute``,
so every study-origin run's ``result_fingerprint`` stayed permanently NULL.

This is a REAL end-to-end run — ``subprocess.run`` is NOT mocked here,
unlike ``test_composite_subprocess_lib.py`` — because the fix's core piece
(the child script snapshotting ``composite.state``) only actually executes
inside that real subprocess; a canned/mocked stdout can't exercise it.
Mirrors ``test_run_runner.py::test_execute_completes_and_persists_trajectory``'s
own use of a real run against the ``ws_increase_demo`` fixture, just through
the study-side engine instead.
"""
import shutil
import sys
from pathlib import Path

from vivarium_workbench.lib import composite_runs as cr
from vivarium_workbench.lib import composite_subprocess as cs

FIXTURE_WS = Path(__file__).parent / "_fixtures" / "ws_increase_demo"

# Real, runnable composite state (same shape as the fixture's
# increase-demo.composite.yaml, hand-built here rather than loaded from the
# generator registry). spec_id is deliberately NOT a registered
# @composite_generator id, so run_composite_subprocess takes its LEGACY
# (state-serialization) branch — study-origin runs normally take the
# generator branch instead, but both branches share the exact completion
# tail this fix touches (the shared child-script tail + the parent's
# post-subprocess success block), so exercising either proves the fix.
_STATE = {
    "increase": {
        "_type": "process", "address": "local:IncreaseProcess",
        "config": {"rate": 2.0},
        "inputs": {"level": ["stores", "level"]},
        "outputs": {"level": ["stores", "level"]},
        "interval": 1.0,
    },
    "stores": {"level": 1.0},
}


def _make_study_ws(tmp_path):
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE_WS, ws)
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    return ws


def test_study_origin_run_gets_result_fingerprint(tmp_path):
    ws = _make_study_ws(tmp_path)
    db_file = ws / "workspace" / "studies" / "s1" / "runs.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    run_id = "study-fp-check-1"

    manifest = cr.build_run_manifest(
        origin="study", study="s1", spec_id="test.legacy.increase",
        params={}, n_steps=3, emitter=None, emit_paths=["stores/level"],
        runtime={}, fingerprint_fields=["stores/level"],
    )

    resp, code = cs.run_composite_subprocess(
        ws, pkg="pbg_ws_increase_demo", state=_STATE, steps=3,
        db_file=str(db_file), run_id=run_id, spec_id="test.legacy.increase",
        emit_paths=["stores/level"], label="baseline", manifest=manifest,
    )

    assert code == 200
    conn = cr.connect(db_file)
    row = cr.query_run_meta(conn, run_id=run_id)
    conn.close()
    assert row["status"] == "completed"
    # The core assertion this fix is for: NOT null, and a real sha256 hex digest.
    assert row["result_fingerprint"] is not None
    assert len(row["result_fingerprint"]) == 64
    int(row["result_fingerprint"], 16)  # raises ValueError if not valid hex

    # The child's snapshot round-trips to the value the composite actually
    # produced (rate=2.0 applied 3 times to initial_level=1.0 -> 8.0... the
    # fixture's IncreaseProcess multiplies by rate each step: 1*2*2*2=8, but
    # what matters for THIS test is only that the declared field resolved to
    # a real number, not that it's null.
    run_dir = ws / ".pbg" / "runs" / run_id
    snapshot = (run_dir / "observables.json")
    assert snapshot.is_file()
    import json
    data = json.loads(snapshot.read_text())
    assert isinstance(data.get("stores/level"), float)


def test_study_origin_run_missing_manifest_falls_back_to_emit_paths(tmp_path):
    # No manifest passed at all (legacy caller) — fingerprint_fields must
    # fall back to emit_paths (mirrors run_runner.execute's own fallback)
    # rather than leaving result_fingerprint unset.
    ws = _make_study_ws(tmp_path)
    db_file = ws / "workspace" / "studies" / "s2" / "runs.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    run_id = "study-fp-check-2"

    resp, code = cs.run_composite_subprocess(
        ws, pkg="pbg_ws_increase_demo", state=_STATE, steps=2,
        db_file=str(db_file), run_id=run_id, spec_id="test.legacy.increase.2",
        emit_paths=["stores/level"], label="baseline",
    )

    assert code == 200
    conn = cr.connect(db_file)
    row = cr.query_run_meta(conn, run_id=run_id)
    conn.close()
    assert row["result_fingerprint"] is not None
    assert len(row["result_fingerprint"]) == 64
