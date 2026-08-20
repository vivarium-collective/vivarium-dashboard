"""Emitter-type classification helpers used by the dashboard's Simulations DB.

De-vendored in Phase 2.1a: the plugin's canonical copy of this module was
deleted in Phase 2.0, so this is now the only copy.

The workspace-wide run listing itself is owned by
``vivarium_workbench.lib.simulations_index.list_simulations``; these helpers
just classify an emitter store path into its canonical type label and are
reused by the ``GET /api/simulations`` handler to tag each sim's emitter_type.
"""
from __future__ import annotations


def emitter_type_of(emitter_path: str | None) -> str:
    p = str(emitter_path or "").lower()
    if ".zarr" in p:
        return "XArray"
    if ".parquet" in p:
        return "Parquet"
    return "SQLite"

