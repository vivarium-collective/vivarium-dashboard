"""A composite generator that embeds an already-constructed, live file-backed
emitter instance into its document — the realized-edge shape v2ecoli's
generator-declared ParquetEmitter produces via ``_build_declared_emitter`` /
``make_edge``.

The emitter edge carries a live ``instance`` (with an un-deep-copyable
``ThreadPoolExecutor``) plus realized ``_inputs`` / ``_outputs`` and a real
``config`` (``out_dir``). ``export_composite_pbg`` must strip the realized-edge
fields BEFORE deep-copying the document, then rewrite ``local:FileEmitter`` to
its full import path; the exported ``.pbg`` reloads into a fresh ``Composite``
that rebuilds the emitter from ``address`` + ``config`` alone.
"""
from __future__ import annotations

from process_bigraph.composite_generator import composite_generator

from pbg_ws_emitter_demo.emitter import FileEmitter


@composite_generator(
    name="emitter_demo",
    description="Composite with a live, un-deep-copyable file-backed emitter.",
    parameters={
        "out_dir": {"type": "string", "default": "out", "description": "Emitter output dir"},
        "initial_level": {"type": "float", "default": 1.0, "description": "Starting level"},
    },
)
def emitter_demo(core=None, out_dir="out", initial_level=1.0):
    # Build the live emitter instance up front (as v2ecoli's helper does), so the
    # returned document embeds an already-constructed Step object on the edge.
    instance = FileEmitter(config={"out_dir": out_dir}, core=core)
    emitter_edge = {
        "priority": 1.0,
        "_type": "step",
        # Short local address; export rewrites it to local:!<module>.<qualname>.
        "address": "local:FileEmitter",
        "config": {"out_dir": out_dir},
        # Realized-edge runtime fields that must be stripped for a portable spec.
        "_inputs": {"level": "float"},
        "_outputs": {},
        "instance": instance,
        "inputs": {"level": ["stores", "level"]},
        "outputs": {},
    }
    return {
        "state": {
            "stores": {"level": initial_level},
            "emitter": emitter_edge,
        }
    }
