"""Build a transient single-composite study spec to drive the results driver.

Never persisted, never registered -- the input struct for ``run_declared_results``
(a later task) only. See the design doc's "Declaration + ephemeral spec" section
(``docs/superpowers/specs/2026-09-06-composite-run-auto-results-design.md``).

Two declaration shapes feed ``merge_declarations``:

- ``composite_defaults`` -- ``GeneratorEntry.analyses`` / ``CompositeSpec.analyses``,
  a FLAT list of ``{"name": ..., "params"?: ...}`` dicts, mirroring
  ``.visualizations`` (``process_bigraph/composite_spec.py:250-251``).
- ``config_declared`` -- the run-config's declared block, in the study-shaped,
  SCALE-GROUPED form real ``study.yaml`` files use (``{single: [...],
  multigeneration: [...], ...}``), where each scale's entries are bare analysis
  name strings (confirmed on disk, e.g.
  ``workspace/studies/cd2-antibiotic-cocktail/study.yaml``), though a dict
  ``{"name": ..., "params": ...}`` entry is also accepted for a params override.

``build_analysis_options`` (``vivarium_workbench/lib/study_run_post.py:184``)
resolves each entry's scale itself from the analysis registry by name, so scale
grouping carries no meaning for this module -- both sides are flattened to a
flat list of ``{"name", ...}`` dicts before merging.
"""
from __future__ import annotations


def _flatten_analyses(block) -> list[dict]:
    """Normalize an analyses declaration into a flat list of ``{name, ...}`` dicts.

    Accepts either the flat composite-defaults shape (a list of bare-string
    names or ``{"name": ...}`` dicts) or the scale-grouped study.yaml shape (a
    dict of ``scale -> list of entries``, entries themselves bare strings or
    dicts). Scale grouping is dropped -- it is not preserved in the output.
    """

    def _norm(entry) -> dict:
        if isinstance(entry, str):
            return {"name": entry}
        return dict(entry)

    if isinstance(block, dict):
        out: list[dict] = []
        for entries in block.values():
            for entry in entries or []:
                out.append(_norm(entry))
        return out
    return [_norm(entry) for entry in (block or [])]


def _by_name(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in items or []:
        n = it.get("name")
        if n:
            out[n] = it
    return out


def merge_declarations(composite_defaults: dict, config_declared: dict) -> dict:
    """Config wins over composite defaults, keyed by analysis/viz name.

    Analyses from both sides are flattened first (see ``_flatten_analyses``);
    visualizations are already flat on both sides.
    """
    composite_defaults = composite_defaults or {}
    config_declared = config_declared or {}

    a = _by_name(_flatten_analyses(composite_defaults.get("analyses")))
    a.update(_by_name(_flatten_analyses(config_declared.get("analyses"))))

    v = _by_name(composite_defaults.get("visualizations"))
    v.update(_by_name(config_declared.get("visualizations")))

    return {"analyses": list(a.values()), "visualizations": list(v.values())}


def ephemeral_study_spec(composite_ref: str, declared: dict) -> dict:
    """A study-shaped dict carrying only the keys the results stages read.

    No ``variants``/``findings``/``verdicts``/``behavior_tests`` -- those are
    study-identity stages that assume persistence; this spec exists only to
    drive the shared results machinery, then is discarded.
    """
    declared = declared or {}
    return {
        "name": f"__ephemeral__{composite_ref}",
        "baseline": {"composite": composite_ref},
        "analyses": declared.get("analyses", []),
        "visualizations": declared.get("visualizations", []),
        "_ephemeral": True,
    }
