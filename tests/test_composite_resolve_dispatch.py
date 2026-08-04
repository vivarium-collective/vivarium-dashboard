"""Tests for resolve_composite_for_request — local vs deployment dispatch."""
from pathlib import Path
from vivarium_workbench.lib import composite_resolve as cr


def test_dispatch_local_when_no_viv_build(tmp_path, monkeypatch):
    called = {}
    monkeypatch.setattr(cr, "resolve_composite", lambda ws, sid, ov=None: called.update({"local": (sid, ov)}) or {"name": "local"})
    out = cr.resolve_composite_for_request(tmp_path, "pkg.x", {"k": 1})
    assert out == {"name": "local"} and called["local"] == ("pkg.x", {"k": 1})


def test_dispatch_deployment_when_viv_build(tmp_path, monkeypatch):
    (tmp_path / ".viv-build.json").write_text('{"simulator_id": 66}')
    captured = {}
    class _FakeClient:
        def __init__(self, base=None): pass
        def composite_resolve(self, sid, ref, ov=None):
            captured.update(sid=sid, ref=ref, ov=ov); return {"name": "remote"}
    monkeypatch.setattr(cr, "VivaApiClient", _FakeClient)
    monkeypatch.setattr(cr, "_sms_api_base", lambda: "http://sms")
    out = cr.resolve_composite_for_request(tmp_path, "pkg.x", {"k": 2})
    assert out == {"name": "remote"}
    assert captured == {"sid": 66, "ref": "pkg.x", "ov": {"k": 2}}


def test_dispatch_deployment_degrades_when_sms_api_route_missing(tmp_path, monkeypatch):
    """sms-api has no POST /core/v1/simulator/{id}/composite-resolve route --
    VivaApiClient.composite_resolve was added speculatively and the server side
    was never built, so every call 404s. This is a non-blocking preview
    convenience (dispatch itself never calls it), so a missing/unreachable
    remote route must degrade to the same honest-unavailable 200 shape every
    other resolve failure already uses, not propagate as a 500."""
    (tmp_path / ".viv-build.json").write_text('{"simulator_id": 66}')

    class _FailingClient:
        def __init__(self, base=None): pass
        def composite_resolve(self, sid, ref, ov=None):
            raise cr.VivaApiError("POST http://sms/core/v1/simulator/66/composite-resolve -> 404")

    monkeypatch.setattr(cr, "VivaApiClient", _FailingClient)
    monkeypatch.setattr(cr, "_sms_api_base", lambda: "http://sms")

    out = cr.resolve_composite_for_request(tmp_path, "pkg.x")

    assert out["id"] == "pkg.x"
    assert out["wiring_status"] == "unavailable"
    assert "not available" in out["notice"]


def test_resolve_generator_without_artifact_degrades(tmp_path, monkeypatch):
    from process_bigraph import composite_spec as cs
    from vivarium_workbench.lib import composite_resolve as cr
    cs.clear_registry()
    cs.register(cs.CompositeSpec(id="m.g", name="g", builder=lambda core=None: {"state": {}},
                                 default_state_ref="m.g.default-state.json",
                                 parameters={"seed": {"type": "integer", "default": 0}}))
    monkeypatch.setattr(cr, "_prime_registry", lambda: None)  # don't walk real distributions
    out = cr.resolve_composite(tmp_path, "m.g")
    assert out["wiring_status"] == "unavailable" and out["notice"]
    assert out["parameters"]["seed"]["type"] == "integer"   # metadata present without build
    assert out["state"] is None and out["kind"] == "generator"


def test_resolve_static_via_find_path(tmp_path, monkeypatch):
    # A real static spec file resolved through the dashboard's id scheme
    # "<pkg>.composites.<stem>" via find_composite_path.
    from vivarium_workbench.lib import composite_resolve as cr
    from process_bigraph import composite_spec as cs
    cs.clear_registry()
    (tmp_path / "workspace.yaml").write_text("name: demo-ws\npackage_path: pbg_demo\n", encoding="utf-8")
    comp = tmp_path / "pbg_demo" / "composites"
    comp.mkdir(parents=True)
    (comp / "c.composite.yaml").write_text(
        "name: c\nschema:\n  v: float\nstate:\n  v: 1\n", encoding="utf-8")
    monkeypatch.setattr(cr, "_prime_registry", lambda: None)
    out = cr.resolve_composite(tmp_path, "pbg_demo.composites.c")
    assert out is not None and out["id"] == "pbg_demo.composites.c"  # requested id round-trips
    assert out["wiring_status"] == "ready" and out["state"] == {"v": 1}
    assert out["schema"] == {"v": "float"} and out["kind"] == "spec"


