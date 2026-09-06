"""Round-trip test for the ``ui.auto_results`` write path (Task 9).

Task 7 added the read side (``system_info.build_ui_config`` — default True,
overridable via ``workspace.yaml``'s ``ui.auto_results``). This covers the new
write side: ``lib.ui_settings_mutations.ui_config_update`` persists a bool into
``workspace.yaml``'s ``ui:`` block, and a subsequent ``build_ui_config`` read
reflects it — mirroring the read-modify-write pattern in
``lib.viz_commit_mutations`` (raw ``yaml.safe_load``/``safe_dump`` against
``workspace.yaml``, no schema validation — same as the existing
``ui.auto_results`` read-side tests in ``test_auto_results_setting.py``).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from vivarium_workbench.lib import ui_settings_mutations
from vivarium_workbench.lib.system_info import build_ui_config


def test_write_false_then_read_back_false(tmp_path: Path) -> None:
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (ws_root / "workspace.yaml").write_text(yaml.safe_dump({"name": "testws"}))

    body, status = ui_settings_mutations.ui_config_update(ws_root, {"auto_results": False})

    assert status == 200
    assert body == {"ok": True, "auto_results": False}
    assert build_ui_config(ws_root)["auto_results"] is False


def test_write_true_then_read_back_true(tmp_path: Path) -> None:
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (ws_root / "workspace.yaml").write_text(yaml.safe_dump({
        "name": "testws",
        "ui": {"auto_results": False},
    }))

    body, status = ui_settings_mutations.ui_config_update(ws_root, {"auto_results": True})

    assert status == 200
    assert body == {"ok": True, "auto_results": True}
    assert build_ui_config(ws_root)["auto_results"] is True


def test_default_true_when_unset(tmp_path: Path) -> None:
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (ws_root / "workspace.yaml").write_text(yaml.safe_dump({"name": "testws"}))

    assert build_ui_config(ws_root)["auto_results"] is True


def test_write_preserves_other_ui_keys(tmp_path: Path) -> None:
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (ws_root / "workspace.yaml").write_text(yaml.safe_dump({
        "name": "testws",
        "ui": {"composite_view": "bigraph-viz"},
    }))

    ui_settings_mutations.ui_config_update(ws_root, {"auto_results": False})

    cfg = build_ui_config(ws_root)
    assert cfg["auto_results"] is False
    assert cfg["composite_view"] == "bigraph-viz"


def test_rejects_non_bool_value(tmp_path: Path) -> None:
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (ws_root / "workspace.yaml").write_text(yaml.safe_dump({"name": "testws"}))

    body, status = ui_settings_mutations.ui_config_update(ws_root, {"auto_results": "nope"})

    assert status == 400
    assert "error" in body
    # Unaffected by the rejected write.
    assert build_ui_config(ws_root)["auto_results"] is True


def test_rejects_missing_key(tmp_path: Path) -> None:
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (ws_root / "workspace.yaml").write_text(yaml.safe_dump({"name": "testws"}))

    body, status = ui_settings_mutations.ui_config_update(ws_root, {})

    assert status == 400
    assert "error" in body
