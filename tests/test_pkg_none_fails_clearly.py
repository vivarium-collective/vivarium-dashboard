"""A workspace with no package must be refused, not turned into a SyntaxError.

The generated run script opens with `from {pkg}.core import build_core`. `pkg`
is allowed to be None upstream — `study_runs` degrades it deliberately so a
workspace.yaml-less caller "must never block the launch" — but nothing checked
before interpolating it into source, so the child died on

    File "<string>", line 3
        from None.core import build_core
    SyntaxError: invalid syntax

which surfaced to the caller as "could not parse run output". Observed on a real
deployment whose workspace had studies/ and investigations/ but no
workspace.yaml.
"""

from __future__ import annotations

import pytest

from vivarium_workbench.lib.composite_subprocess import run_composite_subprocess


def _run(tmp_path, pkg):
    return run_composite_subprocess(
        tmp_path,
        pkg=pkg,
        state={},
        steps=1,
        db_file=str(tmp_path / "runs.db"),
        run_id="r1",
        spec_id="x.y",
        label="core",
    )


@pytest.mark.parametrize("pkg", [None, "", 0])
def test_a_missing_package_is_refused_before_any_script_is_built(tmp_path, pkg):
    """400, not a subprocess. The point is that nothing is spawned at all."""
    body, code = _run(tmp_path, pkg)
    assert code == 400
    assert "no package" in body["error"]


def test_the_error_names_the_workspace_and_what_is_missing(tmp_path):
    """ "could not parse run output" sent me looking at composites for an hour.
    The message has to name the workspace and the two fields that would fix it,
    because the reader is looking at a study and the fault is in a file they did
    not open."""
    body, _ = _run(tmp_path, None)
    msg = body["error"]
    assert str(tmp_path) in msg, "must name WHICH workspace"
    assert "workspace.yaml" in msg
    assert "package_path" in msg and "name" in msg
    assert "build_core" in msg, "and why a package is needed at all"


def test_the_run_id_is_echoed_so_the_caller_can_correlate(tmp_path):
    """Every other failure path returns simulation_id; a refusal that omitted it
    would be the odd one out for whatever is recording the attempt."""
    body, _ = _run(tmp_path, None)
    assert body["simulation_id"] == "r1"


def test_none_never_reaches_the_generated_source(tmp_path):
    """The actual regression: `from None.core import` must be unreachable."""
    body, code = _run(tmp_path, None)
    assert code == 400
    assert "SyntaxError" not in body["error"]
    assert "from None" not in body["error"]
