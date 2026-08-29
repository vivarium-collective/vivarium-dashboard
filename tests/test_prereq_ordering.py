"""Plan §A3′ — run items are ordered by declared `pipeline_gate.prerequisites`.

Before this, `run_unblocked_views` emitted items in investigation-member order
and the worker ran them in that order, so a study declaring a prerequisite could
run BEFORE the study it depends on — while `build_investigation_composite`,
compiling the same investigation, ordered it correctly. Same investigation, two
answers. These pin the ordering AND the deliberate non-goals.
"""
from __future__ import annotations

import yaml

from vivarium_workbench.lib.run_jobs import order_items_by_prereqs, study_prereqs
from vivarium_workbench.lib.workspace_paths import WorkspacePaths


def _ws(tmp_path, studies: dict[str, list[str] | None]):
    """Build a workspace whose studies declare the given prerequisites."""
    (tmp_path / "workspace.yaml").write_text("name: prereq-ws\n")
    ws = WorkspacePaths.load(tmp_path)
    ws.studies.mkdir(parents=True, exist_ok=True)
    for slug, prereqs in studies.items():
        d = ws.studies / slug
        d.mkdir(parents=True, exist_ok=True)
        spec: dict = {"name": slug}
        if prereqs is not None:
            spec["pipeline_gate"] = {"prerequisites": list(prereqs)}
        (d / "study.yaml").write_text(yaml.safe_dump(spec))
    return ws


def _items(*slugs):
    return [{"study": s, "variant": "baseline", "kind": "baseline",
             "status": "queued"} for s in slugs]


def _order(items):
    return [it["study"] for it in items]


# --- study_prereqs: the reading ------------------------------------------- #

def test_reads_declared_prerequisites_both_spellings(tmp_path):
    """An entry is `{study: X}` or a bare string; both are real in the wild."""
    ws = _ws(tmp_path, {"a": None, "b": None})
    (ws.studies / "c").mkdir(parents=True)
    (ws.studies / "c" / "study.yaml").write_text(
        "name: c\npipeline_gate:\n  prerequisites:\n    - {study: a}\n    - b\n")
    assert study_prereqs(ws, "c") == ["a", "b"]


def test_no_pipeline_gate_is_no_edges_not_legacy_parent_studies(tmp_path):
    """Keying STRICTLY on pipeline_gate is the point: a study carrying only the
    legacy `parent_studies` must contribute no edges, not silently gain them."""
    ws = _ws(tmp_path, {"a": None})
    (ws.studies / "a" / "study.yaml").write_text(
        "name: a\nparent_studies:\n  - somewhere-else\n")
    assert study_prereqs(ws, "a") == []


def test_missing_and_malformed_study_yaml_yield_no_edges(tmp_path):
    """Total by design — one unreadable file must not break ordering for the
    whole investigation."""
    ws = _ws(tmp_path, {"a": None})
    assert study_prereqs(ws, "nonexistent") == []
    (ws.studies / "bad").mkdir(parents=True)
    (ws.studies / "bad" / "study.yaml").write_text("name: bad\n  : [unbalanced\n")
    assert study_prereqs(ws, "bad") == []


# --- order_items_by_prereqs: the ordering --------------------------------- #

def test_dependent_declared_first_is_moved_after_its_prerequisite(tmp_path):
    """THE bug: declared order puts the dependent first, so it ran first."""
    ws = _ws(tmp_path, {"a": None, "b": ["a"]})
    assert _order(order_items_by_prereqs(_items("b", "a"), ws)) == ["a", "b"]


def test_chain_is_fully_ordered_from_reversed_declaration(tmp_path):
    ws = _ws(tmp_path, {"a": None, "b": ["a"], "c": ["b"]})
    assert _order(order_items_by_prereqs(_items("c", "b", "a"), ws)) == ["a", "b", "c"]


def test_unconstrained_studies_keep_declared_order(tmp_path):
    """7 of 9 v2ecoli investigations declare nothing; they must not be reshuffled
    — declared order is what the composite path's synthetic serial edges give."""
    ws = _ws(tmp_path, {"x": None, "y": None, "z": None})
    assert _order(order_items_by_prereqs(_items("z", "x", "y"), ws)) == ["z", "x", "y"]


