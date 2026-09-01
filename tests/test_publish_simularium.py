"""publish._export_simularium_trajectories bakes the viewer + trajectories into
a read-only bundle so the Simularium tool works on the static site."""
from __future__ import annotations

from pathlib import Path

import yaml

from vivarium_workbench import publish


def _ws(tmp_path: Path) -> Path:
    (tmp_path / "workspace.yaml").write_text(
        yaml.safe_dump({"name": "t", "package_path": "p",
                        "layout": {"studies": "workspace/studies"}}),
        encoding="utf-8")
    sd = tmp_path / "workspace" / "studies" / "run-a"
    (sd / "viz" / "simularium").mkdir(parents=True)
    (sd / "study.yaml").write_text(yaml.safe_dump({"name": "run-a"}), encoding="utf-8")
    (sd / "viz" / "simularium" / "run-a.simularium").write_text(
        '{"trajectoryInfo": {}}', encoding="utf-8")
    return tmp_path


def test_export_copies_viewer_and_trajectories(tmp_path):
    ws = _ws(tmp_path)
    out = tmp_path / "bundle"
    out.mkdir()
    publish._export_simularium_trajectories(ws, out)

    # viewer page at bundle root
    assert (out / "simularium-viewer.html").is_file()
    # trajectory copied preserving its workspace-relative path
    copied = out / "workspace" / "studies" / "run-a" / "viz" / "simularium" / "run-a.simularium"
    assert copied.is_file()
    assert copied.read_text() == '{"trajectoryInfo": {}}'


def test_export_no_trajectories_is_noop(tmp_path):
    (tmp_path / "workspace.yaml").write_text(
        yaml.safe_dump({"name": "t", "package_path": "p"}), encoding="utf-8")
    out = tmp_path / "bundle"
    out.mkdir()
    publish._export_simularium_trajectories(tmp_path, out)  # must not raise
    assert not list((out / "workspace").glob("**/*.simularium")) if (out / "workspace").exists() else True
