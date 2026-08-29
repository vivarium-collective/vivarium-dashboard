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


# --- the gate: §A3′ option (c) -------------------------------------------- #
#
# Ordering alone sequences a LOCAL target, where each run blocks. It does not
# sequence a DEPLOYMENT target: A2' made dispatch return `submitted` at once, so
# a dependent would start while its prerequisite is still on Batch. These pin
# the gate that closes it, and the explicit release that follows.

def _inv_ws(tmp_path, studies, members):
    ws = _ws(tmp_path, studies)
    for slug in studies:
        spec = yaml.safe_load((ws.studies / slug / "study.yaml").read_text())
        spec["conditions"] = {"baseline": {"composite": "pkg.composites.cell"}}
        (ws.studies / slug / "study.yaml").write_text(yaml.safe_dump(spec))
    ws.investigations.mkdir(parents=True, exist_ok=True)
    inv = ws.investigations / "inv"
    inv.mkdir(parents=True, exist_ok=True)
    (inv / "investigation.yaml").write_text(
        yaml.safe_dump({"name": "inv", "members": list(members)}))
    return ws


class _Job:
    """Duck-typed stand-in matching what the worker actually uses."""

    def __init__(self, items):
        self.items = [dict(it) for it in items]

    def update_item(self, idx, **fields):
        self.items[idx].update(fields)


def _run_worker(monkeypatch, tmp_path, ws_root, responses):
    """Drive the REAL worker closure, returning (job, studies_actually_run)."""
    from vivarium_workbench.lib import run_unblocked_views as ruv

    captured: dict = {}
    ran: list[str] = []

    def _submit(inv_slug, items, worker):
        captured["items"] = items
        captured["worker"] = worker
        return type("J", (), {"job_id": "j1"})()

    def _baseline(_ws, body):
        ran.append(body["study"])
        return responses.get(body["study"], ({"run_id": "r"}, 200))

    monkeypatch.setattr(ruv.manager, "submit", _submit)
    monkeypatch.setattr(ruv.study_runs, "run_study_baseline", _baseline)
    monkeypatch.setattr(ruv.comparative_runs,
                        "render_investigation_comparative_visualisations",
                        lambda *a, **k: None)
    body, code = ruv.investigation_run_unblocked(ws_root, {"investigation": "inv"})
    assert code == 202, body
    assert captured, "manager.submit was never called — test proves nothing"
    job = _Job(captured["items"])
    captured["worker"](job)
    return job, ran, captured["worker"]


def test_dependent_is_held_waiting_while_its_prereq_is_submitted(tmp_path, monkeypatch):
    """THE deployment-path gap: 'a' dispatches to Batch (202 -> submitted) and
    'b' must NOT run against a prerequisite that is still going."""
    ws = _inv_ws(tmp_path, {"a": None, "b": ["a"]}, ["a", "b"])
    job, ran, _ = _run_worker(
        monkeypatch, tmp_path, tmp_path,
        {"a": ({"simulation_id": 7, "phase": "running"}, 202)})
    by = {it["study"]: it for it in job.items}
    assert by["a"]["status"] == "submitted"
    assert by["b"]["status"] == "waiting", job.items
    assert "waiting on: a" in by["b"]["error"]
    assert ran == ["a"], f"b must not have been run: {ran}"


def test_dependent_runs_once_its_prereq_is_done(tmp_path, monkeypatch):
    """A locally-completed prerequisite (200 -> done) does not gate anything."""
    ws = _inv_ws(tmp_path, {"a": None, "b": ["a"]}, ["a", "b"])
    job, ran, _ = _run_worker(monkeypatch, tmp_path, tmp_path, {})
    assert [it["status"] for it in job.items] == ["done", "done"]
    assert ran == ["a", "b"]


