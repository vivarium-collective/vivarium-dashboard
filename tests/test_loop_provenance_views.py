"""Tests for the Assurance › Build worker
(`lib/loop_provenance_views.build_study_loop_state`).

Mirrors the availability-gate convention `test_audit_views.py` established:
the workbench pins pbg-superpowers bare from PyPI, so
`viva_superpowers.loop_state` only lights up once a viva-superpowers release
(or a git pin) includes it. When absent, `build_study_loop_state` degrades
to a 200 `{"present": false, ...}` body — the SAME graceful contract a study
simply never run through `/viva-model-build` gets, so this worker behaves
identically in both worlds; the populated-state specifics (locked hash,
reopen trail) are gated on availability.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from vivarium_workbench.lib.loop_provenance_views import build_study_loop_state


def _has_loop_state() -> bool:
    try:
        import viva_superpowers.loop_state  # noqa: F401
    except Exception:
        return False
    return True


_HAS_LOOP_STATE = _has_loop_state()


def _make_workspace(tmp_path: Path, slug: str = "s1") -> Path:
    ws = tmp_path / "ws"
    sd = ws / "studies" / slug
    sd.mkdir(parents=True)
    (ws / "workspace.yaml").write_text("name: probe-ws\n", encoding="utf-8")
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3,
        "name": slug,
        "baseline": [{"name": "core", "composite": "pkg.composites.core"}],
        "variants": [],
    }), encoding="utf-8")
    return ws


def _write_loop_file(ws: Path, slug: str, state: dict) -> None:
    loop_dir = ws / ".pbg" / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    (loop_dir / f"{slug}.json").write_text(json.dumps(state), encoding="utf-8")


def test_missing_study_param_is_400(tmp_path):
    ws = _make_workspace(tmp_path)
    body, status = build_study_loop_state(ws, "")
    assert status == 400
    assert "error" in body


def test_absent_loop_file_is_graceful_present_false_not_404(tmp_path):
    """The REQUIREMENT: a study never run through /viva-model-build (no
    .pbg/loop/<slug>.json) must degrade to a 200 {"present": false, ...}
    body — never a 404, never a 500."""
    ws = _make_workspace(tmp_path)
    body, status = build_study_loop_state(ws, "s1")
    assert status == 200
    assert body.get("present") is False
    assert body.get("study") == "s1"
    assert "reason" in body


def test_absent_loop_file_graceful_even_for_unknown_study(tmp_path):
    """Unlike rigor/audit, this worker never validates the study exists —
    a stray/renamed slug still degrades to present:false, not 404."""
    ws = _make_workspace(tmp_path)
    body, status = build_study_loop_state(ws, "does-not-exist")
    assert status == 200
    assert body.get("present") is False


def test_present_loop_state_returns_locked_hash_and_reopen_trail(tmp_path):
    """The core requirement: when a .pbg/loop/<slug>.json exists, the
    payload surfaces locked_tests_hash, prereg_record.prior_hashes,
    reopen_count, iteration history, and state/outcome.

    Reading the file requires `viva_superpowers.loop_state` to be importable
    (same availability caveat as `test_audit` — see module docstring); when
    it is absent this degrades to `present: false` like the absent-file case,
    so gate this specific "populated" assertion on availability."""
    if not _HAS_LOOP_STATE:
        import pytest
        pytest.skip("viva_superpowers.loop_state not importable in this environment")

    ws = _make_workspace(tmp_path)
    state = {
        "schema": "model_build_loop/v1",
        "study": "s1",
        "question": "Does the model reproduce daughter-cell hydration?",
        "state": "DONE",
        "iteration": 3,
        "budget": {"max_iterations": 12, "spent": 3},
        "audit": None,
        "locked_tests_hash": "sha256:deadbeef",
        "prereg_record": {"locked_at_iteration": 1, "prior_hashes": ["sha256:aaaa"]},
        "reopen_count": 1,
        "last_verdict": {"roll_up": "passed", "gate": "pass"},
        "history": [
            {"iteration": 1, "edit": "widen band", "target": "daughters_hydrated",
             "margin_deltas": {"daughters_hydrated": 0.1}, "gate": "warn"},
            {"iteration": 2, "edit": "fix hydration calc", "target": "core.division",
             "margin_deltas": {"daughters_hydrated": 0.4}, "gate": "pass"},
        ],
    }
    _write_loop_file(ws, "s1", state)

    body, status = build_study_loop_state(ws, "s1")
    assert status == 200
    assert body.get("present") is True
    assert body.get("study") == "s1"
    assert body.get("state") == "DONE"
    assert body.get("locked_tests_hash") == "sha256:deadbeef"
    assert body.get("reopen_count") == 1
    assert body.get("prereg_record", {}).get("prior_hashes") == ["sha256:aaaa"]
    assert len(body.get("history") or []) == 2
    assert body.get("last_verdict", {}).get("roll_up") == "passed"


def test_give_up_reason_is_surfaced(tmp_path):
    """A GIVE_UP loop carries a `give_up_reason` explaining why no model tweak
    cleared the locked bar; the payload must surface it so the Build tab can
    render the honest give-up rather than a bare state chip."""
    if not _HAS_LOOP_STATE:
        import pytest
        pytest.skip("viva_superpowers.loop_state not importable in this environment")
    ws = _make_workspace(tmp_path)
    reason = ("No mechanism reaches biomass 6.0 — coarse/kinetic/FBA all converge to ~5.0 "
              "because yield·S0 = 5.0 caps it (mass conservation).")
    state = {
        "schema": "model_build_loop/v1", "study": "s1", "question": "q",
        "state": "GIVE_UP", "iteration": 3,
        "budget": {"max_iterations": 12, "spent": 3},
        "locked_tests_hash": "sha256:cafe",
        "prereg_record": {"locked_at_iteration": 0, "prior_hashes": []},
        "reopen_count": 0,
        "last_verdict": {"roll_up": "failed", "gate": "fail"},
        "give_up_reason": reason,
        "history": [{"iteration": 3, "edit": "try mechanism fba", "target": "biomass",
                     "margin_deltas": {}, "gate": "fail"}],
    }
    _write_loop_file(ws, "s1", state)
    body, status = build_study_loop_state(ws, "s1")
    assert status == 200
    assert body.get("state") == "GIVE_UP"
    assert body.get("give_up_reason") == reason


def test_loop_state_module_reads_the_same_file_this_worker_writes_the_shape_for(tmp_path):
    """Round-trip through the real `viva_superpowers.loop_state` writer (when
    importable) proves the worker reads the SAME on-disk shape the loop
    itself produces, not a hand-rolled fixture shape."""
    if not _HAS_LOOP_STATE:
        import pytest
        pytest.skip("viva_superpowers.loop_state not importable in this environment")

    from viva_superpowers import loop_state

    ws = _make_workspace(tmp_path, slug="loop-study")
    state = loop_state.create(ws, "loop-study", "Does X hold?", max_iterations=5)
    state = loop_state.lock_tests(state, [{"name": "t1"}])
    state = loop_state.lock_tests(state, [{"name": "t1"}, {"name": "t2"}])  # a re-open→re-lock
    loop_state.save(ws, "loop-study", state)

    body, status = build_study_loop_state(ws, "loop-study")
    assert status == 200
    assert body.get("present") is True
    assert body.get("reopen_count") == 1
    assert len(body.get("prereg_record", {}).get("prior_hashes") or []) == 1
