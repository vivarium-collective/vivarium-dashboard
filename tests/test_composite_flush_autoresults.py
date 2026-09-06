"""Composite-run auto-results (Task 5): config-declared analyses merge into
the composite's own ``@composite_generator(analyses=[...])`` defaults before
dispatch.

``_dispatch_analyses`` now sources its declaration from
``merge_declarations(composite_defaults, config_declared)`` (from
``vivarium_workbench.lib.ephemeral_study``), where ``composite_defaults`` is
whatever ``_composite_analyses`` returns (the generator entry's own
declarations) and ``config_declared`` is ``req.declared_results["analyses"]``
— ``{}``/absent until a future task populates it on the request, in which
case composite defaults flow through unchanged (a no-op merge). Config wins
on name collision.

process_bigraph is non-editable in this venv, so ``entry.analyses`` may not
be visible at runtime here even though Task 1 added the field upstream — per
plan ruling, these tests mock ``_composite_analyses`` (the generator-entry
lookup) directly rather than relying on a live process_bigraph registry.
"""
import json
from pathlib import Path

from vivarium_workbench.lib import composite_flush


class _Req:
    steps = 10
    run_id = "r1"
    spec_id = "some.composite.spec"


class _ReqWithDeclared(_Req):
    def __init__(self, declared_results):
        self.declared_results = declared_results


def test_dispatch_merges_config_declared_over_composite_defaults(tmp_path, monkeypatch):
    # Composite declares two analyses; config declares one new one plus an
    # override of one of the composite's own (same name, different params).
    monkeypatch.setattr(
        composite_flush, "_composite_analyses",
        lambda spec_id, core: [
            {"name": "mass_over_time"},
            {"name": "shared_analysis", "params": {"from": "composite"}},
        ],
        raising=False,
    )
    rendered_calls = []

    def _render(**k):
        rendered_calls.append({"name": k.get("name"), "params": k.get("params")})
        return {"name": k.get("name"), "written": [], "errors": []}

    monkeypatch.setattr(composite_flush, "_render_analysis", _render, raising=False)

    req = _ReqWithDeclared({
        "analyses": [
            {"name": "config_only"},
            {"name": "shared_analysis", "params": {"from": "config"}},
        ],
    })

    out = composite_flush._dispatch_analyses(
        spec_id="c", db_file=str(tmp_path / "x.db"), run_id="r1", core=object(),
        req=req,
    )

    names = {c["name"] for c in rendered_calls}
    assert names == {"mass_over_time", "config_only", "shared_analysis"}
    # config wins on collision: exactly one render call for the shared name,
    # carrying the config's params.
    shared_calls = [c for c in rendered_calls if c["name"] == "shared_analysis"]
    assert len(shared_calls) == 1
    assert shared_calls[0]["params"] == {"from": "config"}
    assert {a["name"] for a in out} == names


def test_dispatch_with_no_declared_results_behaves_as_before(tmp_path, monkeypatch):
    # req has no declared_results attribute at all (today's shape, before a
    # future task populates it) -- composite defaults flow through unchanged.
    monkeypatch.setattr(
        composite_flush, "_composite_analyses",
        lambda spec_id, core: [{"name": "mass_over_time"}],
        raising=False,
    )
    monkeypatch.setattr(
        composite_flush, "_render_analysis",
        lambda **k: {"name": k.get("name"), "written": [], "errors": []},
        raising=False,
    )
    out = composite_flush._dispatch_analyses(
        spec_id="c", db_file=str(tmp_path / "x.db"), run_id="r1", core=object(),
        req=_Req(),
    )
    assert [a["name"] for a in out] == ["mass_over_time"]


def test_dispatch_with_empty_declared_results_is_a_noop_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(
        composite_flush, "_composite_analyses",
        lambda spec_id, core: [{"name": "mass_over_time"}],
        raising=False,
    )
    monkeypatch.setattr(
        composite_flush, "_render_analysis",
        lambda **k: {"name": k.get("name"), "written": [], "errors": []},
        raising=False,
    )
    out = composite_flush._dispatch_analyses(
        spec_id="c", db_file=str(tmp_path / "x.db"), run_id="r1", core=object(),
        req=_ReqWithDeclared({}),
    )
    assert [a["name"] for a in out] == ["mass_over_time"]


def test_run_flush_threads_req_into_dispatch_and_writes_merged_analyses_json(
    tmp_path, monkeypatch
):
    # End-to-end through run_flush: the merged, flattened list reaches
    # _dispatch_analyses (via req) and lands in analyses.json as a list.
    monkeypatch.setattr(
        composite_flush, "_composite_analyses",
        lambda spec_id, core: [{"name": "mass_over_time"}],
        raising=False,
    )
    monkeypatch.setattr(
        composite_flush, "_render_analysis",
        lambda **k: {"name": k.get("name"), "written": [], "errors": []},
        raising=False,
    )
    req = _ReqWithDeclared({"analyses": [{"name": "config_only"}]})

    out = composite_flush.run_flush(
        tmp_path, req=req, spec_id="some.composite.spec",
        db_file=str(tmp_path / "runs.db"), run_id="r1", core=object(),
    )

    assert out["has_analyses"] is True
    written = json.loads((tmp_path / "analyses.json").read_text())
    assert isinstance(written, list)
    assert {a["name"] for a in written} == {"mass_over_time", "config_only"}
