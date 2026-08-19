"""Regression: a local workspace's own ``@composite_generator`` id must resolve.

The package-wide ``discover_generators()`` in ``_prime_registry`` walks a fixed
set of bigraph packages and does not reach a local workspace's own
``<pkg>.composites.*`` modules. Before the fix, a generator id like
``pbg_cpm_studies.composites.chemotaxis.recruitment`` therefore stayed
unregistered, ``composite_spec.get`` returned ``None``, the resolve fell through
to the static-file branch (a miss, since it is a generator not a file), and the
Model tab showed *Could not resolve "…"*. ``resolve_composite`` now imports the
module the id names so its decorator registers, then retries.
"""
import sys

from vivarium_workbench.lib import composite_resolve as cr


def _write_generator_module(tmp_path, module_name="wsgen_mod", gen_name="mygen"):
    """A minimal importable module that registers a generator on import,
    standing in for a workspace's decorated ``@composite_generator``."""
    (tmp_path / f"{module_name}.py").write_text(
        "from process_bigraph import composite_spec as cs\n"
        f"cs.register(cs.CompositeSpec(id={module_name!r} + '.' + {gen_name!r},\n"
        f"                             name={gen_name!r},\n"
        "                             builder=lambda core=None: {'state': {}}))\n",
        encoding="utf-8",
    )
    return f"{module_name}.{gen_name}"


def test_resolve_imports_workspace_generator_module(tmp_path, monkeypatch):
    from process_bigraph import composite_spec as cs
    cs.clear_registry()
    sid = _write_generator_module(tmp_path)
    # Simulate the real gap: the package-wide prime does NOT register this id.
    monkeypatch.setattr(cr, "_prime_registry", lambda: None)
    # A live build is out of scope for this test; give the generator any state.
    monkeypatch.setattr(cr, "_live_generator_state", lambda ws, i: {"store": {}})
    monkeypatch.setattr(cr, "_committed_default_state", lambda ws, i: None)

    # tmp_path is the workspace root; resolve_composite adds it to sys.path.
    out = cr.resolve_composite(tmp_path, sid)
    assert out is not None, "generator id should resolve after its module is imported"
    assert out["id"] == sid
    assert out["kind"] == "generator"
    # cleanup the import so the module doesn't leak into other tests
    sys.modules.pop("wsgen_mod", None)
    cs.clear_registry()


def test_prime_generator_module_returns_false_for_bare_id():
    # A bare registry name (no dot) has no module to import.
    assert cr._prime_generator_module("recruitment") is False


def test_prime_generator_module_returns_false_for_unimportable_module():
    assert cr._prime_generator_module("no_such_pkg.no_such_mod.gen") is False
