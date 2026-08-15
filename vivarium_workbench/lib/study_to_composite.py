"""``study_to_composite`` -- compile a Study spec into a runnable workflow
composite.

The end-to-end closing move: a Study **is** a workflow composite. This
module compiles a study's normalized execution interface
(:func:`~vivarium_workbench.lib.study_spec.study_interface`) into the
``process_bigraph.workflow`` shape (a ``CompositeTask`` scatter node over
the study's seeds, gated by a report-card Step, run via
``process_bigraph.workflow.run_workflow``) -- content-addressing parity with
the dead pull-or-compute resolver, ``resolve_study``
(``lib/artifacts/pipeline.py``), since both key off the SAME
``process_bigraph.artifacts.artifact_id`` formula (single-sourced -- see
``lib/artifacts/hashing.py``).

Minimal slice (Task 10 of the workflow-execution-phases-1-3 plan): a PURE
compiler + a run path. No UI, no backend selector, no detached-run
integration, no codegen retirement (those are Phase 5), and no
``inputs[].from`` producer wiring yet (a study with declared inputs raises
``NotImplementedError`` rather than being silently mis-compiled -- a
producer-less study is this slice's full scope).
"""
from __future__ import annotations

import os
from typing import Any, Optional

from process_bigraph import Composite, allocate_core
from process_bigraph.composite import Step
from process_bigraph.workflow.tasks import CompositeTask

from vivarium_workbench.lib.study_spec import study_interface

# Study-config keys that are run-control (the CompositeTask's own ``steps``
# field), not generator parameters -- mirrors
# ``lib.artifacts.pipeline._RUN_CONTROL_KEYS`` so a study's ``config.n_steps``
# doesn't leak into the generator's ``overrides`` and get rejected as an
# unknown parameter by the generator's own config schema.
_RUN_CONTROL_KEYS = ("n_steps",)


class _StudyGateCard(Step):
    """Minimal gating report card over a ``CompositeTask``'s per-seed results.

    Grades the composite's own execution state -- whether every scattered
    seed actually produced a result -- rather than reading emitted
    observables off a real ``ResultsHandle``. That ResultsStep/parquet
    integration is already proven elsewhere (``viva_superpowers.ResultsStep``
    + the v2ecoli milestone workflow); this minimal slice's gate grades
    run-free off what the study DAG itself already knows, keeping the toy
    slice runnable with no emitter/parquet machinery at all. Verdict shape
    follows the gating convention: ``{status, checks, summary}`` with
    ``status`` in ``{"pass", "fail"}`` (``"warn"`` is a valid status in the
    wider vocabulary this compiles toward -- e.g. a future card grading
    partial seed coverage -- just not one this minimal gate emits itself).
    """

    name = "study_gate"

    def inputs(self):
        return {"results": "tree"}

    def outputs(self):
        return {"verdict": "tree"}

    def update(self, state, interval=None):
        results = state.get("results") or {}
        checks = [{
            "name": "sims_produced_results",
            "passed": bool(results),
            "detail": f"{len(results)} seed result(s)",
        }]
        status = "pass" if results else "fail"
        summary = (
            f"{len(results)} seed(s) produced results" if results
            else "no seed produced a result -- sim(s) may have failed to run")
        return {"verdict": {"status": status, "checks": checks, "summary": summary}}


def _outer_core():
    """A bare core with just the links this workflow's outer Step network
    needs. Mirrors ``v2ecoli.workflow.build._outer_core`` -- the outer
    composite never runs the study's own generator in-process
    (``CompositeTask`` shells out to ``run_composite --build``, which
    resolves its own core via the generator's ``core_extensions``); this
    core only orchestrates the two outer Steps.
    """
    core = allocate_core()
    core.register_link("CompositeTask", CompositeTask)
    core.register_link("StudyGateCard", _StudyGateCard)
    return core


