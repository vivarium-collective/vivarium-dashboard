import pytest
import yaml

from vivarium_workbench.lib.artifacts import pipeline
from vivarium_workbench.lib.artifacts.pipeline import resolve_investigation
from vivarium_workbench.lib.artifacts.store import ArtifactStore


def make_stub(fail_for=()):
    calls = []

    def stub(ws_root, slug, *, artifact_id, composite, config, input_ids, out_dir,
             resolved_inputs=None):
        calls.append(slug)
        if slug in fail_for:
            raise RuntimeError(f"boom: {slug}")
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "out.bin"
        p.write_bytes(b"fake:" + slug.encode())
        return p

    return stub, calls


def _write_study(ws_root, slug, *, inputs_from=(), config=None):
    d = ws_root / "studies" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "study.yaml").write_text(yaml.safe_dump({
        "name": slug,
        "composite": f"c.{slug}",
        "config": config if config is not None else {},
        "inputs": [{"artifact": f"{f}_out", "from": f} for f in inputs_from],
        "outputs": [f"{slug}_out"],
    }))


@pytest.fixture
def diamond(tmp_path):
    """parca -> a, parca -> b, {a, b} -> c, all declared as inv1 members."""
    _write_study(tmp_path, "parca")
    _write_study(tmp_path, "a", inputs_from=["parca"])
    _write_study(tmp_path, "b", inputs_from=["parca"])
    _write_study(tmp_path, "c", inputs_from=["a", "b"])

    inv_dir = tmp_path / "investigations" / "inv1"
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "investigation.yaml").write_text(yaml.safe_dump({
        "name": "inv1",
        "members": ["parca", "a", "b", "c"],
    }))
    return tmp_path


def test_resolve_investigation_topo_order_and_cache(diamond):
    stub, calls = make_stub()
    result = resolve_investigation(diamond, "inv1", compute_fn=stub)

    assert result["error"] is None
    order = result["order"]
    assert order.index("parca") < order.index("a")
    assert order.index("parca") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("c")

    statuses = {n["slug"]: n["status"] for n in result["nodes"]}
    assert statuses == {"parca": "computed", "a": "computed", "b": "computed", "c": "computed"}
    assert set(calls) == {"parca", "a", "b", "c"}
    assert calls.index("parca") < calls.index("a")
    assert calls.index("parca") < calls.index("b")
    assert calls.index("a") < calls.index("c")
    assert calls.index("b") < calls.index("c")


def test_second_resolve_is_all_cached(diamond):
    stub1, calls1 = make_stub()
    resolve_investigation(diamond, "inv1", compute_fn=stub1)

    stub2, calls2 = make_stub()
    result2 = resolve_investigation(diamond, "inv1", compute_fn=stub2)

    assert calls2 == []
    statuses = {n["slug"]: n["status"] for n in result2["nodes"]}
    assert statuses == {"parca": "cached", "a": "cached", "b": "cached", "c": "cached"}


def test_upstream_change_rekeys_descendants(diamond):
    stub1, calls1 = make_stub()
    resolve_investigation(diamond, "inv1", compute_fn=stub1)

    # Change a's config -> a's artifact_id changes -> c (which depends on a)
    # must recompute too; parca and b are untouched and stay cached.
    _write_study(diamond, "a", inputs_from=["parca"], config={"seed": 1})

    stub2, calls2 = make_stub()
    result2 = resolve_investigation(diamond, "inv1", compute_fn=stub2)

    statuses = {n["slug"]: n["status"] for n in result2["nodes"]}
    assert statuses["parca"] == "cached"
    assert statuses["b"] == "cached"
    assert statuses["a"] == "computed"
    assert statuses["c"] == "computed"
    assert set(calls2) == {"a", "c"}


def test_upstream_failure_skips_descendants(diamond):
    stub, calls = make_stub(fail_for=("a",))
    result = resolve_investigation(diamond, "inv1", compute_fn=stub)

    statuses = {n["slug"]: n["status"] for n in result["nodes"]}
    assert statuses["parca"] == "computed"
    assert statuses["a"] == "failed"
    assert statuses["b"] == "computed"
    assert statuses["c"] == "skipped"
    assert "c" not in calls


def test_cycle_reports_error(tmp_path, monkeypatch):
    specs = {
        "a": {"composite": "c.a", "config": {}, "outputs": [],
              "inputs": [{"artifact": "x", "from": "b"}]},
        "b": {"composite": "c.b", "config": {}, "outputs": [],
              "inputs": [{"artifact": "x", "from": "a"}]},
    }
    monkeypatch.setattr(pipeline, "_load_study_spec", lambda ws, slug: specs[slug])
    monkeypatch.setattr(pipeline, "_load_investigation_spec", lambda ws, slug: {})
    monkeypatch.setattr(pipeline, "investigation_member_slugs", lambda spec: ["a", "b"])

    stub, calls = make_stub()
    result = resolve_investigation(tmp_path, "inv1", compute_fn=stub)

    assert result["error"] is not None
    assert result["nodes"] == []
    assert calls == []


def test_force_bypasses_cache(diamond):
    stub1, calls1 = make_stub()
    resolve_investigation(diamond, "inv1", compute_fn=stub1)

    stub2, calls2 = make_stub()
    result = resolve_investigation(diamond, "inv1", compute_fn=stub2, force=True)

    assert set(calls2) == {"parca", "a", "b", "c"}
    statuses = {n["slug"]: n["status"] for n in result["nodes"]}
    assert all(s == "computed" for s in statuses.values())


def test_force_refreshes_stored_content(diamond):
    """force=True must not just relabel status "computed" — the newly
    recomputed payload has to actually land in the store, not be discarded
    by ArtifactStore.put's default idempotent early-return."""

    def write_bytes(data):
        def stub(ws_root, slug, *, artifact_id, composite, config, input_ids, out_dir,
             resolved_inputs=None):
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / "out.bin"
            p.write_bytes(data)
            return p
        return stub

    r1 = pipeline.resolve_study(diamond, "parca", compute_fn=write_bytes(b"A"))
    store = ArtifactStore(diamond)
    assert store.path(r1["artifact_id"]).read_bytes() == b"A"

    r2 = pipeline.resolve_study(diamond, "parca", compute_fn=write_bytes(b"B"), force=True)
    assert r2["artifact_id"] == r1["artifact_id"]
    assert store.path(r2["artifact_id"]).read_bytes() == b"B"


def test_non_member_producer_is_discovered_and_ordered(tmp_path):
    """`parca` is a real producer study but is NOT listed in the
    investigation's `members:` — resolve_investigation must still discover
    it (via `a`'s inputs.from), order it ahead of `a`, and resolve without
    crashing."""
    _write_study(tmp_path, "parca")
    _write_study(tmp_path, "a", inputs_from=["parca"])
    _write_study(tmp_path, "c")

    inv_dir = tmp_path / "investigations" / "inv2"
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "investigation.yaml").write_text(yaml.safe_dump({
        "name": "inv2",
        "members": ["a", "c"],
    }))

    stub, calls = make_stub()
    result = resolve_investigation(tmp_path, "inv2", compute_fn=stub)

    assert result["error"] is None
    assert "parca" in result["order"]
    assert result["order"].index("parca") < result["order"].index("a")

    statuses = {n["slug"]: n["status"] for n in result["nodes"]}
    assert statuses["parca"] == "computed"
    assert statuses["a"] == "computed"
    assert statuses["c"] == "computed"
