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
