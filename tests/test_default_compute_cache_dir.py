"""`_default_compute` cache_dir wiring (Phase 2, sim_data reproducibility).

The unit resolver tests inject a stub ``compute_fn``, so the real-engine adapter
``_default_compute`` — which wires a producer's/consumer's ``sim_data`` cache
bundle to/from the content-addressed store — is never exercised there. These
tests mock the run subsystem (``run_core.invoke_run`` / ``run_runner.execute``)
and assert the run-request ``overrides["cache_dir"]`` is wired correctly:

- **Producer** (a study declaring ``outputs: [sim_data]``): its run must write
  the ParCa bundle INTO the artifact-store scratch dir (``out_dir``), so the
  stored artifact IS the bundle a downstream ``cache_dir`` consumer reads.
- **Consumer** (a study declaring ``inputs: [{artifact: sim_data, ...}]``): its
  run's ``cache_dir`` must point at the producer's resolved store path.
"""
from __future__ import annotations

import json
import subprocess
import types

import yaml

from vivarium_workbench.lib import run_core
from vivarium_workbench.lib.artifacts.pipeline import _default_compute


def _write_study(ws, slug, data):
    p = ws / "studies" / slug / "study.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"name": slug, **data}), encoding="utf-8")


def _patch_run(monkeypatch):
    """Stub invoke_run (returns a plan) + the run subprocess (success no-op).
    The request is written before the subprocess spawns, so it is read back
    from out_dir/request.json to assert the wiring."""
    def fake_invoke_run(ws_root, *, spec_id, config, db_path):
        return types.SimpleNamespace(run_id="r1", spec_id=spec_id, target="ecoli")
    monkeypatch.setattr(run_core, "invoke_run", fake_invoke_run)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: types.SimpleNamespace(returncode=0),
    )


def _overrides_from(out_dir):
    return json.loads((out_dir / "request.json").read_text())["overrides"]


def test_producer_redirects_cache_dir_into_store(tmp_path, monkeypatch):
    _patch_run(monkeypatch)
    _write_study(tmp_path, "parca", {
        "composite": "parca", "config": {"cache_dir": "out/cache"},
        "outputs": ["sim_data"],
    })
    out_dir = tmp_path / "scratch-parca"
    out_dir.mkdir()
    _default_compute(
        tmp_path, "parca", artifact_id="oid1", composite="parca",
        config={"cache_dir": "out/cache"}, input_ids=[], out_dir=out_dir,
        resolved_inputs=None,
    )
    # The producer's bundle is redirected into the store scratch dir, NOT the
    # study's declared out/cache path — so store.put captures the bundle.
    assert _overrides_from(out_dir)["cache_dir"] == str(out_dir)


def test_consumer_reads_cache_dir_from_producer_store(tmp_path, monkeypatch):
    _patch_run(monkeypatch)
    _write_study(tmp_path, "baseline", {
        "composite": "ecoli_baseline", "config": {"seed": 0, "cache_dir": "out/cache"},
        "inputs": [{"artifact": "sim_data", "from": "parca"}],
        "outputs": ["run_zarr"],
    })
    out_dir = tmp_path / "scratch-baseline"
    out_dir.mkdir()
    producer_store = "/tmp/store/oidP"
    _default_compute(
        tmp_path, "baseline", artifact_id="oid2", composite="ecoli_baseline",
        config={"seed": 0, "cache_dir": "out/cache"}, input_ids=["oidP"],
        out_dir=out_dir, resolved_inputs={"sim_data": producer_store},
    )
    ov = _overrides_from(out_dir)
    assert ov["cache_dir"] == producer_store
    assert ov["sim_data_path"] == producer_store


def test_failed_run_raises_and_is_not_cached(tmp_path, monkeypatch):
    """A nonzero run exit MUST raise so resolve_study never store.puts (caches)
    a failed/empty run — the cache-poisoning bug the real-data proof exposed."""
    import pytest

    def fake_invoke_run(ws_root, *, spec_id, config, db_path):
        return types.SimpleNamespace(run_id="r1", spec_id=spec_id, target="ecoli")
    monkeypatch.setattr(run_core, "invoke_run", fake_invoke_run)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=1))
    _write_study(tmp_path, "parca", {
        "composite": "parca", "config": {}, "outputs": ["sim_data"]})
    out_dir = tmp_path / "scratch-fail"
    out_dir.mkdir()
    with pytest.raises(RuntimeError):
        _default_compute(
            tmp_path, "parca", artifact_id="oidF", composite="parca",
            config={}, input_ids=[], out_dir=out_dir, resolved_inputs=None,
        )


def test_produce_command_runs_with_artifact_dir(tmp_path, monkeypatch):
    """A study declaring produce.command runs THAT (not the composite runner),
    with $ARTIFACT_DIR = the store scratch dir, and captures out_dir."""
    captured = {}

    def fake_run(cmd, *, cwd, env, stdout, stderr):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["artifact_dir"] = env.get("ARTIFACT_DIR")
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    _write_study(tmp_path, "parca", {
        "composite": "parca", "config": {"mode": "full"}, "outputs": ["sim_data"],
        "produce": {"command": 'build_cache --cache "$ARTIFACT_DIR"'},
    })
    out_dir = tmp_path / "scratch-prod"
    out_dir.mkdir()
    result = _default_compute(
        tmp_path, "parca", artifact_id="oidP", composite="parca",
        config={"mode": "full"}, input_ids=[], out_dir=out_dir, resolved_inputs=None,
    )
    assert result == out_dir
    assert captured["artifact_dir"] == str(out_dir)
    assert captured["cwd"] == str(tmp_path)
    assert captured["cmd"][0] == "bash"


def test_produce_command_failure_raises(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=2))
    _write_study(tmp_path, "parca", {
        "composite": "parca", "config": {}, "outputs": ["sim_data"],
        "produce": {"command": "false"},
    })
    out_dir = tmp_path / "scratch-pf"
    out_dir.mkdir()
    with pytest.raises(RuntimeError):
        _default_compute(
            tmp_path, "parca", artifact_id="oid", composite="parca",
            config={}, input_ids=[], out_dir=out_dir, resolved_inputs=None,
        )
