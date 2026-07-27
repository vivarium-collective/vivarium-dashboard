import json
import sqlite3

import pytest
import yaml

from vivarium_workbench.lib.artifacts.pipeline import resolve_study
from vivarium_workbench.lib.artifacts.store import ArtifactStore


def make_stub():
    calls = []

    def stub(ws_root, slug, *, artifact_id, composite, config, input_ids, out_dir,
              resolved_inputs=None):
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
    """Test that _default_compute collects emit_paths from study spec readouts/tests.

    Order-independent test: patches attributes on the already-imported real modules
    (via importlib and monkeypatch.setattr on the module object itself) rather than
    swapping modules in sys.modules. This ensures the test works correctly whether
    or not other test files that import run_core/run_runner have already been loaded.
    """
    import importlib
    from pathlib import Path

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

    # Import the real modules
    run_core = importlib.import_module("vivarium_workbench.lib.run_core")
    run_runner = importlib.import_module("vivarium_workbench.lib.run_runner")

    # Create a fake plan object with the attributes _default_compute reads
    class FakePlan:
        def __init__(self):
            self.run_id = "test-run-123"
            self.spec_id = "sim_composite"
            self.target = "process_bigraph"

    fake_plan = FakePlan()

    # Patch invoke_run to return our fake plan
    monkeypatch.setattr(run_core, "invoke_run", lambda *a, **k: fake_plan)

    # Capture request.json when run_runner.execute is called
    captured_requests = []

    def capture_execute(request_path):
        request_data = json.loads(Path(request_path).read_text(encoding="utf-8"))
        captured_requests.append(request_data)
        return 0

    # Patch execute on the real module
    monkeypatch.setattr(run_runner, "execute", capture_execute)

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


def test_consumer_compute_receives_producer_store_path(ws):
    """`ko`'s compute call must receive `resolved_inputs["sim_data"]["path"]`
    == the producer (`parca`)'s artifact store path — this is how a consumer
    run would actually read its input's on-disk content. `ko`'s input entry
    declares no `into`, so `resolved_inputs["sim_data"]["into"]` is `None`."""
    captured = {}

    def capturing_stub(ws_root, slug, *, artifact_id, composite, config, input_ids,
                        out_dir, resolved_inputs=None):
        if slug == "ko":
            captured["resolved_inputs"] = resolved_inputs
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "out.bin"
        p.write_bytes(b"fake:" + slug.encode())
        return p

    r = resolve_study(ws, "ko", compute_fn=capturing_stub)

    store = ArtifactStore(ws)
    expected_path = str(store.path(r["inputs"]["parca"]))
    assert captured["resolved_inputs"] == {
        "sim_data": {"path": expected_path, "into": None}
    }


def test_default_compute_merges_resolved_inputs_into_overrides(tmp_path, monkeypatch):
    """Unit-test `_default_compute`'s override merge: `overrides["cache_dir"]`
    and `overrides["sim_data_path"]` must both point at the producer's store
    path (v2ecoli convention: ecoli_baseline reads ParCa sim_data via
    `cache_dir`). Patches attributes on the already-imported real modules
    (importlib + monkeypatch.setattr on the module object) rather than
    swapping sys.modules — same pattern as
    test_default_compute_populates_emit_paths_from_study_readouts above.
    """
    import importlib
    import json
    from pathlib import Path as _Path

    from vivarium_workbench.lib.artifacts.pipeline import _default_compute

    (tmp_path / "studies" / "sim").mkdir(parents=True)
    spec = {
        "name": "sim",
        "composite": "sim_composite",
        "config": {"seed": 0},
        "outputs": ["run_result"],
    }
    (tmp_path / "studies" / "sim" / "study.yaml").write_text(
        yaml.safe_dump(spec), encoding="utf-8"
    )

    run_core = importlib.import_module("vivarium_workbench.lib.run_core")
    run_runner = importlib.import_module("vivarium_workbench.lib.run_runner")

    class FakePlan:
        def __init__(self):
            self.run_id = "test-run-456"
            self.spec_id = "sim_composite"
            self.target = "process_bigraph"

    monkeypatch.setattr(run_core, "invoke_run", lambda *a, **k: FakePlan())

    captured_requests = []

    def capture_execute(request_path):
        captured_requests.append(
            json.loads(_Path(request_path).read_text(encoding="utf-8"))
        )
        return 0

    monkeypatch.setattr(run_runner, "execute", capture_execute)

    out_dir = tmp_path / "scratch"
    out_dir.mkdir(parents=True)
    producer_path = "/fake/store/abcd1234/payload"
    orig_config = {"seed": 0}
    _default_compute(
        tmp_path, "sim",
        artifact_id="oid123",
        composite="sim_composite",
        config=orig_config,
        input_ids=["abcd1234"],
        out_dir=out_dir,
        resolved_inputs={"sim_data": {"path": producer_path, "into": None}},
    )

    assert len(captured_requests) == 1
    overrides = captured_requests[0]["overrides"]
    assert overrides["sim_data_path"] == producer_path
    assert overrides["cache_dir"] == producer_path
    # Caller's config dict must not be mutated in place.
    assert orig_config == {"seed": 0}


