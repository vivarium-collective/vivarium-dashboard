"""Store-derived capability tags for one simulation run.

Best-effort and pure: opens the run's store via the existing explorer reader,
maps present leaf-categories to tags, and returns a sorted tag list. Any read
failure or empty store yields ``[]`` (such a run matches no tool).
"""
from __future__ import annotations

from vivarium_workbench.lib import explorer_data
from vivarium_workbench.lib.capabilities import CATEGORY_TO_TAG


def derive_capabilities(db_path, run_id=None, workspace=None) -> list[str]:
    try:
        obs = explorer_data.list_observables(db_path, run_id, workspace)
    except Exception:  # noqa: BLE001 — unreadable store -> no capabilities
        return []
    categories = (obs or {}).get("categories") or {}
    tags: set[str] = set()
    for name, leaves in categories.items():
        if not leaves:
            continue
        tags.add("observables")
        tag = CATEGORY_TO_TAG.get(name)
        if tag:
            tags.add(tag)
    return sorted(tags)
