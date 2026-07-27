"""Derive typed chain nodes from a study's existing result fields (RFC-0002 B2).

Read-time view: lifts each ``conclusion_verdicts[]`` entry into a deterministic
Finding->Evidence->Decision->Conclusion micro-chain (verdict + gate_status drive
the lifecycle states) and each ``findings.entries[]`` into a Finding node. Pure:
no I/O, no clock, no randomness. Every node is stamped ``provenance.actor =
"derived"`` so a lifted chain is never mistaken for a human-gated one. By
construction every emitted chain passes ``investigation_contracts.validate_chain``.
"""
from __future__ import annotations

_DECISION_OUTCOME = {"supported": "accept", "refuted": "reject", "partial": "defer"}
_EVIDENCE_STATE = {"accept": "accepted", "reject": "rejected", "defer": "proposed"}
_STATUS_VERDICT = {"confirms": "supported", "contradicts": "refuted",
                   "partial": "partial", "inconclusive": "partial"}


def _prov(slug: str, source: str) -> dict:
    return {"actor": "derived", "agent_id": "chain-derivation", "timestamp": "",
            "source_objects": [f"study/{slug}"],
            "justification": f"derived from study.yaml {source}",
            "tool": "b2/chain-derivation", "commit": ""}


def _prov_computed(slug: str, source: str) -> dict:
    """Provenance for a chain lifted from a COMPUTED report-card verdict
    artifact (Phase 2d), as opposed to authored study.yaml fields. Keeps
    ``actor="derived"`` — a computed-from-artifact chain is still
    non-human-gated, and reusing the proven shape keeps
    ``investigation_contracts.validate_chain`` happy; the distinguishing
    signal is ``justification``/``tool``, not ``actor``.
    """
    return {"actor": "derived", "agent_id": "report-card-evidence", "timestamp": "",
            "source_objects": [f"study/{slug}"],
            "justification": f"computed from report-card verdict {source}",
            "tool": "2d/report-card-evidence", "commit": ""}


def _lift_finding_list(findings, slug: str, *, id_tag: str, prov) -> dict[str, dict]:
    """Lift a list of ``{statement, status, evidence:{observed}}`` findings into
    the deterministic Finding->Evidence(->Decision->Conclusion) micro-chain.

    Shared by the authored v4-``findings``-list path (``id_tag="fl"``) and the
    computed report-card path (``id_tag="rc"``, Phase 2d) — identical node
    shape, so both pass ``validate_chain`` by construction. ``prov(raw_j, fe)``
    returns the provenance dict for a raw entry. Pure — no I/O.
    """
    nodes: dict[str, dict] = {}
    k = 0
    for raw_j, fe in enumerate(findings):
        if not (isinstance(fe, dict) and str(fe.get("statement", "")).strip()):
            continue
        claim = str(fe["statement"]).strip()
        ev = fe.get("evidence") if isinstance(fe.get("evidence"), dict) else {}
        basis = str(ev.get("observed") or claim).strip()
        verdict = _STATUS_VERDICT.get(str(fe.get("status", "")).strip().lower(), "")
        fid, eid = f"finding/derived-{slug}-{id_tag}{k}", f"evidence/derived-{slug}-{id_tag}{k}"
        did, cid = f"decision/derived-{slug}-{id_tag}{k}", f"conclusion/derived-{slug}-{id_tag}{k}"
        p = prov(raw_j, fe)
        # The finding's status IS the verdict for these studies (they use
        # confidence/status rather than a separate gate), so derive the
        # decision directly from it rather than gating on gate_status.
        outcome = _DECISION_OUTCOME.get(verdict)
        ev_state = _EVIDENCE_STATE.get(outcome, "proposed") if outcome else "proposed"
        nodes[fid] = {"id": fid, "type": "finding", "lifecycle_state": "asserted",
                      "owner": "derived", "provenance": p,
                      "validation_status": "derived",
                      "statement": claim, "runs": [f"run/{slug}"]}
        nodes[eid] = {"id": eid, "type": "evidence", "lifecycle_state": ev_state,
                      "owner": "derived", "provenance": p,
                      "validation_status": "derived",
                      "findings": [fid], "hypotheses": [f"hyp/derived-{slug}-{id_tag}{k}"],
                      "confidence": 0.0, "statement": basis}
        if outcome:
            nodes[did] = {"id": did, "type": "decision", "lifecycle_state": "recorded",
                          "owner": "derived", "provenance": p,
                          "validation_status": "derived",
                          "evidence": [eid], "outcome": outcome,
                          "rationale": basis, "decided_by": "chain-derivation"}
        if verdict == "supported":
            nodes[cid] = {"id": cid, "type": "conclusion", "lifecycle_state": "published",
                          "owner": "derived", "provenance": p,
                          "validation_status": "derived",
                          "evidence": [eid], "decisions": [did], "hypotheses": [],
                          "statement": claim}
        k += 1
    return nodes


