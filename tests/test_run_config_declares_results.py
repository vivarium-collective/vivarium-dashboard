"""Round-trip test: config-declared ``analyses``/``visualizations`` reach
``RunRequest.declared_results``.

Task 6 (composite-auto-results): the config declaration surface. A composite
run body may carry optional ``analyses``/``visualizations`` blocks; these must
be written into ``request.json`` as a ``declared_results`` block and survive
``RunRequest.from_file`` so Task 5's ``composite_flush._dispatch_analyses``
(``getattr(req, "declared_results", None) or {}``) picks them up. The absent
case must degrade to an empty/no-op shape, never crash.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vivarium_workbench.lib import run_registry
from vivarium_workbench.lib import composite_test_run_views as views
from vivarium_workbench.lib import composite_runs as cr
from vivarium_workbench.lib.run_runner import RunRequest


def _make_ws(tmp_path: Path, *, name: str = "demo-ws") -> Path:
    (tmp_path / "workspace.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    (tmp_path / ".pbg").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def fixed_run_id(monkeypatch):
    rid = "demo.spec__1700000000__abcdef"
    monkeypatch.setattr(cr, "generate_run_id", lambda spec_id, params=None, now=None: rid)
    return rid


@pytest.fixture
def _no_spawn(monkeypatch):
    monkeypatch.setattr(run_registry, "count_running", lambda db_file: 0)
    monkeypatch.setattr(run_registry, "spawn_detached",
                        lambda request_path, *, workspace, log_path: 1)


def test_declared_analyses_and_visualizations_reach_request_json(
        tmp_path, monkeypatch, fixed_run_id, _no_spawn):
    ws = _make_ws(tmp_path)
    analyses = [{"name": "ptools_rxns_multigeneration"}]
    visualizations = [{"name": "titer"}]

    body, status = views.composite_test_run(ws, {
        "id": "demo.spec",
        "analyses": analyses,
        "visualizations": visualizations,
    })
    assert status == 202

    req_path = ws / ".pbg" / "runs" / fixed_run_id / "request.json"
    data = json.loads(req_path.read_text())
    assert data["declared_results"] == {
        "analyses": analyses,
        "visualizations": visualizations,
    }


def test_absent_declaration_degrades_to_empty(tmp_path, monkeypatch, fixed_run_id, _no_spawn):
    ws = _make_ws(tmp_path)
    body, status = views.composite_test_run(ws, {"id": "demo.spec"})
    assert status == 202

    req_path = ws / ".pbg" / "runs" / fixed_run_id / "request.json"
    data = json.loads(req_path.read_text())
    assert data["declared_results"] == {"analyses": [], "visualizations": []}


def test_declared_analyses_scale_grouped_dict_round_trips(
        tmp_path, monkeypatch, fixed_run_id, _no_spawn):
    """The documented config shape for ``analyses`` is scale-grouped -- a DICT
    like ``{"multigeneration": [...]}`` -- not a flat list. A prior bug
    coerced any non-list value (i.e. this dict) to ``[]``, silently dropping
    it. It must survive into ``request.json`` unchanged."""
    ws = _make_ws(tmp_path)
    analyses = {"multigeneration": ["ptools_rxns_multigeneration"]}

    body, status = views.composite_test_run(ws, {
        "id": "demo.spec",
        "analyses": analyses,
    })
    assert status == 202

    req_path = ws / ".pbg" / "runs" / fixed_run_id / "request.json"
    data = json.loads(req_path.read_text())
    assert data["declared_results"]["analyses"] == analyses

    req = RunRequest.from_file(req_path)
    assert req.declared_results["analyses"] == analyses

    from vivarium_workbench.lib.ephemeral_study import merge_declarations
    merged = merge_declarations({}, req.declared_results)
    assert merged["analyses"] == [{"name": "ptools_rxns_multigeneration"}]


def test_declared_analyses_invalid_type_degrades_to_empty(
        tmp_path, monkeypatch, fixed_run_id, _no_spawn):
    """A genuinely invalid type (not list, not dict) still degrades safely."""
    ws = _make_ws(tmp_path)
    body, status = views.composite_test_run(ws, {
        "id": "demo.spec",
        "analyses": "not-a-valid-shape",
        "visualizations": 42,
    })
    assert status == 202

    req_path = ws / ".pbg" / "runs" / fixed_run_id / "request.json"
    data = json.loads(req_path.read_text())
    assert data["declared_results"] == {"analyses": [], "visualizations": []}


def test_run_request_from_file_populates_declared_results(tmp_path):
    run_dir = tmp_path
    request_path = run_dir / "request.json"
    request_path.write_text(json.dumps({
        "run_id": "r", "spec_id": "s", "pkg": "p", "workspace": str(tmp_path),
        "overrides": {}, "steps": 1, "emit_paths": [],
        "db_file": "/tmp/x.db", "log_path": "x.log",
        "declared_results": {
            "analyses": [{"name": "a"}],
            "visualizations": [{"name": "v"}],
        },
    }), encoding="utf-8")

    req = RunRequest.from_file(request_path)
    assert req.declared_results == {
        "analyses": [{"name": "a"}],
        "visualizations": [{"name": "v"}],
    }


def test_run_request_from_file_defaults_declared_results_when_absent(tmp_path):
    """A request.json written before this task (no declared_results key at all)
    must not crash from_file, and must degrade to a shape that makes Task 5's
    merge a no-op."""
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps({
        "run_id": "r", "spec_id": "s", "pkg": "p", "workspace": str(tmp_path),
        "overrides": {}, "steps": 1, "emit_paths": [],
        "db_file": "/tmp/x.db", "log_path": "x.log",
    }), encoding="utf-8")

    req = RunRequest.from_file(request_path)
    assert req.declared_results == {"analyses": [], "visualizations": []}
