"""`study_precheck` — the tier asking, before it commits a worker.

§B built the declared-scale check and put it in `launch_into_study`, which runs
INSIDE the worker. By the time it fires, two things have already gone wrong:
the worker is occupied, and the refusal comes back as an entry in a harvest's
`errors[]` — which under the task tier's own semantics reads as *the science
failed*, when it actually means *you sent this to the wrong tier*.

This method lets the tier ask first. It is arithmetic on a spec, not a run, so
it stays inside what protocol §12 permits a worker to answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import vivarium_workbench.env_worker as ew


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "workspace.yaml").write_text(
        yaml.safe_dump({"schema_version": 2, "name": "probe", "package_path": "pbg_probe"}), encoding="utf-8"
    )
    (tmp_path / "studies").mkdir()
    return tmp_path


def _study(ws: Path, slug: str, params: dict[str, Any] | None) -> None:
    d = ws / "studies" / slug
    d.mkdir(parents=True, exist_ok=True)
    spec: dict[str, Any] = {"schema_version": 3, "name": slug}
    if params is not None:
        spec["baseline"] = [{"name": "b", "composite": "pkg.composites.x", "params": params}]
    d.joinpath("study.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")


# --- the caller's own knobs -------------------------------------------------


def test_a_small_declared_run_is_allowed(workspace: Path) -> None:
    out = ew._study_precheck({"workspace": str(workspace), "study_slug": "s", "n_seeds": 2, "n_generations": 3})
    assert out["exceeds"] is False
    assert out["declared"] == 6


def test_a_large_declared_run_is_refused_with_the_numbers(workspace: Path) -> None:
    out = ew._study_precheck({"workspace": str(workspace), "study_slug": "s", "n_seeds": 1000, "n_generations": 10})
    assert out["exceeds"] is True
    assert out["declared"] == 10_000
    assert out["budget"] > 0
    assert "Batch" in out["hint"], "a refusal must name where the work should go instead"


def test_the_hint_names_the_override_knob(workspace: Path) -> None:
    """Somebody who disagrees with the budget needs to know what to change."""
    out = ew._study_precheck({"workspace": str(workspace), "study_slug": "s", "n_seeds": 1000, "n_generations": 10})
    assert "LOCAL_RUN_MAX_SIMULATIONS" in out["hint"]


# --- falling back to what the study declares --------------------------------


def test_the_study_spec_supplies_the_knobs_when_the_caller_sends_none(workspace: Path) -> None:
    """`atlantis worker submit <job> run_study --params '{"study_slug": "x"}'`
    sends no scale at all; the spec is then the only source."""
    _study(workspace, "big", {"n_seeds": 500, "n_generations": 10})
    out = ew._study_precheck({"workspace": str(workspace), "study_slug": "big"})
    assert out["exceeds"] is True
    assert out["declared"] == 5000


def test_the_callers_knobs_win_over_the_spec(workspace: Path) -> None:
    """A caller overriding scale upward must be judged on what they sent."""
    _study(workspace, "small", {"n_seeds": 1, "n_generations": 1})
    out = ew._study_precheck(
        {"workspace": str(workspace), "study_slug": "small", "n_seeds": 900, "n_generations": 10}
    )
    assert out["exceeds"] is True


# --- silence is not a claim of scale ----------------------------------------


def test_a_study_declaring_nothing_is_allowed(workspace: Path) -> None:
    """§B's rule, and it is why `basal` (declared=1) passes: an undeclared study
    is never blocked. Note what that means — this check does NOT know whether a
    composite is heavy, only how many simulations were declared."""
    _study(workspace, "quiet", {})
    out = ew._study_precheck({"workspace": str(workspace), "study_slug": "quiet"})
    assert out["exceeds"] is False
    assert out["declared"] == 1


def test_an_unreadable_spec_is_allowed_not_refused(workspace: Path) -> None:
    """A malformed yaml must not become an outage. Same posture as the rest of
    this codebase: a metadata problem does not block a launch."""
    d = workspace / "studies" / "broken"
    d.mkdir(parents=True)
    d.joinpath("study.yaml").write_text("{{{ not yaml", encoding="utf-8")
    out = ew._study_precheck({"workspace": str(workspace), "study_slug": "broken"})
    assert out["exceeds"] is False


def test_a_missing_study_is_allowed_not_refused(workspace: Path) -> None:
    out = ew._study_precheck({"workspace": str(workspace), "study_slug": "nope"})
    assert out["exceeds"] is False


def test_it_never_raises_on_junk_input() -> None:
    for params in ({}, {"study_slug": None}, {"workspace": "/nonexistent", "study_slug": "x"}):
        assert ew._study_precheck(params)["exceeds"] is False


# --- it is an interactive method, not a runner ------------------------------


def test_precheck_is_advertised_and_is_not_job_class() -> None:
    """§12: the worker answers questions; jobs are jobs. This one is a question,
    so it belongs in the advertised capabilities AND must stay out of
    JOB_CLASS_METHODS, or the tier would route the precheck through the tier."""
    from vivarium_workbench.lib.env_worker_routing import is_job_class

    assert "study_precheck" in ew._CAPABILITIES
    assert not is_job_class("study_precheck")


def test_precheck_runs_nothing(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The claim that keeps it §12-legal. If this ever launches a run, it has
    become a runner and belongs on the other side of the boundary."""
    import vivarium_workbench.lib.study_runs as sr

    def _boom(*a: Any, **k: Any) -> None:
        raise AssertionError("study_precheck launched a run")

    monkeypatch.setattr(sr, "launch_into_study", _boom)
    _study(workspace, "s", {"n_seeds": 4, "n_generations": 4})
    assert ew._study_precheck({"workspace": str(workspace), "study_slug": "s"})["declared"] == 16
