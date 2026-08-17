"""``GET /api/study-test-audit`` worker — Assurance › Audit "Sufficiency" group.

Study-spine reorg (spec §3.7, plan Task 3): "is the bar high enough to
trust?" starts with sufficiency — is the study's OWN Test set rigorous
enough that passing it means something (bands not trivially wide, every
claimed mechanism actually tested, no redundant coverage masquerading as
breadth, a discriminating control, bands with cited provenance)? That is
:func:`viva_superpowers.test_audit.build_audit_report`, already used by
``/viva-audit-tests`` to gate a Test set before it is locked — this worker
is the read-only seam that surfaces the SAME report on the page, plus
:func:`viva_superpowers.test_audit.audit_gate`'s pass/warn/fail rollup.

Mirrors :mod:`vivarium_workbench.lib.rigor_views` / :mod:`.audit_views`'s
contract exactly: ``build_study_test_audit(ws_root, slug) -> (body, status)``.
400 when ``?study=`` is missing; 404 when no study.yaml/spec.yaml exists for
the slug. Never a 500: an unimportable ``viva_superpowers.test_audit`` (the
workbench pins pbg-superpowers bare from PyPI — ``test_audit`` only lights up
once a viva-superpowers release/pin includes it, same caveat as
``study_audit``) or any scoring failure degrades to a 200 body
``{"unavailable": true, "reason": ...}`` — never a fabricated empty report
(spec §2 R2, "absent != empty").
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def build_study_test_audit(ws_root: Path, slug: Optional[str]) -> tuple[dict, int]:
    """Worker for ``GET /api/study-test-audit?study=<slug>`` → ``(body, status)``.

    200 with the ``report_card_verdict/v2`` sufficiency report
    (``schema``/``model_ref``/``overall``/``groups``) plus a top-level
    ``gate`` key (``"pass"``/``"warn"``/``"fail"``, from
    :func:`viva_superpowers.test_audit.audit_gate`).
    """
    ws_root = Path(ws_root)
    slug = (slug or "").strip()
    if not slug:
        return {"error": "missing ?study="}, 400

    from vivarium_workbench.lib.study_spec import load_study_detail_spec

    spec = load_study_detail_spec(ws_root, slug)
    if spec is None:
        return {"error": "study not found"}, 404

    try:
        from viva_superpowers import test_audit
        report = test_audit.build_audit_report(spec)
        gate = test_audit.audit_gate(report)
    except Exception as e:  # noqa: BLE001 — degrade, never a 500
        return {"unavailable": True, "reason": f"{type(e).__name__}: {e}"}, 200

    payload = dict(report)
    payload["gate"] = gate
    return payload, 200
