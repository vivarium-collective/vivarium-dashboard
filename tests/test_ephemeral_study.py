"""Tests for the ephemeral single-composite study-spec builder.

The composite-defaults side (``GeneratorEntry.analyses`` / ``CompositeSpec.analyses``)
is a FLAT list of ``{name, params?}`` dicts (mirroring ``.visualizations``; see
``process_bigraph/composite_spec.py:250-251``). The config-declared side is the
study-shaped, SCALE-GROUPED form (``{single: [...], multigeneration: [...]}``)
that real ``study.yaml`` files use -- confirmed on disk, e.g.
``workspace/studies/cd2-antibiotic-cocktail/study.yaml``:

    analyses:
      single:
      - mass_fraction_summary
      multigeneration:
      - selected_fluxes
      - selected_bulk

and entries there are bare analysis-name strings, not dicts. ``build_analysis_options``
(a later task, ``vivarium_workbench/lib/study_run_post.py:184``) consumes a flat
list of ``{name, ...}`` dicts and resolves scale itself from the analysis
registry, so scale grouping is not meaningful input to this module -- both
composite-defaults and config-declared analyses are flattened before merging.
"""

from vivarium_workbench.lib.ephemeral_study import (
    _flatten_analyses,
    ephemeral_study_spec,
    merge_declarations,
)


def test_flatten_analyses_flat_list_of_dicts_passes_through():
    # composite-defaults shape: already flat, dict entries.
    block = [{"name": "ptools_rna_multigeneration"}, {"name": "selected_fluxes", "params": {"x": 1}}]
    assert _flatten_analyses(block) == block


def test_flatten_analyses_scale_grouped_strings_are_flattened():
    # real study.yaml shape: scale-grouped, bare-string entries.
    block = {
        "single": ["mass_fraction_summary"],
        "multigeneration": ["selected_fluxes", "selected_bulk"],
    }
    flat = _flatten_analyses(block)
    assert {e["name"] for e in flat} == {"mass_fraction_summary", "selected_fluxes", "selected_bulk"}
    assert all(set(e) == {"name"} for e in flat)


def test_flatten_analyses_empty_or_missing():
    assert _flatten_analyses(None) == []
    assert _flatten_analyses([]) == []
    assert _flatten_analyses({}) == []


def test_merge_config_wins_by_name():
    composite = {
        "analyses": [{"name": "ptools_rna_multigeneration"}],
        "visualizations": [{"name": "growth"}],
    }
    config = {
        "analyses": {
            "multigeneration": [
                {"name": "ptools_rna_multigeneration", "params": {"n_tp": 12}},
                "ptools_rxns_multigeneration",
            ],
        },
        "visualizations": [{"name": "titer"}],
    }
    m = merge_declarations(composite, config)
    rna = [a for a in m["analyses"] if a["name"] == "ptools_rna_multigeneration"]
    assert rna == [{"name": "ptools_rna_multigeneration", "params": {"n_tp": 12}}]  # config won
    assert {a["name"] for a in m["analyses"]} == {"ptools_rna_multigeneration", "ptools_rxns_multigeneration"}
    assert {v["name"] for v in m["visualizations"]} == {"growth", "titer"}


def test_merge_declarations_handles_missing_blocks():
    assert merge_declarations({}, {}) == {"analyses": [], "visualizations": []}
    assert merge_declarations(None, None) == {"analyses": [], "visualizations": []}


def test_ephemeral_spec_shape_is_study_subset():
    spec = ephemeral_study_spec(
        "ecoli_baseline",
        {"analyses": [{"name": "ptools_rna_multigeneration"}], "visualizations": []},
    )
    assert spec["baseline"]["composite"] == "ecoli_baseline"
    assert spec["_ephemeral"] is True
    assert "variants" not in spec and "verdicts" not in spec
    assert "findings" not in spec and "behavior_tests" not in spec
    assert set(spec.keys()) == {"name", "baseline", "analyses", "visualizations", "_ephemeral"}
