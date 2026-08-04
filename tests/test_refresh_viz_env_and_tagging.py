"""Regression test for Phase 2.1a (de-vendoring).

``vivarium_workbench/lib/refresh_viz.py`` was a vendored copy of
``viva_superpowers/refresh_viz.py`` that silently drifted *behind* the
canonical: it was missing the ``VIVA_RUN_DIR``/``VIVA_RUN_ID`` env vars
(only the deprecated ``PBG_RUN_*`` names were set) and never called
``chart_store.tag_chart`` to record which run produced a chart. Nothing
caught this because the only guard was a byte-diff mirror test that never
ran in CI (no sibling checkout). 2.1a made the workbench copy canonical and
ported the two missing fixes forward — this test pins both so they cannot
silently regress again.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from viva_superpowers import chart_store

from vivarium_workbench.lib.refresh_viz import refresh_study_viz


def _write_render_script(tmp_path: Path, env_dump: Path) -> Path:
    """A small script the render: command shells out to. It writes the chart
    file (so refresh_study_viz sees status="rendered") AND dumps the env vars
    we care about to ``env_dump`` for the test to inspect afterward."""
    script = tmp_path / "render.py"
    script.write_text(textwrap.dedent(f"""
        import json, os, sys
        chart_path = sys.argv[1]
        env = {{k: os.environ.get(k) for k in
                ("VIVA_RUN_DIR", "VIVA_RUN_ID", "PBG_RUN_DIR", "PBG_RUN_ID")}}
        with open({str(env_dump)!r}, "w") as f:
            json.dump(env, f)
        with open(chart_path, "w") as f:
            f.write("<svg/>")
    """), encoding="utf-8")
    return script


def test_refresh_sets_viva_and_pbg_run_env_vars(tmp_path: Path):
    """Both the new VIVA_RUN_DIR/VIVA_RUN_ID and the deprecated PBG_RUN_DIR/
    PBG_RUN_ID must be present in the render subprocess's env (§0.3 fix 1)."""
    study_dir = tmp_path / "study"
    (study_dir / "charts").mkdir(parents=True)
    env_dump = tmp_path / "env_dump.json"
    script = _write_render_script(tmp_path, env_dump)

    render = f'{sys.executable} {script} {{chart}}'
    spec = {"visualizations": [{"name": "c", "chart": "charts/c.svg", "render": render}]}
    latest = {"run_id": "run-1", "emitter_path": "out/run-1", "generation_id": "gen0"}

    results = refresh_study_viz(study_dir, spec, latest)

    assert results[0]["status"] == "rendered", results
    env_seen = json.loads(env_dump.read_text(encoding="utf-8"))
    expected_dir = str(study_dir / "out/run-1")
    assert env_seen["VIVA_RUN_DIR"] == expected_dir
    assert env_seen["PBG_RUN_DIR"] == expected_dir
    assert env_seen["VIVA_RUN_ID"] == "run-1"
    assert env_seen["PBG_RUN_ID"] == "run-1"


def test_refresh_tags_chart_with_producing_run(tmp_path: Path):
    """A rendered chart with a known run_id must be recorded in chart_store's
    manifest (§0.3 fix 2) so a later canonical run can prune it as superseded."""
    study_dir = tmp_path / "study"
    charts_dir = study_dir / "charts"
    charts_dir.mkdir(parents=True)
    env_dump = tmp_path / "env_dump.json"
    script = _write_render_script(tmp_path, env_dump)

    render = f'{sys.executable} {script} {{chart}}'
    spec = {"visualizations": [{"name": "c", "chart": "charts/c.svg", "render": render}]}
    latest = {"run_id": "run-42", "emitter_path": None, "generation_id": None}

    results = refresh_study_viz(study_dir, spec, latest)

    assert results[0]["status"] == "rendered", results
    manifest = chart_store.load_manifest(charts_dir)
    assert manifest.get("c.svg", {}).get("run_id") == "run-42"
