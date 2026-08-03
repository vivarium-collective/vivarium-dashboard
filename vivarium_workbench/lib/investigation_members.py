"""Shared helper for reading an investigation's member-study list.

``study-registry-migration`` moved an investigation's member-study list from
the `studies:` key to `members:` (nested studies -> top-level registry +
investigations-as-members). Every reader of an ``investigation.yaml`` spec's
member-study list must accept both keys so pre- and post-migration
investigations behave identically.

Pure leaf module (stdlib only) so any ``lib/`` reader can import it without
risking an import cycle.
"""

from __future__ import annotations

from typing import Any


def investigation_member_slugs(spec: dict[str, Any]) -> list:
    """Return an investigation spec's member-study list.

    Reads `studies:` (pre-migration) if present and non-empty, else falls
    back to `members:` (post-migration). Safe superset: `members` is only
    consulted when `studies` is absent/empty, so a spec that (transitionally)
    carries both keeps `studies` as the authoritative list. List items may be
    bare slug strings or dicts (``{study|slug|name: ...}``) depending on the
    call site — this helper does not normalize item shape, only which key is
    read.
    """
    if not isinstance(spec, dict):
        return []
    return list(spec.get("studies") or spec.get("members") or [])


def member_slug(entry: Any) -> str | None:
    """Normalize one member-list entry (a bare slug string or a
    ``{study|slug|name: ...}`` dict, per ``investigation_member_slugs``) to its
    slug string, or ``None`` if unresolvable."""
    if isinstance(entry, str):
        return entry or None
    if isinstance(entry, dict):
        return entry.get("study") or entry.get("slug") or entry.get("name")
    return None