def test_default_compute_strips_run_control_keys_from_overrides(tmp_path, monkeypatch):
    """`n_steps` is a run-control key routed to RunRequest.steps, NOT a generator
    parameter — it must be stripped from the generator `overrides` (else
    build_generator rejects it as an unknown parameter), while `steps` is still
    derived from it. Order-independent (attribute-patching, per the emit_paths test)."""
    import importlib
    from pathlib import Path

    (tmp_path / "studies" / "sim").mkdir(parents=True)
    spec = {
        "name": "sim",
        "composite": "sim_composite",
        "config": {"seed": 0, "n_steps": 3},
    }
    (tmp_path / "studies" / "sim" / "study.yaml").write_text(
        yaml.safe_dump(spec), encoding="utf-8"
    )

    run_core = importlib.import_module("vivarium_workbench.lib.run_core")
    run_runner = importlib.import_module("vivarium_workbench.lib.run_runner")

    class FakePlan:
        run_id = "rc-run-1"
        spec_id = "sim_composite"
        target = "process_bigraph"

    monkeypatch.setattr(run_core, "invoke_run", lambda *a, **k: FakePlan())

    captured = []

    def _capture_execute(request_path):
        captured.append(json.loads(Path(request_path).read_text(encoding="utf-8")))
        return 0

    monkeypatch.setattr(run_runner, "execute", _capture_execute)

    resolve_study(tmp_path, "sim")

    assert len(captured) == 1
    req = captured[0]
    assert "n_steps" not in req["overrides"], "run-control key leaked into generator overrides"
    assert req["overrides"].get("seed") == 0, "generator param must be preserved"
    assert req["steps"] == 3, "steps must still be derived from n_steps"


def test_default_compute_routes_generic_into_config_key(tmp_path, monkeypatch):
    """An input edge declaring `into: cache_dir` on an artifact NOT named
    `sim_data` (e.g. `parca_cache`) must still land at `overrides["cache_dir"]`
    — proving `into` is a fully generic mechanism, not a `sim_data`
    special-case. A sibling `sim_data` input with NO `into` at all must still
    populate `overrides["cache_dir"]` via the documented back-compat default
    (proving that default is preserved alongside the generic path)."""
    import importlib
    from pathlib import Path

    (tmp_path / "studies" / "parca").mkdir(parents=True)
    (tmp_path / "studies" / "consumer").mkdir(parents=True)
    (tmp_path / "studies" / "parca" / "study.yaml").write_text(yaml.safe_dump({
        "name": "parca",
        "composite": "parca_builder",
        "config": {},
        "outputs": ["sim_data"],
    }))
    (tmp_path / "studies" / "consumer" / "study.yaml").write_text(yaml.safe_dump({
        "name": "consumer",
        "composite": "consumer_composite",
        "config": {"seed": 0},
        "inputs": [
            {"artifact": "parca_cache", "from": "parca", "into": "cache_dir"},
        ],
        "outputs": ["run_zarr"],
    }))

    stub_calls = []

    def parca_stub(ws_root, slug, *, artifact_id, composite, config, input_ids,
                    out_dir, resolved_inputs=None):
        stub_calls.append(slug)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "out.bin"
        p.write_bytes(b"fake:parca")
        return p

    run_core = importlib.import_module("vivarium_workbench.lib.run_core")
    run_runner = importlib.import_module("vivarium_workbench.lib.run_runner")

    class FakePlan:
        run_id = "generic-into-run-1"
        spec_id = "consumer_composite"
        target = "process_bigraph"

    monkeypatch.setattr(run_core, "invoke_run", lambda *a, **k: FakePlan())

    captured = []

    def _capture_execute(request_path):
        captured.append(json.loads(Path(request_path).read_text(encoding="utf-8")))
        return 0

    monkeypatch.setattr(run_runner, "execute", _capture_execute)

    # `parca`'s own compute is a plain stub (not exercised by run_runner at
    # all) — only `consumer` needs to hit the real `_default_compute` adapter.
    def compute_fn(ws_root, slug, **kwargs):
        if slug == "parca":
            return parca_stub(ws_root, slug, **kwargs)
        from vivarium_workbench.lib.artifacts.pipeline import _default_compute
        return _default_compute(ws_root, slug, **kwargs)

    r = resolve_study(tmp_path, "consumer", compute_fn=compute_fn)

    store = ArtifactStore(tmp_path)
    producer_path = str(store.path(r["inputs"]["parca"]))

    assert len(captured) == 1
    overrides = captured[0]["overrides"]
    assert overrides["parca_cache_path"] == producer_path
    assert overrides["cache_dir"] == producer_path


