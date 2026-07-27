"""Study-detail header: two distinct buttons — Reproduce (manifest replay)
vs Run current spec (re-derive) — never one ambiguous "Rerun" (reproducible-
rerun-spine Task 4 / G2). Cheap "the wiring exists" checks against the live
FastAPI app, in-process (mirrors test_api_app.py::TestStudyDetailPageRoute),
not exhaustive behavioral tests — the endpoint behavior itself is covered by
test_rerun.py / test_launch_into_study.py / test_rerun_run.py.
"""
from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from vivarium_workbench.api.app import create_app, get_workspace


def _client_with_study(tmp_path, slug="s1"):
    sd = tmp_path / "studies" / slug
    sd.mkdir(parents=True)
    (sd / "study.yaml").write_text(yaml.safe_dump({
        "schema_version": 3, "name": slug, "created": "2026-07-27",
        "status": "draft", "objective": "",
        "baseline": [{"name": "core", "composite": "pkg.composites.x", "params": {}}],
        "variants": [], "runs": [], "visualizations": [], "comparisons": [],
        "conclusion": None, "parent_studies": [], "interventions": [],
    }))
    app = create_app()
    app.dependency_overrides[get_workspace] = lambda: tmp_path
    return TestClient(app), slug


def test_study_detail_has_both_reproduce_and_run_current_spec_buttons(tmp_path):
    client, slug = _client_with_study(tmp_path)
    r = client.get(f"/studies/{slug}")
    assert r.status_code == 200
    # Two distinct ids — never a single ambiguous "Rerun" control.
    assert 'id="study-reproduce"' in r.text
    assert 'id="study-run-current-spec"' in r.text
    # The old ambiguous single button is gone.
    assert 'id="study-rerun"' not in r.text


def test_study_detail_hides_both_buttons_in_snapshot_mode(tmp_path):
    client, slug = _client_with_study(tmp_path)
    r = client.get(f"/studies/{slug}")
    assert r.status_code == 200
    # The inline snapshot-mode gate must reference BOTH ids so a published
    # read-only bundle (no live backend to launch against) hides both —
    # mirrors the existing remote-run-panel hide right above it.
    assert 'getElementById("study-reproduce")' in r.text
    assert 'getElementById("study-run-current-spec")' in r.text
    assert 'mode === "snapshot"' in r.text
