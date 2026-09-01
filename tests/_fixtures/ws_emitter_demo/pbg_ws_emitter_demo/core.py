from process_bigraph import allocate_core

from pbg_ws_emitter_demo.emitter import FileEmitter


def build_core():
    core = allocate_core()
    # Register under the short link name the composite's address uses
    # (``local:FileEmitter``) so rewrite_local_addresses can resolve it to the
    # full import path, and under the full dotted path too (mirroring how
    # v2ecoli.core registers its emitters both ways).
    core.register_link("FileEmitter", FileEmitter)
    core.register_link("pbg_ws_emitter_demo.emitter.FileEmitter", FileEmitter)
    return core
