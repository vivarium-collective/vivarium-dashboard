"""POST /api/config-to-composite handler — vEcoli config JSON -> loom document.

Routes to the workspace env worker's ``config_to_composite`` method (the fork +
translator live on the workspace interpreter) and shapes the result into the
``{state, schema, kind}`` envelope the loom already renders."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from vivarium_workbench.lib.env_worker_pool import get_pool


def build_config_composite(ws_root: "Path | str", config: Any) -> "tuple[dict, int]":
    if not isinstance(config, dict):
        return {"error": "config must be a JSON object"}, 422
    try:
        res = get_pool().call(Path(ws_root), "config_to_composite", {"config": config})
    except Exception as e:  # noqa: BLE001 — worker unavailable, etc.
        return {"error": f"env worker unavailable: {e}"}, 503
    if not isinstance(res, dict):
        return {"error": "translator returned no document"}, 500
    if res.get("__unavailable__"):
        return {"error": "config→composite translator not available in this workspace"}, 501
    if res.get("__error__"):
        return {"error": res["__error__"]}, 400
    return {"state": res.get("state", {}), "schema": res.get("schema", {}),
            "kind": "config-composite"}, 200
