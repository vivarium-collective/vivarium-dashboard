"""Tests for the ``ui.auto_results`` workspace setting (Task 7).

Covers:
  - build_ui_config: default True with no workspace.yaml ui.auto_results key
  - build_ui_config: ui.auto_results: false reads False
  - composite_flush.run_flush: gates _dispatch_analyses on the setting —
    False skips dispatch (and analyses.json stays empty), True (default)
    dispatches as before.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
import pytest

from vivarium_workbench.lib import composite_flush


# ---------------------------------------------------------------------------
# build_ui_config: auto_results default + override
# ---------------------------------------------------------------------------

class TestAutoResultsUiConfig:
    def test_defaults_true_with_no_ui_block(self, tmp_path: Path) -> None:
        from vivarium_workbench.lib.system_info import build_ui_config
        result = build_ui_config(tmp_path)
        assert result["auto_results"] is True

    def test_defaults_true_with_ui_block_but_no_key(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yaml").write_text(yaml.safe_dump({
            "ui": {"composite_view": "bigraph-loom"},
        }))
        from vivarium_workbench.lib.system_info import build_ui_config
        result = build_ui_config(tmp_path)
        assert result["auto_results"] is True

    def test_reads_false_override(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yaml").write_text(yaml.safe_dump({
            "ui": {"auto_results": False},
        }))
        from vivarium_workbench.lib.system_info import build_ui_config
        result = build_ui_config(tmp_path)
        assert result["auto_results"] is False

    def test_reads_true_override_explicit(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yaml").write_text(yaml.safe_dump({
            "ui": {"auto_results": True},
        }))
        from vivarium_workbench.lib.system_info import build_ui_config
        result = build_ui_config(tmp_path)
        assert result["auto_results"] is True


# ---------------------------------------------------------------------------
# UiConfig model default
# ---------------------------------------------------------------------------

def test_ui_config_model_defaults_auto_results_true() -> None:
    from vivarium_workbench.lib.models import UiConfig
    m = UiConfig(composite_view="bigraph-loom")
    assert m.auto_results is True


# ---------------------------------------------------------------------------
# run_flush gate
# ---------------------------------------------------------------------------

class _Req:
    steps = 10
    run_id = "r1"
    spec_id = "multiscale_bats.composites.bats_fba.bats_fba"


def _run_dir_for(ws_root: Path) -> Path:
    """A run_dir positioned the way _render_analysis expects:
    ``<ws_root>/.pbg/runs/<run_id>`` so ``run_dir.parents[2] == ws_root``."""
    run_dir = ws_root / ".pbg" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    return run_dir


def test_auto_results_false_skips_dispatch(tmp_path, monkeypatch):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (ws_root / "workspace.yaml").write_text(yaml.safe_dump({
        "ui": {"auto_results": False},
    }))
    run_dir = _run_dir_for(ws_root)

    called = {}

    def _boom(**kw):
        called["dispatched"] = True
        return [{"name": "mass_over_time"}]

    monkeypatch.setattr(composite_flush, "_dispatch_analyses", _boom)
    out = composite_flush.run_flush(
        run_dir, req=_Req(), spec_id=_Req.spec_id,
        db_file=str(run_dir / "runs.db"), run_id="r1", core=object(),
    )
    assert "dispatched" not in called
    assert out["has_analyses"] is False
    assert json.loads((run_dir / "analyses.json").read_text()) == []


def test_auto_results_true_dispatches(tmp_path, monkeypatch):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (ws_root / "workspace.yaml").write_text(yaml.safe_dump({
        "ui": {"auto_results": True},
    }))
    run_dir = _run_dir_for(ws_root)

    called = {}

    def _dispatch(**kw):
        called["dispatched"] = True
        return [{"name": "mass_over_time"}]

    monkeypatch.setattr(composite_flush, "_dispatch_analyses", _dispatch)
    out = composite_flush.run_flush(
        run_dir, req=_Req(), spec_id=_Req.spec_id,
        db_file=str(run_dir / "runs.db"), run_id="r1", core=object(),
    )
    assert called.get("dispatched") is True
    assert out["has_analyses"] is True
    assert json.loads((run_dir / "analyses.json").read_text()) == [
        {"name": "mass_over_time"}
    ]


def test_auto_results_default_true_when_no_ui_block(tmp_path, monkeypatch):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    # No workspace.yaml at all — build_ui_config degrades to default True.
    run_dir = _run_dir_for(ws_root)

    called = {}

    def _dispatch(**kw):
        called["dispatched"] = True
        return []

    monkeypatch.setattr(composite_flush, "_dispatch_analyses", _dispatch)
    composite_flush.run_flush(
        run_dir, req=_Req(), spec_id=_Req.spec_id,
        db_file=str(run_dir / "runs.db"), run_id="r1", core=object(),
    )
    assert called.get("dispatched") is True


def test_auto_results_enabled_helper_tolerates_bad_run_dir():
    # A run_dir with too few parents (e.g. a bare relative path) must not
    # raise — degrade to the default True.
    assert composite_flush._auto_results_enabled(Path("r1")) is True
