"""Tests for the nested-studies -> top-level-registry migrator."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vivarium_workbench.lib.study_migrate import StudyMigrationError, migrate_studies


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _make_inv_a(ws_root: Path) -> None:
    _write_yaml(
        ws_root / "investigations" / "A" / "studies" / "parca" / "study.yaml",
        {"name": "parca", "composite": "parca_builder", "outputs": ["sim_data"]},
    )
    _write_yaml(
        ws_root / "investigations" / "A" / "studies" / "ko" / "study.yaml",
        {"name": "ko", "composite": "baseline"},
    )
    _write_yaml(ws_root / "investigations" / "A" / "investigation.yaml", {"title": "A"})


def test_moves_nested_studies_to_registry(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _make_inv_a(ws)

    migrate_studies(ws)

    assert (ws / "studies" / "parca" / "study.yaml").is_file()
    assert (ws / "studies" / "ko" / "study.yaml").is_file()
    assert not (ws / "investigations" / "A" / "studies").exists()

    inv_spec = yaml.safe_load((ws / "investigations" / "A" / "investigation.yaml").read_text())
    assert inv_spec["members"] == ["ko", "parca"]


def test_backfills_sim_data_input(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _make_inv_a(ws)

    result = migrate_studies(ws)

    ko_spec = yaml.safe_load((ws / "studies" / "ko" / "study.yaml").read_text())
    assert ko_spec["inputs"] == [{"artifact": "sim_data", "from": "parca"}]

    parca_spec = yaml.safe_load((ws / "studies" / "parca" / "study.yaml").read_text())
    assert "inputs" not in parca_spec

    assert {"study": "ko", "from": "parca"} in result["backfilled"]


def test_non_inferable_leaves_todo(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _write_yaml(
        ws / "investigations" / "B" / "studies" / "lonely" / "study.yaml",
        {"name": "lonely", "composite": "x"},
    )
    _write_yaml(ws / "investigations" / "B" / "investigation.yaml", {"title": "B"})

    result = migrate_studies(ws)

    text = (ws / "studies" / "lonely" / "study.yaml").read_text()
    assert "TODO(inputs)" in text
    assert "lonely" in result["todos"]

    spec = yaml.safe_load(text)
    assert "inputs" not in spec


def test_slug_collision_raises(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _write_yaml(
        ws / "studies" / "parca" / "study.yaml",
        {"name": "parca", "composite": "parca_builder", "outputs": ["sim_data"]},
    )
    _write_yaml(
        ws / "investigations" / "A" / "studies" / "parca" / "study.yaml",
        {"name": "parca", "composite": "parca_builder", "outputs": ["sim_data"]},
    )
    _write_yaml(ws / "investigations" / "A" / "investigation.yaml", {"title": "A"})

    with pytest.raises(StudyMigrationError):
        migrate_studies(ws)

    # Near-atomic: nothing moved.
    assert (ws / "investigations" / "A" / "studies" / "parca").exists()


def test_explicit_empty_inputs_preserved(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _write_yaml(
        ws / "investigations" / "A" / "studies" / "parca" / "study.yaml",
        {"name": "parca", "composite": "parca_builder", "outputs": ["sim_data"]},
    )
    _write_yaml(
        ws / "investigations" / "A" / "studies" / "ko" / "study.yaml",
        {"name": "ko", "composite": "baseline", "inputs": []},
    )
    _write_yaml(ws / "investigations" / "A" / "investigation.yaml", {"title": "A"})

    result = migrate_studies(ws)

    ko_spec = yaml.safe_load((ws / "studies" / "ko" / "study.yaml").read_text())
    assert ko_spec["inputs"] == []
    assert not any(b["study"] == "ko" for b in result["backfilled"])
    assert "ko" not in result["todos"]


def test_cross_investigation_duplicate_slug_raises(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _write_yaml(
        ws / "investigations" / "A" / "studies" / "dup" / "study.yaml",
        {"name": "dup", "composite": "x"},
    )
    _write_yaml(ws / "investigations" / "A" / "investigation.yaml", {"title": "A"})
    _write_yaml(
        ws / "investigations" / "B" / "studies" / "dup" / "study.yaml",
        {"name": "dup", "composite": "y"},
    )
    _write_yaml(ws / "investigations" / "B" / "investigation.yaml", {"title": "B"})

    with pytest.raises(StudyMigrationError):
        migrate_studies(ws)

    assert (ws / "investigations" / "A" / "studies" / "dup").exists()
    assert (ws / "investigations" / "B" / "studies" / "dup").exists()


def test_dry_run_touches_nothing(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _make_inv_a(ws)

    result = migrate_studies(ws, dry_run=True)

    assert not (ws / "studies" / "parca").exists()
    assert not (ws / "studies" / "ko").exists()
    assert (ws / "investigations" / "A" / "studies" / "parca").exists()
    assert (ws / "investigations" / "A" / "studies" / "ko").exists()

    inv_spec = yaml.safe_load((ws / "investigations" / "A" / "investigation.yaml").read_text())
    assert "members" not in inv_spec

    assert result["would_move"] == ["ko", "parca"]
    assert result["dry_run"] is True