def test_all_items_of_one_study_move_together_and_keep_their_order(tmp_path):
    """Baseline and variants share a study slug; the baseline must stay first."""
    ws = _ws(tmp_path, {"a": None, "b": ["a"]})
    items = [
        {"study": "b", "variant": "baseline", "status": "queued"},
        {"study": "b", "variant": "v1", "status": "queued"},
        {"study": "a", "variant": "baseline", "status": "queued"},
    ]
    out = order_items_by_prereqs(items, ws)
    assert _order(out) == ["a", "b", "b"]
    assert [it["variant"] for it in out] == ["baseline", "baseline", "v1"]


def test_prerequisite_outside_this_batch_is_not_an_edge(tmp_path):
    """A prereq excluded by the request's `studies` filter (or not a member at
    all) cannot be waited for here, so it must not reorder anything. Mirrors
    build_investigation_composite's own filter to member_set."""
    ws = _ws(tmp_path, {"a": None, "b": ["not-in-this-run"]})
    assert _order(order_items_by_prereqs(_items("b", "a"), ws)) == ["b", "a"]


def test_self_reference_is_ignored(tmp_path):
    ws = _ws(tmp_path, {"a": ["a"]})
    assert _order(order_items_by_prereqs(_items("a"), ws)) == ["a"]


def test_cycle_does_not_raise_and_keeps_every_item(tmp_path):
    """A metadata typo must not become an outage — the pbg path does not refuse
    either. Order within the cycle is unspecified; completeness is not."""
    ws = _ws(tmp_path, {"a": ["b"], "b": ["a"], "c": None})
    out = order_items_by_prereqs(_items("a", "b", "c"), ws)
    assert sorted(_order(out)) == ["a", "b", "c"]


def test_empty_items_is_a_noop(tmp_path):
    ws = _ws(tmp_path, {})
    assert order_items_by_prereqs([], ws) == []


def test_diamond_places_both_middles_before_the_join(tmp_path):
    ws = _ws(tmp_path, {"top": None, "l": ["top"], "r": ["top"], "join": ["l", "r"]})
    out = _order(order_items_by_prereqs(_items("join", "r", "l", "top"), ws))
    assert out.index("top") < out.index("l") < out.index("join")
    assert out.index("top") < out.index("r") < out.index("join")


# --- the real entry point actually applies it ----------------------------- #

def test_investigation_run_unblocked_orders_the_items_it_submits(tmp_path, monkeypatch):
    """Not the sort in isolation — the REAL route builder must reach it, and the
    items it hands the job manager must already be ordered. Asserts the worker
    was captured, so this cannot pass vacuously."""
    from vivarium_workbench.lib import run_unblocked_views as ruv

    ws = _ws(tmp_path, {"a": None, "b": ["a"]})
    for slug in ("a", "b"):
        spec = yaml.safe_load((ws.studies / slug / "study.yaml").read_text())
        spec["conditions"] = {"baseline": {"composite": "pkg.composites.cell"}}
        (ws.studies / slug / "study.yaml").write_text(yaml.safe_dump(spec))
    ws.investigations.mkdir(parents=True, exist_ok=True)
    inv = ws.investigations / "inv"
    inv.mkdir(parents=True, exist_ok=True)
    # Declared order puts the DEPENDENT first — the condition being fixed.
    (inv / "investigation.yaml").write_text(
        yaml.safe_dump({"name": "inv", "members": ["b", "a"]}))

    captured: dict = {}

    class _Job:
        job_id = "j1"

    def _submit(inv_slug, items, worker):
        captured["items"] = items
        captured["worker"] = worker
        return _Job()

    monkeypatch.setattr(ruv.manager, "submit", _submit)
    body, code = ruv.investigation_run_unblocked(tmp_path, {"investigation": "inv"})
    assert code == 202, body
    assert captured, "manager.submit was never called — test proves nothing"
    assert _order(captured["items"]) == ["a", "b"], captured["items"]
    assert _order(body["items"]) == ["a", "b"], body["items"]