def lift_report_card_findings(findings, slug: str) -> dict[str, dict]:
    """Lift COMPUTED report-card findings (Phase 2d) into typed chain nodes.

    ``findings`` is the list from
    ``study_spec.report_card_findings_for_study`` — each entry already carries
    ``{statement, status, evidence:{observed}}`` (the same shape the authored
    v4 ``findings`` list uses), where ``status`` came from the report card's
    machine-readable ``verdict.json`` (``within_tol->confirms``,
    ``drift->partial``, ``mismatch->contradicts``, ``ungraded->novel``). The
    caller performs the verdict.json I/O; this function is pure. Node ids use
    the ``rc`` tag to stay distinct from authored ``fl``/``cv``/``fe`` chains.
    """
    if not isinstance(findings, list):
        return {}
    return _lift_finding_list(
        findings, slug, id_tag="rc",
        prov=lambda raw_j, fe: _prov_computed(slug, str(fe.get("id") or f"[{raw_j}]")))


def derive_chain_nodes(study_spec: dict, slug: str) -> dict[str, dict]:
    nodes: dict[str, dict] = {}
    gate = str((study_spec or {}).get("gate_status", "")).strip().lower()
    passed = gate in ("passed", "pass")

    raw = (study_spec or {}).get("conclusion_verdicts")
    raw_list = raw if isinstance(raw, list) else []
    i = 0  # filtered index -> drives node ids (stable, matches tests)
    for raw_j, cv in enumerate(raw_list):
        if not (isinstance(cv, dict) and str(cv.get("claim", "")).strip()):
            continue
        claim = str(cv["claim"]).strip()
        basis = str(cv.get("basis") or claim).strip()
        verdict = str(cv.get("verdict", "")).strip().lower()
        fid, eid = f"finding/derived-{slug}-cv{i}", f"evidence/derived-{slug}-cv{i}"
        did, cid = f"decision/derived-{slug}-cv{i}", f"conclusion/derived-{slug}-cv{i}"
        src = f"conclusion_verdicts[{raw_j}]"  # raw index -> provenance justification

        outcome = _DECISION_OUTCOME.get(verdict) if passed else None
        ev_state = _EVIDENCE_STATE.get(outcome, "proposed") if outcome else "proposed"

        nodes[fid] = {"id": fid, "type": "finding", "lifecycle_state": "asserted",
                      "owner": "derived", "provenance": _prov(slug, src),
                      "validation_status": "derived",
                      "statement": claim, "runs": [f"run/{slug}"]}
        nodes[eid] = {"id": eid, "type": "evidence", "lifecycle_state": ev_state,
                      "owner": "derived", "provenance": _prov(slug, src),
                      "validation_status": "derived",
                      "findings": [fid], "hypotheses": [f"hyp/derived-{slug}-cv{i}"],
                      "confidence": 0.0, "statement": basis}
        if outcome:
            nodes[did] = {"id": did, "type": "decision", "lifecycle_state": "recorded",
                          "owner": "derived", "provenance": _prov(slug, src),
                          "validation_status": "derived",
                          "evidence": [eid], "outcome": outcome,
                          "rationale": basis, "decided_by": "chain-derivation"}
        if verdict == "supported" and passed:
            nodes[cid] = {"id": cid, "type": "conclusion", "lifecycle_state": "published",
                          "owner": "derived", "provenance": _prov(slug, src),
                          "validation_status": "derived",
                          "evidence": [eid], "decisions": [did], "hypotheses": [],
                          "statement": claim}
        i += 1

    findings = (study_spec or {}).get("findings")
    entries = findings.get("entries") if isinstance(findings, dict) else None
    if isinstance(entries, list):
        for j, fe in enumerate(entries):
            if not isinstance(fe, dict):
                continue
            stmt = str(fe.get("description") or fe.get("signature") or "").strip()
            if not stmt:
                continue
            fid = f"finding/derived-{slug}-fe{j}"
            nodes[fid] = {"id": fid, "type": "finding", "lifecycle_state": "asserted",
                          "owner": "derived", "provenance": _prov(slug, f"findings.entries[{j}]"),
                          "validation_status": "derived",
                          "statement": stmt, "runs": [f"run/{slug}"]}

    # v4 studies carry findings as a LIST of {statement, status, evidence:{...}}
    # (not the {entries:[...]} dict shape above). Lift each into the SAME
    # Finding->Evidence->Decision(->Conclusion) micro-chain the conclusion_verdicts
    # path emits — sourced from the finding's status (confirms/contradicts/partial)
    # — so these investigations' cards populate the Evidence chain like the others.
    if isinstance(findings, list):
        nodes.update(_lift_finding_list(
            findings, slug, id_tag="fl",
            prov=lambda raw_j, fe: _prov(slug, f"findings[{raw_j}]")))
    return nodes
