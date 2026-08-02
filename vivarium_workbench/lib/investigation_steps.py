"""Investigation-as-composite building blocks.

A ``StudyStep`` is a process-bigraph ``Step`` wrapping one study. Prerequisite
edges are expressed as input wires so the engine orders StudySteps by data
dependency (design: docs/superpowers/specs/2026-08-01-investigation-as-composite-design.md).

``update()`` dispatches each study run to the persistent env worker's
``run_study`` capability via the shared pool (same pattern as
``study_run_post.py`` / ``composite_flush.py``'s ``run_study_analyses``
dispatch). Tests may still run the walking-skeleton path — assign a list to
``_RUN_ORDER`` to record execution order instead of hitting a live worker
(used by the hermetic ordering tests in
``tests/test_investigation_steps_skeleton.py``).
"""
from __future__ import annotations

import process_bigraph

# Skeleton test hook: when a list is assigned here, each StudyStep.update()
# appends its slug (proves execution order) and returns a marker instead of
# dispatching to a live env worker. None in production.
_RUN_ORDER: list | None = None


def _run_study_hook(workspace: str, study_slug: str) -> dict:
    """Run one study: skeleton-record order, or dispatch to the env worker."""
    if _RUN_ORDER is not None:
        _RUN_ORDER.append(study_slug)
        return {"study": study_slug, "ran": True}

    from vivarium_workbench.lib.env_worker_pool import get_pool

    return get_pool().call(workspace, "run_study", {
        "workspace": workspace, "study_slug": study_slug})


class StudyStep(process_bigraph.Step):
    config_schema = {
        "workspace": "string",
        "study_slug": "string",
        "prereqs": {"_type": "list[string]", "_default": []},
    }

    def inputs(self):
        return {f"prereq_{p}": "node" for p in self.config.get("prereqs", [])}

    def outputs(self):
        return {"result": "node"}

    def update(self, state=None):
        result = _run_study_hook(self.config["workspace"], self.config["study_slug"])
        return {"result": result}


# Skeleton test hook (mirrors ``_RUN_ORDER``): when a list is assigned here,
# each AnalysisStep.update() appends its ``name`` (proves it runs after its
# wired studies) instead of dispatching to a live env worker. None in
# production.
_ANALYSIS_RUN_ORDER: list | None = None


def _run_analysis_hook(workspace: str, name: str, config: dict, report_dir: str) -> dict:
    """Run one investigation-level analysis: skeleton-record order, or
    dispatch to the env worker's ``run_investigation_analysis`` capability."""
    if _ANALYSIS_RUN_ORDER is not None:
        _ANALYSIS_RUN_ORDER.append(name)
        return {"written": [], "errors": []}

    from vivarium_workbench.lib.env_worker_pool import get_pool

    return get_pool().call(workspace, "run_investigation_analysis", {
        "workspace": workspace, "name": name, "config": config,
        "report_dir": report_dir})


class AnalysisStep(process_bigraph.Step):
    """One investigation-level Analysis (e.g. ``comparison_matrix``), wired to
    every study whose verdict it needs. ``inputs()`` — one ``"node"`` port per
    ``study_slugs`` entry, wired by the generator to that study's
    ``StudyStep`` ``result`` store — both orders this step to run AFTER those
    studies (the engine's ``determine_steps`` dependency ordering, same
    mechanism as ``StudyStep``'s ``prereq_*`` ports) AND delivers each study's
    result dict (which carries its ``verdict``) as this step's wired state.

    ``update()`` assembles ``config_verdicts = {slug: state[f"study_{slug}"]}``
    from the wired study results, merges it into the static ``params``, and
    dispatches to the ``run_investigation_analysis`` worker capability (design:
    docs/superpowers/specs/2026-08-01-investigation-as-composite-design.md,
    §Architecture 2-3). Bypasses the parquet-coupled ``run_study_analyses``
    path entirely — the #712 blocker this exists to route around.
    """

    config_schema = {
        "workspace": "string",
        "name": "string",
        "params": {"_type": "map", "_default": {}},
        "study_slugs": {"_type": "list[string]", "_default": []},
        "report_dir": "string",
    }

    def inputs(self):
        return {f"study_{slug}": "node" for slug in self.config.get("study_slugs", [])}

    def outputs(self):
        return {"written": "node"}

    def update(self, state=None):
        state = state or {}
        config_verdicts = {
            slug: state.get(f"study_{slug}")
            for slug in self.config.get("study_slugs", [])
        }
        params = dict(self.config.get("params") or {})
        analysis_config = {**params, "config_verdicts": config_verdicts}
        reply = _run_analysis_hook(
            self.config["workspace"], self.config["name"], analysis_config,
            self.config["report_dir"])
        return {"written": reply.get("written")}
