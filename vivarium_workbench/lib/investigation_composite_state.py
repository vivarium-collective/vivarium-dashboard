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


def _first_sentence(text: str, limit: int = 260) -> str:
    """First line/sentence of a multi-line field, trimmed to ``limit`` chars."""
    if not text:
        return ""
    s = str(text).strip().split("\n")[0].strip()
    return (s[: limit - 1] + "…") if len(s) > limit else s


def _study_status_pill(s: dict) -> "tuple[str, str]":
    """(label, color) status pill for a study, mirroring the knowledge-graph
    DAG card logic (gate verdict → lifecycle status → default 'Planned')."""
    conf = s.get("confidence")
    if conf:
        return (str(conf).title(), "#0d9488")
    gate = str(s.get("gate_status") or "").lower()
    if gate in ("passed", "pass"):
        return ("Accepted", "#16a34a")
    if gate in ("partial", "needs_calibration"):
        return ("Investigating", "#ca8a04")
    if gate in ("failed", "failed_evaluation", "refuted", "blocked"):
        return ("Refuted", "#dc2626")
    st = str(s.get("effective_status") or s.get("status") or "").lower()
    if st in ("completed", "complete", "ran"):
        return ("Accepted", "#16a34a")
    if st in ("in_progress", "running"):
        return ("Investigating", "#ca8a04")
    if st in ("failed", "invalid"):
        return ("Refuted", "#dc2626")
    return ("Planned", "#2563eb")


def _claim_status(finding, evidence, decision, conclusion) -> "tuple[str, str]":
    """(label, color) for one evidence-chain claim, mirroring aig-graph.js."""
    if conclusion and conclusion.get("lifecycle_state") == "published":
        return ("published", "#2563eb")
    if (decision and decision.get("outcome") == "reject") or (
        evidence and evidence.get("lifecycle_state") == "rejected"
    ):
        return ("refuted", "#e11d48")
    if decision and decision.get("outcome") == "accept":
        return ("accepted", "#0d9488")
    if decision and decision.get("outcome") == "defer":
        return ("partial", "#d97706")
    return ("pending", "#94a3b8")


def _group_evidence(chain: dict) -> list:
    """Group a study's evidence-chain nodes into claims for the loom study card.

    Chain node ids are ``<kind>/<claim-key>`` (kind ∈ finding/evidence/decision/
    conclusion); nodes sharing a claim-key form one claim. Returns a list of
    ``{glyphs: [[glyph, present], ...], text, status, color}`` — the four glyphs
    are ●finding ◆evidence ▣decision ★conclusion (filled when that stage exists).
    """
    from collections import OrderedDict

    groups: "OrderedDict[str, dict]" = OrderedDict()
    for n in (chain.get("nodes") or []):
        nid = n.get("id") or ""
        if "/" not in nid:
            continue
        kind, key = nid.split("/", 1)
        groups.setdefault(key, {})[kind] = n

    claims = []
    for byk in groups.values():
        finding = byk.get("finding")
        evidence = byk.get("evidence")
        decision = byk.get("decision")
        conclusion = byk.get("conclusion")
        label, color = _claim_status(finding, evidence, decision, conclusion)
        text = _first_sentence(
            (finding or {}).get("statement")
            or (conclusion or {}).get("statement")
            or (finding or {}).get("summary")
            or "",
            limit=200,
        )
        claims.append({
            "glyphs": [
                ["●", finding is not None],
                ["◆", evidence is not None],
                ["▣", decision is not None],
                ["★", conclusion is not None],
            ],
            "text": text,
            "status": label,
            "color": color,
        })
    return claims


def _enrich_study_nodes(ws_root: Path, inv_slug: str, tree: dict) -> None:
    """Best-effort: stamp knowledge-graph card metadata onto each study node in
    ``tree`` (status pill, title, Asks/Finds, evidence chain) so the loom's study
    card can render like the Investigation-graph view. Never raises."""
    try:
        from vivarium_workbench.lib.report_views import build_iset_detail
        from vivarium_workbench.lib.investigation_graph_views import (
            build_investigation_graph,
        )
    except Exception:  # noqa: BLE001
        return

    by_slug: dict = {}
    try:
        detail = build_iset_detail(ws_root, inv_slug) or {}
        for s in (detail.get("studies") or []):
            if s.get("name"):
                by_slug[s["name"]] = s
    except Exception:  # noqa: BLE001
        pass

    chains: dict = {}
    try:
        graph, _st = build_investigation_graph(ws_root, inv_slug)
        chains = (graph or {}).get("chains") or {}
    except Exception:  # noqa: BLE001
        pass

    for slug, node in tree.items():
        if not (isinstance(node, dict) and node.get("_type") == "step"):
            continue
        s = by_slug.get(slug) or {}
        label, color = _study_status_pill(s)
        finds = s.get("claim")
        findings = s.get("findings") or []
        if not finds and findings:
            f0 = findings[0] or {}
            finds = f0.get("summary") or f0.get("statement") or f0.get("id")
        node["_study_title"] = s.get("title") or slug
        node["_study_status_label"] = label
        node["_study_status_color"] = color
        node["_asks"] = _first_sentence(s.get("question") or "")
        node["_finds"] = _first_sentence(finds or "")
        node["_n_findings"] = len(findings)
        ch = chains.get(slug)
        if ch:
            ev = _group_evidence(ch)
            if ev:
                node["_evidence"] = ev
                node["_evidence_derived"] = bool(ch.get("derived"))


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

    # Stamp knowledge-graph card metadata (status/asks/finds/evidence) onto each
    # study node so the loom renders rich study cards, not bare process boxes.
    _enrich_study_nodes(ws_root, slug, tree)

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
