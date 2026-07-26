import json
import sqlite3

import pytest
import yaml

from vivarium_workbench.lib.artifacts.pipeline import resolve_study


def make_stub():
    calls = []

    def stub(ws_root, slug, *, artifact_id, composite, config, input_ids, out_dir):
        calls.append(slug)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "out.bin"
        p.write_bytes(b"fake:" + slug.encode())
        return p

    return stub, calls


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "studies" / "parca").mkdir(parents=True)
    (tmp_path / "studies" / "ko").mkdir(parents=True)
    (tmp_path / "studies" / "parca" / "study.yaml").write_text(yaml.safe_dump({
        "name": "parca",
        "composite": "parca_builder",
        "config": {},
        "outputs": ["sim_data"],
    }))
    (tmp_path / "studies" / "ko" / "study.yaml").write_text(yaml.safe_dump({
        "name": "ko",
        "composite": "baseline",
        "config": {"seed": 0},
        "inputs": [{"artifact": "sim_data", "from": "parca"}],
        "outputs": ["run_zarr"],
    }))
    return tmp_path


def _write_ko_config(ws, config):
    (ws / "studies" / "ko" / "study.yaml").write_text(yaml.safe_dump({
        "name": "ko",
        "composite": "baseline",
        "config": config,
        "inputs": [{"artifact": "sim_data", "from": "parca"}],
        "outputs": ["run_zarr"],
    }))


def test_resolves_producer_first_and_computes_once(ws):
    stub, calls = make_stub()
    r = resolve_study(ws, "ko", compute_fn=stub)
    assert calls == ["parca", "ko"]
    assert r["cached"] is False
    assert set(r["inputs"].keys()) == {"parca"}


def test_second_resolve_is_all_store_hits(ws):
    stub, calls = make_stub()
    r = resolve_study(ws, "ko", compute_fn=stub)

    stub2, calls2 = make_stub()
    r2 = resolve_study(ws, "ko", compute_fn=stub2)
    assert calls2 == []
    assert r2["cached"] is True
    assert r2["inputs"]["parca"] == r["inputs"]["parca"]


def test_config_change_reruns_only_that_study(ws):
    stub, calls = make_stub()
    resolve_study(ws, "ko", compute_fn=stub)

    _write_ko_config(ws, {"seed": 1})

    stub3, calls3 = make_stub()
    resolve_study(ws, "ko", compute_fn=stub3)
    assert calls3 == ["ko"]


def test_runs_db_pointer_recorded(ws):
    stub, calls = make_stub()
    r = resolve_study(ws, "ko", compute_fn=stub)

    conn = sqlite3.connect(str(ws / "studies" / "ko" / "runs.db"))
    try:
        row = conn.execute(
            "SELECT stage, artifact_id FROM artifact_pointers WHERE stage = ?",
            ("run_zarr",),
        ).fetchone()
    finally:
        conn.close()
    assert row == ("run_zarr", r["artifact_id"])


def test_producer_output_id_is_stable(ws):
    stub, calls = make_stub()
    r = resolve_study(ws, "ko", compute_fn=stub)

    stub_parca, _ = make_stub()
    r_parca = resolve_study(ws, "parca", compute_fn=stub_parca)
    assert r_parca["artifact_id"] == r["inputs"]["parca"]


def test_resolve_study_detects_cycle(tmp_path, monkeypatch):
    from vivarium_workbench.lib.artifacts import pipeline

    # a -> b -> a
    specs = {
        "a": {"composite": "c.a", "config": {}, "outputs": [],
              "inputs": [{"artifact": "x", "from": "b"}]},
        "b": {"composite": "c.b", "config": {}, "outputs": [],
              "inputs": [{"artifact": "x", "from": "a"}]},
    }
    monkeypatch.setattr(pipeline, "_load_study_spec", lambda ws, slug: specs[slug])
    stub, calls = make_stub()
    with pytest.raises(pipeline.CyclicDependencyError):
        pipeline.resolve_study(tmp_path, "a", compute_fn=stub)


def test_default_compute_populates_emit_paths_from_study_readouts(tmp_path, monkeypatch):
    """Test that _default_compute collects emit_paths from study spec readouts/tests."""
    from collections import namedtuple
    from unittest.mock import MagicMock

    # Create a study with readouts and tests that declare observable paths
    (tmp_path / "studies" / "sim").mkdir(parents=True)
    spec = {
        "name": "sim",
        "composite": "sim_composite",
        "config": {},
        "outputs": ["run_result"],
        "readouts": [
            {"store_path": "growth_rate"}
        ],
        "tests": [
            {"name": "test_division", "measure": {"path": "division/count"}},
        ],
    }
    (tmp_path / "studies" / "sim" / "study.yaml").write_text(
        yaml.safe_dump(spec), encoding="utf-8"
    )

    # Mock run_core.invoke_run to return a minimal plan
    Plan = namedtuple("Plan", ["run_id", "spec_id", "target"])
    plan = Plan(run_id="test-run-123", spec_id="sim_composite", target="process_bigraph")

    mock_run_core = MagicMock()
    mock_run_core.invoke_run = MagicMock(return_value=plan)

    # Capture request.json when run_runner.execute is called
    captured_requests = []

    def mock_execute(request_path):
        request_data = json.loads(request_path.read_text(encoding="utf-8"))
        captured_requests.append(request_data)

    mock_run_runner = MagicMock()
    mock_run_runner.execute = mock_execute

    # Patch sys.modules to inject our mocks
    import sys
    original_run_core = sys.modules.get("vivarium_workbench.lib.run_core")
    original_run_runner = sys.modules.get("vivarium_workbench.lib.run_runner")

    sys.modules["vivarium_workbench.lib.run_core"] = mock_run_core
    sys.modules["vivarium_workbench.lib.run_runner"] = mock_run_runner

    try:
        # Resolve the study with _default_compute
        resolve_study(tmp_path, "sim")

        # Verify that emit_paths was populated with observables from readouts and tests
        assert len(captured_requests) == 1, f"Expected 1 request, got {len(captured_requests)}"
        request = captured_requests[0]
        assert "emit_paths" in request
        assert isinstance(request["emit_paths"], list)
        # Should contain the readout path and test path (with agents/0/ variants too)
        assert "growth_rate" in request["emit_paths"], f"emit_paths: {request['emit_paths']}"
        assert "division/count" in request["emit_paths"], f"emit_paths: {request['emit_paths']}"
        # Verify agent-scoped variants are also present
        assert "agents/0/growth_rate" in request["emit_paths"], f"emit_paths: {request['emit_paths']}"
        assert "agents/0/division/count" in request["emit_paths"], f"emit_paths: {request['emit_paths']}"
    finally:
        # Restore original modules
        if original_run_core is not None:
            sys.modules["vivarium_workbench.lib.run_core"] = original_run_core
        else:
            sys.modules.pop("vivarium_workbench.lib.run_core", None)
        if original_run_runner is not None:
            sys.modules["vivarium_workbench.lib.run_runner"] = original_run_runner
        else:
            sys.modules.pop("vivarium_workbench.lib.run_runner", None)
