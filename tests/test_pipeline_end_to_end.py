"""End-to-end integration test (Study Pipeline Spec 1, Task 8, Step 1).

Proves the pull-or-compute pipeline resolver (Task 5) and the many-to-many
investigation graph (registry-only reference model, Tasks 3-4) compose
correctly: a shared upstream artifact (ParCa ``sim_data``) is computed exactly
ONCE and reused across two independent investigations, and the fixture
workspace itself passes the no-nested-studies guard (Task 7).

Scope note: this file covers ONLY Step 1 of the Task 8 brief (the in-repo
integration test). Steps 2-4 (running the migrator against the real v2ecoli
workspace and committing there) are out of scope for this repo and are
handled separately.
"""
from __future__ import annotations

import yaml

from vivarium_workbench.lib.artifacts.pipeline import resolve_study
from vivarium_workbench.lib.investigation_graph_views import build_investigation_graph


def make_stub():
    calls = []

    def stub(ws_root, slug, *, artifact_id, composite, config, input_ids, out_dir):
        calls.append(slug)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "out.bin"
        p.write_bytes(b"fake:" + slug.encode())
        return p

    return stub, calls


def _write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def build_fixture(tmp_path):
    """Registry-only workspace: two investigations (invA, invB) sharing a
    common ParCa producer study, each with its own ko study depending on it."""
    _write_yaml(tmp_path / "studies" / "parca" / "study.yaml", {
        "name": "parca",
        "composite": "parca_builder",
        "config": {},
        "outputs": ["sim_data"],
    })
    _write_yaml(tmp_path / "studies" / "ko1" / "study.yaml", {
        "name": "ko1",
        "composite": "baseline",
        "config": {"seed": 0},
        "inputs": [{"artifact": "sim_data", "from": "parca"}],
        "outputs": ["run_zarr"],
    })
    _write_yaml(tmp_path / "studies" / "ko2" / "study.yaml", {
        "name": "ko2",
        "composite": "baseline",
        "config": {"seed": 1},
        "inputs": [{"artifact": "sim_data", "from": "parca"}],
        "outputs": ["run_zarr"],
    })
    _write_yaml(tmp_path / "investigations" / "invA" / "investigation.yaml", {
        "title": "A",
        "members": ["parca", "ko1"],
    })
    _write_yaml(tmp_path / "investigations" / "invB" / "investigation.yaml", {
        "title": "B",
        "members": ["parca", "ko2"],
    })
    return tmp_path


def test_shared_producer_computed_once_across_investigations(tmp_path):
    ws = build_fixture(tmp_path)
    stub, calls = make_stub()

    r1 = resolve_study(ws, "ko1", compute_fn=stub)
    r2 = resolve_study(ws, "ko2", compute_fn=stub)

    # parca computed exactly once (store hit on the second resolve's recursion
    # into its producer), then each ko computed once.
    assert calls == ["parca", "ko1", "ko2"]

    # Both investigations' ko studies reference the identical content-addressed
    # sim_data artifact id — the shared producer was reused, not recomputed.
    assert r1["inputs"]["parca"] == r2["inputs"]["parca"]

    # Each ko study itself is newly computed (not a store hit)...
    assert r1["cached"] is False
    assert r2["cached"] is False
    # ...but the shared producer wasn't recomputed for r2 (already proven via
    # `calls` not containing a second "parca").


def test_both_investigations_show_shared_node(tmp_path):
    ws = build_fixture(tmp_path)

    payloadA, statusA = build_investigation_graph(ws, "invA")
    payloadB, statusB = build_investigation_graph(ws, "invB")

    assert statusA == 200
    assert statusB == 200

    idsA = {s["id"] for s in payloadA["studies"]}
    idsB = {s["id"] for s in payloadB["studies"]}
    assert "study/parca" in idsA
    assert "study/parca" in idsB

    edgesA = [e for e in payloadA["study_edges"]
              if e["source"] == "study/parca" and e["target"] == "study/ko1"]
    edgesB = [e for e in payloadB["study_edges"]
              if e["source"] == "study/parca" and e["target"] == "study/ko2"]
    assert len(edgesA) == 1
    assert len(edgesB) == 1


def test_fixture_is_registry_clean(tmp_path):
    ws = build_fixture(tmp_path)
    # Inline the registry-clean scan (mirrors tests/test_no_nested_studies_guard.
    # find_nested_studies) rather than importing across test modules: a top-level
    # `tests` package shipped in site-packages shadows the repo's tests/ under CI.
    nested = sorted((ws / "investigations").rglob("study.yaml"))
    assert nested == []
