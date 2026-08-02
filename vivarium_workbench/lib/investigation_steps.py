"""Investigation-as-composite building blocks.

A ``StudyStep`` is a process-bigraph ``Step`` wrapping one study. Prerequisite
edges are expressed as input wires so the engine orders StudySteps by data
dependency (design: docs/superpowers/specs/2026-08-01-investigation-as-composite-design.md).

This module is the walking skeleton: ``update()`` records order + returns a
marker via ``_run_study_hook``. A later task replaces the hook body with the
real worker dispatch (``get_pool().call(ws, "run_study", ...)``).
"""
from __future__ import annotations

import process_bigraph

# Skeleton test hook: when a list is assigned here, each StudyStep.update()
# appends its slug (proves execution order). None in production.
_RUN_ORDER: list | None = None


def _run_study_hook(workspace: str, study_slug: str) -> dict:
    """Default (skeleton) study run: record order + return a marker."""
    if _RUN_ORDER is not None:
        _RUN_ORDER.append(study_slug)
    return {"study": study_slug, "ran": True}


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