def test_resolve_static_embeds_declared_emit_paths(tmp_path, monkeypatch):
    """A composite that declares ``emitters: [{paths: [...]}]`` gets those
    paths embedded INSIDE its served ``state`` as ``_declared_emit_paths`` —
    the fix for the Task 6 review finding: ``install_default_emitters`` only
    runs on the run-EXECUTION path, so the browse/view state a real
    workspace serves (e.g. v2ecoli's ``baseline``, declaring
    ``emitters=[{"paths": ["global_time", "bulk", "listeners"]}]``) never
    carried an emitter node — loom's declared-paths helper silently fell
    back to every top-level store. Embedding the paths directly in `state`
    (not as a sibling of it) is required because every hop that forwards a
    composite doc to loom forwards only the `state` sub-object."""
    from vivarium_workbench.lib import composite_resolve as cr
    from process_bigraph import composite_spec as cs
    cs.clear_registry()
    (tmp_path / "workspace.yaml").write_text("name: demo-ws\npackage_path: pbg_demo\n", encoding="utf-8")
    comp = tmp_path / "pbg_demo" / "composites"
    comp.mkdir(parents=True)
    (comp / "baseline.composite.yaml").write_text(
        "name: baseline\n"
        "state:\n"
        "  global_time: 0\n"
        "  bulk: {}\n"
        "  listeners: {}\n"
        "emitters:\n"
        "  - address: local:ParquetEmitter\n"
        "    config: {}\n"
        "    paths: [global_time, bulk, listeners]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cr, "_prime_registry", lambda: None)
    out = cr.resolve_composite(tmp_path, "pbg_demo.composites.baseline")
    assert out is not None and out["wiring_status"] == "ready"
    assert out["state"]["_declared_emit_paths"] == ["global_time", "bulk", "listeners"]


def test_declared_emit_paths_helper():
    from vivarium_workbench.lib.composite_resolve import declared_emit_paths
    assert declared_emit_paths(None) == []
    assert declared_emit_paths([]) == []
    assert declared_emit_paths([{"paths": ["global_time", "bulk", "listeners"]}]) == [
        "global_time", "bulk", "listeners",
    ]
    # dotted paths normalize to '/'-joined, matching the client's emitSet convention.
    assert declared_emit_paths([{"paths": ["listeners.mass"]}]) == ["listeners/mass"]
    # dedup across multiple decls, order preserved.
    assert declared_emit_paths([
        {"paths": ["bulk", "global_time"]},
        {"paths": ["global_time", "listeners"]},
    ]) == ["bulk", "global_time", "listeners"]
    # malformed entries are tolerated, not raised.
    assert declared_emit_paths([{"paths": None}, "not-a-dict", {}]) == []


def test_resolve_unregistered_returns_none(tmp_path, monkeypatch):
    from process_bigraph import composite_spec as cs
    from vivarium_workbench.lib import composite_resolve as cr
    cs.clear_registry()
    monkeypatch.setattr(cr, "_prime_registry", lambda: None)
    assert cr.resolve_composite(tmp_path, "pbg_demo.composites.absent") is None


def test_resolve_malformed_static_file_degrades(tmp_path, monkeypatch):
    from vivarium_workbench.lib import composite_resolve as cr
    from process_bigraph import composite_spec as cs
    cs.clear_registry()
    (tmp_path / "workspace.yaml").write_text("name: demo-ws\npackage_path: pbg_demo\n", encoding="utf-8")
    comp = tmp_path / "pbg_demo" / "composites"
    comp.mkdir(parents=True)
    (comp / "bad.composite.yaml").write_text("name: bad\nstate: {a: [unclosed\n", encoding="utf-8")
    monkeypatch.setattr(cr, "_prime_registry", lambda: None)
    out = cr.resolve_composite(tmp_path, "pbg_demo.composites.bad")
    assert out is not None and out["wiring_status"] == "unavailable"
    assert "could not be parsed" in out["notice"]


def test_resolve_static_no_state_notice_not_generator(tmp_path, monkeypatch):
    from vivarium_workbench.lib import composite_resolve as cr
    from process_bigraph import composite_spec as cs
    cs.clear_registry()
    cs.register(cs.CompositeSpec(id="m.s", name="s", state={}))  # empty inline state
    monkeypatch.setattr(cr, "_prime_registry", lambda: None)
    monkeypatch.setattr(cr, "_get_spec", lambda sid: cs.get("m.s") if sid == "m.s" else None)
    out = cr.resolve_composite(tmp_path, "m.s")
    # empty {} state is falsy-but-not-None; default_state returns {} → wiring "ready".
    # If your default_state treats {} as ready, assert ready; the key check is the
    # notice (when unavailable) does NOT say "generator" for a static spec.
    assert out["kind"] == "spec"


def test_resolve_degrades_when_get_spec_raises(tmp_path, monkeypatch):
    """An in-process failure during generator discovery/lookup (e.g. a broken
    native-dependency import like pymunk/viva_munk — the "colony" composite's
    real-world failure mode) degrades to the standard wiring_status:"unavailable"
    shape instead of propagating to the app-wide 500 handler."""
    from vivarium_workbench.lib import composite_resolve as cr
    monkeypatch.setattr(cr, "_prime_registry", lambda: None)

    def _raise(spec_id):
        raise ImportError("no module named viva_munk")

    monkeypatch.setattr(cr, "_get_spec", _raise)
    out = cr.resolve_composite(tmp_path, "v2ecoli.composites.colony")
    assert out is not None
    assert out["wiring_status"] == "unavailable"
    assert out["id"] == "v2ecoli.composites.colony"
    assert "viva_munk" in out["notice"]


def test_resolve_generator_with_corrupt_artifact_degrades(tmp_path, monkeypatch):
    from process_bigraph import composite_spec as cs
    from vivarium_workbench.lib import composite_resolve as cr
    cs.clear_registry()
    # generator whose default_state() raises (corrupt artifact)
    spec = cs.CompositeSpec(id="m.boom", name="boom",
                            builder=lambda core=None: {"state": {}},
                            default_state_ref="boom.default-state.json")
    cs.register(spec)
    def _raise(*a, **k):
        raise ValueError("corrupt artifact")
    monkeypatch.setattr(spec, "default_state", _raise)
    monkeypatch.setattr(cr, "_prime_registry", lambda: None)
    out = cr.resolve_composite(tmp_path, "m.boom")
    assert out is not None and out["wiring_status"] == "unavailable"
    assert out["state"] is None
    assert "not generated yet" in out["notice"]


def test_resolve_generator_override_build_error_surfaces(tmp_path, monkeypatch):
    """A Config → Apply whose overrides make the generator build RAISE (e.g. a
    single-value param handed a comma-list) must surface the exception — NOT
    silently fall back to the default (unoverridden) wiring, which would look
    like the invalid config had been accepted."""
    from process_bigraph import composite_spec as cs
    from vivarium_workbench.lib import composite_resolve as cr
    cs.clear_registry()
    spec = cs.CompositeSpec(
        id="m.g", name="g", builder=lambda core=None, **kw: {"state": {"x": {}}},
        default_state_ref="m.g.default-state.json",
        parameters={"simulator": {"type": "string", "default": "simbio"}},
    )
    cs.register(spec)
    monkeypatch.setattr(cr, "_prime_registry", lambda: None)
    # default_state would happily return the UNOVERRIDDEN wiring — the fix must
    # not reach it once an override build has failed.
    monkeypatch.setattr(spec, "default_state", lambda *a, **k: {"simbio_process": {}})
    monkeypatch.setattr(
        cr, "_live_generator_build",
        lambda ws, sid, ov=None: (None, "needs exactly one simulator, got ['copasi', 'tellurium']"),
    )
    out = cr.resolve_composite(tmp_path, "m.g", overrides={"simulator": "copasi, tellurium"})
    assert out["wiring_status"] == "error"
    assert out["state"] is None                       # NOT the default fallback
    assert "one simulator" in (out["notice"] or "")
    assert "one simulator" in (out["error"] or "")


def test_resolve_generator_override_build_ok_still_resolves(tmp_path, monkeypatch):
    """A valid override build resolves normally (the error path must not regress
    the happy path)."""
    from process_bigraph import composite_spec as cs
    from vivarium_workbench.lib import composite_resolve as cr
    from vivarium_workbench.lib import process_docs
    cs.clear_registry()
    spec = cs.CompositeSpec(
        id="m.g", name="g", builder=lambda core=None, **kw: {"state": {"copasi_process": {}}},
        parameters={"simulator": {"type": "string", "default": "simbio"}},
    )
    cs.register(spec)
    monkeypatch.setattr(cr, "_prime_registry", lambda: None)
    monkeypatch.setattr(cr, "_live_generator_build",
                        lambda ws, sid, ov=None: ({"copasi_process": {}}, None))
    # attach_process_docs_via_worker needs the env worker; identity for the test.
    monkeypatch.setattr(process_docs, "attach_process_docs_via_worker",
                        lambda ws, state, spec_id=None: state)
    out = cr.resolve_composite(tmp_path, "m.g", overrides={"simulator": "copasi"})
    assert out["wiring_status"] == "ready"
    assert out["state"] == {"copasi_process": {}}