def _sim_workspace(tmp_path):
    (tmp_path / "studies" / "sim").mkdir(parents=True)
    (tmp_path / "studies" / "sim" / "study.yaml").write_text(yaml.safe_dump({
        "name": "sim",
        "composite": "sim_composite",
        "config": {"seed": 0},
        "outputs": ["run_result"],
    }))


def _patch_run_core_plan(monkeypatch, run_id="failed-run-1"):
    import importlib

    run_core = importlib.import_module("vivarium_workbench.lib.run_core")

    class FakePlan:
        pass

    FakePlan.run_id = run_id
    FakePlan.spec_id = "sim_composite"
    FakePlan.target = "process_bigraph"
    monkeypatch.setattr(run_core, "invoke_run", lambda *a, **k: FakePlan())
    return run_id


def test_nonzero_execute_raises_and_never_caches(tmp_path, monkeypatch):
    """`run_runner.execute` returning a non-zero exit code must raise BEFORE
    `resolve_study` reaches `store.put` — a failed run's output directory
    must never become a cache hit for this study's artifact id."""
    import importlib

    _sim_workspace(tmp_path)
    run_id = _patch_run_core_plan(monkeypatch)
    run_runner = importlib.import_module("vivarium_workbench.lib.run_runner")

    def failing_execute(request_path):
        return 1

    monkeypatch.setattr(run_runner, "execute", failing_execute)

    from vivarium_workbench.lib.artifacts import hashing
    from vivarium_workbench.lib.artifacts.pipeline import _workspace_commit

    oid = hashing.artifact_id(
        composite_id="sim_composite", config={"seed": 0}, input_ids=[],
        commit=_workspace_commit(tmp_path),
    )

    with pytest.raises(RuntimeError, match="sim"):
        resolve_study(tmp_path, "sim")

    assert ArtifactStore(tmp_path).has(oid) is False


def test_completed_rc_but_failed_runs_meta_status_raises_and_never_caches(
    tmp_path, monkeypatch,
):
    """Belt-and-suspenders: even when `run_runner.execute` returns 0, a
    `runs_meta.status` that landed as `failed` (not `completed`) in the run's
    own `runs.db` must still make `_default_compute` raise — never cache a
    run whose own terminal status disagrees with the exit code."""
    import importlib
    from pathlib import Path

    _sim_workspace(tmp_path)
    run_id = _patch_run_core_plan(monkeypatch, run_id="rc-ok-status-failed")
    run_runner = importlib.import_module("vivarium_workbench.lib.run_runner")

    def execute_writes_failed_status(request_path):
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        db_file = request["db_file"]
        conn = sqlite3.connect(db_file)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runs_meta ("
                "run_id TEXT PRIMARY KEY, status TEXT)"
            )
            conn.execute(
                "INSERT INTO runs_meta (run_id, status) VALUES (?, ?)",
                (run_id, "failed"),
            )
            conn.commit()
        finally:
            conn.close()
        return 0  # exit code claims success; runs_meta disagrees

    monkeypatch.setattr(run_runner, "execute", execute_writes_failed_status)

    from vivarium_workbench.lib.artifacts import hashing
    from vivarium_workbench.lib.artifacts.pipeline import _workspace_commit

    oid = hashing.artifact_id(
        composite_id="sim_composite", config={"seed": 0}, input_ids=[],
        commit=_workspace_commit(tmp_path),
    )

    with pytest.raises(RuntimeError, match="sim"):
        resolve_study(tmp_path, "sim")

    assert ArtifactStore(tmp_path).has(oid) is False
