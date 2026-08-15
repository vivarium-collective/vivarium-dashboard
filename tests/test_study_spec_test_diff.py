"""Slice 3 Task 2: spec["test_diff"] surfaced from the latest run's
run_dir/test_diff.json (written by composite_flush._write_test_diff), plus
verifying the report_card_verdict/v2 axis extras (margin/severity/knob/
citation) pass through report_card_urls[card].groups verbatim (no new code
needed for that — study_spec.py already assigns groups = _vj.get("groups")
directly, so this is a regression-guard, not a feature test).
"""
import json
import sqlite3

from vivarium_workbench.lib import study_spec


def _ws_with_run(tmp_path, *, write_diff=True):
    ws = tmp_path
    d = ws / "studies" / "demo"
    (d / "viz" / "report_card").mkdir(parents=True)
    (d / "viz" / "report_card" / "standard.html").write_text("<h1>card</h1>", encoding="utf-8")
    (d / "viz" / "report_card" / "standard.verdict.json").write_text(
        json.dumps({
            "overall": "within_tol",
            "groups": {
                "grp1": {"axes": [
                    {"id": "ax1", "verdict": "within_tol", "margin": 0.42,
                     "severity": "hard", "knob": "k1", "citation": "cite1"},
                ]},
            },
        }), encoding="utf-8")
    (d / "study.yaml").write_text(
        "schema_version: 4\nname: demo\nquestion: demo question\n"
        "conditions:\n  baseline:\n    composite: v2ecoli.composites.baseline.baseline\n"
        "tests:\n"
        "- {name: card-one, kind: report_card, card: standard}\n"
        "status: planned\n",
        encoding="utf-8")

    run_id = "r1"
    run_dir = ws / ".pbg" / "runs" / run_id
    run_dir.mkdir(parents=True)
    if write_diff:
        (run_dir / "test_diff.json").write_text(json.dumps({
            "schema": "test_diff/v1",
            "per": [{"card": "standard", "group": "grp1", "id": "ax1",
                     "prev": "mismatch", "curr": "within_tol",
                     "change": "fixed", "margin_delta": 0.9}],
            "rollup": {"fixed": 1},
        }), encoding="utf-8")

    conn = sqlite3.connect(d / "runs.db")
    conn.execute(
        "CREATE TABLE runs_meta (run_id TEXT PRIMARY KEY, started_at REAL, "
        "completed_at REAL)")
    conn.execute("INSERT INTO runs_meta VALUES (?, 1.0, 2.0)", (run_id,))
    conn.commit()
    conn.close()
    return ws


def test_spec_test_diff_surfaced_from_latest_run(tmp_path):
    ws = _ws_with_run(tmp_path)
    spec = study_spec.load_study_detail_spec(str(ws), "demo")
    assert spec["test_diff"]["schema"] == "test_diff/v1"
    assert spec["test_diff"]["per"][0]["change"] == "fixed"


def test_spec_test_diff_absent_when_not_written(tmp_path):
    ws = _ws_with_run(tmp_path, write_diff=False)
    spec = study_spec.load_study_detail_spec(str(ws), "demo")
    assert "test_diff" not in spec


def test_spec_test_diff_absent_when_no_runs(tmp_path):
    ws = tmp_path
    d = ws / "studies" / "demo"
    (d / "viz" / "report_card").mkdir(parents=True)
    (d / "study.yaml").write_text(
        "schema_version: 4\nname: demo\nquestion: demo question\n"
        "conditions:\n  baseline:\n    composite: v2ecoli.composites.baseline.baseline\n"
        "status: planned\n",
        encoding="utf-8")
    spec = study_spec.load_study_detail_spec(str(ws), "demo")
    assert "test_diff" not in spec


def test_v2_axis_extras_pass_through_report_card_urls_groups(tmp_path):
    # Regression guard: margin/severity/knob/citation ALREADY pass through
    # report_card_urls[card].groups verbatim (study_spec.py assigns
    # groups = _vj.get("groups") directly) — no new code for this, just
    # verifying it still holds after the test_diff addition.
    ws = _ws_with_run(tmp_path)
    spec = study_spec.load_study_detail_spec(str(ws), "demo")
    axis = spec["report_card_urls"]["standard"]["groups"]["grp1"]["axes"][0]
    assert axis["margin"] == 0.42
    assert axis["severity"] == "hard"
    assert axis["knob"] == "k1"
    assert axis["citation"] == "cite1"
