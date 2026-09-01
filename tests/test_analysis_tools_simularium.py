"""The Simularium Viewer analysis tool: discover studies with a .simularium
trajectory and match the built-in tool to them."""
from __future__ import annotations

from pathlib import Path

import yaml

from vivarium_workbench.lib.analysis_tools import (
    _simularium_candidates, build_analysis_tools)
from vivarium_workbench.lib.analysis_tools_simularium import (
    studies_with_simularium)


def _ws(tmp_path: Path) -> Path:
    (tmp_path / "workspace.yaml").write_text(
        yaml.safe_dump({"name": "t", "package_path": "p",
                        "layout": {"studies": "workspace/studies"}}),
        encoding="utf-8")
    return tmp_path


def _study_with_traj(ws: Path, slug: str) -> Path:
    d = ws / "workspace" / "studies" / slug / "viz" / "simularium"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.simularium").write_text('{"trajectoryInfo": {}}', encoding="utf-8")
    return d


def test_studies_with_simularium_finds_trajectory(tmp_path):
    ws = _ws(tmp_path)
    _study_with_traj(ws, "run-a")
    # a study with no trajectory is not listed
    (ws / "workspace" / "studies" / "run-b").mkdir(parents=True)
    found = studies_with_simularium(ws)
    slugs = {s["study"] for s in found}
    assert slugs == {"run-a"}
    traj = found[0]["trajectories"][0]
    assert traj["name"] == "run-a"
    assert traj["url"] == "/workspace/studies/run-a/viz/simularium/run-a.simularium"


def test_parquet_runs_internal_trajectories_excluded(tmp_path):
    ws = _ws(tmp_path)
    pr = ws / "workspace" / "studies" / "run-c" / "parquet-runs" / "exp"
    pr.mkdir(parents=True)
    (pr / "x.simularium").write_text("{}", encoding="utf-8")
    assert studies_with_simularium(ws) == []


def test_build_tools_matches_simularium_viewer(tmp_path):
    ws = _ws(tmp_path)
    _study_with_traj(ws, "run-a")
    cands = _simularium_candidates(ws)
    assert cands and cands[0]["capabilities"] == ["simularium"]

    tools = build_analysis_tools(ws)
    sim = next((t for t in tools if t["id"] == "simularium-viewer"), None)
    assert sim is not None, "simularium-viewer tool should surface when a study has a trajectory"
    assert sim["kind"] == "embed-simularium"
    assert [m["ref"] for m in sim["matched"]] == ["run-a"]


def test_simularium_tool_absent_without_trajectories(tmp_path):
    ws = _ws(tmp_path)
    (ws / "workspace" / "studies" / "run-b").mkdir(parents=True)
    tools = build_analysis_tools(ws)
    assert not any(t["id"] == "simularium-viewer" for t in tools)
