"""result_fingerprint — sha256 over a run's DECLARED fields only
(reproducible-rerun-spine Task 3 / G4).

``write_outputs`` is a tiny test-local stand-in for what
``run_runner.execute``'s completion tail does for real: persist the run's
canonical output snapshot (``observables.json``) under its run directory.
"""
import json

import pytest

from vivarium_workbench.lib.result_fingerprint import (
    fingerprint_run, write_snapshot, SNAPSHOT_FILENAME,
)


@pytest.fixture
def tmp_run_dir(tmp_path):
    return tmp_path


def write_outputs(run_dir, **fields):
    """Write a flat {field: value} snapshot directly (bypassing write_snapshot's
    state-tree walk) — the shape fingerprint_run reads regardless of how it
    was produced."""
    (run_dir / SNAPSHOT_FILENAME).write_text(json.dumps(fields), encoding="utf-8")


def test_fingerprint_ignores_volatile_matches_on_declared(tmp_run_dir):
    write_outputs(tmp_run_dir, doubling_time=42.0, ran_at="2026-01-01T00:00Z")
    fp1 = fingerprint_run(tmp_run_dir, ["doubling_time"])
    write_outputs(tmp_run_dir, doubling_time=42.0, ran_at="2026-02-02T00:00Z")  # volatile changed
    assert fingerprint_run(tmp_run_dir, ["doubling_time"]) == fp1               # same declared → same fp


def test_fingerprint_changes_when_declared_value_changes(tmp_run_dir):
    write_outputs(tmp_run_dir, doubling_time=42.0)
    fp1 = fingerprint_run(tmp_run_dir, ["doubling_time"])
    write_outputs(tmp_run_dir, doubling_time=43.0)
    fp2 = fingerprint_run(tmp_run_dir, ["doubling_time"])
    assert fp1 != fp2


def test_fingerprint_missing_declared_field_hashes_as_null(tmp_run_dir):
    # A field never present in the output is recorded as an explicit null,
    # not skipped — two runs that both lack it still compare equal on it...
    write_outputs(tmp_run_dir, doubling_time=42.0)
    fp_missing = fingerprint_run(tmp_run_dir, ["doubling_time", "not_emitted"])
    # ...but a run that DOES declare and emit the field hashes differently.
    write_outputs(tmp_run_dir, doubling_time=42.0, not_emitted=1.0)
    fp_present = fingerprint_run(tmp_run_dir, ["doubling_time", "not_emitted"])
    assert fp_missing != fp_present


def test_fingerprint_is_a_hex_sha256(tmp_run_dir):
    write_outputs(tmp_run_dir, doubling_time=42.0)
    fp = fingerprint_run(tmp_run_dir, ["doubling_time"])
    assert isinstance(fp, str) and len(fp) == 64
    int(fp, 16)  # raises ValueError if not valid hex


def test_fingerprint_no_snapshot_file_is_deterministic_all_null(tmp_run_dir):
    # No observables.json at all (e.g. write_snapshot failed) still yields a
    # stable digest rather than raising.
    fp1 = fingerprint_run(tmp_run_dir, ["doubling_time"])
    fp2 = fingerprint_run(tmp_run_dir, ["doubling_time"])
    assert fp1 == fp2


def test_fingerprint_field_order_does_not_matter(tmp_run_dir):
    write_outputs(tmp_run_dir, a=1.0, b=2.0)
    assert fingerprint_run(tmp_run_dir, ["a", "b"]) == fingerprint_run(tmp_run_dir, ["b", "a"])


def test_fingerprint_rounds_float_noise(tmp_run_dir):
    write_outputs(tmp_run_dir, x=1.0000000001)
    fp1 = fingerprint_run(tmp_run_dir, ["x"])
    write_outputs(tmp_run_dir, x=1.0000000002)
    fp2 = fingerprint_run(tmp_run_dir, ["x"])
    assert fp1 == fp2  # both round to 1.0 at the fixed precision


# --- write_snapshot: the real WRITE side (state-tree walk) -----------------

def test_write_snapshot_resolves_declared_paths_from_state(tmp_path):
    state = {"listeners": {"mass": {"dry_mass": 350.5}}, "time": 10}
    ok = write_snapshot(tmp_path, state, ["listeners/mass/dry_mass"])
    assert ok is True
    fp = fingerprint_run(tmp_path, ["listeners/mass/dry_mass"])
    # round-trips: re-snapshotting the identical state gives the identical fp
    write_snapshot(tmp_path, state, ["listeners/mass/dry_mass"])
    assert fingerprint_run(tmp_path, ["listeners/mass/dry_mass"]) == fp


def test_write_snapshot_agents_0_fallback(tmp_path):
    # v2ecoli single-cell composites nest biology under agents/0/ — a field
    # declared at the bare path must still resolve (mirrors
    # composite_runs.collect_emit_paths_from_spec's own agents/0/ retry).
    state = {"agents": {"0": {"listeners": {"mass": {"dry_mass": 400.0}}}}}
    write_snapshot(tmp_path, state, ["listeners/mass/dry_mass"])
    data = json.loads((tmp_path / SNAPSHOT_FILENAME).read_text())
    assert data["listeners/mass/dry_mass"] == 400.0


def test_write_snapshot_missing_path_is_null_not_a_crash(tmp_path):
    ok = write_snapshot(tmp_path, {"time": 1}, ["nonexistent/path"])
    assert ok is True
    data = json.loads((tmp_path / SNAPSHOT_FILENAME).read_text())
    assert data["nonexistent/path"] is None


def test_write_snapshot_never_raises_on_bad_run_dir(tmp_path):
    # A non-existent parent that can't be created (file where a dir is
    # expected) must degrade to False, not raise.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    assert write_snapshot(blocker / "child", {"a": 1}, ["a"]) is False
