"""UI-settings POST mutation builder (Task 9, composite-run-auto-results).

Pure builder for the one write route this covers:

    (ws_root: Path, body: dict) -> tuple[dict, int]

File side-effects only — no HTTP, no server imports, no git operations.
Mirrors the read-modify-write ``workspace.yaml`` pattern used by
``lib.viz_commit_mutations.observable_add`` (raw ``yaml.safe_load``/
``safe_dump`` against ``workspace.yaml``, no schema validation — the ``ui:``
block is a workspace preference, not the schema-validated scientific record
that ``lib.workspace_yaml.save_workspace`` guards).

Routes covered:
  - POST /api/ui-config  → persist ``ui.auto_results`` in workspace.yaml
                            (Task 7's default-on setting read by
                            ``lib.system_info.build_ui_config``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def ui_config_update(ws_root: Path, body: dict[str, Any]) -> "tuple[dict, int]":
    """POST /api/ui-config — persist ``ui.auto_results`` in workspace.yaml.

    Body: ``{auto_results: bool}``

    Returns:
      200  ``{ok: True, auto_results: <bool>}``
      400  ``auto_results`` missing or not a bool
    """
    if "auto_results" not in body:
        return {"error": "auto_results is required"}, 400
    value = body["auto_results"]
    if not isinstance(value, bool):
        return {"error": "auto_results must be a bool"}, 400

    ws_root = Path(ws_root)
    ws_file = ws_root / "workspace.yaml"
    ws: dict = yaml.safe_load(ws_file.read_text(encoding="utf-8")) or {} if ws_file.exists() else {}
    ui = ws.setdefault("ui", {})
    if ui is None:
        ui = {}
        ws["ui"] = ui
    ui["auto_results"] = value
    ws_file.write_text(yaml.safe_dump(ws, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {"ok": True, "auto_results": value}, 200
