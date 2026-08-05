"""`.json` analysis-output downloads, scoped to `analyses/`.

A Step baseline can drop a JSON artifact into the run's `analyses/<run_id>/`
dir (via the injected `analysis_out_dir` config); the Analysis/Runs tab lists
it. `.json` is surfaced ONLY under `analyses/` so viewer/config packs
(`viz/atlas/atlas.json`, `config.json`) are never wrongly offered as downloads.
"""
from __future__ import annotations

from vivarium_workbench.lib.analysis_outputs import _iter_result_files, _RESULT_EXTS


def test_json_allowed_and_csv_tsv_still_allowed():
    assert {".csv", ".tsv", ".json"} <= _RESULT_EXTS


def test_json_listed_only_under_analyses(tmp_path):
    sd = tmp_path
    (sd / "analyses" / "r1").mkdir(parents=True)
    (sd / "analyses" / "r1" / "biomodel_hra_map.json").write_text("{}", encoding="utf-8")
    (sd / "analyses" / "r1" / "table.csv").write_text("a,b\n1,2", encoding="utf-8")
    (sd / "viz" / "atlas").mkdir(parents=True)
    (sd / "viz" / "atlas" / "atlas.json").write_text("{}", encoding="utf-8")  # must NOT surface
    (sd / "config.json").write_text("{}", encoding="utf-8")                    # must NOT surface
    (sd / "result.tsv").write_text("a\tb", encoding="utf-8")

    names = {p.name for p in _iter_result_files(sd)}
    assert "biomodel_hra_map.json" in names   # json under analyses/ -> listed
    assert "table.csv" in names               # csv anywhere -> listed
    assert "result.tsv" in names              # tsv anywhere -> listed
    assert "atlas.json" not in names          # viz json -> NOT listed
    assert "config.json" not in names         # top-level json -> NOT listed