def test_dependent_of_a_failed_prereq_is_skipped_not_waiting(tmp_path, monkeypatch):
    """A failed prerequisite can never become done. Leaving the dependent
    `waiting` would be indistinguishable from a hang and would make the redrive
    loop spin on it forever."""
    ws = _inv_ws(tmp_path, {"a": None, "b": ["a"]}, ["a", "b"])
    job, ran, _ = _run_worker(monkeypatch, tmp_path, tmp_path,
                              {"a": ({"error": "boom"}, 500)})
    by = {it["study"]: it for it in job.items}
    assert by["a"]["status"] == "failed"
    assert by["b"]["status"] == "skipped", job.items
    assert "prerequisite did not complete: a" in by["b"]["error"]
    assert ran == ["a"]


def test_redrive_releases_the_waiting_item_once_the_prereq_lands(tmp_path, monkeypatch):
    """The explicit release. Re-running the SAME worker closure after the
    prerequisite settles must start the dependent — that is what makes option
    (c) whole rather than a way to strand work."""
    ws = _inv_ws(tmp_path, {"a": None, "b": ["a"]}, ["a", "b"])
    job, ran, worker = _run_worker(
        monkeypatch, tmp_path, tmp_path,
        {"a": ({"simulation_id": 7, "phase": "running"}, 202)})
    assert ran == ["a"]
    # Batch finished; refresh_submitted would have settled it to done.
    for i, it in enumerate(job.items):
        if it["study"] == "a":
            job.update_item(i, status="done")
    worker(job)          # the redrive
    by = {it["study"]: it for it in job.items}
    assert by["b"]["status"] == "done", job.items
    assert ran == ["a", "b"]


def test_redrive_is_idempotent_and_reports_nothing_waiting(tmp_path):
    """A caller may poll redrive safely: no waiting items is an ordinary answer,
    and a job it does not know is a 'no such job', not a crash."""
    from vivarium_workbench.lib.run_jobs import RunJobManager

    mgr = RunJobManager()
    job = mgr.submit("inv", [{"study": "a", "status": "queued"}], lambda j: None)
    job._worker.join(timeout=5)
    assert mgr.redrive(job.job_id)["redriven"] is False
    assert mgr.redrive(job.job_id)["reason"] == "nothing waiting"
    assert mgr.redrive("nope")["reason"] == "no such job"


def test_redrive_reruns_the_worker_when_something_is_waiting(tmp_path):
    from vivarium_workbench.lib.run_jobs import RunJobManager

    calls: list[int] = []

    def _w(job):
        calls.append(1)
        if len(calls) == 1:
            job.update_item(0, status="waiting")
        else:
            job.update_item(0, status="done")

    mgr = RunJobManager()
    job = mgr.submit("inv", [{"study": "a", "status": "queued"}], _w)
    job._worker.join(timeout=5)
    assert job.status == "waiting", job.to_dict()
    assert mgr.redrive(job.job_id)["redriven"] is True
    job._worker.join(timeout=5)
    assert job.items[0]["status"] == "done"
    assert job.status == "done"
    assert len(calls) == 2


def test_a_redriven_item_loses_its_stale_waiting_reason(tmp_path, monkeypatch):
    """An item released by a redrive must not keep showing 'waiting on: a' after
    it succeeds — but a plain dispatch must still carry NO `error` key at all
    (test_run_jobs_async_dispatch pins that), so the clear is conditional."""
    ws = _inv_ws(tmp_path, {"a": None, "b": ["a"]}, ["a", "b"])
    job, ran, worker = _run_worker(
        monkeypatch, tmp_path, tmp_path,
        {"a": ({"simulation_id": 7, "phase": "running"}, 202)})
    by = {it["study"]: it for it in job.items}
    assert by["b"]["error"], "precondition: b was gated with a reason"
    assert "error" not in by["a"], "a dispatched cleanly and must carry no error"
    for i, it in enumerate(job.items):
        if it["study"] == "a":
            job.update_item(i, status="done")
    worker(job)
    by = {it["study"]: it for it in job.items}
    assert by["b"]["status"] == "done"
    assert by["b"]["error"] is None, by["b"]
