"""``GET /api/study-loop-state`` worker — Assurance › Build panel.

Study-spine reorg (spec §3.8, plan Task 3): "was the pass earned honestly?"
Reads the agentic model-building loop's persisted protocol state,
``.pbg/loop/<study>.json`` (schema ``model_build_loop/v1``, written/advanced
by ``/viva-model-build`` via :mod:`viva_superpowers.loop_state`) — the
locked-tests hash, the reopen trail (``reopen_count`` + the retained
``prior_hashes``, which make a post-hoc weakening of a locked Test set
visible), the iteration history, and the current state/outcome.

Unlike :mod:`.audit_panel_views` / :mod:`.rigor_views` / :mod:`.audit_views`,
this worker never 404s on a missing study and never treats a missing loop
file as an error: MOST studies are not built via the loop (they're authored
directly), so ``{"present": false, ...}`` is the expected, common, graceful
response the Build panel renders as a one-line note — not an
``unavailable``/error state (spec: "GRACEFUL empty state ... NOT an
error/500").
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def build_study_loop_state(ws_root: Path, slug: Optional[str]) -> tuple[dict, int]:
    """Worker for ``GET /api/study-loop-state?study=<slug>`` → ``(body, status)``.

    200 with ``{"present": true, "study", "schema", "question", "state",
    "iteration", "budget", "locked_tests_hash", "prereg_record",
    "reopen_count", "last_verdict", "history"}`` when
    ``.pbg/loop/<slug>.json`` exists; 200 with ``{"present": false, "study",
    "reason"}`` when it does not (never built via ``/viva-model-build``) or
    when ``viva_superpowers.loop_state`` is unimportable/errors — never a
    404, never a 500.

    400 only when ``?study=`` itself is missing/empty.
    """
    ws_root = Path(ws_root)
    slug = (slug or "").strip()
    if not slug:
        return {"error": "missing ?study="}, 400

    try:
        from viva_superpowers import loop_state
        state = loop_state.load(ws_root, slug)
    except Exception as e:  # noqa: BLE001 — degrade, never a 500
        return {"present": False, "study": slug,
                "reason": f"{type(e).__name__}: {e}"}, 200

    if state is None:
        return {"present": False, "study": slug,
                "reason": "not built via the agentic model-building loop"}, 200

    payload = {
        "present": True,
        "study": slug,
        "schema": state.get("schema"),
        "question": state.get("question"),
        "state": state.get("state"),
        "iteration": state.get("iteration"),
        "budget": state.get("budget"),
        "locked_tests_hash": state.get("locked_tests_hash"),
        "prereg_record": state.get("prereg_record"),
        "reopen_count": state.get("reopen_count"),
        "last_verdict": state.get("last_verdict"),
        "give_up_reason": state.get("give_up_reason"),
        "history": state.get("history"),
    }
    return payload, 200
