"""C3: export_composite_pbg must not crash on a composite whose realized emitter
edge embeds a live, un-deep-copyable instance, and the exported .pbg must reload
into a Composite that rebuilds the emitter from address + config.

Regression guard for the P0 blocker: ``rewrite_local_addresses`` starts with
``copy.deepcopy(document)``; ``to_document`` embeds an already-constructed
emitter Step (holding a ``ThreadPoolExecutor`` whose ``_queue.SimpleQueue``
can't be pickled). Deep-copying that live instance raised
``TypeError: cannot pickle '_queue.SimpleQueue' object`` — so no ``.pbg`` was
ever written. The fix strips realized-edge fields BEFORE the rewrite's deepcopy.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

FIXTURE_WS = Path(__file__).parent / "_fixtures" / "ws_emitter_demo"
# Registry key is "<module>.<funcname>" (see process_bigraph.composite_spec).
COMPOSITE_ID = "pbg_ws_emitter_demo.composites.emitter_demo"


@pytest.fixture(autouse=True)
def _ws_on_path():
    ws = str(FIXTURE_WS)
    inserted = ws not in sys.path
    if inserted:
        sys.path.insert(0, ws)
    # Re-fire the @composite_generator decorator each test: conftest's
    # _restore_composite_spec_registry autouse fixture snapshots the registry
    # before this fixture runs and prunes emitter_demo on teardown, and the
    # module stays cached in sys.modules — so a plain import won't re-register.
    import importlib

    import pbg_ws_emitter_demo.composites as _composites
    importlib.reload(_composites)
    yield
    if inserted:
        try:
            sys.path.remove(ws)
        except ValueError:
            pass


def _find_emitter(node):
    """Return the emitter edge node anywhere in the document tree."""
    if isinstance(node, dict):
        addr = node.get("address")
        if isinstance(addr, str) and "emitter" in addr.lower():
            return node
        for v in node.values():
            found = _find_emitter(v)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_emitter(item)
            if found is not None:
                return found
    return None


def _build_core():
    from pbg_ws_emitter_demo.core import build_core

    return build_core()


def _spec():
    from process_bigraph.composite_spec import get as get_spec

    spec = get_spec(COMPOSITE_ID)
    assert spec is not None, f"generator {COMPOSITE_ID} not registered"
    return spec


def test_old_order_deepcopy_crashes_on_live_instance():
    """Documents the bug: deep-copying the un-stripped document (as the old
    rewrite-then-strip order did) fails on the live emitter instance."""
    from vivarium_workbench.lib.pbg_export import rewrite_local_addresses

    core = _build_core()
    document = _spec().to_document(overrides=None, core=core)
    em = _find_emitter(document)
    assert em is not None and em.get("instance") is not None, "fixture must embed a live instance"
    with pytest.raises(TypeError, match="pickle|deepcopy|SimpleQueue"):
        rewrite_local_addresses(document, core)  # deepcopy of live instance -> crash


def test_export_succeeds_and_strips_and_rewrites(tmp_path):
    """The fixed order writes a portable .pbg: emitter address is full-path, its
    config survives, and no realized-edge runtime fields remain."""
    from vivarium_workbench.lib.pbg_export import export_composite_pbg

    out = tmp_path / "emitter_demo.pbg"
    export_composite_pbg(
        FIXTURE_WS, COMPOSITE_ID, out, core=_build_core(),
        overrides={"out_dir": str(tmp_path / "declared")},
    )
    assert out.is_file()

    doc = json.loads(out.read_text(encoding="utf-8"))
    em = _find_emitter(doc)
    assert em is not None
    # Redirectable declaration form: full import-path address + a config dict.
    assert em["address"] == "local:!pbg_ws_emitter_demo.emitter.FileEmitter"
    assert isinstance(em["config"], dict)
    # Realized-edge runtime fields must not survive into the portable spec.
    for field in ("instance", "_inputs", "_outputs"):
        assert field not in em, f"{field} must be stripped from the exported .pbg"


def test_reloaded_composite_rebuilds_emitter_and_emits(tmp_path):
    """The real end-to-end check: reload the exported (+ redirected) .pbg into a
    Composite, confirm it rebuilds a FRESH emitter from address + config, and run
    it so the emitter writes output to the redirected dir."""
    from process_bigraph import Composite
    from vivarium_workbench.lib.pbg_export import export_composite_pbg

    core = _build_core()
    out = tmp_path / "emitter_demo.pbg"
    export_composite_pbg(
        FIXTURE_WS, COMPOSITE_ID, out, core=core,
        overrides={"out_dir": str(tmp_path / "declared")},
    )
    doc = json.loads(out.read_text(encoding="utf-8"))

    # Mirror sms-api run_pbg._redirect_emitters: inject out_dir on the file-backed
    # emitter so output lands where the container syncs from.
    redirect = tmp_path / "redirected"
    em = _find_emitter(doc)
    em.setdefault("config", {})["out_dir"] = str(redirect)

    composite = Composite(doc, core=core)  # full-path local:! resolves via importlib

    # A fresh emitter instance was rebuilt (nothing left over from the stripped one).
    from pbg_ws_emitter_demo.emitter import FileEmitter

    rebuilt = [
        v for v in _iter_instances(composite.state)
        if isinstance(v, FileEmitter)
    ]
    assert rebuilt, "Composite did not rebuild a FileEmitter from address + config"

    composite.run(2)
    written = list(redirect.glob("emit_*.json"))
    assert written, "rebuilt emitter did not write output to the redirected dir"


def _iter_instances(node):
    if isinstance(node, dict):
        inst = node.get("instance")
        if inst is not None:
            yield inst
        for v in node.values():
            yield from _iter_instances(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_instances(item)