def study_to_composite(
    spec: dict, *, outdir: str = ".", commit: Optional[str] = None,
) -> Composite:
    """Compile a Study spec into a runnable workflow composite.

    A pure function over ``study_interface(spec)``:

    - ``iface.composite`` -> the ``CompositeTask``'s ``generator``.
    - ``iface.config`` -> its base ``overrides`` (with any ``n_steps`` split
      off into the task's ``steps`` field, never left in ``overrides`` --
      see ``_RUN_CONTROL_KEYS``).
    - ``spec['seeds']`` (default ``[0]``) -> the ``per_match`` scatter axis
      (``scatter_param='seed'``) -- one content-addressed
      ``run_composite --build`` subprocess per seed (see
      ``process_bigraph.workflow.tasks.CompositeTask``).
    - a gating ``_StudyGateCard`` Step reads the scatter's raw per-seed
      results and produces the bridge's ``verdict``.

    ``inputs[].from`` producers (upstream studies feeding this one) are NOT
    yet wired -- a declared ``inputs`` entry raises ``NotImplementedError``
    rather than being silently dropped; a producer-less study is this
    minimal slice's full scope.

    Args:
      spec: a study spec dict (the same shape ``study_interface`` reads).
      outdir: base directory for this run's artifact store
        (``<outdir>/.pbg/artifacts``) -- mirrors
        ``build_parca_sim_composite``'s ``outdir`` convention.
      commit: optional -- when given, threaded into the ``CompositeTask``'s
        ``code_version`` so its per-seed sim-cache address is keyed on the
        SAME commit axis ``resolve_study`` (``lib/artifacts/pipeline.py``)
        uses for its own study-level artifact address (see that module's
        ``_workspace_commit``) -- see the module docstring above and
        ``tests/test_study_to_composite.py``'s address-parity test for the
        precise relationship between the two addresses. Left unset,
        ``CompositeTask`` falls back to its own framework/package-version
        default, appropriate for a study compiled and run outside any
        workspace's git history at all.

    Returns:
      An unbuilt/unrun :class:`~process_bigraph.Composite` -- pass it to
      ``process_bigraph.workflow.run_workflow`` to execute.
    """
    iface = study_interface(spec)
    if not iface["composite"]:
        raise ValueError(
            "study spec has no composite (interface.composite / "
            "conditions.baseline.composite)")
    if iface["inputs"]:
        raise NotImplementedError(
            "study_to_composite: interface.inputs[].from producers are not "
            "yet wired (Task 10's minimal slice covers a producer-less "
            f"study only); study declares inputs={iface['inputs']!r}")

    seeds = list(spec.get("seeds") or [0])

    overrides = dict(iface["config"] or {})
    n_steps = spec.get("n_steps")
    if n_steps is None:
        n_steps = overrides.get("n_steps")
    for key in _RUN_CONTROL_KEYS:
        overrides.pop(key, None)
    steps = float(n_steps or 1)

    outdir = os.path.abspath(outdir)
    artifact_root = os.path.join(outdir, ".pbg", "artifacts")

    task_config: dict[str, Any] = {
        "generator": iface["composite"],
        "import": list(spec.get("import") or []),
        "overrides": overrides,
        "artifact_params": {},
        "scatter_param": "seed",
        "steps": steps,
        "provision": [],
        "artifact_root": artifact_root,
        "allow_in_memory_emitter": True,
    }
    if commit is not None:
        task_config["code_version"] = commit

    state: dict[str, Any] = {
        "seeds": seeds,
        "sims_results": {},
        "verdict": {},
        "sims": {
            "_type": "step",
            "address": "local:CompositeTask",
            "config": task_config,
            "inputs": {"seed": ["seeds"]},
            "outputs": {"results": ["sims_results"]},
        },
        "report": {
            "_type": "step",
            "address": "local:StudyGateCard",
            "config": {},
            "inputs": {"results": ["sims_results"]},
            "outputs": {"verdict": ["verdict"]},
        },
    }

    document = {
        "state": state,
        "bridge": {"outputs": {
            "verdict": ["verdict"],
            "results": ["sims_results"],
        }},
        "parallel_steps": True,
    }
    return Composite(document, core=_outer_core())
