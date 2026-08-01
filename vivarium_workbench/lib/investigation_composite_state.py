"""Lower an investigation to a composite bigraph state for the embedded loom.

An investigation IS a composite (the process-bigraph template model): its member
studies are the nodes, wired to the studies they depend on. This module
synthesizes that composite ``{state}`` so the SAME loom that renders a composite
or a study renders the investigation as a GRAPH of member studies — each node
marked ``is_composite_process`` (the exact flag the loom's drill-in reads) so
drilling a study node reveals that study's own composite (its subcomposites).

The drill is served by extending ``/api/composite-inner-state`` to accept an
``investigation:<slug>`` root ref (see ``composite_state_views``): the first hop
is the clicked study node (its bigraph path is ``[<study slug>]``); we resolve
that study to its composite and hand any deeper hops to the normal
inner-composite walk on the study's composite generator — so drilling keeps
working "all the way down".
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from vivarium_workbench.lib.investigation_composite import (
    InvestigationCompositeError,
    build_investigation_document,
)
from vivarium_workbench.lib.study_composite_state import resolve_study_composite


def build_investigation_composite_state(
    ws_root: Path | str, inv_slug: str
) -> Tuple[dict, int]:
    """``(payload, status)`` — the investigation as a composite ``{state}``.

    Each member study becomes one top-level node (``_type: step``, address
    ``local:<study composite>``, ``is_composite_process: True``) wired to the
    studies it depends on through a per-producer results store, so the loom draws
    the dependency DAG. The envelope mirrors ``/api/composite-state`` so the card
    + loom render it unchanged; the double-nested ``state.state`` matches a
    process-bigraph composite document (tree under ``state``).
    """
    ws_root = Path(ws_root)
    slug = (inv_slug or "").strip()
    if not slug:
        return {"error": "investigation slug required"}, 400
    try:
        doc = build_investigation_document(ws_root, slug)
    except InvestigationCompositeError as e:
        return {"error": str(e), "unresolved": True, "ref": slug}, 404
    except Exception as e:  # noqa: BLE001 — surface, don't crash the route
        return {"error": f"investigation lower failed: {e}"}, 500

    tree: dict = {}
    for member_slug, region in doc.items():
        study = (region or {}).get("_study") or {}
        comp = study.get("id") or member_slug
        out_store = f"{member_slug}__results"
        tree.setdefault(out_store, {})
        inputs: dict = {}
        for edge in (study.get("inputs") or []):
            producer = edge.get("from")
            if not producer:
                continue
            artifact = edge.get("artifact") or producer
            tree.setdefault(f"{producer}__results", {})
            # Wire this study's input to the producer study's results store →
            # the loom renders a producer→consumer dependency edge.
            inputs[artifact] = [f"{producer}__results"]
        tree[member_slug] = {
            "_type": "step",
            "address": f"local:{comp}",
            # Each member study IS a composite → mark it drillable. The loom reads
            # this flag verbatim (it never re-derives it from the address, which
            # points at a generator, not a registered process class).
            "is_composite_process": True,
            "inputs": inputs,
            "outputs": {"results": [out_store]},
            "_study_id": comp,
            "_study_kind": study.get("kind"),
        }

    payload = {
        "state": {"state": tree, "_declared_emit_paths": []},
        "kind": "investigation",
        "investigation": slug,
    }
    return payload, 200


def build_investigation_inner_state(
    ws_root: Path | str, inv_slug: str, hops: List[List[str]]
) -> Tuple[dict, int]:
    """Drill resolution for an ``investigation:<slug>`` root ref.

    ``hops[0]`` is the clicked study node's bigraph path — its last segment is the
    study slug. Resolve that study to its composite: a single hop returns the
    study's composite state (its subcomposites); deeper hops delegate to the
    normal inner-composite walk on the study's composite generator.
    """
    from vivarium_workbench.lib import composite_state_views as _views

    if not hops or not hops[0]:
        return {"error": "investigation drill requires a study hop"}, 400
    study_slug = hops[0][-1]
    resolved = resolve_study_composite(ws_root, study_slug)
    if resolved is None:
        return {"error": f"study not resolvable: {study_slug}", "unresolved": True}, 404
    study_ref, config = resolved

    if len(hops) == 1:
        body, status = _views.build_composite_state(
            ws_root, study_ref, overrides=config or None
        )
        if status != 200:
            return body, status
        return {"state": body.get("state"), "kind": "inner", "crumbs": [study_slug]}, 200

    # Deeper: walk the remaining hops into the study's own composite generator.
    body, status = _views.build_inner_composite_state(ws_root, study_ref, hops[1:])
    if status == 200 and isinstance(body, dict):
        body["crumbs"] = [study_slug] + list(body.get("crumbs") or [])
    return body, status
