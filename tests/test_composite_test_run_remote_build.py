"""SP-D2: remote-build workspace → dispatches to deployment (was SP-A's 409 guard).

A workspace carrying a ``.viv-build.json`` stamp has been materialised from a
remote build; ``run_core.run_target_for`` resolves it to the ``deployment``
target. Under SP-A this returned 409 (deployment execution unbuilt). SP-D2 BUILDS
that path: ``composite_test_run`` now accepts (202) and stamps ``target:
"deployment"`` into the run-request, so the detached runner dispatches to sms-api
``/compose/v1`` instead of running locally.
"""
from __future__ import annotations

import json
from pathlib import Path


def test_composite_test_run_on_remote_build_dispatches(tmp_path, monkeypatch):
    from vivarium_workbench.lib import composite_test_run_views as v
    from vivarium_workbench.lib import run_registry

    (tmp_path / ".pbg").mkdir()
    (tmp_path / "workspace.yaml").write_text("name: remote-ws\n", encoding="utf-8")
    (tmp_path / ".viv-build.json").write_text('{"simulator_id": 66}')

    monkeypatch.setattr(run_registry, "count_running", lambda db_file: 0)
    monkeypatch.setattr(run_registry, "spawn_detached", lambda *a, **k: 4242)

    body, status = v.composite_test_run(
        tmp_path, {"id": "pkg.composites.x", "overrides": {}, "steps": 7})

    assert status == 202
    assert body["status"] == "running"

    # The run-request carries the deployment target so run_runner.execute dispatches remotely.
    run_dir = tmp_path / ".pbg" / "runs" / body["run_id"]
    req = json.loads((run_dir / "request.json").read_text())
    assert req["target"] == "deployment"
    assert req["steps"] == 7


def test_execute_remote_forwards_overrides_to_run_remote(tmp_path, monkeypatch):
    """The remote-dispatch path must apply the run form's parameter overrides —
    previously they were dropped, so a UI Run used the composite DEFAULTS (e.g.
    batch_baseline's 4 cells x 3600s) regardless of what the user set."""
    from vivarium_workbench.lib import run_runner
    from vivarium_workbench.lib import remote_run
    from vivarium_workbench.lib import composite_runs as cr

    req = run_runner.RunRequest(
        run_id="r1", spec_id="pkg.composites.batch", pkg="pkg", workspace=tmp_path,
        overrides={"n_seeds": 1, "max_duration": 60.0}, steps=3, emit_paths=[],
        db_file=str(tmp_path / "runs.db"), log_path="log", target="deployment")

    captured = {}

    def fake_run_remote(ws, spec_id, dest=None, n_steps=1, overrides=None, on_submit=None):
        captured.update(overrides=overrides, spec_id=spec_id, n_steps=n_steps)

    class _Conn:
        def close(self):
            pass

    monkeypatch.setattr(remote_run, "run_remote", fake_run_remote)
    monkeypatch.setattr(cr, "connect", lambda db: _Conn())
    monkeypatch.setattr(cr, "complete_metadata", lambda *a, **k: None)

    rc = run_runner._execute_remote(req, tmp_path)
    assert rc == 0
    assert captured["overrides"] == {"n_seeds": 1, "max_duration": 60.0}
    assert captured["n_steps"] == 3


def test_execute_remote_persists_compose_sim_id(tmp_path, monkeypatch):
    """_execute_remote must persist the compose sim id via on_submit, so the Runs
    tab can enrich the row with live BatchProgress (#183) while the batch runs."""
    from vivarium_workbench.lib import run_runner
    from vivarium_workbench.lib import remote_run
    from vivarium_workbench.lib import composite_runs as cr

    req = run_runner.RunRequest(
        run_id="r1", spec_id="pkg.composites.batch", pkg="pkg", workspace=tmp_path,
        overrides={}, steps=3, emit_paths=[],
        db_file=str(tmp_path / "runs.db"), log_path="log", target="deployment")

    # run_remote reports the sim id via on_submit right after submit.
    def fake_run_remote(ws, spec_id, dest=None, n_steps=1, overrides=None, on_submit=None):
        if on_submit is not None:
            on_submit(999)

    persisted = {}

    class _Conn:
        def close(self):
            pass

    monkeypatch.setattr(remote_run, "run_remote", fake_run_remote)
    monkeypatch.setattr(cr, "connect", lambda db: _Conn())
    monkeypatch.setattr(cr, "complete_metadata", lambda *a, **k: None)
    monkeypatch.setattr(cr, "write_run_remote_sim_id",
                        lambda conn, run_id, sid: persisted.update(run_id=run_id, sim_id=sid))

    rc = run_runner._execute_remote(req, tmp_path)
    assert rc == 0
    assert persisted == {"run_id": "r1", "sim_id": 999}


def test_write_run_remote_sim_id_persists_and_migrates(tmp_path):
    """The remote_sim_id column migrates in and round-trips."""
    from vivarium_workbench.lib import composite_runs as cr

    conn = cr.connect(tmp_path / "composite-runs.db")
    try:
        cr.save_metadata(conn, spec_id="pkg.composites.batch", run_id="r1",
                         params={}, label="batch", started_at=1.0, n_steps=0)
        # Column exists (migrated) and starts NULL.
        row = conn.execute("SELECT remote_sim_id FROM runs_meta WHERE run_id=?", ("r1",)).fetchone()
        assert row["remote_sim_id"] is None
        cr.write_run_remote_sim_id(conn, "r1", 4242)
        row = conn.execute("SELECT remote_sim_id FROM runs_meta WHERE run_id=?", ("r1",)).fetchone()
        assert row["remote_sim_id"] == 4242
    finally:
        conn.close()


def test_run_remote_reports_sim_id_via_on_submit(tmp_path, monkeypatch):
    """run_remote calls on_submit with the compose sim id right after submit —
    the hook _execute_remote uses to persist it before the blocking poll."""
    from vivarium_workbench.lib import remote_run, remote_pinned

    monkeypatch.setattr(remote_run, "export_composite_pbg",
                        lambda ws, cid, path, overrides=None: Path(path).write_bytes(b"x"))
    monkeypatch.setattr(remote_pinned, "pinned_config", lambda: None)
    monkeypatch.setattr(remote_run, "git_pip_url", lambda ws: "git+https://x@sha")
    monkeypatch.setattr(remote_run, "workspace_pinned_deps", lambda ws: [])
    monkeypatch.setattr(remote_run, "_poll_until_terminal", lambda c, sid, pi, pt: ("completed", {}))

    class _Client:
        def compose_submit(self, pbg_bytes, extra_pip_deps=None, interval_time=0.0):
            return 4242

        def download_compose_results(self, sim_id, dest, timeout=None):
            return Path(dest) / "results.zip"

    seen = {}
    remote_run.run_remote(tmp_path, "pkg.composites.x", client=_Client(),
                          dest=tmp_path, n_steps=3,
                          on_submit=lambda sid: seen.update(sim_id=sid))
    assert seen == {"sim_id": 4242}
