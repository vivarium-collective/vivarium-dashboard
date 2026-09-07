"""Composite-auto-results Task 8: GovCloud composite deployment runs inject
declared analyses at dispatch, same as the study path.

Before this task, ``run_runner._execute_remote`` (the composite deployment
branch) called ``remote_run.run_remote`` with no ``analysis_options`` at all —
every remote composite run's server-side analyses came out empty regardless of
what the composite or the run config declared. This mirrors the fix already
shipped for the study path (``remote_run_views.py``'s ``build_analysis_options``
call feeding ``client.run_simulation(..., analysis_options=...)``).

Hermetic: no real sms-api, no real composite build. ``_execute_remote`` is
exercised directly (as ``test_composite_test_run_remote_build.py`` already
does for the overrides-forwarding regression), with ``composite_runs.connect``/
``complete_metadata`` and ``remote_run.run_remote`` stubbed, and the analyses
machinery (``composite_flush``/``study_run_post``) monkeypatched at the module
boundary so no real v2ecoli / process-bigraph registry is needed.
"""
from __future__ import annotations

from vivarium_workbench.lib import run_runner
from vivarium_workbench.lib import remote_run
from vivarium_workbench.lib import composite_flush
from vivarium_workbench.lib import study_run_post
from vivarium_workbench.lib import composite_runs as cr


class _Conn:
    def close(self):
        pass


def _req(tmp_path, *, declared_results=None):
    return run_runner.RunRequest(
        run_id="r1", spec_id="pkg.composites.demo", pkg="pkg", workspace=tmp_path,
        overrides={}, steps=3, emit_paths=[], db_file=str(tmp_path / "runs.db"),
        log_path="run.log", target="deployment",
        declared_results=declared_results,
    )


def _stub_run_lifecycle(monkeypatch):
    """Stub the db-connection/metadata bookkeeping _execute_remote touches so
    only the run_remote() call itself is under test."""
    monkeypatch.setattr(cr, "connect", lambda db: _Conn())
    monkeypatch.setattr(cr, "complete_metadata", lambda *a, **k: None)


def test_composite_remote_injects_analysis_options_when_declared(tmp_path, monkeypatch):
    """A composite run with declared analyses + auto_results True → the
    resolved analysis_options reaches remote_run.run_remote's call, grouped by
    v2ecoli scale exactly as build_analysis_options returns it."""
    _stub_run_lifecycle(monkeypatch)
    monkeypatch.setattr(composite_flush, "_auto_results_enabled", lambda run_dir: True)
    monkeypatch.setattr(composite_flush, "_composite_analyses", lambda spec_id, core: [])

    captured = {}

    def _fake_build_analysis_options(entries, ws_root):
        assert entries == [{"name": "ptools_rxns_multigeneration"}]
        return {"multigeneration": {"ptools_rxns_multigeneration": {}}}, []

    monkeypatch.setattr(study_run_post, "build_analysis_options", _fake_build_analysis_options)

    def _fake_run_remote(ws, spec_id, *, dest, n_steps, overrides, analysis_options=None):
        captured["analysis_options"] = analysis_options

    monkeypatch.setattr(remote_run, "run_remote", _fake_run_remote)

    req = _req(tmp_path, declared_results={
        "analyses": [{"name": "ptools_rxns_multigeneration"}], "visualizations": [],
    })
    rc = run_runner._execute_remote(req, tmp_path)

    assert rc == 0
    assert "multigeneration" in captured["analysis_options"]
    assert captured["analysis_options"]["multigeneration"] == {
        "ptools_rxns_multigeneration": {}
    }


def test_composite_remote_merges_composite_defaults_with_config_declared(tmp_path, monkeypatch):
    """Composite-declared defaults and config-declared analyses both flow into
    the merged entries handed to build_analysis_options (config wins by name,
    per ephemeral_study.merge_declarations — exercised here via distinct names
    so both must appear)."""
    _stub_run_lifecycle(monkeypatch)
    monkeypatch.setattr(composite_flush, "_auto_results_enabled", lambda run_dir: True)
    monkeypatch.setattr(
        composite_flush, "_composite_analyses",
        lambda spec_id, core: [{"name": "mass_fraction_summary"}],
    )

    seen_entries = {}

    def _fake_build_analysis_options(entries, ws_root):
        seen_entries["names"] = sorted(e["name"] for e in entries)
        return {"single": {"mass_fraction_summary": {}},
                "multigeneration": {"selected_fluxes": {}}}, []

    monkeypatch.setattr(study_run_post, "build_analysis_options", _fake_build_analysis_options)

    captured = {}

    def _fake_run_remote(ws, spec_id, *, dest, n_steps, overrides, analysis_options=None):
        captured["analysis_options"] = analysis_options

    monkeypatch.setattr(remote_run, "run_remote", _fake_run_remote)

    req = _req(tmp_path, declared_results={
        "analyses": [{"name": "selected_fluxes"}], "visualizations": [],
    })
    rc = run_runner._execute_remote(req, tmp_path)

    assert rc == 0
    assert seen_entries["names"] == ["mass_fraction_summary", "selected_fluxes"]
    assert captured["analysis_options"] == {
        "single": {"mass_fraction_summary": {}},
        "multigeneration": {"selected_fluxes": {}},
    }


def test_composite_remote_injects_nothing_when_auto_results_disabled(tmp_path, monkeypatch):
    """auto_results False → no analysis_options is injected, even though
    declared_results carries analyses (today's un-fixed behavior for that
    workspace setting)."""
    _stub_run_lifecycle(monkeypatch)
    monkeypatch.setattr(composite_flush, "_auto_results_enabled", lambda run_dir: False)

    def _boom_build_analysis_options(entries, ws_root):
        raise AssertionError("build_analysis_options must not be called when auto_results is False")

    monkeypatch.setattr(study_run_post, "build_analysis_options", _boom_build_analysis_options)

    captured = {"called_with_analysis_options": False}

    def _fake_run_remote(ws, spec_id, *, dest, n_steps, overrides, analysis_options=None):
        captured["called_with_analysis_options"] = analysis_options is not None

    monkeypatch.setattr(remote_run, "run_remote", _fake_run_remote)

    req = _req(tmp_path, declared_results={
        "analyses": [{"name": "ptools_rxns_multigeneration"}], "visualizations": [],
    })
    rc = run_runner._execute_remote(req, tmp_path)

    assert rc == 0
    assert captured["called_with_analysis_options"] is False


def test_composite_remote_calls_run_remote_without_analysis_options_kwarg_when_nothing_declared(
    tmp_path, monkeypatch
):
    """No composite defaults and no req.declared_results → run_remote is called
    exactly like a pre-Task-8 caller (no analysis_options kwarg at all), so a
    test double / caller built against the 3-kwarg (dest/n_steps/overrides)
    signature still works unchanged."""
    _stub_run_lifecycle(monkeypatch)
    monkeypatch.setattr(composite_flush, "_auto_results_enabled", lambda run_dir: True)
    monkeypatch.setattr(composite_flush, "_composite_analyses", lambda spec_id, core: [])

    def _fake_run_remote(ws, spec_id, *, dest, n_steps, overrides):
        # No analysis_options param here at all -- a TypeError below means
        # _execute_remote passed a kwarg this pre-Task-8-shaped caller lacks.
        return None

    monkeypatch.setattr(remote_run, "run_remote", _fake_run_remote)

    req = _req(tmp_path, declared_results={"analyses": [], "visualizations": []})
    rc = run_runner._execute_remote(req, tmp_path)

    assert rc == 0
