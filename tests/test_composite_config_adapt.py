"""Tests for ``lib.composite_config_adapt`` (item 86: the "external config"
JSON-spec input mode).

``adapt_translated_config`` is pure — no fixture workspace needed. The
synthetic fixture below is shaped like a real translated legacy config (the
same key names ``config_adapter.translate_vecoli_config`` would produce:
fork_repo/add_processes/swap_processes/process_configs/topology/time_step/
exclude_processes) but with made-up generic values, per this project's
standing rule against usecase-identifying content in this repo.
``composite_config_translate`` is tested against a monkeypatched
``resolve_composite_for_request`` so no real composite registry is needed.
"""
from __future__ import annotations

from pathlib import Path

from vivarium_workbench.lib.composite_config_adapt import (
    adapt_translated_config,
    composite_config_translate,
)
from vivarium_workbench.lib import composite_resolve as composite_resolve_mod


_SYNTHETIC_DECLARED_PARAMS = {
    "n_cells": {"type": "int", "default": 2},
    "env_size": {"type": "float", "default": 10.0},
    "injected_processes": {"type": "map", "default": {}},
}


# ---------------------------------------------------------------------------
# adapt_translated_config — pure logic
# ---------------------------------------------------------------------------

def test_direct_param_name_passes_through():
    result = adapt_translated_config(
        {"n_cells": 8, "env_size": 25.0}, _SYNTHETIC_DECLARED_PARAMS
    )
    assert result["params"] == {"n_cells": 8, "env_size": 25.0}
    assert result["unmatched"] == []


def test_known_injection_keys_nest_into_declared_map_param():
    raw = {
        "fork_repo": "https://example.invalid/synthetic-fork.git",
        "add_processes": ["synthetic_process_a"],
        "swap_processes": {"synthetic_a": "synthetic_b"},
        "process_configs": {"synthetic_a": {"knob": 1}},
        "topology": {"synthetic_a": {"port": ["synthetic", "path"]}},
        "time_step": 0.5,
        "exclude_processes": ["synthetic_process_c"],
    }
    result = adapt_translated_config(raw, _SYNTHETIC_DECLARED_PARAMS)
    assert result["unmatched"] == []
    injected = result["params"]["injected_processes"]
    assert injected["fork_repo"] == "https://example.invalid/synthetic-fork.git"
    assert injected["add_processes"] == ["synthetic_process_a"]
    assert injected["time_step"] == 0.5


def test_injection_keys_ignored_without_a_declared_map_param():
    declared = {"n_cells": {"type": "int", "default": 2}}  # no injected_processes
    result = adapt_translated_config({"fork_repo": "x", "n_cells": 4}, declared)
    assert result["params"] == {"n_cells": 4}
    assert result["unmatched"] == ["fork_repo"]


def test_unmatched_keys_reported_not_silently_dropped():
    result = adapt_translated_config(
        {"n_cells": 4, "totally_unrelated_key": "synthetic_value"},
        _SYNTHETIC_DECLARED_PARAMS,
    )
    assert result["params"] == {"n_cells": 4}
    assert result["unmatched"] == ["totally_unrelated_key"]


def test_mixed_direct_injected_processes_merges_with_flat_injection_keys():
    raw = {
        "injected_processes": {"add_processes": ["already_nested"]},
        "fork_repo": "https://example.invalid/synthetic.git",
    }
    result = adapt_translated_config(raw, _SYNTHETIC_DECLARED_PARAMS)
    injected = result["params"]["injected_processes"]
    assert injected["add_processes"] == ["already_nested"]
    assert injected["fork_repo"] == "https://example.invalid/synthetic.git"


def test_empty_raw_returns_empty():
    result = adapt_translated_config({}, _SYNTHETIC_DECLARED_PARAMS)
    assert result == {"params": {}, "unmatched": []}


# ---------------------------------------------------------------------------
# composite_config_translate — the request-handler wrapper
# ---------------------------------------------------------------------------

def test_missing_composite_id_400(tmp_path: Path):
    body, status = composite_config_translate(tmp_path, {"config_json": {}})
    assert status == 400
    assert "composite_id" in body["error"]


def test_config_json_not_a_dict_422(tmp_path: Path):
    body, status = composite_config_translate(
        tmp_path, {"composite_id": "synthetic.composite", "config_json": [1, 2, 3]}
    )
    assert status == 422


def test_config_json_missing_422(tmp_path: Path):
    body, status = composite_config_translate(
        tmp_path, {"composite_id": "synthetic.composite"}
    )
    assert status == 422


def test_unknown_composite_404(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        composite_resolve_mod, "resolve_composite_for_request", lambda *a, **k: None
    )
    body, status = composite_config_translate(
        tmp_path, {"composite_id": "nope.does.not.exist", "config_json": {"x": 1}}
    )
    assert status == 404


def test_happy_path_200(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        composite_resolve_mod,
        "resolve_composite_for_request",
        lambda ws, spec_id, overrides=None: {
            "id": spec_id,
            "parameters": _SYNTHETIC_DECLARED_PARAMS,
        },
    )
    body, status = composite_config_translate(
        tmp_path,
        {
            "composite_id": "synthetic.composite",
            "config_json": {"n_cells": 6, "fork_repo": "https://example.invalid/x.git"},
        },
    )
    assert status == 200
    assert body["params"]["n_cells"] == 6
    assert body["params"]["injected_processes"]["fork_repo"] == "https://example.invalid/x.git"
    assert body["unmatched"] == []
