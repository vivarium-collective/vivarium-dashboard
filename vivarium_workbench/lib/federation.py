"""Read-only federation of installed ecosystem modules' content.

A "linked workspace" is an installed module that ships a workspace.yaml — landed
on disk at <ws_root>/external/<name>/ by the marketplace's full-repo install
path (or editable-installed to a repo root). Its studies, investigation-sets,
and composites are surfaced read-only in the host workspace, each tagged with
its origin repo. All helpers are best-effort: a malformed linked workspace is
skipped, never raising, so the host workspace's own listings always render.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from vivarium_workbench.lib.workspace_paths import WorkspacePaths


@dataclass
class LinkedWorkspace:
    repo: str          # display name (workspace.yaml `name`, else dir name)
    root: Path         # repo root on disk
    layout: WorkspacePaths


def _repo_name(root: Path) -> str:
    try:
        data = yaml.safe_load((root / "workspace.yaml").read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("name"):
            return str(data["name"])
    except Exception:
        pass
    return root.name


def linked_workspaces(ws_root: Path) -> list[LinkedWorkspace]:
    ws_root = Path(ws_root).resolve()
    seen: set[Path] = {ws_root}
    out: list[LinkedWorkspace] = []
    ext = ws_root / "external"
    if ext.is_dir():
        for child in sorted(ext.iterdir()):
            if not child.is_dir() or not (child / "workspace.yaml").is_file():
                continue
            root = child.resolve()
            if root in seen:
                continue
            try:
                layout = WorkspacePaths.load(root)
            except Exception:
                continue
            seen.add(root)
            out.append(LinkedWorkspace(repo=_repo_name(root), root=root, layout=layout))
    return out
