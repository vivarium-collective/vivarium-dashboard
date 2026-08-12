"""The shared ``agents/0/`` scoping fallback (dict-side + SQL-side).

Consolidates what used to be 5-6 independent (and drifted) reimplementations
across composite_runs.py, result_fingerprint.py, study_charts.py,
comparative_viz.py, and explorer_data.py — see agents0.py's module docstring
for which sites route through here and which were deliberately left alone.
"""
from vivarium_workbench.lib.agents0 import (
    agents0_json_extract_pair,
    resolve_agents0_fallback,
    resolve_path,
)


# -- resolve_path -------------------------------------------------------

def test_resolve_path_walks_nested_dict():
    state = {"a": {"b": {"c": 1}}}
    assert resolve_path(state, ["a", "b", "c"]) == 1


def test_resolve_path_missing_segment_is_none():
    assert resolve_path({"a": {"b": 1}}, ["a", "x"]) is None


def test_resolve_path_indexing_into_non_dict_is_none():
    assert resolve_path({"a": 1}, ["a", "b"]) is None


def test_resolve_path_empty_parts_returns_state():
    state = {"a": 1}
    assert resolve_path(state, []) is state


# -- resolve_agents0_fallback --------------------------------------------

def test_fallback_prefers_literal_path_when_present():
    state = {"listeners": {"mass": {"dry_mass": 1.0}},
             "agents": {"0": {"listeners": {"mass": {"dry_mass": 2.0}}}}}
    parts, node = resolve_agents0_fallback(state, ["listeners", "mass", "dry_mass"])
    assert node == 1.0
    assert parts == ["listeners", "mass", "dry_mass"]


def test_fallback_retries_under_agents_0_when_literal_missing():
    state = {"agents": {"0": {"listeners": {"mass": {"dry_mass": 400.0}}}}}
    parts, node = resolve_agents0_fallback(state, ["listeners", "mass", "dry_mass"])
    assert node == 400.0
    assert parts == ["agents", "0", "listeners", "mass", "dry_mass"]


def test_fallback_neither_form_resolves_returns_none():
    state = {"time": 1}
    parts, node = resolve_agents0_fallback(state, ["nonexistent", "path"])
    assert node is None
    assert parts == ["nonexistent", "path"]  # unchanged on a miss


def test_fallback_does_not_double_prefix_an_already_agents_path():
    # A path already declared under agents/... must not be retried as
    # agents/0/agents/....
    state = {"agents": {"1": {"foo": 5}}}
    parts, node = resolve_agents0_fallback(state, ["agents", "1", "foo"])
    assert node == 5
    assert parts == ["agents", "1", "foo"]


def test_fallback_already_agents_path_that_misses_stays_a_miss():
    state = {"agents": {"0": {"foo": 5}}}
    # Declared as agents/1/foo (wrong agent id) — must NOT retry as
    # agents/0/agents/1/foo; parts[:1] == ["agents"] short-circuits the retry.
    parts, node = resolve_agents0_fallback(state, ["agents", "1", "foo"])
    assert node is None
    assert parts == ["agents", "1", "foo"]


# -- agents0_json_extract_pair -------------------------------------------

def test_json_extract_pair_scalar_path():
    literal, agent = agents0_json_extract_pair("listeners.mass.cell_mass", None)
    assert literal == "$.listeners.mass.cell_mass"
    assert agent == "$.agents.0.listeners.mass.cell_mass"


def test_json_extract_pair_with_index():
    literal, agent = agents0_json_extract_pair("listeners.monomer_counts", 3861)
    assert literal == "$.listeners.monomer_counts[3861]"
    assert agent == "$.agents.0.listeners.monomer_counts[3861]"


def test_json_extract_pair_index_none_omits_suffix():
    literal, agent = agents0_json_extract_pair("bulk", None)
    assert literal == "$.bulk"
    assert agent == "$.agents.0.bulk"
