"""Per-developer workstream state (active branch, push status, PR linkage).

Persisted at .pbg/state.json — gitignored, never committed.
"""
from __future__ import annotations
import json
from pathlib import Path

from ._root import workspace_root


_STATE_FILENAME = "state.json"


def _state_path() -> Path:
    return workspace_root() / ".pbg" / _STATE_FILENAME


def load_state() -> dict:
    """Return state dict; empty {} if file missing or unparseable."""
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text()) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n")


def clear_state() -> None:
    p = _state_path()
    if p.exists():
        p.unlink()


def get_active_branch() -> str | None:
    return load_state().get("active_branch")
