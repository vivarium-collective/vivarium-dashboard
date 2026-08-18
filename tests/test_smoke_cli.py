"""Tests for `vivarium-workbench smoke` (lib/smoke.py — dual-engine spec §5.4).

The hermetic test is a real end-to-end: scaffold → env-worker ping → a real
3-step run through run_runner.execute (asserting the W1 `environments: [primary]`
manifest pin) → server boot + /health + /. It spawns one server subprocess
(~10s), same as the dashboard_client e2e suites.
"""
from pathlib import Path

from vivarium_workbench.lib import smoke


def test_scaffold_is_complete_and_parseable(tmp_path):
    ws = smoke.scaffold_workspace(tmp_path)
    assert (ws / "workspace.yaml").is_file()
    assert (ws / "pbg_smoke" / "core.py").is_file()
    assert (ws / "pbg_smoke" / "composites" / "increase-demo.composite.yaml").is_file()
    ok, detail = smoke._check_workspace(ws)
    assert ok, detail
    assert "pbg_smoke" in detail


def test_hermetic_smoke_passes_end_to_end(capsys):
    rc = smoke.run_smoke(None)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "4/4 checks passed" in out
    # the W1 provenance really was asserted, not skipped
    assert "environments=['primary']" in out


def test_workspace_mode_is_nonmutating_subset(tmp_path, capsys):
    ws = smoke.scaffold_workspace(tmp_path)
    rc = smoke.run_smoke(ws)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "3/3 checks passed" in out
    assert "tiny-run" not in out            # no run against a real workspace
    assert not (ws / ".pbg" / "composite-runs.db").exists()  # nothing written
