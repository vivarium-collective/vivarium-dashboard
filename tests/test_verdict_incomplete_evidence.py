"""A verdict over runs that did not happen is not a verdict.

Observed on dev: a study whose baseline succeeded and whose two variants both
failed came back with `"overall": "within_tol"`. Nothing lied — the conclusion
card is computed by `build_conclusion_verdict`, which is pure and spec-derived,
and answers *what does this study's evidence chain say*. A run harvest asks
*what did this run establish*, and answering the first while reporting failures
for the second is how a green verdict ended up attached to a mostly-failed run.

The card on disk stays untouched: the artifact is not wrong, and rewriting
someone else's science is not the harvest's business. What is fixed is the
harvest presenting it unqualified.
"""

from __future__ import annotations

from typing import Any

import vivarium_workbench.env_worker as ew


def _harvest(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "verdict": {"schema": "conclusion_card/v1", "overall": "within_tol", "tracks": {}},
        "errors": [],
        "run_refs": [],
    }
    base.update(over)
    return base


def test_a_clean_run_keeps_its_verdict_exactly() -> None:
    """No failures, no qualification. This must not fire on a good run."""
    result = _harvest()
    ew._qualify_verdict_on_incomplete_evidence(result)
    assert result["verdict"]["overall"] == "within_tol"
    assert "evidence_incomplete" not in result["verdict"]


def test_a_failed_stage_demotes_the_overall_to_ungraded() -> None:
    """The actual bug. `ungraded` is the existing vocabulary's own word for
    "not graded" — not a new token consumers have to learn."""
    result = _harvest(errors=[{"stage": "variant:fails-bad-param", "error": "run failed"}])
    ew._qualify_verdict_on_incomplete_evidence(result)
    assert result["verdict"]["overall"] == "ungraded"


def test_the_original_verdict_is_preserved_not_destroyed() -> None:
    """Qualifying is not deleting. Somebody comparing against the card on disk
    needs to see what it said."""
    result = _harvest(errors=[{"stage": "baseline", "error": "boom"}])
    ew._qualify_verdict_on_incomplete_evidence(result)
    assert result["verdict"]["evidence_incomplete"]["overall_before"] == "within_tol"


def test_it_names_which_stages_failed() -> None:
    """"Incomplete" without saying what is missing sends the reader hunting."""
    result = _harvest(
        errors=[
            {"stage": "variant:a", "error": "x"},
            {"stage": "variant:b", "error": "y"},
        ]
    )
    ew._qualify_verdict_on_incomplete_evidence(result)
    assert result["verdict"]["evidence_incomplete"]["failed_stages"] == ["variant:a", "variant:b"]


def test_the_note_explains_why_rather_than_just_flagging() -> None:
    result = _harvest(errors=[{"stage": "baseline", "error": "boom"}])
    ew._qualify_verdict_on_incomplete_evidence(result)
    note = result["verdict"]["evidence_incomplete"]["note"]
    assert "did not happen" in note
    assert "card on disk is unchanged" in note, "the reader must know the artifact was not rewritten"


# --- plumbing failures must not cry wolf ------------------------------------


def test_a_verdict_read_failure_does_not_demote_the_verdict() -> None:
    """Failing to READ the card says nothing about whether the runs happened.
    Demoting for it would train people to ignore the flag."""
    result = _harvest(errors=[{"stage": "read_verdict", "error": "bad json"}])
    ew._qualify_verdict_on_incomplete_evidence(result)
    assert result["verdict"]["overall"] == "within_tol"
    assert "evidence_incomplete" not in result["verdict"]


def test_a_harvest_failure_does_not_demote_the_verdict() -> None:
    result = _harvest(errors=[{"stage": "harvest_run_refs", "error": "db locked"}])
    ew._qualify_verdict_on_incomplete_evidence(result)
    assert "evidence_incomplete" not in result["verdict"]


def test_a_science_failure_alongside_plumbing_still_demotes() -> None:
    """One real failure is enough; the plumbing entry must not mask it."""
    result = _harvest(
        errors=[
            {"stage": "read_verdict", "error": "bad json"},
            {"stage": "variant:real", "error": "run failed"},
        ]
    )
    ew._qualify_verdict_on_incomplete_evidence(result)
    assert result["verdict"]["overall"] == "ungraded"
    assert result["verdict"]["evidence_incomplete"]["failed_stages"] == ["variant:real"]


# --- it must never be the thing that breaks a harvest -----------------------


def test_no_verdict_is_not_an_error() -> None:
    """Most studies have no conclusion card at all."""
    result = _harvest(verdict=None, errors=[{"stage": "baseline", "error": "x"}])
    ew._qualify_verdict_on_incomplete_evidence(result)
    assert result["verdict"] is None


def test_a_non_dict_verdict_is_left_alone() -> None:
    result = _harvest(verdict="unexpected", errors=[{"stage": "baseline", "error": "x"}])
    ew._qualify_verdict_on_incomplete_evidence(result)
    assert result["verdict"] == "unexpected"


def test_malformed_error_entries_do_not_raise() -> None:
    result = _harvest(errors=["a bare string", {"no_stage": 1}, {"stage": "variant:ok", "error": "e"}])
    ew._qualify_verdict_on_incomplete_evidence(result)
    assert result["verdict"]["evidence_incomplete"]["failed_stages"] == ["variant:ok"]
