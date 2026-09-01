"""Single source of truth for the analysis-tool capability vocabulary.

A *capability* is a lowercase tag a run/study advertises about the data it
produced. Tools declare a ``requires`` list of these tags; the matcher pairs a
tool with a run/study when ``set(requires) <= set(capabilities)``.

Two sources of tags:
  * store-derived — from a run's emitted leaves (see lib/run_capabilities.py),
    reusing the explorer's leaf categorisation (lib/explorer_data._categorize_leaves).
  * artifact-sourced — from workspace files (e.g. 3D packs on disk / hosted).
"""
from __future__ import annotations

CAPABILITY_TAGS: dict[str, str] = {
    "observables": "run has a readable store with at least one emitted leaf",
    "mass": "run emits cell-mass observables",
    "bulk_counts": "run emits bulk molecule counts",
    "fluxes": "run emits reaction fluxes / FBA results",
    "listeners": "run emits listener observables",
    "growth_division": "run emits growth & division observables",
    "3d_pack": "study has a 3D molecular pack (viz/3d/*.pack.json or hosted)",
    "atlas_pack": "study has an HRA atlas pack (viz/atlas/atlas.json) — its run's output that an atlas viewer consumes as input",
    "simularium": "study has a Simularium trajectory (viz/**/*.simularium) an agent-based analysis produced",
}

# lib/explorer_data._categorize_leaves bucket name -> capability tag.
CATEGORY_TO_TAG: dict[str, str] = {
    "Mass": "mass",
    "Bulk molecules": "bulk_counts",
    "Fluxes": "fluxes",
    "Listeners": "listeners",
    "Growth & division": "growth_division",
}
